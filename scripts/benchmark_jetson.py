"""Benchmark the Jetson vision pipeline (no camera needed if a stream
is available; otherwise uses a synthetic frame).

Measures per-stage latency (detection, recognition), processing
throughput, and reports the face database size.

Run on the Jetson:
    cd ~/edgeguard && EDGEGUARD_CAMERA_PASSWORD=... ~/py38env/bin/python -u scripts/benchmark_jetson.py
"""

import statistics
import time

import numpy as np

from cameras.config import CAMERA_PASSWORD, CAMERAS
from cameras.stream import RtspStream
from face_recognition.database import FaceDatabase
from face_recognition.detector import FaceDetector
from face_recognition.recognizer import FaceRecognizer


def fmt(values, unit="ms"):

    if not values:
        return "-"

    avg = statistics.mean(values)
    p95 = sorted(values)[
        int(len(values) * 0.95) - 1
    ]

    return (
        f"{avg:.1f} avg / {p95:.1f} p95 {unit}"
    )


def main():

    print("== EdgeGuard Jetson benchmark ==")

    print("Loading model + database...")

    detector = FaceDetector()

    database = FaceDatabase()

    recognizer = FaceRecognizer(database)

    people = database.get_people()

    total_embeddings = sum(
        len(e) for e in people.values()
    )

    print(
        f"Face database: {len(people)} people, "
        f"{total_embeddings} embeddings"
    )

    frame = np.zeros(
        (720, 960, 3),
        dtype=np.uint8,
    )

    camera = CAMERAS[0] if CAMERAS else None

    stream = None

    if camera:

        camera = dict(camera)

        camera["password"] = CAMERA_PASSWORD

        try:

            stream = RtspStream(camera)

            stream.open()

            live_frame = stream.read_frame()

            if live_frame is not None:
                frame = live_frame
                print(
                    f"Using LIVE frame from "
                    f"camera '{camera['id']}' "
                    f"{frame.shape}"
                )

        except Exception as exc:

            print(
                f"Camera stream unavailable "
                f"({exc.__class__.__name__}); "
                "using synthetic frame"
            )

            stream = None

    # ---- detection latency ----

    print("\n-- detection (buffalo_l, det_size 640) --")

    det_times = []

    for _ in range(30):

        t0 = time.perf_counter()

        faces = detector.detect(frame)

        det_times.append(
            (time.perf_counter() - t0) * 1000
        )

    print(f"faces found: {len(faces)}")

    print(f"latency:     {fmt(det_times)}")

    # ---- recognition latency ----

    print("\n-- recognition (cosine, brute-force) --")

    rec_times = []

    for _ in range(100):

        embedding = (
            faces[0].embedding
            if faces
            else np.random.rand(512).astype(np.float32)
        )

        t0 = time.perf_counter()

        recognizer.recognize(embedding)

        rec_times.append(
            (time.perf_counter() - t0) * 1000
        )

    print(f"latency:     {fmt(rec_times)}")

    # ---- throughput (full pipeline: detect + recognize) ----

    print("\n-- throughput (full frame pipeline) --")

    pipe_times = []

    for _ in range(30):

        t0 = time.perf_counter()

        faces = detector.detect(frame)

        for face in faces:

            recognizer.recognize(face.embedding)

        pipe_times.append(
            (time.perf_counter() - t0) * 1000
        )

    avg_ms = statistics.mean(pipe_times)

    print(f"per frame:   {avg_ms:.1f} ms avg")

    print(f"throughput:  {1000.0 / avg_ms:.2f} FPS")

    if stream is not None:

        stream.close()


if __name__ == "__main__":
    main()