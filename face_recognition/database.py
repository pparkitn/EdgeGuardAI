import numpy as np

from .config import EMBEDDING_DIR, EMBEDDING_FILE


class FaceDatabase:

    def __init__(self):

        EMBEDDING_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.people = {}

        if EMBEDDING_FILE.exists():
            self.load()

    def add_person(
        self,
        name: str,
        embeddings: list,
    ):

        self.people[name] = np.asarray(
            embeddings,
            dtype=np.float32,
        )

        self.save()

    def save(self):

        data = {}

        for name, embeddings in self.people.items():
            data[name] = embeddings

        np.savez(
            EMBEDDING_FILE,
            **data,
        )

    def load(self):

        data = np.load(
            EMBEDDING_FILE,
            allow_pickle=False,
        )

        for name in data.files:
            self.people[name] = data[name]

    def get_people(self):

        return self.people