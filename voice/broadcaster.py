import functools
from http.server import (
    SimpleHTTPRequestHandler,
    ThreadingHTTPServer,
)
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import signal
import socket
import sys
import threading
import time

import paho.mqtt.client as mqtt

from .announcements import build_announcement
from .cast import SpeakerManager
from .config import (
    ANNOUNCE_RECOGNIZED,
    ANNOUNCEMENT_COOLDOWN,
    AUDIO_DIR,
    HTTP_PORT,
    LOCAL_PLAYBACK,
    MQTT_HOST,
    MQTT_PORT,
    MQTT_TOPIC,
    PROJECT_ROOT,
    UNKNOWN_GRACE_PERIOD,
)
from .delivery import DeliveryWorker
from .local_player import LocalPlayer
from .polly import PollyClient
from .scheduler import Scheduler

logger = logging.getLogger("voice.broadcaster")


class QuietHandler(SimpleHTTPRequestHandler):

    def log_message(self, format, *args):

        logger.debug(
            "HTTP %s",
            format % args,
        )


def start_http_server(directory: Path, port: int):

    handler = functools.partial(
        QuietHandler,
        directory=str(directory),
    )

    server = ThreadingHTTPServer(
        ("0.0.0.0", port),
        handler,
    )

    thread = threading.Thread(
        target=server.serve_forever,
        daemon=True,
    )

    thread.start()

    logger.info(
        "HTTP server serving %s on :%d",
        directory,
        port,
    )

    return server


def get_lan_ip() -> str:

    try:

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        try:

            sock.connect((MQTT_HOST, 80))

            return sock.getsockname()[0]

        finally:

            sock.close()

    except OSError:

        return "127.0.0.1"


class Broadcaster:

    def __init__(self):

        self.polly = PollyClient()

        self.speakers = SpeakerManager()

        self.local_player = (
            LocalPlayer()
            if LOCAL_PLAYBACK
            else None
        )

        self.delivery = None

        self.scheduler = None

        self.http_server = None

        self.last_announcement = {}

        self.last_known_seen = {}

        self.lan_ip = get_lan_ip()

        self.running = True

    def start(self):

        self.http_server = start_http_server(
            AUDIO_DIR,
            HTTP_PORT,
        )

        self.speakers.discover()

        if not self.speakers.casts:

            logger.warning(
                "No cast speakers available; "
                "Google Home broadcast disabled"
            )

        if self.local_player is None:

            logger.warning(
                "Local playback disabled"
            )

        self.delivery = DeliveryWorker(
            self.local_player,
            self.speakers,
            self.lan_ip,
        )

        self.scheduler = Scheduler(
            self.say,
        )

        self.scheduler.load()

        self.scheduler.start()

        self._connect_mqtt()

    def _connect_mqtt(self):

        self.mqtt_client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
        )

        self.mqtt_client.on_connect = (
            self._on_connect
        )

        self.mqtt_client.on_message = (
            self._on_message
        )

        self.mqtt_client.reconnect_delay_set(
            min_delay=1,
            max_delay=30,
        )

        try:

            self.mqtt_client.connect(
                MQTT_HOST,
                MQTT_PORT,
            )

            self.mqtt_client.loop_start()

        except Exception:

            logger.exception(
                "MQTT connection failed"
            )

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code,
        properties=None,
    ):

        if reason_code == 0:

            logger.info(
                "Connected to MQTT broker "
                "at %s:%s",
                MQTT_HOST,
                MQTT_PORT,
            )

            client.subscribe(
                MQTT_TOPIC,
                qos=1,
            )

        else:

            logger.warning(
                "MQTT connect failed: %s",
                reason_code,
            )

    def _on_message(
        self,
        client,
        userdata,
        msg,
    ):

        try:

            event = json.loads(
                msg.payload.decode()
            )

        except (json.JSONDecodeError, UnicodeDecodeError):

            logger.debug(
                "Non-JSON message on %s ignored",
                msg.topic,
            )

            return

        self.handle_event(event)

    def handle_event(self, event: dict):

        event_type = event.get("event_type")

        camera_id = event.get("camera_id")

        logger.info(
            "Event: %s from %s",
            event_type,
            camera_id,
        )

        now = time.time()

        if event_type == "person_recognized":

            self.last_known_seen[camera_id] = now

            if not ANNOUNCE_RECOGNIZED:

                logger.info(
                    "Recognized-person announcements "
                    "disabled"
                )

                return

        if event_type == "unknown_person_detected":

            last_known = self.last_known_seen.get(
                camera_id,
                0.0,
            )

            if now - last_known < UNKNOWN_GRACE_PERIOD:

                logger.info(
                    "Unknown detection on %s "
                    "suppressed: known person seen "
                    "%.0fs ago (grace %.0fs)",
                    camera_id,
                    now - last_known,
                    UNKNOWN_GRACE_PERIOD,
                )

                return

        text = build_announcement(event)

        if text is None:

            logger.debug(
                "No announcement template for %s",
                event_type,
            )

            return

        if not self._cooldown_ok(event_type):

            logger.info(
                "Announcement for %s in cooldown",
                event_type,
            )

            return

        self.announce(event_type, text)

    def _cooldown_ok(self, event_type: str) -> bool:

        last = self.last_announcement.get(
            event_type,
            0.0,
        )

        return (
            time.time() - last
            >= ANNOUNCEMENT_COOLDOWN
        )

    def say(
        self,
        text: str,
        speakers=None,
        local: bool = True,
    ):

        """Speak arbitrary text through the delivery channels."""

        logger.info(
            "Saying: %s",
            text,
        )

        path = self.polly.synthesize(text)

        if path is None:

            logger.error(
                "Skipping: no audio generated"
            )

            return

        self.delivery.deliver(
            path,
            speakers=speakers,
            local=local,
        )

    def announce(self, event_type: str, text: str):

        logger.info(
            "Announcing: %s",
            text,
        )

        path = self.polly.synthesize(text)

        if path is None:

            logger.error(
                "Skipping announcement: "
                "no audio generated"
            )

            return

        self.last_announcement[event_type] = (
            time.time()
        )

        self.delivery.deliver(path)

        logger.info(
            "Announcement handed to delivery "
            "(local + Google Cast)",
        )

    def stop(self):

        self.running = False

        if self.scheduler is not None:

            self.scheduler.stop()

        try:

            self.mqtt_client.loop_stop()

            self.mqtt_client.disconnect()

        except Exception:

            logger.debug(
                "MQTT shutdown error",
                exc_info=True,
            )

        self.speakers.disconnect()

        if self.http_server is not None:

            self.http_server.shutdown()


def setup_logging():

    log_dir = PROJECT_ROOT / "logs"

    log_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # pychromecast/zeroconf spam full tracebacks in a reconnect
    # loop when a speaker drops; silence them to keep logs usable
    for noisy in (
        "pychromecast",
        "zeroconf",
    ):

        logging.getLogger(noisy).setLevel(
            logging.CRITICAL
        )

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)-7s "
            "%(name)s: %(message)s"
        ),
        handlers=[
            logging.StreamHandler(sys.stdout),
            RotatingFileHandler(
                log_dir / "broadcaster.log",
                maxBytes=5 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            ),
        ],
    )


def main():

    setup_logging()

    broadcaster = Broadcaster()

    def handle_sigint(sig, frame):

        logger.info("Shutting down")

        broadcaster.stop()

        sys.exit(0)

    signal.signal(
        signal.SIGINT,
        handle_sigint,
    )

    broadcaster.start()

    logger.info(
        "Broadcaster running; "
        "waiting for events on %s",
        MQTT_TOPIC,
    )

    try:

        while broadcaster.running:

            time.sleep(1)

    except KeyboardInterrupt:

        handle_sigint(None, None)


if __name__ == "__main__":
    main()