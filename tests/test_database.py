import numpy as np

from face_recognition import database as db_module
from face_recognition.database import FaceDatabase


def test_empty_database(tmp_path, monkeypatch):

    monkeypatch.setattr(
        db_module,
        "EMBEDDING_DIR",
        tmp_path,
    )

    monkeypatch.setattr(
        db_module,
        "EMBEDDING_FILE",
        tmp_path / "faces.npz",
    )

    db = FaceDatabase()

    assert db.get_people() == {}


def test_add_person_saves_and_reloads(
    tmp_path,
    monkeypatch,
):

    monkeypatch.setattr(
        db_module,
        "EMBEDDING_DIR",
        tmp_path,
    )

    monkeypatch.setattr(
        db_module,
        "EMBEDDING_FILE",
        tmp_path / "faces.npz",
    )

    embedding = np.ones(512, dtype=np.float32)

    FaceDatabase().add_person(
        "piotr",
        [embedding],
    )

    reloaded = FaceDatabase()

    stored = reloaded.get_people()["piotr"]

    assert stored.shape == (1, 512)

    assert np.array_equal(
        stored[0],
        embedding,
    )


def test_add_person_overwrites_previous(tmp_path, monkeypatch):

    monkeypatch.setattr(
        db_module,
        "EMBEDDING_DIR",
        tmp_path,
    )

    monkeypatch.setattr(
        db_module,
        "EMBEDDING_FILE",
        tmp_path / "faces.npz",
    )

    db = FaceDatabase()

    db.add_person(
        "piotr",
        [np.ones(512, dtype=np.float32)],
    )

    db.add_person(
        "piotr",
        [
            np.zeros(512, dtype=np.float32),
            np.zeros(512, dtype=np.float32),
        ],
    )

    assert db.get_people()["piotr"].shape == (2, 512)