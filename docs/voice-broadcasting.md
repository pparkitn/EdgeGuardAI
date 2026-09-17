# EdgeGuard AI - Voice Broadcasting

> Part of the [EdgeGuard AI](../README.md) documentation.
> Everything is configured centrally in [`config.yaml`](../config.yaml).

## Voice Broadcasting

The broadcaster listens to the MQTT event bus and turns security events into **spoken announcements** on the Google Home/Nest speakers around the house.

### Flow

```
MQTT event (edgeguard/#)
        │
        ▼
Broadcaster (voice/broadcaster.py)
        ├── decide: template + cooldown
        ▼
Announcement text
        │
        ▼
AWS Polly (neural, voice: Brian)
        │
        ▼
MP3 (cached in data/audio/)
        │
        ▼
Local HTTP server (:8000)
        │
        ▼
Google Cast → speakers (3x)
```

### Speakers (discovered on the LAN)

| Friendly name | Device | IP |
|---|---|---|
| `Kitchen speaker` (lowercase s) | Google Nest Mini | KITCHEN_SPEAKER_IP |
| `Kitchen Speaker` (capital S) | Google Home Mini | KITCHEN_SPEAKER2_IP |
| `Natalia speaker` | Google Home Max | NATALIA_SPEAKER_IP |
| `Bedroom  speaker` (double space) | Google Home | BEDROOM_SPEAKER_IP |

Names are exact and case-sensitive (the two Kitchen speakers differ only by capitalization) — see `SPEAKERS` in `voice/config.py`. Discovery is by friendly name, so DHCP IP changes don't matter.

### Running

The broadcaster runs on the **Raspberry Pi** as a systemd service (auto-start + auto-restart):

```bash
# from any machine - deploy/update the Pi (also installs the service with INSTALL_SERVICE=1)
AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... \
  EDGEGUARD_MQTT_HOST=JETSON_IP \
  INSTALL_SERVICE=1 ./scripts/deploy_voice.sh

# manage on the Pi
ssh pi@PI_IP
sudo systemctl status edgeguard-voice
journalctl -u edgeguard-voice -f
```

Local development (any machine): `AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... .venv/bin/python -m voice.broadcaster`

The broadcaster is self-contained: it embeds the HTTP server that serves cached audio to the cast speakers, discovers cast speakers once at startup, plays locally via pygame when a speaker is attached to the machine, and subscribes to `edgeguard/#`.

### Behavior

| Event | Action |
|---|---|
| `unknown_person_detected` | announced: *"Security alert. An unknown person has been detected at the front entrance."* |
| `person_recognized` | logged only (`ANNOUNCE_RECOGNIZED = False` by default) |
| Unknown event types | ignored |

- **Two independent delivery channels** (`voice/delivery.py`): the audio is always sent to both the machine's **local speaker** (`EDGEGUARD_LOCAL_PLAYBACK`, pygame) and the **Google Cast speakers** (`EDGEGUARD_SPEAKERS`); each is optional, logged separately ("Local playback: ...", "Google Cast: played on N of M speaker(s)") and isolated from the other's failures.
- **Delivery worker thread**: playback never blocks the MQTT callback — announcements are queued and delivered on a background thread.
- **Cooldown**: max one announcement per event type every `ANNOUNCEMENT_COOLDOWN` (60 s) — prevents alert spam while a person stands in frame.
- **Audio cache**: each announcement text is synthesized once; identical text reuses the MP3 (SHA-256 filename in `data/audio/`, git-ignored).
- **Graceful degradation** (no crashes):
  - Polly down / bad credentials → announcement skipped, pipeline continues
  - Speaker offline → other speakers still get the audio
  - MQTT down → broadcaster reconnects (1–30 s backoff)
- Logs to console + `logs/broadcaster.log` (or journald under systemd).

### Components (`voice/`)

| Module | Purpose |
|---|---|
| `broadcaster.py` | Main loop: MQTT subscription, HTTP server, decision + cooldown |
| `scheduler.py` | `Scheduler` — daily/weekly/interval announcements (`schedule` lib) |
| `delivery.py` | `DeliveryWorker` — two independent channels (local + cast) on a background thread |
| `polly.py` | `PollyClient` — boto3 synthesis with retry-safe error handling |
| `audio_cache.py` | `AudioCache` — text-hash → MP3 persistence |
| `cast.py` | `SpeakerManager` — one-time discovery, `play_url()` to speakers |
| `local_player.py` | `LocalPlayer` — pygame playback on this machine's speaker |
| `announcements.py` | Event → announcement text templates |
| `config.py` | Env-driven speakers, voice, templates, cooldown, schedules, ports |

### Scheduled Announcements

The broadcaster fires **scheduled messages** (daily, weekly, or interval-based) through the same pipeline as security events. Each entry lives in `config.yaml` → `schedule` and supports **per-entry speaker targeting** and a **local playback flag** (ported from the legacy HomeAuto scheduler):

```yaml
schedule:
  - time: "07:10"                      # 24h, local time
    speakers: ["Natalia speaker"]      # cast ONLY to these; absent = ALL speakers
    local: false                       # false = don't play on this machine's speaker
    text: "Good morning, Magda! Have a wonderful day."

  - time: "08:44"                      # local-only entry
    speakers: []                       # empty list = no Google Cast
    local: true
    text: "Time to get ready for school, kids!"

  - every: 3600                        # interval instead of time/days
    text: "Hourly status check."
```

- `days` accepts full or short weekday names (`monday`…`sunday` / `mon`…`sun`); omitted = every day.
- All 15 legacy HomeAuto announcements (school, Kumon, dishwasher, climbing, bedtime…) are ported with their original times and speaker targets — see `config.yaml`. "Family Room speaker" was dropped (not on the LAN anymore).
- Not ported (not voice announcements): the Zigbee wall-plug ON/OFF control, IP reporting, Google Sheets jobs, and the expired vacation countdown.
- Verified live: a targeted test announcement played on the Kitchen Speaker only.

### Configuration (`voice/config.py`)

| Setting | Default | Purpose |
|---|---|---|
| `SPEAKERS` | 3 speaker names | Cast targets (exact names) |
| `POLLY_VOICE` | `Brian` | Neural voice |
| `POLLY_REGION` | `us-east-1` | AWS region |
| `ANNOUNCE_RECOGNIZED` | `False` | Also announce known-person events |
| `ANNOUNCEMENT_COOLDOWN` | `60.0` | Seconds between same-type announcements |
| `HTTP_PORT` | `8000` | Audio server port (speakers pull from here) |
| `TEMPLATES` / `CAMERA_LOCATIONS` | — | Announcement text + camera → location labels |

### AWS Credentials

Credentials come from the **standard AWS chain** (env vars or `~/.aws/credentials`) — never from the repo. Example:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
```

### Verified (2026-09-15/16)

- Speaker discovery: all 4 cast speakers found by exact name ✓
- Cast playback: MP3 played on all 4 speakers ✓
- End-to-end (single machine): `unknown_person_detected` MQTT event → Polly synthesis → MP3 cached → announcement audible on 4 speakers ✓
- Cooldown: repeat events within 60 s suppressed ✓
- `person_recognized` suppressed while `ANNOUNCE_RECOGNIZED=False` ✓
- Cache hit: same text reuses cached MP3 (no second Polly call) ✓
- **Cross-machine (Pi as broadcaster)**: dev machine published event → Jetson broker → Pi systemd service → Polly → **local Pi speaker + 4 Google Home speakers** all played ✓
- **Independent delivery channels** (after refactor): one event → `voice.delivery` logged "Local playback: played … on this machine's speaker" **and** "Google Cast: played on 4 of 4 speaker(s)" — both channels fired, separate logs, delivery on a worker thread (MQTT callback never blocks) ✓

> **Design note (vs. the old HomeAuto code):** the reference implementation hardcoded AWS keys in source, re-discovered Chromecasts on every play, exited on Polly errors, and played to a fixed speaker list. EdgeGuard AI reads credentials from the AWS chain, discovers speakers once, caches audio, degrades gracefully, and is fully config-driven.

---

