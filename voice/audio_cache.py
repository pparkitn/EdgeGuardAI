import hashlib
from pathlib import Path

from .config import AUDIO_DIR


class AudioCache:

    def __init__(self, directory: Path = AUDIO_DIR):

        self.directory = Path(directory)

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    @staticmethod
    def filename_for(text: str) -> str:

        digest = hashlib.sha256(
            text.encode("utf-8")
        ).hexdigest()[:16]

        return f"{digest}.mp3"

    def path_for(self, text: str) -> Path:

        return self.directory / self.filename_for(
            text
        )

    def has(self, text: str) -> bool:

        return self.path_for(text).exists()

    def store(self, text: str, data: bytes) -> Path:

        path = self.path_for(text)

        path.write_bytes(data)

        return path