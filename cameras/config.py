from pathlib import Path

from edgeguard_config import (
    get,
    get_float,
    get_int,
)
from face_recognition.config import (
    DETECTION_THRESHOLD,
    MQTT_HOST,
    MQTT_PORT,
    MQTT_REPUBLISH_INTERVAL,
    MQTT_TOPIC_PREFIX,
    RECOGNITION_THRESHOLD,
    UNKNOWN_FACES_DIR,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- Cameras ---
#
# Defined centrally in config.yaml -> cameras.rtsp (or override the
# whole list with EDGEGUARD_CAMERAS_RTSP as a JSON string).
#
#   id:       short name (also the MQTT camera_id, e.g. "back_yard")
#   host:     camera IP
#   port:     RTSP port (default 554)
#   user:     RTSP username
#   path:     RTSP stream path (get it via ONVIF GetStreamUri,
#             e.g. Reolink RLC-510A: /Preview_01_main, /Preview_01_sub)
#   transport: tcp (default) or udp

CAMERA_PASSWORD = get(
    "cameras",
    "rtsp",
    "password",
    default="",
    env="EDGEGUARD_CAMERA_PASSWORD",
)

CAMERAS = get(
    "cameras",
    "rtsp",
    default=[],
)

# --- Frame processing ---

# Frames are resized to this width before detection
FRAME_WIDTH = get_int(
    "vision",
    "frame_width",
    default=1280,
)

# Target frame height (streams are scaled to this)
FRAME_HEIGHT = get_int(
    "vision",
    "frame_height",
    default=720,
)

# Target frames per second processed per camera
FRAME_RATE = get_int(
    "vision",
    "frame_rate",
    default=2,
)

# Seconds to wait before reconnecting after a stream failure
RECONNECT_DELAY = get_float(
    "vision",
    "reconnect_delay",
    default=3.0,
)

# --- MQTT / recognition (shared with face_recognition) ---

CAMERA_MQTT_HOST = MQTT_HOST
CAMERA_MQTT_PORT = MQTT_PORT
CAMERA_MQTT_TOPIC_PREFIX = MQTT_TOPIC_PREFIX

CAMERA_RECOGNITION_THRESHOLD = RECOGNITION_THRESHOLD
CAMERA_DETECTION_THRESHOLD = DETECTION_THRESHOLD
CAMERA_REPUBLISH_INTERVAL = MQTT_REPUBLISH_INTERVAL

CAMERA_UNKNOWN_FACES_DIR = UNKNOWN_FACES_DIR