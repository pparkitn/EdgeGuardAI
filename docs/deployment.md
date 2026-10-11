# EdgeGuard AI - Deployment

> Part of the [EdgeGuard AI](../README.md) documentation.
> Everything is configured centrally in [`config.yaml`](../config.yaml).

## Running the System

### Component map (what runs where)

| Component | Device | How it starts | Auto-restart |
|---|---|---|---|
| MQTT broker (event bus) | **Jetson** | systemd `mosquitto` | ✅ (boot) |
| Reolink camera service (GPU) | **Jetson** | `python -m jetson_gpu.main` (detached, `setsid` + `set -a`) / systemd `edgeguard-cameras-gpu` (ready, needs sudo to install) | ⚠️ detached (manual) / ✅ once installed |
| Garage door monitor | **Jetson** | `python -m garage_doors monitor` (detached, log `/tmp/garage_doors.log`) | ⚠️ detached (manual) |
| USB camera pipeline | **dev machine** | `python -m face_recognition.main` (GUI) | manual |
| Voice broadcaster | **Pi** | systemd `edgeguard-voice` | ✅ (boot + crash) |
| Kasa plug controller | **Pi** | systemd `edgeguard-kasa` | ✅ (boot + crash) |
| Zigbee2MQTT + Pi broker | **Pi** | Docker (`zigbee2mqtt`, `zigbee2mqt_mqtt_1`) | ✅ (docker restart) |
| MQTT monitor / tools | any | `scripts/mqtt_monitor.py`, `scripts/say.py`, `scripts/plug.py`, `scripts/siren.py` | manual |

---

### Jetson (JETSON_IP) — broker + Reolink cameras

**1. MQTT broker** — already a system service; nothing to do:

```bash
ssh pparkitn@JETSON_IP
systemctl status mosquitto        # should be: active
```

**2. Reolink camera service (GPU variant, running live)**

The Jetson runs the **TensorRT GPU pipeline** (`jetson_gpu.main` — TensorRT bindings are py36-only on JetPack 4.4, so it runs under the **system Python 3.6**, not `~/py38env`). Deploy with:

```bash
CONVERT_ENGINES=1 ./scripts/deploy_cameras_gpu.sh   # rsync + build TRT engines (or INSTALL_SERVICE=1 for systemd)
```

Manual (detached) launch — the `set -a` is **required** so `cameras.env` assignments reach the process:

```bash
cd ~/edgeguard && set -a && . ./cameras.env && set +a && \
  setsid bash -c "exec python3 -u -m jetson_gpu.main > /tmp/jetson_cameras_gpu.log 2>&1" \
  < /dev/null > /dev/null 2>&1 &
```

The CPU pipeline (`python -m cameras.main` under `~/py38env`) is the fallback — the GPU module drops back to onnxruntime automatically if the engines are missing.

**3. Garage door monitor** (publishes retained `edgeguard/garage/doors`):

```bash
cd ~/edgeguard && set -a && . ./cameras.env && set +a && \
  setsid bash -c "exec python3 -u -m garage_doors monitor > /tmp/garage_doors.log 2>&1" \
  < /dev/null > /dev/null 2>&1 &
```

First calibrate on the dev machine: `python -m garage_doors reference` (doors closed) → `calibrate` (verify ROI boxes) → `check`. The monitor publishes `{"left": "open|closed", "right": "open|closed"}` only on state change.

---

### Raspberry Pi (PI_IP) — voice broadcaster + zigbee

**1. Voice broadcaster** — already deployed and running:

```bash
ssh pi@PI_IP
sudo systemctl status edgeguard-voice            # active
sudo systemctl restart edgeguard-voice           # restart
journalctl -u edgeguard-voice -f                 # live logs
```

Update it from any machine (rsync + pip + optional service install; **always pass `PI_HOST=192.168.2.168`** — the script's default `PI_HOST` is the literal string `PI_IP`):

```bash
PI_HOST=192.168.2.168 \
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
  INSTALL_SERVICE=1 ./scripts/deploy_voice.sh
```

The broadcaster also: announces **garage door state changes** (`garage_doors_announce:` config — subscribes `edgeguard/garage/doors`, baseline-on-restart, local-only by default), fires **time-slot alert rules** (`alerts:` — e.g. `night_front_door`, optionally with `siren: true` → doorbell siren), and serves **ad-hoc announcements** (`edgeguard/command/say` via `scripts/say.py "text"`).

**2. Kasa plug controller** — systemd `edgeguard-kasa`, MQTT topic `edgeguard/command/plug/<name>` (`on|off|toggle|state`); CLI `python scripts/plug.py <name> on|off|toggle|state`.

**3. Zigbee2MQTT + broker** — Docker containers, auto-start:

```bash
sudo docker ps    # zigbee2mqtt + zigbee2mqt_mqtt_1 should be Up
```

### Doorbell siren (Reolink D340W)

The doorbell's built-in siren is controlled via the HTTP CGI API (`AudioAlarmPlay`) — it needs the **web/admin password** (can differ from the RTSP one), configured in `doorbell:` in the per-device `config.yaml` (gitignored):

```bash
python scripts/siren.py on|off      # from the dev machine
python -m doorbell siren on|off     # equivalent
```

Alert rules can also set `siren: true` to sound it automatically.

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
| Jetson cameras | `ssh pparkitn@JETSON_IP 'tail -f /tmp/jetson_cameras_gpu.log'` | `GPU inference: N ms` lines |
| Garage doors | `mosquitto_sub -h JETSON_IP -t edgeguard/garage/doors -v` | retained `{"left": "…", "right": "…"}` |
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
| `requirements-dev.txt` | CI / lint / tests | pytest, ruff (no AWS/cast deps — CI-safe) |

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
- No USB camera attached (`/dev/video*` absent) — the Jetson consumes the Reolink RTSP cameras only.

### Notes for the Vision Stack

JetPack 4.4 pins the software baseline: **CUDA 10.2 + TensorRT 7.1 + Python 3.6**. Any face-detection/recognition model and inference runtime chosen for the camera pipeline must be compatible with this combination (e.g. TensorRT 7 engines, Python 3.6 wheels, Jetson-era OpenCV builds).

---

