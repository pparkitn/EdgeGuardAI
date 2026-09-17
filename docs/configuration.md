# EdgeGuard AI - Configuration

> Part of the [EdgeGuard AI](../README.md) documentation.
> Everything is configured centrally in [`config.yaml`](../config.yaml).

## Central Configuration

**One file, every device, every setting.** Git-pull the repo on any machine, start the service you want — it reads `config.yaml` to reach all other devices. No per-machine config editing.

```yaml
broker:        # Jetson - the MQTT event bus
  host: JETSON_IP
  port: 1883
jetson:        # host/user for SSH/deploy
raspberry_pi:  # host/user/remote_dir + zigbee broker
cameras:
  usb:         # index, resolution, camera_id
  rtsp:        # list: id/host/port/user/path/transport (Reolink...)
vision:        # thresholds, margins, frame size/rate, reconnect
speakers:      # Google Home friendly names (the cast targets)
voice:         # polly voice/region, http port, local playback,
               # interrupt playback, cooldown, announce policy
announcements: # text templates + camera location labels
schedule:      # scheduled announcements (time/days/every + text)
zigbee:        # device inventory (ieee -> location/type) for reference
```

**How components use it:**

| Component | Reads from | Env override example |
|---|---|---|
| `face_recognition` | `broker.*`, `cameras.usb.*`, `vision.*` | `EDGEGUARD_CAMERA_ID` |
| `cameras` (Reolink) | `cameras.rtsp`, `vision.*` | `EDGEGUARD_CAMERA_PASSWORD` |
| `voice` (broadcaster) | `speakers`, `voice.*`, `announcements.*`, `schedule` | `EDGEGUARD_SPEAKERS="a,b"` |

**Override rules:**

- Env vars win over the file. Full path form `EDGEGUARD_VOICE_POLLY_VOICE` or short form `EDGEGUARD_POLLY_VOICE` both work (`voice/config.py` etc. use the `edgeguard_config.get(...)` helper).
- **Secrets never live in the repo** — camera password via `EDGEGUARD_CAMERA_PASSWORD`, AWS via the standard credential chain.
- The deploy script ships `config.yaml` + `edgeguard_config.py` to the Pi automatically.

**Workflow:** edit `config.yaml` → commit/push → on each device `git pull` → restart the service. Verified live: the Pi broadcaster picked up speakers + schedule from the central file (4/4 cast, announcements working).

---

## Repository Structure

```
edgeguard-ai/
├── README.md              # this document
├── requirements.txt       # all deps (vision + voice)
├── requirements-vision.txt  # camera pipeline deps
├── requirements-voice.txt   # broadcaster deps
├── .gitignore             # keeps faces/embeddings/models out of git
│
├── config.yaml           # ⭐ central config: devices, cameras, speakers, schedule
├── edgeguard_config.py   # config loader (config.yaml + env overrides)
├── events.py             # shared MQTT event bus (publisher + event schema)
├── enroll.py             # CLI: enroll all people from data/faces/
│
├── face_recognition/     # 🎥 USB camera vision module
│   ├── camera.py         #   Camera: OpenCV capture wrapper
│   ├── detector.py       #   FaceDetector: insightface buffalo_l
│   ├── recognizer.py     #   FaceRecognizer: cosine-similarity matching
│   ├── database.py       #   FaceDatabase: faces.npz load/save
│   ├── enrollment.py     #   enroll_person / enroll_all
│   ├── main.py           #   live camera loop (detect -> recognize -> publish)
│   └── mqtt.py           #   re-exports events.py (backward compat)
│
├── cameras/              # 📷 IP/RTSP camera module (Reolink etc.)
│   ├── config.py         #   camera list + frame settings (from config.yaml)
│   ├── stream.py         #   RtspStream: ffmpeg RTSP decoder
│   ├── agent.py          #   CameraAgent: per-camera detect/recognize/publish
│   └── main.py           #   entry: run one agent per camera
│
├── voice/                # 🔊 voice broadcast module
│   ├── broadcaster.py    #   main loop: MQTT -> announcement -> delivery
│   ├── scheduler.py      #   daily/weekly/interval announcements
│   ├── delivery.py       #   two channels: local speaker + Google Cast
│   ├── polly.py          #   PollyClient: boto3 TTS
│   ├── audio_cache.py    #   text-hash -> MP3 cache
│   ├── cast.py           #   SpeakerManager: Google Cast discovery + play
│   ├── local_player.py   #   pygame playback on this machine's speaker
│   ├── announcements.py  #   event -> announcement text templates
│   └── config.py         #   reads everything from config.yaml
│
├── scripts/              # 🛠️ ops tooling
│   ├── mqtt_monitor.py   #   live terminal viewer for MQTT events
│   ├── deploy_voice.sh   #   deploy the voice module to the Pi
│   └── deploy_cameras.sh #   deploy the cameras module to the Jetson
│
├── deploy/               # systemd units
│   ├── edgeguard-voice.service    # Pi broadcaster service
│   └── edgeguard-cameras.service  # Jetson camera service
│
├── docs/                 # setup guides
│   └── create_aws_poly.md
│
├── data/                 # runtime data (faces, embeddings, audio — git-ignored)
├── models/               # (empty) reserved for model files
├── tests/                # pytest tests
└── logs/                 # runtime logs (git-ignored)
```
│   ├── broadcaster.py     # main loop: MQTT -> announcement -> delivery
│   ├── scheduler.py       # daily/weekly/interval announcements
│   ├── delivery.py        # two channels: local speaker + Google Cast
│   ├── polly.py           # PollyClient: boto3 TTS with error handling
│   ├── audio_cache.py     # AudioCache: text-hash -> MP3 files
│   ├── cast.py            # SpeakerManager: Google Cast discovery + play
│   ├── local_player.py    # LocalPlayer: pygame playback (Pi 3.5mm jack)
│   ├── announcements.py   # event -> announcement text templates
│   └── config.py          # env-driven speakers, voice, templates, cooldown
│
├── face_recognition/
│   ├── __init__.py
│   ├── config.py          # all settings (camera, thresholds, MQTT)
│   ├── camera.py          # Camera: OpenCV capture wrapper
│   ├── detector.py        # FaceDetector: insightface buffalo_l wrapper
│   ├── recognizer.py      # FaceRecognizer: cosine-similarity matching
│   ├── database.py        # FaceDatabase: faces.npz load/save
│   ├── enrollment.py      # enroll_person / enroll_all from image dirs
│   ├── mqtt.py            # MqttPublisher: JSON events -> broker
│   └── main.py            # live camera loop: detect -> recognize -> publish
│
├── models/                # (empty) reserved for model files
├── data/
│   ├── faces/<name>/      # enrollment photos per person (git-ignored)
│   ├── unknown_faces/     # auto-captured unknown-person crops (git-ignored)
│   └── embeddings/        # faces.npz — stored embeddings (git-ignored)
│
├── tests/                 # pytest tests (pending implementation)
└── logs/                  # (empty) reserved for runtime logs
```

---

