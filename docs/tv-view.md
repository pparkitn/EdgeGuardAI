# Live Camera View on a Cast Device / TV

`tv_view.py` composes the configured cameras into a single live grid
stream and casts it to any Chromecast-enabled display (TV, Android TV,
Nest Hub...). Everything runs locally — cameras, transcode, and HTTP
serving all stay on the LAN.

## Usage

```bash
python -m tv_view --list          # find cast device names / models / IPs
python -m tv_view                 # start the view (Ctrl+C stops it)
python -m tv_view --tv "GoogleTV7401"
python -m tv_view --port 8100
```

On Ctrl+C the player is stopped, the TV is released, and all
subprocesses are cleaned up.

## Configuration

`config.yaml -> tv_view`:

```yaml
tv_view:
  tv: "GoogleTV7401"      # cast device friendly name (see --list)
  http_port: 8100         # HLS server port (voice broadcaster uses 8000)
  host_ip: ""             # this machine's LAN IP (auto-detected)
  frame_rate: 10
  columns: 0              # grid columns; 0 = auto (2 for 4+ cameras)
  cameras:
    - back_yard                  # id under cameras.rtsp
    - id: garage                 # id + per-entry overrides
      path: /h264Preview_01_sub  # (use sub streams for a light grid)
    - id: front_door             # one-off camera: inline fields
      host: 192.168.2.32
      user: admin
      password: "..."            # its own RTSP password
      path: /h264Preview_01_sub
    - v4l2:/dev/video2           # USB webcam
```

A camera entry can be:

| Form | Meaning |
|---|---|
| `back_yard` | id from `cameras.rtsp`; URL built from its host/port/user/path + its `password` (or the shared `EDGEGUARD_CAMERA_PASSWORD`) |
| `rtsp://...` | used verbatim (percent-encode special characters in credentials) |
| `v4l2:/dev/videoX` | local USB/V4L2 device |
| `{source: ...}` | explicit source with an optional `id` label |
| `{id: ..., path/user/password/...}` | merges over the matching `cameras.rtsp` entry |

Secrets stay in the gitignored per-device `config.yaml` (or
`EDGEGUARD_*` env vars), never in `config.yaml.example`.

## How it works

```
camera -> ffmpeg feeder (scale/pad pane) -> wallclock-paced relay -> FIFO
                                                           |
              ... x N cameras ...                         v
                        one compositor: xstack grid -> libx264 -> fMP4 HLS
                                                           |
                              HTTP server (no-cache, proper MIME) -> Cast player
```

- **Per-camera feeders + relays**: a camera that stalls or drops
  (doorbells do, often) freezes its pane on the last frame and its
  feeder reconnects on its own — the cast keeps playing. One ffmpeg
  with N RTSP inputs instead re-handshakes *every* camera on any
  hiccup, which shows as a multi-second freeze.
- **Wallclock-paced relay**: frames are relayed on a 1/fps clock with
  the newest frame winning, and the last frame is repeated during
  camera silence, so the composite timeline always advances in real
  time (an unpaced relay runs the live edge faster than real time and
  outruns the player).
- **fMP4 HLS**: Cast displays that stall forever on live MPEG-TS
  (BUFFERING, zero segment fetches) play fMP4/CMAF segments fine.
- Expected startup: the compositor writes the playlist within a few
  seconds; the Cast player buffers ~20-30 s before `PLAYING`.

## Notes

- Grid: 1 camera full screen (1920x1080), 2-3 cameras in a row
  (1920x540), 4+ in a 2-column grid (1080p). Control with `columns`.
- Video only (no audio) — it is a surveillance view.
- The USB camera pane holds the V4L2 device, so don't run the USB
  face pipeline (`face_recognition.main`) at the same time.
- `http_port` must be reachable from the Cast device and must not
  collide with the voice broadcaster's server (8000 on the Pi).
- Logs: `journalctl -u <unit>` when run as a service; per-camera
  ffmpeg and compositor logs under `/tmp/tv_view/`.
- Runtime flags worth knowing: each RTSP input uses TCP,
  video-only tracks (`-allowed_media_types video`), a 15 s socket
  timeout, and the relay/overall design above. These tamed the
  D340W doorbell (drops ~1/min) and a stalling garage camera.
