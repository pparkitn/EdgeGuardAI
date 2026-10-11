# EdgeGuard AI - Camera Service

> Part of the [EdgeGuard AI](../README.md) documentation.
> Everything is configured centrally in [`config.yaml`](../config.yaml).

## Reolink Camera Service

Connects to **IP cameras (RTSP)** — e.g. Reolink — processes the video with the same face pipeline (detect → recognize → MQTT → snapshots), fully headless. Any number of cameras, any machine.

### How it works

```
Reolink camera (RTSP) ──► ffmpeg (static binary, scaled to 960x720 @ 2 fps)
                              │
                              ▼
                      FaceDetector (buffalo_l)
                              │
                              ▼
                      FaceRecognizer (faces.npz)
                              │
                              ├── MQTT event  → edgeguard/camera/<camera_id>
                              │                 (same topic family as USB cameras)
                              └── unknown snapshot → data/unknown_faces/<camera_id>/
```

- Streams are decoded with a **static ffmpeg binary** (`imageio-ffmpeg`) — chosen over PyAV because ffmpeg handles the RTSP auth handshake (special characters in passwords) correctly and provides scaling + frame capping for free.
- Reconnection: if the stream dies, the agent waits `EDGEGUARD_RECONNECT_DELAY` (3 s) and reopens.
- **Stream watchdog** (`vision.stream_timeout`, default 15 s): a session can hang silently mid-frame (TCP ESTABLISHED, no data) — the watchdog reads incrementally on a non-blocking pipe with a whole-frame deadline and reconnects hung sessions.
- **Per-camera credentials**: each camera entry can carry its own `user`/`password` (e.g. the D340W doorbell uses `admin` + its own password — not the shared one). Falls back to the shared `CAMERA_PASSWORD`.
- The Pi broadcaster picks up the camera's events automatically (`edgeguard/#`), so unknown people at any camera trigger the same announcements — add the camera id to `CAMERA_LOCATIONS` in `voice/config.py` for a nice location label.

### Live cameras

| camera_id | Camera | Path | Notes |
|---|---|---|---|
| `back_yard` | Reolink RLC-510A (.183) | `/Preview_01_main` | wired, stable |
| `garage` | Reolink RLC-410W (.184) | `/h264Preview_01_main` | wired, stable; also feeds the garage-door monitor |
| `front_door` | Reolink D340W doorbell (.32) | `/h264Preview_01_main` | WiFi — RTSP drops ~1/min, auto-reconnects; 960×720 |

When 2+ faces are in one frame, the agent additionally publishes `multiple_faces_detected` (with `face_count`) — the event that feeds time-slot `alerts:` rules.

### Finding the stream URL (Reolink)

The default path in the config was discovered via **ONVIF** (some Reolink models use non-standard paths):

```bash
.venv/bin/python -c "
from onvif import ONVIFCamera
cam = ONVIFCamera('<ip>', 8000, '<user>', '<password>')
media = cam.create_media_service()
for p in media.GetProfiles():
    uri = media.GetStreamUri({'StreamSetup': {'Stream': 'RTP-Unicast',
          'Transport': {'Protocol': 'RTSP'}}, 'ProfileToken': p.token})
    print(p.Name, '->', uri.Uri)
"
```

RLC-510A at YARD_CAMERA_IP reports: main = `rtsp://…/Preview_01_main`, sub = `…/Preview_01_sub`.

### Configuration

Cameras are defined in `cameras/config.py` (or override with `EDGEGUARD_CAMERAS` as JSON):

```python
CAMERAS = [
    {
        "id": "back_yard",          # becomes the MQTT camera_id + topic
        "host": "YARD_CAMERA_IP",
        "port": 554,
        "user": "edgeguard",
        "path": "/Preview_01_main",  # use the SUB stream for face detection
        "transport": "tcp",          # tcp (default) or udp
    },
    {
        "id": "front_door",          # per-camera credentials: doorbell uses
        "host": "192.168.2.32",      # admin + its OWN password (not shared)
        "user": "admin",
        "password": "…",             # overrides the shared CAMERA_PASSWORD
        "path": "/h264Preview_01_main",
    },
]
```

| Env var | Default | Purpose |
|---|---|---|
| `EDGEGUARD_CAMERA_PASSWORD` | — | RTSP password (shared, or per-camera `"password"` key) |
| `EDGEGUARD_CAMERAS` | default list | JSON array overriding `CAMERAS` |
| `EDGEGUARD_FRAME_WIDTH` | `1280` | Detection frame width cap |
| `EDGEGUARD_FRAME_HEIGHT` | `720` | RTSP stream scale height |
| `EDGEGUARD_FRAME_RATE` | `2` | Processed frames per second per camera |
| `EDGEGUARD_RECONNECT_DELAY` | `3.0` | Reconnect wait after stream failure |

> **Tip:** for face detection use the **sub stream** (`Preview_01_sub`) — lower bitrate, plenty of resolution (720p) for detection. Note: keep an eye on the camera's failed-login lockout — repeated bad attempts lock the account for a few minutes.

### Running

```bash
EDGEGUARD_CAMERA_PASSWORD='...' .venv/bin/python -m cameras.main   # CPU pipeline (any machine)
python3 -m jetson_gpu.main                                         # GPU pipeline (Jetson, TRT)
```

On the Jetson the service runs the **TensorRT GPU variant** (`jetson_gpu.main`, system Python 3.6, detached via `setsid` + `set -a` + `cameras.env`; systemd unit `edgeguard-cameras-gpu` ready but not installed — needs sudo). Verify: `pgrep -f jetson_gpu.main`, `grep -c "GPU inference" /tmp/jetson_cameras_gpu.log`, `tegrastats | grep GR3D_FREQ`.

Verified live: all 3 cameras open (back_yard 960×720, garage 1280×720, front_door 960×720 @ 2 fps, GPU inference ~40 ms); events/snapshots flow through the exact same pipeline as the USB camera when faces appear.

---

