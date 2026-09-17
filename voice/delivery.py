import logging
from pathlib import Path
import queue
import threading

from .cast import SpeakerManager
from .config import HTTP_PORT
from .local_player import LocalPlayer

logger = logging.getLogger("voice.delivery")


class DeliveryWorker:

    """Delivers announcement audio over two independent channels:

    1. local playback (speaker attached to this machine, e.g. Pi 3.5mm jack)
    2. Google Cast broadcast (Google Home / Nest speakers on the LAN)

    Each channel is enabled/disabled, logged and failure-isolated
    independently. Delivery runs on a background thread so the MQTT
    callback never blocks.
    """

    def __init__(
        self,
        local_player: LocalPlayer,
        speakers: SpeakerManager,
        lan_ip: str,
    ):

        self.local_player = local_player
        self.speakers = speakers
        self.lan_ip = lan_ip

        self.queue = queue.Queue()

        self.thread = threading.Thread(
            target=self._run,
            name="delivery-worker",
            daemon=True,
        )

        self.thread.start()

    def deliver(
        self,
        path: Path,
        speakers=None,
        local: bool = True,
    ):

        self.queue.put(
            (path, speakers, local)
        )

    def _run(self):

        while True:

            path, speakers, local = self.queue.get()

            self._deliver_local(path, local)

            self._deliver_cast(path, speakers)

    def _deliver_local(self, path: Path, local: bool):

        if not local:

            logger.info(
                "Local playback disabled for "
                "this announcement"
            )

            return

        if self.local_player is None:

            logger.info(
                "Local playback disabled; "
                "skipping this machine's speaker"
            )

            return

        if self.local_player.play(path):

            logger.info(
                "Local playback: played %s on "
                "this machine's speaker",
                path.name,
            )

        else:

            logger.warning(
                "Local playback failed for %s",
                path.name,
            )

    def _deliver_cast(self, path: Path, speakers):

        if speakers == []:

            logger.info(
                "Google Cast disabled for "
                "this announcement"
            )

            return

        if not self.speakers.casts:

            logger.info(
                "No cast speakers connected; "
                "Google Home broadcast skipped"
            )

            return

        url = (
            f"http://{self.lan_ip}:{HTTP_PORT}/"
            f"{path.name}"
        )

        if speakers is None:

            targets = list(self.speakers.casts)

        else:

            targets = list(speakers)

        played = 0

        for name in targets:

            played += self.speakers.play_url(
                url,
                cast_name=name,
            )

        logger.info(
            "Google Cast: played on %d of %d "
            "targeted speaker(s)",
            played,
            len(targets),
        )