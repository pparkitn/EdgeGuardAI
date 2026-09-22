from pathlib import Path

from edgeguard_config import (
    get,
    get_bool,
    get_float,
    get_int,
    get_list,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- MQTT (the event bus; the broker runs on the Jetson) ---

MQTT_HOST = get(
    "broker",
    "host",
    default="JETSON_IP",
)

MQTT_PORT = get_int(
    "broker",
    "port",
    default=1883,
)

MQTT_TOPIC = get(
    "broker",
    "topic_prefix",
    default="edgeguard",
) + "/#"

# --- AWS Polly ---

POLLY_REGION = get(
    "voice",
    "polly_region",
    default="us-east-1",
)

POLLY_VOICE = get(
    "voice",
    "polly_voice",
    default="Brian",
)

# --- Audio cache ---

AUDIO_DIR = Path(
    get(
        "voice",
        "audio_dir",
        default=str(PROJECT_ROOT / "data" / "audio"),
    )
)

# --- HTTP server (serves cached audio to cast speakers) ---

HTTP_PORT = get_int(
    "voice",
    "http_port",
    default=8000,
)

# --- Google Cast speakers (friendly names, from discovery) ---

SPEAKERS = get_list(
    "speakers",
    default=[
        "Kitchen speaker",
        "Kitchen Speaker",
        "Natalia speaker",
        "Bedroom  speaker",
    ],
)

# --- Local playback (speaker attached to this machine, e.g. Pi 3.5mm) ---

LOCAL_PLAYBACK = get_bool(
    "voice",
    "local_playback",
    default=True,
)

# --- Announcement policy ---

# Announce when a known person is recognized
# (unknown-person events are always announced)
ANNOUNCE_RECOGNIZED = get_bool(
    "voice",
    "announce_recognized",
    default=True,
)

# Minimum seconds between announcements of the same event type
ANNOUNCEMENT_COOLDOWN = get_float(
    "voice",
    "announcement_cooldown",
    default=60.0,
)

# Stop whatever is playing on cast speakers (e.g. Spotify)
# before broadcasting an announcement
INTERRUPT_PLAYBACK = get_bool(
    "voice",
    "interrupt_playback",
    default=True,
)

# If a known person was recognized on the same camera within
# this many seconds, suppress the unknown-person announcement
# (false-alarm reduction for head turns / partial occlusions)
UNKNOWN_GRACE_PERIOD = get_float(
    "voice",
    "unknown_grace_period",
    default=30.0,
)

# Wait this many seconds after an unknown detection before
# announcing it, to see if the person gets recognized. If a known
# person is recognized on the same camera in the meantime, the
# unknown announcement is cancelled.
UNKNOWN_CONFIRM_DELAY = get_float(
    "voice",
    "unknown_confirm_delay",
    default=60.0,
)

# --- Announcement templates ---

TEMPLATES = get(
    "announcements",
    "templates",
    default={
        "unknown_person_detected": (
            "Security alert. An unknown person has been "
            "detected at {location}."
        ),
        "person_recognized": (
            "Welcome home, {person_id}."
        ),
    },
)

CAMERA_LOCATIONS = get(
    "announcements",
    "camera_locations",
    default={},
)

# --- Scheduled announcements ---

SCHEDULED_MESSAGES = get(
    "schedule",
    default=[],
)