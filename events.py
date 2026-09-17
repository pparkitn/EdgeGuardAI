from datetime import datetime
import json
import logging
import uuid

import paho.mqtt.client as mqtt

from edgeguard_config import get, get_int

logger = logging.getLogger(__name__)

DEFAULT_MQTT_HOST = get(
    "broker",
    "host",
    default="JETSON_IP",
)

DEFAULT_MQTT_PORT = get_int(
    "broker",
    "port",
    default=1883,
)

DEFAULT_TOPIC_PREFIX = get(
    "broker",
    "topic_prefix",
    default="edgeguard",
)

DEFAULT_CAMERA_ID = get(
    "cameras",
    "usb",
    "camera_id",
    default="front_entrance",
)


def _generate_event_id():
    return f"evt_{uuid.uuid4().hex[:12]}"


def _iso_timestamp():
    return datetime.now().astimezone().isoformat(
        timespec="seconds",
    )


def build_event(
    event_type: str,
    confidence: float,
    person_id: str = None,
    camera_id: str = None,
):

    event = {
        "event_id": _generate_event_id(),
        "event_type": event_type,
        "source": "camera",
        "camera_id": camera_id or DEFAULT_CAMERA_ID,
        "timestamp": _iso_timestamp(),
        "confidence": round(
            float(confidence),
            4,
        ),
    }

    if person_id is not None:
        event["person_id"] = person_id

    return event


class MqttPublisher:

    def __init__(
        self,
        host: str = DEFAULT_MQTT_HOST,
        port: int = DEFAULT_MQTT_PORT,
        topic_prefix: str = DEFAULT_TOPIC_PREFIX,
        camera_id: str = None,
    ):

        self.host = host
        self.port = port

        self.camera_id = camera_id or DEFAULT_CAMERA_ID

        self.topic = (
            f"{topic_prefix}/camera/{self.camera_id}"
        )

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
        )

        self.client.on_connect = (
            self._on_connect
        )

        self.client.reconnect_delay_set(
            min_delay=1,
            max_delay=30,
        )

        self._connected = False

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties=None,
    ):

        if reason_code == 0:
            self._connected = True
            logger.info(
                "Connected to MQTT broker "
                "at %s:%s",
                self.host,
                self.port,
            )
        else:
            self._connected = False
            logger.warning(
                "MQTT connect failed: %s",
                reason_code,
            )

    def connect(self):

        try:

            self.client.connect_async(
                self.host,
                self.port,
            )

            self.client.loop_start()

        except Exception:

            logger.exception(
                "MQTT connection error"
            )

    def publish(
        self,
        event: dict,
    ) -> bool:

        if not self._connected:

            logger.warning(
                "MQTT not connected; "
                "event dropped"
            )

            return False

        try:

            payload = json.dumps(
                event,
                indent=2,
            )

            result = self.client.publish(
                self.topic,
                payload,
                qos=1,
            )

            result.wait_for_publish(
                timeout=5,
            )

            return True

        except Exception:

            logger.exception(
                "MQTT publish failed"
            )

            return False

    def disconnect(self):

        try:

            self.client.loop_stop()

            self.client.disconnect()

        except Exception:

            logger.exception(
                "MQTT disconnect error"
            )