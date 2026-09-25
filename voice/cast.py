import logging
import time

import pychromecast

from .config import INTERRUPT_PLAYBACK, SPEAKERS

logger = logging.getLogger(__name__)


class SpeakerManager:

    def __init__(self, names=SPEAKERS):

        self.names = list(names)

        self.casts = {}

    def discover(self, timeout: int = 10):

        if not self.names:

            logger.info(
                "No cast speakers configured; "
                "casting disabled"
            )

            return self.casts

        try:

            chromecasts, browser = (
                pychromecast.get_listed_chromecasts(
                    friendly_names=self.names,
                    timeout=timeout,
                )
            )

            for cast in chromecasts:

                cast.wait(timeout=timeout)

                self.casts[cast.name] = cast

                logger.info(
                    "Speaker connected: %s "
                    "(%s)",
                    cast.name,
                    cast.cast_info.model_name,
                )

            browser.stop_discovery()

        except Exception:

            logger.exception(
                "Speaker discovery failed"
            )

        missing = set(self.names) - set(
            self.casts
        )

        if missing:

            logger.warning(
                "Speakers not found: %s",
                ", ".join(sorted(missing)),
            )

        return self.casts

    def play_url(
        self,
        url: str,
        cast_name: str = None,
    ):

        targets = (
            [cast_name]
            if cast_name is not None
            else list(self.casts)
        )

        played = 0

        for name in targets:

            cast = self.casts.get(name)

            if cast is None:

                logger.warning(
                    "Speaker not connected: %s",
                    name,
                )

                continue

            try:

                if self._play_on(
                    cast,
                    url,
                ):

                    logger.info(
                        "Playing %s on %s",
                        url,
                        name,
                    )

                    played += 1

                else:

                    logger.warning(
                        "Speaker %s did not start "
                        "playing our media "
                        "(state=%s, content=%s)",
                        name,
                        cast.media_controller.status.player_state,
                        cast.media_controller.status.content_id,
                    )

            except Exception:

                logger.exception(
                    "Cast playback failed on %s",
                    name,
                )

        return played

    def _play_on(self, cast, url: str) -> bool:

        media = cast.media_controller

        if INTERRUPT_PLAYBACK:

            try:

                # Android TVs can hold a stuck app session (e.g.
                # YouTube with a connected sender) that ignores
                # media.stop() and LOAD; quit the app first so the
                # Default Media Receiver can take over.
                if hasattr(cast, "quit_app"):

                    cast.quit_app()

            except Exception:

                logger.debug(
                    "quit_app failed on %s",
                    cast.name,
                    exc_info=True,
                )

            try:

                media.stop()

            except Exception:

                logger.debug(
                    "Stop before play failed on %s",
                    cast.name,
                    exc_info=True,
                )

        media.play_media(
            url,
            "audio/mp3",
        )

        media.block_until_active(
            timeout=15
        )

        if not self._wait_for_playback(
            media,
            url,
        ):

            return False

        media.play()

        return True

    @staticmethod
    def _wait_for_playback(
        media,
        url: str,
        timeout: float = 10.0,
    ) -> bool:

        deadline = time.time() + timeout

        while time.time() < deadline:

            status = media.status

            if (
                status.player_state == "PLAYING"
                and status.content_id == url
            ):

                return True

            time.sleep(0.5)

        return False

    def disconnect(self):

        for name, cast in self.casts.items():

            try:

                cast.disconnect()

            except Exception:

                logger.debug(
                    "Disconnect failed for %s",
                    name,
                )