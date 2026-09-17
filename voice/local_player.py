import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalPlayer:

    def __init__(self):

        self.mixer = None

        try:

            from pygame import mixer

            mixer.init()

            self.mixer = mixer

            logger.info(
                "Local audio ready "
                "(speaker on this machine)"
            )

        except Exception:

            logger.exception(
                "pygame mixer unavailable; "
                "local playback disabled"
            )

    def play(self, path: Path) -> bool:

        if self.mixer is None:
            return False

        try:

            self.mixer.music.load(str(path))

            self.mixer.music.play()

            logger.info(
                "Playing locally: %s",
                path.name,
            )

            return True

        except Exception:

            logger.exception(
                "Local playback failed for %s",
                path,
            )

            return False