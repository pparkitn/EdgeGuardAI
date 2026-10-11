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

---

### Session Learnings (2026-10-04)

**Configurable unknown-person announcements**

- User asked to stop speakers announcing unknown-person detections. Added `ANNOUNCE_UNKNOWN` (`voice/config.py`, from `voice:announce_unknown`, default `true` so existing setups are unchanged) and an early-return in `Broadcaster.handle_event` for `unknown_person_detected` (`voice/broadcaster.py`) — when disabled, no confirm-delay timer is even scheduled, so nothing is spoken. Camera events + snapshots are unaffected (recording happens on the Jetson pipeline, not the Pi).
- Test added (`tests/test_broadcaster.py::test_unknown_not_announced_when_disabled`); 64 tests pass, ruff clean.
- Deployed live: `PI_HOST=192.168.2.168 ./scripts/deploy_voice.sh` (rsync code), `announce_unknown: false` added under `voice:` in `/home/pi/edgeguard/config.yaml`, `sudo systemctl restart edgeguard-voice` → active; startup log clean (MQTT/Polly/pygame/HTTP all up).
- Note: `voice/config.py` no longer carries the "(unknown-person events are always announced)" comment — unknown announcements are now policy-controllable like recognized ones.
- Committed + pushed as `9abf72e` ("feat: configurable unknown-person announcements + remote control docs").

**Remote control of a running OpenCode session from a phone**

- Added `docs/remote-opencode-tailscale-ssh-tmux.md` (moved from repo root, linked in README docs table): run OpenCode inside a `tmux` session on the laptop, install Tailscale on laptop + phone, `ssh <user>@<tailscale-hostname>` then `tmux attach -t <project>` — the phone drives the SAME TUI session (no web server, no port forwarding, no second process). `tmux` keeps the agent running when SSH drops. Optional `oc()` shell helper creates/attaches a session named after the current directory. Security: keys + Tailscale only, keep all addresses/creds as placeholders in docs.

---

### Session Learnings (2026-10-10)

**Time-slot alert rules (multi-face at night) + front-door camera**

- User wanted: front-house camera, 2+ faces during early-morning hours, broadcast to specific devices (Pi local + Bedroom speaker, but configurable). Chose: FrontDoor Reolink at `192.168.2.32`, 01:00–05:00, min 2 faces, 10 min cooldown.
- **Design**: per-identity events are throttled 10 s per name (2 unknown faces in one frame collapse to ONE `unknown_person_detected`), so "multiple people" can't be derived reliably from per-identity events. Instead the camera agent now publishes a frame-level **`multiple_faces_detected`** event with a `face_count` (`cameras/agent.py::_publish_multiple_faces`, throttled 10 s, added to both CPU and Jetson GPU pipelines since both share `CameraAgent`). `events.py::build_event` gained an optional `face_count` kwarg (backward compatible).
- **Alert engine** lives on the Pi broadcaster: `voice/config.py` `ALERTS` (from `alerts:` in config, empty default) + `time_in_slots()` helper (HH:MM, `start > end` wraps midnight). `Broadcaster._check_alerts()` runs at the top of `handle_event` — matches camera/event/min_faces/time-slot/per-rule cooldown, then fires the targeted `say(message, speakers=..., local=...)` (same path as the scheduler). Per-rule `cooldown` (default 600 s) is independent of the generic `announcement_cooldown`.
- 15 new tests (`tests/test_alerts.py` + 2 in `test_events.py`): slot parsing, overnight slots, rule firing/ignoring (camera/event/face_count/slot), cooldown, speaker/local passthrough. 79 total, ruff + compileall clean.
- **Deploy (live)**:
  - Jetson: camera creds differ from the shared Reolink password — the doorbell uses `admin` + its OWN password. Reolink locks ~5 min after bad RTSP attempts, so the first successful probe after ~10 bad attempts looked like continued 401s. `build_url` (`cameras/stream.py`) already supports a per-camera `password` (falls back to the shared `CAMERA_PASSWORD`), so the `front_door` entry carries `user: admin` + `password` directly in the Jetson's gitignored `config.yaml` (like the Bravia PSK). Deployed `cameras/*.py` + `events.py` (`deploy_cameras_gpu.sh` — the `pip install` step hangs on the Jetson but rsync completes first), restarted the service with the process-group kill + `set -a` setsid pattern. All 3 cameras opened (front_door 960x720 @ 2 fps, GPU inference ~40 ms).
  - Pi: `deploy_voice.sh`, added the `alerts:` rule (`night_front_door`) to the Pi `config.yaml`, `sudo systemctl restart edgeguard-voice` → active; `from voice.config import ALERTS` confirms the rule loaded.
- **Front-door D340W caveat**: the WiFi doorbell's RTSP **drops ~1/min and auto-reconnects** (watchdog/reconnect handles it; only `front_door` does this — the 2 wired Reolinks are stable). Likely weak WiFi on the doorbell. Model: Reolink Video Doorbell WiFi D340W (UID `9527000IKX0F18CT`, DB_566128M5MP_W).

**Doorbell siren (D340W built-in alarm)**

- The doorbell has a built-in siren; RTSP does NOT expose it. Reolink's HTTP CGI API controls it: `AudioAlarmPlay` with `alarm_mode: "manul"` + `manual_switch: 1|0` + `times`.
- **Auth gotcha**: the CGI `Login` needs the password **plaintext with `"action": 0`** in the JSON (`[{"cmd":"Login","action":0,"param":{"User":{"userName":"admin","password":"<plaintext>"}}}]`). Base64-encoded password → `-502 password wrong`; MD5 → `-4 param error` — yet RTSP works with the same creds. This is the newer firmware's web API (Vue UI), different from the old base64 flow. Login response `value.Token.name` = session token (1 h lease, send as `&token=<name>`).
- Also: the doorbell's **RTSP password can differ from the web/admin password** — the siren API needs the admin one (the admin password works for both on this device; the other Reolinks' `edgeguard` user does NOT exist on the doorbell).
- Built `doorbell.py` (repo root, mirrors `bravia.py` style): `DoorbellClient` (login + `trigger_siren(enable)`), CLI `python -m doorbell siren on|off`; config `doorbell:` section (host/port/user/password, `EDGEGUARD_DOORBELL_*` overrides; password in gitignored per-device config like the Bravia PSK). `scripts/siren.py on|off` CLI mirrors `say.py`/`plug.py`.
- Alert rules can now set `siren: true` → `Broadcaster._check_alerts()` sounds the doorbell via `DoorbellClient().trigger_siren(True)` (errors logged, never crash the alert path).
- `scripts/deploy_voice.sh` now ships `bravia.py` + `doorbell.py` to the Pi (the broadcaster imports both at runtime).
- Verified live 2026-10-10: trigger + stop returned `rspCode: 200`, user confirmed the siren sounded. `doorbell:` section added to dev + Pi configs; Pi broadcaster restarted; smoke test `scripts/siren.py off` → `OFF (ok)`.

**CI restored to green (was red since 2026-09-25)**

- Root cause: `tests/test_broadcaster.py`/`test_alerts.py` import `voice.broadcaster` → `voice.cast` (module-level `import pychromecast`) and `voice.polly` (module-level `import boto3`); `tests/test_jetson_gpu_*` import modules that `import cv2`. `requirements-dev.txt` deliberately has none of these.
- Fix: lazy `import pychromecast` inside `SpeakerManager.discover()`, lazy `import boto3`/`botocore` inside `PollyClient` (module import must not require AWS), and `pytest.importorskip("cv2")` at the top of the 3 jetson tests (they already used it inside individual tests). CI compile step also covers `doorbell.py`/`bravia.py`. Local CI mirror (`python3 -m venv /tmp/opencode/ci-venv` + `requirements-dev.txt`): 70 passed, 3 skipped — matches GitHub Actions.

**Garage door open/closed detection (2026-10-11)**

- User asked: can the garage camera tell whether the two garage doors are open/closed? Verified yes — the camera is a fixed RLC-410W whose frame contains both door panels (user confirmed; ROIs drawn on a still and user-verified).
- Built `garage_doors.py` (repo root, CI-safe — cv2 imported lazily inside functions): per-door ROIs (config, frame fractions), one-shot ffmpeg still capture (`capture_still`, py36-safe subprocess), `roi_mads()` (grayscale Gaussian blur on 640-wide downsample, mean absolute diff), `classify()`/`hysteresis()` (open requires MAD > `threshold`, closed requires MAD < `close_threshold`), adaptive **reference refresh** (`refresh_reference`/`refresh_cycles` — while BOTH doors stay closed, re-snapshot the baseline every N cycles so day/night drift doesn't eat into the margin).
- CLI: `python -m garage_doors reference|check|calibrate|monitor`. `calibrate` saves an annotated still with the ROI boxes for user verification. Monitor publishes **retained** state to `edgeguard/garage/doors` (JSON `{"left": "open|closed", "right": "..."}`, QoS 1, change-only). Py36 gotcha: argparse `add_subparsers(required=True)` TypeError → manual `if args.command is None` check.
- **Measured live** (dev machine capturing the garage camera): closed baseline MAD 0.6–0.8 (frame vs its own reference), closed-with-lighting-drift up to ~15 (later in the day, eased by re-capturing the reference / adaptive refresh), fully-open door MAD **55–60** per ROI; my initial guess of threshold 25 sits comfortably between the classes (mid-transition frames read ~10–13 — the monitor polls every 15 s and hysteresis + the door staying open settles the state). Note: an open door did NOT crosstalk to the other ROI via exposure (normalization test: gains differed, MADs stayed; both doors were genuinely open).
- Verification session: reference captured (both closed) → check = closed/closed (0.6/0.7) → user opened door(s) → check = open readings (55–60) → user closed both → check = closed/closed after re-capturing the reference at the new lighting. Thresholds NOT tuned from default (25/12) — separation is 5x+.
- Deployed: `garage_doors.py` + reference JPEG to the Jetson, monitor running detached (`setsid` + `set -a` + cameras.env pattern, log `/tmp/garage_doors.log`, PID via `pgrep -f "garage_doors monitor"`). Retained state readable at any time: subscribe `edgeguard/garage/doors`. The dev machine's `config.yaml` gained the shared per-camera password so `check`/`calibrate` work from there too.
- 13 unit tests (`tests/test_garage_doors.py`: MAD math, hysteresis open/stay/close, adaptive refresh trigger); 12 pass + cv2 pair skipped in the CI minimal venv.

**Garage door announcements on the Pi (2026-10-11)**

- User asked the Pi to speak garage door state changes. Added a `garage_doors_announce:` config section (enabled, speakers — empty = all, local, cooldown 30 s, `open`/`closed` templates with `{side}` = left|right) and routing in `Broadcaster._on_message` for the exact topic `edgeguard/garage/doors` (payload has no event_type so it never reached `handle_event`/`_check_alerts`).
- `_handle_garage_doors()`: first message after (re)start — the retained one — only sets `last_garage_state` baseline and is NOT spoken (matches the `announce_unknown`/alerts philosophy of no restart noise); only real left/right transitions announce, throttled by the garage-door cooldown keyed in `last_announcement["garage_door"]`; both-doors change → one sentence per door; malformed/unknown payloads ignored.
- Deployed: `deploy_voice.sh` + `garage_doors_announce:` in the Pi config.yaml + `sudo systemctl restart edgeguard-voice`. Verified: config loads (topic `edgeguard/garage/doors`, enabled), startup journal shows `Garage door baseline: {'left': 'closed', 'right': 'closed'}` with NO announcement. Ready for the user's live open-the-door test.
- 6 new broadcaster tests (baseline, open change, both change, no-change, malformed, cooldown); 15 in test_broadcaster.py total.
- **Local-only follow-up (same day)**: user wanted garage announcements on the Pi speaker ONLY, not Google devices. My first implementation converted an empty `speakers: []` to `None` (`or None`) — which delivery treats as "all cast speakers" (first live test: "Google Cast: played on 3 of 3 targeted speaker(s)" — unwanted). Fix: pass the config list through unchanged — `delivery.py` already treats `speakers == []` as "Google Cast disabled for this announcement" (the scheduler's local-only semantics). Default is now `[]` (local-only); named lists cast. Verified live after redeploy: "The left garage door is closed." → "Google Cast disabled for this announcement". New test asserts `speakers == []` + `local is True` passthrough. Committed `87e8905`.

**Credential leak found & purged from git history (2026-10-11)**

- User asked to verify everything was committed/pushed and that docs were current. Audit found the docs were stale (README still said "2 cameras", "15 announcements"; devices/camera-service/deployment docs predated the doorbell/siren/alerts/garage/Kasa work) AND — worse — **`docs/development-log.md` contained two plaintext passwords committed and pushed today** in `5b06615`: the doorbell web/admin password and the shared camera password (one in the siren section, one in the garage-deploy section). `config.yaml` and `AGENTS.md` were correctly gitignored (only `config.yaml.example` is tracked); the leak was purely from writing real values into the dev log.
- **Purge workflow that works** (git-filter-repo NOT installed → `git filter-branch`):
  1. Redact the working tree FIRST, commit normally (commit `7a20d36` also brought all 4 stale docs up to date: README/devices/camera-service/deployment).
  2. `FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch --force --tree-filter 'python3 /tmp/opencode/redact_secrets.py' --prune-empty -- --all` — a tiny python script that binary-replaces the secret strings with `[REDACTED]` across every tree (binary-safe, no sed `$` escaping hell).
  3. **Gotcha: `rm -rf .git/refs/original` is NOT enough** — filter-branch's backup refs also live in `.git/packed-refs`; the old commits stay reachable via `git log --all` until you `git update-ref -d refs/original/refs/heads/main` (+ `refs/original/refs/remotes/origin/main`).
  4. `git reflog expire --expire=now --all && git gc --prune=now`; verify with `git log --all --format=%h -S "<secret>" -- . | wc -l` (NOTE: `git log` exits 0 even with zero matches — always count, don't check `$?`). Belt-and-braces: `git rev-list --all --objects` → `git cat-file` every blob → grep.
  5. Push: filter-branch rewrites the LOCAL `origin/main` ref, so the first `--force-with-lease` fails with "stale info" — `git fetch origin` first, then `git push --force-with-lease origin main` succeeds.
- Verify remotely afterwards: `git fetch && git log origin/main -S "<secret>" -- . | wc -l` → 0.
- Remaining risk: GitHub can keep the old (unreachable) objects; **the two passwords were exposed publicly and should be rotated** (doorbell web/admin password + shared Reolink camera password → update `config.yaml` on dev + Jetson `cameras.env`). Documented but NOT rotated — pending user action.
- Face DB verified while updating docs: `data/embeddings/faces.npz` now holds **12 people / 50 embeddings** (README table updated).

**Garage door false-"open" alarm — root cause & hardening (2026-10-11, code fix)**

- Symptom: Pi announced the garage door "open" at ~17:29 while both doors were closed (user report); retained topic stuck on `{"left":"open","right":"open"}`.
- **Bug 1 — reference refresh crash-loop**: `garage_doors.py` refresh path had `tmp_ref, fd2 = tempfile.mkstemp(...)` — `mkstemp()` returns `(fd, path)`, so `fd2` was the *path string* and `os.close(fd2)` threw `TypeError: an integer is required` on the Jetson (log showed the error every cycle for minutes → the monitor was effectively dead-but-alive). The adaptive re-baselining (40 closed cycles = 10 min) therefore **never ran** since deployment → the reference stayed the noon frame.
- **Bug 2 — stale reference + dusk drift**: by evening the *closed* doors measured MAD 38–46 vs the noon reference (crossing `threshold: 25`) → false "open". Verified from the dev machine: `left=38.1, right=45.7` with doors closed. Re-capturing the reference at 18:57 (doors closed) gave MAD 0.4/0.4.
- **Gotcha 3 — hysteresis dead-zone trap**: a door in the 12–25 band stays "open" forever (`close_threshold` never reached) — the log showed `right` stuck at 16.2 for 8 min. Combined with the dead refresh, the state can't heal on its own.
- Fixes (all in `garage_doors.py`, 112 tests green):
  1. `mkstemp` unpacking fixed (`fd2, tmp_ref`).
  2. **`confirm_cycles` (default 2)**: "open" needs N consecutive cycles above threshold — one-cycle transients (shadows/headlights/exposure jumps) can no longer announce. `decide_states()` is a pure, tested state machine replacing bare hysteresis in the loop (with counters).
  3. **`stuck_open_cycles` (default 6)**: a reported-open door whose MAD stays *below* threshold for 6 cycles = measurement no longer supports "open" → falls back to "closed" (drift healing; unblocks the 40-cycle refresh timer which `consecutive_closed` otherwise resets forever).
  4. **`normalize_lighting` (default true)**: per-ROI mean-brightness alignment before the MAD — kills uniform brightness swings (RLC-410W IR cut-filter day/night switch at dusk, auto-gain ramping). Measured at 19:02 (dusk): closed MAD went from raw 25–28 back to **1.8/1.1** after redeploy. An IR-switch step change had pushed the freshly-recaptured reference to 27–28 *two minutes* after capture — normalization is what actually fixed tonight.
  5. **Atomic reference writes** (`os.replace` via temp files): `save_reference()` used to report "Reference saved" on a *stale* file when ffmpeg failed (401 mis-env) — the 13:00 file masqueraded as fresh at 18:57.
- Refresh adoption guard: candidate frame must measure ≤ `refresh_max_mad` (default 50) vs the current reference per ROI — blocks absorbing an actually-open door (measured open ≥ 55) while passing drift (≤ ~46).
- Ops gotchas hit live: `pgrep -f 'garage_doors monitor'` matches the ssh wrapper itself (kill it and you kill your own session — use `pgrep -f 'garage_doors [m]onitor'`); the monitor launched via `setsid` must be killed by its own pid-group (`kill -9 -<pid>`), not the wrapper's; `check`/`reference`/`calibrate` on the Jetson need `set -a && . ./cameras.env && set +a` (camera creds live in the env, not the Jetson's config.yaml).
- Deployed to the Jetson (md5-verified), monitor restarted, retained `edgeguard/garage/doors` = `{"left":"closed","right":"closed"}` at 19:02. Door opens now need 2 cycles (~30 s) before announcing — brief pop-open-close may not announce (acceptable trade for no false alarms).
