# EdgeGuard AI - Deployment

> Part of the [EdgeGuard AI](../README.md) documentation.
> Everything is configured centrally in [`config.yaml`](../config.yaml).

## Running the System

### Component map (what runs where)

| Component | Device | How it starts | Auto-restart |
|---|---|---|---|
| MQTT broker (event bus) | **Jetson** | systemd `mosquitto` | ✅ (boot) |
| Reolink camera service | **Jetson** | `python -m cameras.main` / systemd `edgeguard-cameras` | optional |
| USB camera pipeline | **dev machine** | `python -m face_recognition.main` (GUI) | manual |
| Voice broadcaster | **Pi** | systemd `edgeguard-voice` | ✅ (boot + crash) |
| Zigbee2MQTT + Pi broker | **Pi** | Docker (`zigbee2mqtt`, `zigbee2mqt_mqtt_1`) | ✅ (docker restart) |
| MQTT monitor / tools | any | `scripts/mqtt_monitor.py` | manual |

---

### Jetson (JETSON_IP) — broker + Reolink cameras

**1. MQTT broker** — already a system service; nothing to do:

```bash
ssh pparkitn@JETSON_IP
systemctl status mosquitto        # should be: active
```

**2. Reolink camera service**

*Step A — first-time setup (one-time per device; already done on this Jetson):*

```bash
mkdir -p ~/edgeguard
rsync -az --exclude '.venv' --exclude '.git' --exclude 'data' \
  ./ ~/edgeguard/                # or: git clone/pull on the device
~/py38env/bin/pip install -r requirements-vision.txt
mkdir -p ~/edgeguard/data/embeddings ~/edgeguard/data/unknown_faces
rsync -az data/embeddings/faces.npz ~/edgeguard/data/embeddings/
# set the system ffmpeg in the Jetson's local config.yaml:
#   vision:ffmpeg_path: /usr/bin/ffmpeg
```

*Step B — start it now (manual, foreground; Ctrl+C to stop):*

```bash
cd ~/edgeguard
EDGEGUARD_CAMERA_PASSWORD='...' \
  ~/py38env/bin/python -u -m cameras.main
```

*Step C — make it survive reboots (systemd service):*

```bash
# 1. credentials/settings file (no sudo needed, permissions locked)
printf 'EDGEGUARD_FFMPEG_PATH=/usr/bin/ffmpeg\nEDGEGUARD_CAMERA_PASSWORD=...\n' \
  > ~/edgeguard/cameras.env && chmod 600 ~/edgeguard/cameras.env

# 2. install + start the service (the one command you need):
sudo cp ~/edgeguard/deploy/edgeguard-cameras.service /etc/systemd/system/ \
  && sudo systemctl daemon-reload \
  && sudo systemctl enable --now edgeguard-cameras
```

After any reboot the camera service comes back automatically. Verify:

```bash
systemctl status edgeguard-cameras        # active (running)
journalctl -u edgeguard-cameras -f        # live logs
ss -tn | grep :554                        # RTSP connections to the cameras
```

**How the camera service works** (`deploy/edgeguard-cameras.service`):

| Setting | Value | Why |
|---|---|---|
| `WorkingDirectory` | `/home/pparkitn/edgeguard` | so `cameras.main` finds `config.yaml`, `data/`, models |
| `EnvironmentFile` | `~/edgeguard/cameras.env` | secrets/settings outside the repo: `EDGEGUARD_FFMPEG_PATH` (Jetson has no imageio ffmpeg binary → system `/usr/bin/ffmpeg`) and `EDGEGUARD_CAMERA_PASSWORD` (perms 600) |
| `ExecStart` | `~/py38env/bin/python -m cameras.main` | Python 3.8 venv with the vision deps (Jetson's system Python 3.6 can't run insightface) |
| `Restart=always` | — | auto-restart 10 s after any crash |
| `WantedBy=multi-user.target` | — | starts on every boot |

Manage it like any service: `systemctl status|restart|stop edgeguard-cameras`, `journalctl -u edgeguard-cameras -f`. Everything else (cameras, thresholds, MQTT) comes from `config.yaml` — edit + `git pull` + restart.

Remove the service (if ever needed): `sudo systemctl disable --now edgeguard-cameras && sudo rm /etc/systemd/system/edgeguard-cameras.service && sudo systemctl daemon-reload`

Remove the service (if ever needed): `sudo systemctl disable --now edgeguard-cameras && sudo rm /etc/systemd/system/edgeguard-cameras.service && sudo systemctl daemon-reload`

---

### Raspberry Pi (PI_IP) — voice broadcaster + zigbee

**1. Voice broadcaster** — already deployed and running:

```bash
ssh pi@PI_IP
sudo systemctl status edgeguard-voice            # active
sudo systemctl restart edgeguard-voice           # restart
journalctl -u edgeguard-voice -f                 # live logs
```

Update it from any machine (rsync + pip + optional service install):

```bash
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
  INSTALL_SERVICE=1 ./scripts/deploy_voice.sh
```

**2. Zigbee2MQTT + broker** — Docker containers, auto-start:

```bash
sudo docker ps    # zigbee2mqtt + zigbee2mqt_mqtt_1 should be Up
```

---

### Dev machine — USB camera pipeline + tools

**1. USB camera pipeline** (GUI window, press `q` to quit):

```bash
cd <repo>
.venv/bin/python -m face_recognition.main
```

**2. Enroll new people:**

```bash
.venv/bin/python enroll.py    # after adding photos to data/faces/<name>/
rsync -az data/embeddings/faces.npz pparkitn@JETSON_IP:~/edgeguard/data/embeddings/   # share to Jetson
```

**3. Watch the event bus:**

```bash
.venv/bin/python scripts/mqtt_monitor.py
```

---

### Verify it's working (end to end)

| Check | Command | Expect |
|---|---|---|
| Broker up | `mosquitto_sub -h JETSON_IP -t edgeguard/# -v` | live events as people appear |
| Events | `.venv/bin/python scripts/mqtt_monitor.py` | colorized stream + summary |
| Jetson cameras | `ssh pparkitn@JETSON_IP 'tail -f /tmp/jetson_cameras.log'` (or `journalctl -u edgeguard-cameras -f`) | detection lines |
| Broadcast (Pi) | `ssh pi@PI_IP 'journalctl -u edgeguard-voice -f'` | announcements + playback lines |
| Speakers | audio from the Pi speaker + Google Home devices | announcement text |
| Snapshots | `ls data/unknown_faces/<camera_id>/` | new crops for unknown people |

**Walk in front of any camera:** GUI label + FPS (USB) or a `[camera_id]` line (RTSP) → MQTT event in the monitor → spoken announcement on the Pi speaker + Google Homes.

### Adding more camera machines

Any number of computers with cameras can join — each one only needs to publish to the broker. The Pi broadcaster announces everything regardless of source machine.

On each new camera machine:

```bash
# one-time setup
python3 -m venv .venv
.venv/bin/pip install -r requirements-vision.txt

# enroll a copy of the shared face database (or the machine's own)
# copy data/embeddings/faces.npz from any existing machine

# run with this machine's camera identity
EDGEGUARD_CAMERA_ID=back_door \
EDGEGUARD_MQTT_HOST=JETSON_IP \
  .venv/bin/python -m face_recognition.main
```

- `EDGEGUARD_CAMERA_ID` names the camera (appears in topic `edgeguard/camera/<id>` and in the announcement text).
- Add human labels for new cameras in `voice/config.py` → `CAMERA_LOCATIONS` (e.g. `"back_door": "the back door"`); unknown ids fall back to the raw id with underscores as spaces.
- Everything else is shared: one broker (Jetson), one broadcaster (Pi), one set of speakers. Verified live with a second camera id: announcement correctly said *"…at the back door"* and played on the Pi speaker + all 4 Google Homes.

### Stopping

- Camera pipeline: press `q` in the preview window.
- Broadcaster (Pi): `sudo systemctl stop edgeguard-voice` (or `disable` to stop it starting on boot).
- Monitor: `Ctrl+C` (prints its summary).

### Requirements

| File | For | Packages |
|---|---|---|
| `requirements-vision.txt` | camera pipeline machine | numpy, opencv-python, insightface, onnxruntime, scikit-learn, paho-mqtt |
| `requirements-voice.txt` | broadcaster machine (Pi) | paho-mqtt, pychromecast, boto3, pygame |
| `requirements.txt` | dev machine (everything) | includes both files above |

---

## Deployment Hardware: Jetson Xavier NX

The system runs on a dedicated **NVIDIA Jetson Xavier NX Developer Kit** on the local network.

### SSH Access

```bash
ssh pparkitn@JETSON_IP
```

- Key-based authentication (no password prompt when keys are set up on the client).
- The Jetson answers on the LAN at `JETSON_IP` (hostname `pparkitn-desktop`).
- Newer OpenSSH clients print a *post-quantum key exchange* warning on connect — harmless, just a client/server cipher negotiation notice.
- `sudo` on the device requires a password (no passwordless sudo).
- Useful on-device tools: `tegrastats` (GPU/CPU/memory/temps), `jetson_clocks` (max clocks), `nvpmodel` (power mode).

### Board & Hardware

| Component | Details |
|---|---|
| Board | NVIDIA Jetson Xavier NX Developer Kit (board ID `t186ref`) |
| Hostname | `pparkitn-desktop` |
| CPU | 6-core NVIDIA Carmel ARMv8.2-A 64-bit, up to 1.9 GHz |
| GPU | Volta, 384 CUDA cores + 48 Tensor Cores (6 TFLOPS FP16) |
| Memory | 8 GB LPDDR4x (7.6 GB visible) |
| eMMC | 119 GB (system boot media) |
| NVMe | 1 TB Crucial CT1000P2SSD8 — **root filesystem runs from NVMe** (`/dev/nvme0n1p1`, 916 GB; 312 GB free) |
| Cooling | Fan, quiet profile; idle temps ~42 °C CPU / ~41.5 °C GPU |
| Power mode | `MODE_15W_6CORE` (15 W, all 6 cores) |

### Software Stack

| Component | Version |
|---|---|
| JetPack / L4T | JetPack 4.4 (L4T R32.4.4, GCID 23942405, Oct 2020) |
| OS | Ubuntu 18.04.6 LTS |
| Kernel | 4.9.140-tegra |
| CUDA | 10.2.89 |
| TensorRT | 7.1.3 |
| OpenCV | 4.1.1 (prebuilt `libopencv`), `python3-opencv` 3.2.0 |
| Python | 3.6.9 (system), pip 21.3.1 (user install) |
| Docker | 24.0.2 |
| Monitoring | `tegrastats`, `jetson_clocks`, `nvpmodel` |

### Network

- LAN IP: `JETSON_IP` (`eth0`), also `wlan0`, `docker0`, and a VPN `tun0` interface present.
- Docker bridges (`docker0`, `br-*`) already in use on the device.
- No camera attached yet — no `/dev/video*` devices present (Phase 1 pending).

### Notes for the Vision Stack

JetPack 4.4 pins the software baseline: **CUDA 10.2 + TensorRT 7.1 + Python 3.6**. Any face-detection/recognition model and inference runtime chosen for the camera pipeline must be compatible with this combination (e.g. TensorRT 7 engines, Python 3.6 wheels, Jetson-era OpenCV builds).

---

