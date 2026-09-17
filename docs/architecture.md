# EdgeGuard AI - Architecture

> Part of the [EdgeGuard AI](../README.md) documentation.
> Everything is configured centrally in [`config.yaml`](../config.yaml).

## How the System Works

EdgeGuard AI is a **fully modular, event-driven pipeline**: each component is an independent process that can run on a different machine, communicating only through MQTT events. Nothing is hardwired to a single host.

### Machines & Roles

| Machine | IP | Runs | Required deps |
|---|---|---|---|
| **Dev machine** | — | `face_recognition` camera pipeline (currently; the camera is attached here) | `requirements-vision.txt` |
| **Jetson Xavier NX** | `JETSON_IP` | Mosquitto **MQTT broker** (the event bus) + Zigbee2MQTT target | none (system service) |
| **Raspberry Pi** | `PI_IP` | **voice broadcaster** (local speaker on 3.5 mm jack + Google Cast) and its own Zigbee2MQTT stack | `requirements-voice.txt` |

Any component can move: run the camera pipeline on the Jetson later, run the broadcaster on any machine with a speaker — only the MQTT broker address changes (env var).

### System Diagram

```
                    ┌──────────────────────────────────────┐
                    │  DEV MACHINE  (camera pipeline)      │
                    │                                      │
  USB Camera ─────► │  face_recognition package            │
   /dev/video0      │   camera.py / detector.py            │
                    │   recognizer.py / database.py        │
                    │                                      │
                    │   ├── GUI preview (cv2.imshow)       │
                    │   ├── MQTT publish (edgeguard/...)   │
                    │   └── unknown snapshots (data/)      │
                    └──────────────┬───────────────────────┘
                                   │  MQTT (1883)
                                   ▼
                    ┌──────────────────────────────────────┐
                    │  JETSON XAVIER NX (JETSON_IP)     │
                    │  Mosquitto MQTT broker  (event bus)  │
                    └──────────────┬───────────────────────┘
                                   │  MQTT (1883)
                                   ▼
                    ┌──────────────────────────────────────┐
                    │  RASPBERRY PI (PI_IP)        │
                    │  voice broadcaster (systemd service) │
                    │   edgeguard/# subscriber             │
                    │   ├── AWS Polly → MP3 (cached)       │
                    │   ├── local speaker (3.5mm jack)     │
                    │   ├── HTTP server (:8000)            │
                    │   └── Google Cast → 4 speakers       │
                    │                                      │
                    │  (also: Zigbee2MQTT + own broker)    │
                    └──────────────────────────────────────┘
```

### The Event Lifecycle

1. **Capture** — `Camera` reads a frame from the USB camera (1280×720).

2. **Detect** — `FaceDetector` runs insightface (`buffalo_l`) and returns face boxes + 512-d embeddings for each face.

3. **Recognize** — `FaceRecognizer` compares each embedding against every stored embedding (cosine similarity). Best match above `RECOGNITION_THRESHOLD` (0.55) → named; otherwise `Unknown`.

4. **Act** — for every face, the pipeline:
   - draws a box + label in the GUI preview,
   - publishes a JSON event to `edgeguard/camera/<camera_id>` (throttled: on identity change + every 10 s while present),
   - saves a face crop for `Unknown` faces into `data/unknown_faces/` (same throttle) — a raw library for later enrollment.

5. **Transport** — the Jetson's Mosquitto broker relays the event to any subscriber, on any machine (`mqtt_monitor.py`, the Pi broadcaster, future security engine, Home Assistant…).

6. **Broadcast** — the Pi's `voice.broadcaster` (systemd `edgeguard-voice`) subscribes to `edgeguard/#`; for announceable event types it applies a 60 s cooldown, renders the announcement text, synthesizes speech via AWS Polly (cached by text hash), then hands the audio to the **delivery worker**, which broadcasts it over **two independent channels**:
   - **local playback** — speaker attached to the Pi (3.5 mm jack, pygame),
   - **Google Cast broadcast** — the 4 Google Home/Nest speakers (MP3 served by the broadcaster's embedded HTTP server).

   Each channel has its own enable flag, logging and failure isolation — one can be down while the other still plays. Delivery runs on a background thread so the MQTT callback never blocks on playback.

### Event Example

```json
{
  "event_id": "evt_28cae03f3fe8",
  "event_type": "unknown_person_detected",
  "source": "camera",
  "camera_id": "front_entrance",
  "timestamp": "2026-09-15T15:18:02-04:00",
  "confidence": 0.71
}
```

→ announcement: *"Security alert. An unknown person has been detected at the front entrance."*

### Modularity Rules

- **Configuration is per-machine via environment variables** (see `common.py`, `face_recognition/config.py`, `voice/config.py`). Defaults target the current layout, but e.g. `EDGEGUARD_MQTT_HOST` redirects any component to another broker.
- **No shared state between machines** — the only coupling is the MQTT topic + JSON event schema.
- **Per-component requirements**: `requirements-vision.txt` (camera pipeline) and `requirements-voice.txt` (broadcaster) — a machine only installs what it runs (`requirements.txt` pulls in both for the dev machine).
- **N camera machines → 1 broadcaster**: the Pi subscribes to `edgeguard/#`, so every camera (any machine, any `CAMERA_ID`) triggers the announcement on the Pi speaker + all Google Homes. Verified live with two camera ids.

### Failure Semantics (reliability by design)

| Component fails | Behavior |
|---|---|
| MQTT broker down | Pipeline keeps running; events dropped with a log, reconnects automatically |
| AWS Polly down / bad creds | Announcement skipped; camera pipeline unaffected |
| Pi / broadcaster down | Events still published; nothing else affected |
| Speaker offline | Other speakers still receive the audio |
| Camera disconnects | Pipeline raises and exits cleanly (camera released) |
| No known people in DB | Everything still works; everyone is `Unknown` |

---

## MQTT Event Publishing

Every time the camera pipeline recognizes a person (or detects an unknown face), it publishes a structured JSON event to the MQTT broker. This is the first building block of the project's event-driven architecture: other components (security engine, Home Assistant, dashboards) consume these events by subscribing to the topic.

### Broker

Mosquitto runs on the **Jetson** (`JETSON_IP`) and is already active:

| Item | Value |
|---|---|
| Host | `JETSON_IP` |
| MQTT port | `1883` |
| WebSocket port | `9001` |
| Service | `mosquitto` (systemd, active) |
| Auth | none currently (default config) — see hardening note below |
| Zigbee2MQTT | already uses this broker (`~/zigbee2mqtt` on the Jetson) |

Verify from anywhere on the LAN:

```bash
mosquitto_sub -h JETSON_IP -t edgeguard/# -v
```

### Topic Structure

| Topic | Payload |
|---|---|
| `edgeguard/camera/<camera_id>` | face recognition events (one topic per camera) |

Example topic for the default camera: `edgeguard/camera/front_entrance`. Consumers can subscribe to `edgeguard/#` to receive everything.

### Event Schema

```json
{
  "event_id": "evt_28cae03f3fe8",
  "event_type": "person_recognized",
  "source": "camera",
  "camera_id": "front_entrance",
  "timestamp": "2026-09-15T15:18:02-04:00",
  "confidence": 0.93,
  "person_id": "piotr"
}
```

`event_type` is either:

- `person_recognized` — a known person (includes `person_id`)
- `unknown_person_detected` — face present but below `RECOGNITION_THRESHOLD` (no `person_id`)

### How It Works

1. `MqttPublisher` (`face_recognition/mqtt.py`) connects to the broker in a background thread (`connect_async` + `loop_start`) with automatic reconnection (1–30 s backoff).
2. `main.py` calls `publish_face_event()` for every detected face. Events are throttled so the broker isn't flooded at camera FPS:
   - an event is published when a face's identity **first appears**, and
   - re-published every `MQTT_REPUBLISH_INTERVAL` (10 s) while the same person stays in frame.
3. Broker failures never crash the pipeline — if MQTT is down, events are logged as dropped and the camera loop continues (matching the project's reliability goals).

### Configuration (`face_recognition/config.py`)

| Setting | Default | Purpose |
|---|---|---|
| `MQTT_HOST` | `JETSON_IP` | Broker address (Jetson) |
| `MQTT_PORT` | `1883` | Broker port |
| `CAMERA_ID` | `front_entrance` | Camera name used in topic + events |
| `MQTT_TOPIC_PREFIX` | `edgeguard` | Topic prefix |
| `MQTT_REPUBLISH_INTERVAL` | `10.0` | Seconds between re-publishes for a present person |
| `UNKNOWN_FACES_DIR` | `data/unknown_faces/` | Where unknown-person snapshots are saved |
| `UNKNOWN_FACE_MARGIN` | `0.15` | Padding added around the face crop |

### Testing

Watch events live while the pipeline runs:

```bash
# terminal 1 - subscriber
mosquitto_sub -h JETSON_IP -t edgeguard/# -v

# terminal 2 - pipeline
.venv/bin/python -m face_recognition.main
```

Or publish a synthetic event to verify the broker path (works without a camera):

```python
from face_recognition.mqtt import MqttPublisher, build_event

publisher = MqttPublisher()
publisher.connect()
publisher.publish(build_event("person_recognized", 0.93, "piotr"))
publisher.disconnect()
```

Verified end-to-end: detection → recognition → `edgeguard/camera/front_entrance` delivered to the Jetson broker with the schema above.

### Harden the Broker (TODO for production)

The Mosquitto instance currently has **no authentication** and listens on `0.0.0.0`. Before exposing the system further:

- add a password file (`mosquitto_passwd`) for the `edgeguard` publisher user and consumers,
- restrict listeners to the LAN if possible,
- add `allow_anonymous false` in `/etc/mosquitto/conf.d/`.

---

