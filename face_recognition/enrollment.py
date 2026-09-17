
import cv2

from .config import FACE_DIR
from .database import FaceDatabase
from .detector import FaceDetector

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
}


def enroll_person(
    name: str,
    detector: FaceDetector,
    database: FaceDatabase,
):

    person_dir = FACE_DIR / name

    if not person_dir.exists():
        raise RuntimeError(
            f"No directory found: {person_dir}"
        )

    embeddings = []

    image_files = sorted(
        [
            p
            for p in person_dir.iterdir()
            if p.suffix.lower()
            in IMAGE_EXTENSIONS
        ]
    )

    if not image_files:
        raise RuntimeError(
            f"No images found for {name}"
        )

    for image_file in image_files:

        image = cv2.imread(
            str(image_file)
        )

        if image is None:
            print(
                f"Could not read {image_file}"
            )
            continue

        faces = detector.detect(image)

        if len(faces) == 0:

            print(
                f"No face detected: {image_file}"
            )

            continue

        if len(faces) > 1:

            print(
                f"Multiple faces detected: "
                f"{image_file}"
            )

            continue

        embedding = faces[0].embedding

        embeddings.append(embedding)

        print(
            f"Enrolled: {name} <- "
            f"{image_file.name}"
        )

    if not embeddings:

        raise RuntimeError(
            f"No valid face embeddings "
            f"created for {name}"
        )

    database.add_person(
        name,
        embeddings,
    )

    print()
    print(
        f"{name}: {len(embeddings)} "
        f"embeddings stored"
    )


def enroll_all():

    detector = FaceDetector()

    database = FaceDatabase()

    people = [
        p
        for p in FACE_DIR.iterdir()
        if p.is_dir()
    ]

    for person_dir in people:

        enroll_person(
            person_dir.name,
            detector,
            database,
        )