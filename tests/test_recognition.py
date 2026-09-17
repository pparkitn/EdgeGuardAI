import numpy as np
import pytest

from face_recognition.recognizer import FaceRecognizer


class FakeDatabase:

    def __init__(self, people):
        self.people = people

    def get_people(self):
        return self.people


def test_cosine_similarity_identical():
    a = np.ones(10, dtype=np.float32)
    assert FaceRecognizer.cosine_similarity(a, a) == pytest.approx(1.0)


def test_cosine_similarity_opposite():
    a = np.ones(4, dtype=np.float32)
    b = -np.ones(4, dtype=np.float32)
    assert FaceRecognizer.cosine_similarity(a, b) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector():
    assert (
        FaceRecognizer.cosine_similarity(
            np.zeros(4),
            np.ones(4),
        )
        == 0.0
    )


def test_recognize_known_person():
    embedding = np.ones(512, dtype=np.float32)
    database = FakeDatabase(
        {"piotr": np.array([embedding])}
    )
    recognizer = FaceRecognizer(
        database,
        threshold=0.5,
    )
    name, score = recognizer.recognize(embedding)
    assert name == "piotr"
    assert score == pytest.approx(1.0)


def test_recognize_best_match_wins():
    target = np.ones(512, dtype=np.float32)
    other = np.ones(512, dtype=np.float32) * -0.9
    database = FakeDatabase(
        {
            "piotr": np.array([other]),
            "magda": np.array([target]),
        }
    )
    name, _ = FaceRecognizer(
        database,
        threshold=0.5,
    ).recognize(target)
    assert name == "magda"


def test_recognize_below_threshold_is_unknown():
    unrelated = np.ones(512, dtype=np.float32) * -1.0
    database = FakeDatabase(
        {"piotr": np.array([unrelated])}
    )
    name, score = FaceRecognizer(
        database,
        threshold=0.5,
    ).recognize(np.ones(512, dtype=np.float32))
    assert name == "Unknown"
    assert score < 0.5


def test_recognize_empty_database():
    name, score = FaceRecognizer(
        FakeDatabase({}),
        threshold=0.5,
    ).recognize(np.ones(512, dtype=np.float32))
    assert name == "Unknown"
    assert score == 0.0