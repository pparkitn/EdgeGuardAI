from datetime import datetime
import logging
from pathlib import Path
import threading
import time

import cv2

from .config import (
    CAMERA_REPUBLISH_INTERVAL,
    CAMERA_UNKNOWN_FACES_DIR,
    FRAME_RATE,
    FRAME_WIDTH,
    RECONNECT_DELAY,
)
from .stream import RtspStream

logger = logging.getLogger("cameras.agent")


class CameraAgent(threading.Thread):

    def __init__(
        self,
        camera: dict,
        detector,
        recognizer,
        publisher,
    ):

        super().__init__(
            name=f"camera-{camera['id']}",
            daemon=True,
        )

        self.camera = camera

        self.camera_id = camera["id"]

        self.detector = detector

        self.recognizer = recognizer

        self.publisher = publisher

        self.stream = RtspStream(camera)

        self.running = True

        self.last_publish_time = {}

        self.snapshot_dir = (
            Path(CAMERA_UNKNOWN_FACES_DIR)
            / self.camera_id
        )

    def stop(self):

        self.running = False

    def run(self):

        while self.running:

            try:

                self.stream.open()

                self._process_stream()

            except Exception:

                logger.exception(
                    "Camera %s stream failed",
                    self.camera_id,
                )

            finally:

                self.stream.close()

            if not self.running:
                break

            logger.info(
                "Camera %s reconnecting in %.0f s",
                self.camera_id,
                RECONNECT_DELAY,
            )

            time.sleep(RECONNECT_DELAY)

    def _process_stream(self):

        frame_interval = 1.0 / FRAME_RATE

        last_processed = 0.0

        while self.running:

            frame = self.stream.read_frame()

            if frame is None:
                return

            now = time.time()

            if now - last_processed < frame_interval:
                continue

            last_processed = now

            self._process_frame(frame)

    def _process_frame(self, frame):

        frame = self._resize(frame)

        faces = self.detector.detect(frame)

        if not faces:

            logger.debug(
                "Camera %s: no faces",
                self.camera_id,
            )

            return

        logger.info(
            "Camera %s: %d face(s)",
            self.camera_id,
            len(faces),
        )

        now = time.time()

        for face in faces:

            name, score = self.recognizer.recognize(
                face.embedding
            )

            logger.info(
                "Camera %s: %s (%.3f)",
                self.camera_id,
                name,
                score,
            )

            self._publish_event(
                name,
                score,
                now,
            )

            if name == "Unknown":

                self._save_snapshot(frame, face)

    def _resize(self, frame):

        height, width = frame.shape[:2]

        if width <= FRAME_WIDTH:
            return frame

        new_height = int(
            height * FRAME_WIDTH / width
        )

        return cv2.resize(
            frame,
            (FRAME_WIDTH, new_height),
            interpolation=cv2.INTER_AREA,
        )

    def _publish_event(self, name, score, now):

        last_time = self.last_publish_time.get(
            name,
            0.0,
        )

        if (
            now - last_time
            < CAMERA_REPUBLISH_INTERVAL
        ):
            return

        if name == "Unknown":
            event_type = (
                "unknown_person_detected"
            )
            person_id = None
        else:
            event_type = "person_recognized"
            person_id = name

        from events import build_event

        event = build_event(
            event_type,
            score,
            person_id,
            camera_id=self.camera_id,
        )

        if self.publisher.publish(event):

            print(
                f"[{self.camera_id}] {event_type}: "
                f"{name} ({score:.2f})"
            )

            self.last_publish_time[name] = now

    def _save_snapshot(self, frame, face):

        x1, y1, x2, y2 = face.bbox.astype(int)

        height, width = frame.shape[:2]

        margin_x = int((x2 - x1) * 0.15)
        margin_y = int((y2 - y1) * 0.15)

        x1 = max(0, x1 - margin_x)
        y1 = max(0, y1 - margin_y)
        x2 = min(width, x2 + margin_x)
        y2 = min(height, y2 + margin_y)

        crop = frame[y1:y2, x1:x2]

        if crop.size == 0:
            return

        try:

            self.snapshot_dir.mkdir(
                parents=True,
                exist_ok=True,
            )

            filename = (
                "unknown_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
                ".jpg"
            )

            path = self.snapshot_dir / filename

            cv2.imwrite(str(path), crop)

            print(
                f"[{self.camera_id}] snapshot -> "
                f"{path}"
            )

        except OSError:

            logger.exception(
                "Could not save snapshot for %s",
                self.camera_id,
            )