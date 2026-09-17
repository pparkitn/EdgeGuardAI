# EdgeGuard AI - Getting Started

> Part of the [EdgeGuard AI](../README.md) documentation.
> Everything is configured centrally in [`config.yaml`](../config.yaml).

## Getting Started

### 1. Setup the environment

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2. Add face photos

Each person needs a directory under `data/faces/<name>/` with 3–5 good-quality photos (one face per photo, clearly visible).

### 3. Enroll faces

```bash
.venv/bin/python enroll.py
```

Creates/stores all embeddings in `data/embeddings/faces.npz` (git-ignored).

### 4. Run the camera pipeline

```bash
.venv/bin/python -m face_recognition.main
```

Press `q` in the preview window to quit. Every recognized/unknown person is published to MQTT (see [Architecture → MQTT](architecture.md#mqtt-event-publishing)).

### 5. Watch the events

```bash
mosquitto_sub -h JETSON_IP -t edgeguard/# -v
```

Or use the built-in live monitor (colorized, with a summary on Ctrl+C):

```bash
.venv/bin/python scripts/mqtt_monitor.py
.venv/bin/python scripts/mqtt_monitor.py --topic 'edgeguard/camera/#' --host JETSON_IP --port 1883
```

The monitor prints every event on `edgeguard/#` as it arrives — known people in green, unknown detections in red — and keeps per-type/ per-person counters shown in a summary when you stop it with Ctrl+C.

---

