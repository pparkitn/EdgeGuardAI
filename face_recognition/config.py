from pathlib import Path

from edgeguard_config import (
    get,
    get_float,
    get_int,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Paths ---

FACE_DIR = PROJECT_ROOT / "data" / "faces"
EMBEDDING_DIR = PROJECT_ROOT / "data" / "embeddings"

EMBEDDING_FILE = EMBEDDING_DIR / "faces.npz"

# Unknown-face snapshots (for later enrollment)
UNKNOWN_FACES_DIR = PROJECT_ROOT / "data" / "unknown_faces"

# Padding added around the face bbox when saving snapshots
UNKNOWN_FACE_MARGIN = get_float(
    "vision",
    "unknown_face_margin",
    default=0.15,
)

# --- USB camera ---

CAMERA_INDEX = get_int(
    "cameras",
    "usb",
    "index",
    default=0,
)

CAMERA_WIDTH = get_int(
    "cameras",
    "usb",
    "width",
    default=1280,
)

CAMERA_HEIGHT = get_int(
    "cameras",
    "usb",
    "height",
    default=720,
)

# --- Recognition ---

# Recognition threshold.
# We will calibrate this later using your actual camera.
RECOGNITION_THRESHOLD = get_float(
    "vision",
    "recognition_threshold",
    default=0.55,
)

# Minimum face detection confidence
DETECTION_THRESHOLD = get_float(
    "vision",
    "detection_threshold",
    default=0.60,
)

# --- Display ---

WINDOW_NAME = "EdgeGuard AI - Face Recognition"

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

# Camera identifier used in MQTT topic and events
CAMERA_ID = get(
    "cameras",
    "usb",
    "camera_id",
    default="front_entrance",
)

# Events are published to: edgeguard/camera/<CAMERA_ID>
MQTT_TOPIC_PREFIX = get(
    "broker",
    "topic_prefix",
    default="edgeguard",
)

# Re-publish an event for a still-present person after this many seconds
MQTT_REPUBLISH_INTERVAL = get_float(
    "vision",
    "republish_interval",
    default=10.0,
)