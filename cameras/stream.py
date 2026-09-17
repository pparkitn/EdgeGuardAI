import logging
import re
import subprocess
from urllib.parse import quote

from edgeguard_config import get

from .config import CAMERA_PASSWORD, FRAME_HEIGHT, FRAME_RATE

logger = logging.getLogger("cameras.stream")

SIZE_RE = re.compile(
    r",\s*(\d{3,5})x(\d{3,5}),"
)


def get_ffmpeg_binary() -> str:

    configured = get(
        "vision",
        "ffmpeg_path",
        default="",
    )

    if configured:
        return configured

    from imageio_ffmpeg import get_ffmpeg_exe

    return get_ffmpeg_exe()


def build_url(camera: dict) -> str:

    host = camera["host"]

    port = camera.get("port", 554)

    user = camera.get("user", "")

    password = camera.get(
        "password",
        CAMERA_PASSWORD,
    )

    path = camera.get(
        "path",
        "/Preview_01_main",
    )

    if user:

        credentials = (
            f"{user}:{quote(password, safe='')}@"
        )

    else:

        credentials = ""

    return (
        f"rtsp://{credentials}{host}:{port}{path}"
    )


class RtspStream:

    """RTSP stream via a static ffmpeg process; yields scaled BGR frames.

    ffmpeg (not PyAV) is used because it handles the RTSP
    authentication handshake correctly (incl. special characters
    in passwords) and gives us scaling + frame-rate capping for free.
    """

    def __init__(
        self,
        camera: dict,
        height: int = FRAME_HEIGHT,
        frame_rate: int = FRAME_RATE,
    ):

        self.url = build_url(camera)

        self.transport = camera.get(
            "transport",
            "tcp",
        )

        self.height = height

        self.frame_rate = frame_rate

        self.ffmpeg = get_ffmpeg_binary()

        self.proc = None

        self.frame_size = None

    def open(self):

        width, height = self._probe_size()

        self.frame_size = (width, height)

        logger.info(
            "Opening stream: %s (%dx%d @ %d fps)",
            self._masked_url(),
            width,
            height,
            self.frame_rate,
        )

        args = [
            self.ffmpeg,
            "-rtsp_transport",
            self.transport,
            "-i",
            self.url,
            "-an",
            "-vf",
            f"scale={width}:{height}",
            "-r",
            str(self.frame_rate),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-",
        ]

        self.proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

    def _probe_size(self):

        """Queries the native stream resolution by parsing ffmpeg's
        stream info (one quick decode)."""

        args = [
            self.ffmpeg,
            "-rtsp_transport",
            self.transport,
            "-i",
            self.url,
            "-t",
            "1",
            "-f",
            "null",
            "-",
        ]

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=15,
        )

        match = SIZE_RE.search(result.stderr)

        if match is None:

            raise RuntimeError(
                f"Could not determine stream size for "
                f"{self._masked_url()}: "
                f"{result.stderr[-200:]}"
            )

        native_width = int(match.group(1))
        native_height = int(match.group(2))

        width = int(
            native_width
            * self.height
            / native_height
            / 2
        ) * 2

        return width, self.height

    def read_frame(self):

        """Reads one BGR frame (bytes -> ndarray),
        or None on stream end / failure."""

        if self.proc is None:
            return None

        width, height = self.frame_size

        bytes_per_frame = width * height * 3

        try:

            data = self.proc.stdout.read(
                bytes_per_frame
            )

        except Exception:

            logger.exception(
                "Frame read failed"
            )

            return None

        if len(data) != bytes_per_frame:

            logger.warning(
                "Short frame read (%d/%d); "
                "stream ended",
                len(data),
                bytes_per_frame,
            )

            return None

        import numpy as np

        return np.frombuffer(
            data,
            dtype=np.uint8,
        ).reshape(height, width, 3)

    def close(self):

        if self.proc is not None:

            try:

                self.proc.terminate()

                self.proc.wait(timeout=5)

            except Exception:

                self.proc.kill()

            self.proc = None

        self.frame_size = None

    def _masked_url(self):

        if "@" in self.url:

            return (
                "rtsp://***@" + self.url.split("@")[1]
            )

        return self.url