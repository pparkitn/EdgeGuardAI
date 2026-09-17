# EdgeGuard AI - Development Log

> Part of the [EdgeGuard AI](../README.md) documentation.
> Everything is configured centrally in [`config.yaml`](../config.yaml).

## Development Log

Session notes and findings from hands-on work with the codebase.

### Environment (dev machine)

| Item | Detail |
|---|---|
| OS | Linux, Python 3.14.4, pip 25.1.1 |
| Virtualenv | `.venv/` at repo root (git-ignored) |
| Face stack | `insightface` 2.0 (buffalo_l), `onnxruntime` 1.30 (CPU), `opencv-python` 5.0.0.93, `numpy` 2.5.3, `scikit-learn` 1.9.1 |
| GPU | None on dev machine — detector runs on `CPUExecutionProvider` |
| Camera | USB camera present: `/dev/video0`, `/dev/video1` (dev machine only; Jetson has no camera yet) |

### Face Enrollment

- `python enroll.py` scans every subdirectory of `data/faces/`, detects one face per image, and stores embeddings in `data/embeddings/faces.npz`.
- **12 people / 42 embeddings** enrolled: alex, basia, janusz, magda, marcin, michael, natalia, oksana, piotr, teresa, tomek, wojtek.
- michael's original photos (HEIC-derived JPGs) contained **no detectable faces**; replacing them with fresh PNGs worked (2 of 3 enrolled; one image had multiple faces and was skipped).
- `data/faces/` and `data/embeddings/` are git-ignored — face photos and embeddings stay out of the repo.

### Camera Pipeline

- `python -m face_recognition.main` opens the camera, runs detection + recognition per frame, draws boxes/labels and live FPS, quits on `q`.
- Each recognized/unknown person is published to MQTT (`edgeguard/camera/front_entrance`) — see [Architecture → MQTT](architecture.md#mqtt-event-publishing).
- Every **unknown person** also gets a face-crop snapshot saved to `data/unknown_faces/` (timestamped filename, throttled with the MQTT events, git-ignored) — a growing raw library you can later organize into named folders and re-run `enroll.py` to build a proper identity.
- Verified working on the dev machine (model + DB load, camera streams, GUI renders, events delivered to the Jetson broker).
- When piping stdout, Python buffers it — use `python -u` to see startup messages live.
- `QFontDatabase: Cannot find font directory ...` warnings from OpenCV Qt are cosmetic.

### Full End-to-End Verification (2026-09-15)

Ran subscriber + live camera pipeline together:

| Stage | Result |
|---|---|
| Enrollment | 12 people / 42 embeddings in `faces.npz` ✓ |
| Camera pipeline | live capture, detection, recognition (`piotr` at conf 0.56–0.71) ✓ |
| MQTT publishing | 7 throttled events over a 45 s run ✓ |
| Broker delivery | all 7 events received on `edgeguard/camera/front_entrance` from JETSON_IP, 1:1 match ✓ |
| Throttling | known-person events ~10 s apart; Unknown events interleaved on identity change ✓ |
| Cleanup | no stray processes after shutdown ✓ |

### Known Issues

1. **Batch enrollment aborts on first failure** — `enroll_all()` raises when one person has no valid embeddings, so later people (alphabetically/filesystem-order later) are skipped. Fix: skip-and-report instead of raising.
2. **michael's old photos are useless for enrollment** — keep the replacement PNGs.

### Session Learnings (2026-09-16)

Hands-on findings across the multi-machine system, cameras, and speakers.

**Raspberry Pi (voice broadcaster host)**

- Raspbian 11 (bullseye), Python 3.9.2, 922 MB RAM, passwordless sudo, internet OK.
- Already runs Docker: `zigbee2mqtt` (koenkk image) + its own `eclipse-mosquitto` broker (ports 1883/9001) — a **second broker** on the LAN alongside the Jetson's.
- Legacy HomeAuto stack runs there too (`ReadMQTT.py`, `googlecast.py`, an `http.server` on :8000). Our broadcaster took over port 8000 (the legacy server had to be killed).
- Local audio: bcm2835 3.5 mm jack (`aplay -l` → "Headphones"). pygame's mixer needs the OS package `libsdl2-mixer-2.0-0` — installed after `ImportError: libSDL2_mixer-2.0.so.0`.
- Deploy via `scripts/deploy_voice.sh`: rsync `voice/`+`common.py` → venv (`requirements-voice.txt`) → `voice.env` (AWS + `EDGEGUARD_*` overrides) → systemd unit `deploy/edgeguard-voice.service` (`sudo systemctl enable --now edgeguard-voice`). ALSA "underrun" messages during playback are cosmetic.

**Google Cast speakers**

- Cast speakers are identified by exact friendly name (case-sensitive): "Kitchen speaker" (Nest Mini, .133) vs "Kitchen Speaker" (Home Mini, .43) are *different devices*; "Bedroom  speaker" has a double space.
- Discovery is by name, so DHCP IP changes don't matter (Bedroom moved .40 → .39).
- **Silent cast failure:** `play_media` + `block_until_active()` can "succeed" while the speaker reverts to its existing session (e.g. Spotify on the Natalia speaker) — audio never plays but the call returns. Fix: `media.stop()` first (interrupt), then verify each speaker is `PLAYING` *our* URL (`content_id`) before counting it. See `voice/cast.py`.
- First discovery run can miss recently-powered-on speakers — re-run discovery / restart the service.

**Reolink RLC-510A (YARD_CAMERA_IP)**

- Ports: 80/443 (web UI behind nginx), 554 (RTSP), 1935 (RTMP — unusable, always I/O error), 8000 (ONVIF gSOAP), 9000.
- **Standard Reolink RTSP paths (`/h264/ch01/main`, …) return 404** on this firmware. The real paths came from ONVIF `GetStreamUri`: `/Preview_01_main` (H.264, 2560×1920, 30 fps) and `/Preview_01_sub`. Query with `onvif-zeep` (works with plaintext creds).
- RTSP accepts the credentials (401 with wrong password) but the HTTP API login (`/cgi-bin/api.cgi?cmd=Login`) rejects even correct creds (tried plain, MD5, SHA256, with/without `action:0`) — don't rely on it.
- **Account lockout:** repeated failed logins lock the RTSP stream for ~5 min (even correct creds → 401). The `auth_warning_info.remain_times` counter in API responses counts down.
- **PyAV cannot open the stream** — its bundled FFmpeg sends the `%40`-encoded password literally → 401. The ffmpeg CLI (static binary via `imageio-ffmpeg`) handles it correctly, so `cameras/stream.py` uses an ffmpeg pipe (auto size-probe, `scale`, `-r` cap → raw BGR frames).
- Password containing `@` must be percent-encoded (`%40`) in the RTSP URL.

**Camera service (`cameras/` package)**

- One `MqttPublisher` per camera — the topic must match the camera id (`edgeguard/camera/back_yard`), not the shared default (`front_entrance`); events carry the same id in the payload.
- `cameras/main.py` is headless: stream → detect → recognize → publish → snapshots (`data/unknown_faces/<camera_id>/`), auto-reconnect after failures.
- Verified live: recognized `piotr` from the yard camera and published the event; unknown faces saved snapshots.

**Zigbee sensors (reading them over MQTT)**

- Sensors live on the Pi's broker (`PI_IP:1883`), not the Jetson's. Zigbee2MQTT publishes each device's full state to `zigbee2mqtt/<ieee_address>` as JSON, e.g.:
  ```json
  {"battery":100,"battery_low":false,"contact":true,"linkquality":191,"tamper":false,"voltage":3200}
  ```
  - `contact`: door/window state (true = closed), `battery`/`battery_low`/`voltage`: power, `linkquality`: LQI radio signal, `tamper`: case-open flag.
- **Sleeping sensors only publish on state change** — subscribing and waiting gets nothing from idle devices until a door opens (the backyard/side door sensors are silent in the same window where garage/main door reported).
- The `zigbee2mqtt` frontend API (port 8080) returned a non-JSON/error response without auth; reading state via MQTT subscription is the reliable path. The device list itself lives in the container's `/app/data/configuration.yaml` (5 devices: 4 door contacts + 1 wall plug).
- Main door sensor battery is at **0%** — needs a new battery (confirmed live).

**Ops footguns (mea culpa)**

- `pkill -f '<pattern>'` matches its own command line (the bash wrapper contains the pattern) → kills the shell. Use `pkill -f '[c]lassname'` or `pgrep` + explicit PID.
- Backgrounding over ssh: `nohup … &` + shell exit can kill the child; `(setsid cmd &)` detaches reliably. For production use systemd, not manual backgrounding.
- Python buffers stdout when piped — use `-u` for live logs.

### Jetson Deployment Constraints (verified)

- JetPack 4.4 pins **Python 3.6.9, CUDA 10.2, TensorRT 7.1**.
- `insightface` and `onnxruntime` are **not pip-installable** on Python 3.6; the Jetson needs `onnxruntime-gpu` wheels built for aarch64/JetPack 4.4, or a Jetson-era alternative (e.g. TensorRT-optimized models via `jetson-inference`, which is already present in `~/jetson-inference` on the device).
- The Jetson has **no camera attached** (`/dev/video*` absent) — Phase 1 (connect camera) is still pending on the device.

---


### Session Learnings (2026-09-17)

**CI / quality tooling**

- GitHub Actions workflow (`.github/workflows/test.yml`): ruff → compileall → pytest on push/PR. No hardware needed — the tests mock by design: MQTT (publisher returns `False` when offline), and Polly/Google Cast/cameras are never imported (minimal `requirements-dev.txt` means boto3/pychromecast/insightface/opencv can't even install).
- 27 unit tests cover recognizer (cosine), database (save/load), events (schema/topics), config (env overrides), scheduler (targeting).
- `pyproject.toml`: `[tool.pytest.ini_options] pythonpath=["."]` is required so tests can import root modules; ruff select `E4,E7,E9,F,I` kept fixes small (26 auto-fixed: import sorting + unused imports).
- Verified locally in a clean venv with only dev deps — mirrors CI exactly.

**Performance (measured on the Jetson, CPU-only onnxruntime)**

- Detection (buffalo_l, det 640): **439 ms avg / 448 ms p95** — 99 % of frame time.
- Recognition (cosine, 12 people / 42 embeddings): **2.7 ms avg / 3.4 ms p95** — negligible.
- Full-pipeline throughput: **2.29 FPS** (437 ms/frame) — comfortably above the configured 2 FPS.
- MQTT LAN round-trip: **9.2 ms avg / 21.0 ms p95**.
- Memory: **~750 MB** RSS (vision pipeline incl. models); CPU ~2.4 cores during inference.
- `scripts/benchmark_jetson.py` reproduces these; TensorRT/GPU is the documented next step (est. 5–10×).

**Repo hygiene / public exposure**

- Private LAN IPs and Zigbee IEEE (MAC) addresses are now **completely absent** from the public repo: README, docs, config, and *all git history*. Twice-rewritten history (`git filter-branch` then full squash) — after `filter-branch`, remember to delete `refs/original/*` and expire reflogs or old objects stay alive.
- `config.yaml` (real IPs) is **gitignored**; the repo ships `config.yaml.example` with placeholders (`JETSON_IP`, `PI_IP`, `CAMERA_USER`, `..._IEEE`). `edgeguard_config.py` falls back to the example if absent; deploy scripts never overwrite a device's real config.
- User-facing docs keep placeholders even for usernames (`JETSON_USER`, `PI_USER`, `CAMERA_USER`).

**Git operations footguns**

- Squashing history to a single commit: `git checkout --orphan tmp && git add -A && git commit && git branch -M tmp main && git tag -f v1.0.0 -m ...` then force-push main + tag. Verify with `git ls-remote`.
- `git tag` has **no `-q` flag** (only `git commit` does).
- `gh` CLI absent and no `GITHUB_TOKEN` → release creation must be done via the web UI (`/releases/new?tag=v1.0.0`).
- GitHub Actions can show stale runs/caches after force-push; workflow file name doesn't matter (`test.yml` = `ci.yml`).

**Documentation discipline**

- Claims must match implementation: reworded "correlates camera + Zigbee" → "designed around event correlation … Zigbee integration under development"; README documents 4 speakers everywhere (stale "3" fixed in architecture.md/deployment.md/voice-broadcasting.md).
- Rebranded as **"Distributed Edge AI Security Platform"** (job-search positioning); added Reliability section (async delivery + isolated channels), measured Performance section, note that demo face images aren't in the repo.
- Architecture PDF (`docs/EdgeGuard_AI_Architecture.pdf`) added and linked; repo has a single commit + single `v1.0.0` tag.
