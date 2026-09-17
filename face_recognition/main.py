from datetime import datetime
import time

import cv2

from .camera import Camera
from .config import (
    MQTT_REPUBLISH_INTERVAL,
    RECOGNITION_THRESHOLD,
    UNKNOWN_FACE_MARGIN,
    UNKNOWN_FACES_DIR,
    WINDOW_NAME,
)
from .database import FaceDatabase
from .detector import FaceDetector
from .mqtt import MqttPublisher, build_event
from .recognizer import FaceRecognizer


def draw_face(
    frame,
    face,
    name,
    score,
):

    x1, y1, x2, y2 = (
        face.bbox.astype(int)
    )

    if name == "Unknown":
        label = f"Unknown ({score:.2f})"
    else:
        label = f"{name} ({score:.2f})"

    cv2.rectangle(
        frame,
        (x1, y1),
        (x2, y2),
        (0, 255, 0),
        2,
    )

    cv2.putText(
        frame,
        label,
        (x1, y1 - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
    )


def main():

    print("Starting EdgeGuard AI")

    print("Loading face recognition model...")

    detector = FaceDetector()

    print("Loading face database...")

    database = FaceDatabase()

    print(
        "Known people:",
        list(database.get_people().keys()),
    )

    recognizer = FaceRecognizer(
        database,
        threshold=RECOGNITION_THRESHOLD,
    )

    publisher = MqttPublisher()

    publisher.connect()

    print(
        "MQTT publisher started ->",
        publisher.topic,
    )

    camera = Camera()

    print("Camera started")

    previous_time = time.time()

    last_publish_time = {}

    try:

        while True:

            frame = camera.read()

            faces = detector.detect(frame)

            now = time.time()

            for face in faces:

                name, score = recognizer.recognize(
                    face.embedding
                )

                draw_face(
                    frame,
                    face,
                    name,
                    score,
                )

                status = publish_face_event(
                    publisher,
                    name,
                    score,
                    now,
                    last_publish_time,
                )

                if (
                    name == "Unknown"
                    and status != "throttled"
                ):

                    saved = save_unknown_face(
                        frame,
                        face,
                    )

                    if saved is not None:

                        print(
                            f"[SNAPSHOT] saved -> "
                            f"{saved}"
                        )

            current_time = time.time()

            fps = 1.0 / (
                current_time - previous_time
            )

            previous_time = current_time

            cv2.putText(
                frame,
                f"FPS: {fps:.1f}",
                (20, 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
            )

            cv2.imshow(
                WINDOW_NAME,
                frame,
            )

            key = cv2.waitKey(1) & 0xFF

            if key == ord("q"):
                break

    finally:

        publisher.disconnect()

        camera.release()

        cv2.destroyAllWindows()


def save_unknown_face(
    frame,
    face,
    directory=UNKNOWN_FACES_DIR,
    margin=UNKNOWN_FACE_MARGIN,
):

    x1, y1, x2, y2 = (
        face.bbox.astype(int)
    )

    height, width = frame.shape[:2]

    margin_x = int(
        (x2 - x1) * margin
    )

    margin_y = int(
        (y2 - y1) * margin
    )

    x1 = max(0, x1 - margin_x)
    y1 = max(0, y1 - margin_y)
    x2 = min(width, x2 + margin_x)
    y2 = min(height, y2 + margin_y)

    crop = frame[y1:y2, x1:x2]

    if crop.size == 0:
        return None

    try:

        directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        filename = (
            "unknown_"
            f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
            ".jpg"
        )

        path = directory / filename

        cv2.imwrite(
            str(path),
            crop,
        )

        return path

    except OSError:

        print(
            f"Could not save snapshot to "
            f"{directory}"
        )

        return None


def publish_face_event(
    publisher,
    name,
    score,
    now,
    last_publish_time,
):

    last_time = last_publish_time.get(
        name,
        0.0,
    )

    if now - last_time < MQTT_REPUBLISH_INTERVAL:
        return "throttled"

    if name == "Unknown":
        event_type = (
            "unknown_person_detected"
        )
        person_id = None
    else:
        event_type = "person_recognized"
        person_id = name

    event = build_event(
        event_type,
        score,
        person_id,
    )

    if publisher.publish(event):

        print(
            f"[MQTT] {event_type}: "
            f"{name} ({score:.2f})"
        )

        last_publish_time[name] = now

        return "published"

    return "mqtt_down"


if __name__ == "__main__":
    main()