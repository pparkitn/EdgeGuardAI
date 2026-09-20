"""GPU camera service entry point (Jetson).

Same service as `python -m cameras.main` but inference runs on the
TensorRT engines; falls back to the CPU insightface pipeline if the
engines are unavailable, so the service never fails to start.

    python -m jetson_gpu.main
"""

import logging
import signal
import sys
import time

from cameras.agent import CameraAgent
from cameras.config import (
    CAMERA_MQTT_HOST,
    CAMERA_MQTT_PORT,
    CAMERA_MQTT_TOPIC_PREFIX,
    CAMERA_RECOGNITION_THRESHOLD,
    CAMERAS,
)
from events import MqttPublisher
from face_recognition.database import FaceDatabase
from face_recognition.recognizer import FaceRecognizer

from .detector import GpuFaceDetector

logger = logging.getLogger("jetson_gpu.main")


def main():

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)-7s "
            "%(name)s: %(message)s"
        ),
    )

    print("Starting EdgeGuard AI - GPU camera service")

    detector = GpuFaceDetector()

    print(
        "Inference provider: "
        f"{detector.provider}"
    )

    print("Loading face database...")

    database = FaceDatabase()

    recognizer = FaceRecognizer(
        database,
        threshold=CAMERA_RECOGNITION_THRESHOLD,
    )

    agents = []

    camera_publishers = []

    for camera in CAMERAS:

        camera_publisher = MqttPublisher(
            host=CAMERA_MQTT_HOST,
            port=CAMERA_MQTT_PORT,
            topic_prefix=CAMERA_MQTT_TOPIC_PREFIX,
            camera_id=camera["id"],
        )

        camera_publisher.connect()

        camera_publishers.append(
            camera_publisher
        )

        agent = CameraAgent(
            camera,
            detector,
            recognizer,
            camera_publisher,
        )

        agents.append(agent)

        agent.start()

        print(
            f"Camera agent started: "
            f"{camera['id']} -> "
            f"{camera['host']}:{camera.get('port', 554)}"
            f"{camera.get('path', '/Preview_01_main')}"
            f" (topic {camera_publisher.topic})"
        )

    def handle_sigint(sig, frame):

        print("Shutting down")

        for agent in agents:

            agent.stop()

        for camera_publisher in camera_publishers:

            camera_publisher.disconnect()

        sys.exit(0)

    signal.signal(signal.SIGINT, handle_sigint)

    try:

        while True:

            time.sleep(1)

    except KeyboardInterrupt:

        handle_sigint(None, None)


if __name__ == "__main__":
    main()