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
- The Pi broadcaster picks up the camera's events automatically (`edgeguard/#`), so unknown people at any camera trigger the same announcements — add the camera id to `CAMERA_LOCATIONS` in `voice/config.py` for a nice location label.

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
EDGEGUARD_CAMERA_PASSWORD='...' .venv/bin/python -m cameras.main
```

Verified live: RLC-510A stream opened (2560×1920 native, scaled 960×720 @ 2 fps), 15 frames read cleanly, no errors; events/snapshots flow through the exact same pipeline as the USB camera when faces appear.

---

