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

# Ad-hoc announcement command topic: the broadcaster listens here
# for {"text": "..."} (or raw text) and speaks it on all speakers
SAY_TOPIC = get(
    "broker",
    "say_topic",
    default="edgeguard/command/say",
)

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
ANNOUNCE_RECOGNIZED = get_bool(
    "voice",
    "announce_recognized",
    default=True,
)

# Announce when an unknown person is detected
ANNOUNCE_UNKNOWN = get_bool(
    "voice",
    "announce_unknown",
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

# --- Alert rules ---
#
# Multi-face / time-slot alert rules. Each rule watches one camera for
# a given event type with min_faces and fires the message to the given
# speakers when the current time is inside one of the time_slots.
#
#   id:          unique rule id (used for cooldown bookkeeping)
#   camera:      camera_id to watch (e.g. "front_door")
#   event:       event_type that triggers the rule
#               (e.g. "multiple_faces_detected")
#   min_faces:   minimum face_count in the event payload
#   time_slots:  list of {"start": "01:00", "end": "05:00"};
#               overnight ranges (start > end) wrap past midnight
#   speakers:    cast speaker friendly names to broadcast to
#   local:       also play on the local (Pi) speaker
#   cooldown:    seconds between alerts from the same rule
#   message:     text spoken (through the same Polly/cast pipeline)

ALERTS = get(
    "alerts",
    default=[],
)


def _slot_minutes(value: str) -> int:

    """Parse "HH:MM" (24 h) into minutes since midnight."""

    try:

        hours, minutes = value.split(":")

        return int(hours) * 60 + int(minutes)

    except (ValueError, AttributeError):

        raise ValueError(
            f"Invalid time slot time: {value!r} "
            "(expected \"HH:MM\")"
        ) from None


def time_in_slots(now, slots) -> bool:

    """True if the current time falls in any time slot.

    `now` is a time.struct_time / datetime with .tm_hour/.tm_min
    (or .hour/.min). Overnight slots (start > end) wrap midnight.
    """

    if not slots:

        return True

    now_min = (
        getattr(
            now,
            "tm_hour",
            getattr(now, "hour", 0),
        )
        * 60
        + getattr(
            now,
            "tm_min",
            getattr(now, "min", 0),
        )
    )

    for slot in slots:

        start = _slot_minutes(slot["start"])

        end = _slot_minutes(slot["end"])

        if start <= end:

            if start <= now_min < end:
                return True

        else:

            # overnight: wraps past midnight
            if now_min >= start or now_min < end:
                return True

    return False


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