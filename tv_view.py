"""Live camera view on a Cast device (TV / Chromecast).

Composes the configured cameras into a single live grid stream
(H.264 / fMP4 HLS), serves it over HTTP and casts it to a
Chromecast-enabled display. Everything stays on the LAN.

    python -m tv_view                start the view (Ctrl+C stops it)
    python -m tv_view --list         list cast devices on the network
    python -m tv_view --tv NAME      override the configured device
    python -m tv_view --port 8100    override the HLS server port

Config: config.yaml -> tv_view (tv, http_port, host_ip, frame_rate,
columns, cameras). A camera entry can be:

  - the id of an entry under cameras.rtsp (URL built from its
    host/port/user/path and its own `password`, else the shared
    EDGEGUARD_CAMERA_PASSWORD),
  - a full source string (rtsp:// URL or v4l2:/dev/videoX),
  - a dict: {source: ...} or {id: ..., host/user/password/path
    overrides} for one-off cameras (e.g. a doorbell with its own
    RTSP password).

Secrets stay in the gitignored per-device config.yaml (or EDGEGUARD_*
env vars), never in config.yaml.example.

Design notes (learned the hard way):
  - fMP4 HLS plays on Cast displays where live MPEG-TS stalls in
    BUFFERING forever.
  - Every camera gets its own ffmpeg feeder and a wallclock-paced
    relay thread; a single compositor encodes the grid. A camera
    that stalls or drops (doorbells do, often) freezes its pane on
    the last frame and reconnects on its own - the cast keeps
    playing. One ffmpeg with N RTSP inputs instead re-handshakes
    every camera on any hiccup.
  - The relay duplicates the last frame on a 1/FR clock so the
    composite timeline always advances in real time.
"""

import argparse
import functools
import http.server
import logging
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.parse import quote, urlsplit

from edgeguard_config import get, get_int

logger = logging.getLogger("tv_view")

WORK_DIR = "/tmp/tv_view"
GRID_WIDTH = 1920
ROW_HEIGHT = 540
RTSP_TIMEOUT_US = 15_000_000
CAST_TIMEOUT = 90.0
RELOAD_AFTER_IDLE = 25.0

TV_VIEW_TV = get("tv_view", "tv", default="")

TV_VIEW_HTTP_PORT = get_int(
    "tv_view",
    "http_port",
    default=8100,
)

TV_VIEW_HOST_IP = get(
    "tv_view",
    "host_ip",
    default="",
)

TV_VIEW_FRAME_RATE = get_int(
    "tv_view",
    "frame_rate",
    default=10,
)

TV_VIEW_COLUMNS = get_int(
    "tv_view",
    "columns",
    default=0,
)

TV_VIEW_CAMERAS = get(
    "tv_view",
    "cameras",
    default=[],
)

RTSP_CAMERAS = get(
    "cameras",
    "rtsp",
    default=[],
)

CAMERA_PASSWORD = get(
    "cameras",
    "rtsp",
    "password",
    env="EDGEGUARD_CAMERA_PASSWORD",
    default="",
)


def find_ffmpeg() -> str:
    """Locate an ffmpeg binary (config, imageio-ffmpeg, PATH)."""

    configured = get(
        "vision",
        "ffmpeg_path",
        default="",
    )

    if configured:
        return configured

    try:

        from imageio_ffmpeg import get_ffmpeg_exe

        return get_ffmpeg_exe()

    except ImportError:

        on_path = shutil.which("ffmpeg")

        if on_path:
            return on_path

        raise


def build_rtsp_url(camera: dict, password=None) -> str:
    """Build an RTSP URL from a camera dict.

    Special characters in credentials are percent-encoded (ffmpeg
    expects that); `%` itself is safe because encoding is single-pass.
    """

    host = camera.get("host", "")

    if not host:
        raise ValueError("camera has no host")

    port = camera.get("port", 554)

    user = camera.get("user", "")

    if password is None:
        password = camera.get("password") or ""

    path = camera.get("path", "/Preview_01_main")

    credentials = ""

    if user:
        credentials = (
            f"{quote(user, safe='')}:"
            f"{quote(password, safe='')}@"
        )

    return f"rtsp://{credentials}{host}:{port}{path}"


def resolve_cameras(
    entries,
    rtsp_cameras=None,
    shared_password="",
):
    """Turn tv_view.cameras config entries into (label, source)."""

    if rtsp_cameras is None:
        rtsp_cameras = []

    by_id = {}

    for camera in rtsp_cameras:

        if isinstance(camera, dict) and camera.get("id"):
            by_id[camera["id"]] = camera

    resolved = []

    for entry in entries:

        if isinstance(entry, str):

            if "://" in entry or entry.startswith("v4l2:"):
                resolved.append((entry, entry))
                continue

            camera = by_id.get(entry)

            if camera is None:
                raise ValueError(
                    f"tv_view camera {entry!r} is not a "
                    "source string and not defined under "
                    "cameras.rtsp"
                )

            password = camera.get(
                "password",
                shared_password,
            )

            resolved.append(
                (
                    entry,
                    build_rtsp_url(camera, password),
                )
            )

            continue

        if isinstance(entry, dict):

            if entry.get("source"):
                source = entry["source"]
                resolved.append(
                    (entry.get("id", source), source)
                )
                continue

            base = by_id.get(entry.get("id"), {})

            merged = dict(base)
            merged.update(entry)

            password = entry.get("password")

            if password is None:
                password = base.get(
                    "password",
                    shared_password,
                )

            resolved.append(
                (
                    entry.get("id", "camera"),
                    build_rtsp_url(merged, password),
                )
            )

            continue

        raise ValueError(
            f"unsupported tv_view camera entry: {entry!r}"
        )

    return resolved


def compute_grid(count: int, columns: int = 0) -> dict:
    """Compute a grid of H.264-friendly (even) panes for N cameras."""

    if count <= 0:
        raise ValueError("no cameras to display")

    if count == 1:

        cols, rows = 1, 1

        pane_w, pane_h = GRID_WIDTH, 2 * ROW_HEIGHT

    else:

        if columns > 0:
            cols = columns
        elif count <= 3:
            cols = count
        else:
            cols = 2

        rows = -(-count // cols)

        pane_w = GRID_WIDTH // cols
        total_h = ROW_HEIGHT if rows == 1 else 2 * ROW_HEIGHT
        pane_h = total_h // rows

    pane_w -= pane_w % 2
    pane_h -= pane_h % 2

    return {
        "cols": cols,
        "rows": rows,
        "pane_w": pane_w,
        "pane_h": pane_h,
    }


def grid_layout(grid: dict, count: int) -> str:
    """xstack layout string for the pane positions."""

    return "|".join(
        f"{(i % grid['cols']) * grid['pane_w']}_"
        f"{(i // grid['cols']) * grid['pane_h']}"
        for i in range(count)
    )


def feeder_cmd(
    source: str,
    grid: dict,
    frame_rate: int,
    ffmpeg: str,
) -> list:
    """ffmpeg command: camera -> scaled rawvideo frames on stdout."""

    pane_w = grid["pane_w"]
    pane_h = grid["pane_h"]

    vf = (
        f"fps={frame_rate},"
        f"scale={pane_w - 20}:{pane_h}:"
        "force_original_aspect_ratio=decrease,"
        f"pad={pane_w}:{pane_h}:"
        "(ow-iw)/2:(oh-ih)/2,"
        "format=yuv420p"
    )

    if source.startswith("v4l2:"):

        inputs = ["-f", "v4l2", "-i", source[len("v4l2:"):]]

    else:

        inputs = [
            "-rtsp_transport", "tcp",
            "-allowed_media_types", "video",
            "-timeout", str(RTSP_TIMEOUT_US),
            "-i", source,
        ]

    return (
        [
            ffmpeg,
            "-hide_banner", "-loglevel", "warning",
            "-fflags", "+genpts",
        ]
        + inputs
        + [
            "-vf", vf,
            "-an",
            "-f", "rawvideo",
            "-",
        ]
    )


def compositor_cmd(
    fifos,
    grid: dict,
    frame_rate: int,
    hls_dir: str,
    base_url: str,
    seq: int,
    ffmpeg: str,
) -> list:
    """ffmpeg command: rawvideo pipes -> fMP4 HLS grid stream."""

    count = len(fifos)

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "warning"]

    for fifo in fifos:
        cmd += [
            "-f", "rawvideo",
            "-pix_fmt", "yuv420p",
            "-s", f"{grid['pane_w']}x{grid['pane_h']}",
            "-r", str(frame_rate),
            "-i", fifo,
        ]

    filter_complex = (
        "".join(f"[{i}:v]" for i in range(count))
        + f"xstack=inputs={count}:"
        f"layout={grid_layout(grid, count)}[out]"
    )

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-crf", "23",
        "-g", "20",
        "-keyint_min", "20",
        "-sc_threshold", "0",
        "-f", "hls",
        "-hls_time", "1",
        "-hls_list_size", "12",
        "-hls_flags", "delete_segments+omit_endlist",
        "-hls_segment_type", "fmp4",
        "-hls_fmp4_init_filename", f"init{seq}.mp4",
        "-start_number", str(seq),
        "-hls_segment_filename",
        os.path.join(hls_dir, f"seg{seq}_%05d.m4s"),
        "-hls_base_url", f"{base_url}/",
        os.path.join(hls_dir, "live.m3u8"),
    ]

    return cmd


def detect_host_ip(hosts) -> str:
    """Local IP used to reach the given hosts (no packets sent)."""

    for host in hosts:

        if not host:
            continue

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        try:

            sock.connect((host, 9))
            return sock.getsockname()[0]

        except OSError:

            continue

        finally:

            sock.close()

    return ""


class HlsHandler(http.server.SimpleHTTPRequestHandler):

    """Static server with the MIME types a Cast player expects."""

    def guess_type(self, path):

        for ext, mime in (
            (".m3u8", "application/x-mpegurl"),
            (".m4s", "video/mp4"),
            (".mp4", "video/mp4"),
        ):

            if path.endswith(ext):
                return mime

        return super().guess_type(path)

    def end_headers(self):

        self.send_header("Cache-Control", "no-cache")
        self.send_header(
            "Access-Control-Allow-Origin", "*"
        )

        super().end_headers()

    def log_message(self, fmt, *args):

        logger.debug("hls: " + fmt, *args)


class TvViewer:

    """Live camera grid cast to a Chromecast display."""

    def __init__(
        self,
        tv_name,
        sources,
        http_port=TV_VIEW_HTTP_PORT,
        host_ip=TV_VIEW_HOST_IP,
        frame_rate=TV_VIEW_FRAME_RATE,
        columns=TV_VIEW_COLUMNS,
        work_dir=WORK_DIR,
        ffmpeg=None,
    ):

        if not tv_name:
            raise ValueError(
                "no cast device configured "
                "(config.yaml -> tv_view.tv)"
            )

        if not sources:
            raise ValueError(
                "tv_view.cameras is empty - add cameras "
                "in config.yaml"
            )

        self.tv_name = tv_name
        self.sources = list(sources)
        self.http_port = http_port
        self.host_ip = host_ip
        self.frame_rate = frame_rate
        self.work_dir = work_dir
        self.grid = compute_grid(
            len(self.sources),
            columns,
        )
        self.ffmpeg = ffmpeg or find_ffmpeg()

        self.hls_dir = os.path.join(work_dir, "hls")
        self.pipe_dir = os.path.join(work_dir, "pipes")

        self._stop = threading.Event()
        self._children = []

        self._count = len(self.sources)

        self._frame_bytes = (
            self.grid["pane_w"]
            * self.grid["pane_h"]
            * 3
            // 2
        )

    # -- lifecycle -------------------------------------------------

    def stop(self):

        self._stop.set()

        for proc in list(self._children):

            try:
                proc.kill()
            except OSError:
                pass

    def run(self) -> bool:

        """Run until stop(); returns True if the view went live."""

        for path in (self.hls_dir, self.pipe_dir):
            shutil.rmtree(path, ignore_errors=True)
            os.makedirs(path)

        self._fifos = [
            os.path.join(self.pipe_dir, f"cam{i}.raw")
            for i in range(self._count)
        ]

        for fifo in self._fifos:
            os.mkfifo(fifo)

        host_ip = self.host_ip or detect_host_ip(
            self._probe_hosts()
        )

        if not host_ip:
            raise RuntimeError(
                "could not detect this machine's LAN IP; "
                "set tv_view.host_ip in config.yaml"
            )

        self.base_url = f"http://{host_ip}:{self.http_port}"

        logger.info(
            "serving %d camera(s) at %s",
            self._count,
            self.base_url,
        )

        self._httpd = http.server.ThreadingHTTPServer(
            ("0.0.0.0", self.http_port),
            functools.partial(
                HlsHandler,
                directory=self.hls_dir,
            ),
        )

        threading.Thread(
            target=self._httpd.serve_forever,
            daemon=True,
        ).start()

        threading.Thread(
            target=self._compositor_loop,
            daemon=True,
        ).start()
        time.sleep(1)

        for index, (label, source) in enumerate(
            self.sources
        ):

            logger.info("camera %d: %s", index, label)

            threading.Thread(
                target=self._camera_loop,
                args=(index, source),
                daemon=True,
            ).start()

        try:

            self._wait_ready()
            cast = self._discover_cast()

            if cast is None:
                logger.error(
                    "cast device %r not found",
                    self.tv_name,
                )
                return False

            return self._cast_and_watch(cast)

        finally:

            self.stop()
            self._httpd.shutdown()
            logger.info("view stopped")

    # -- pipeline --------------------------------------------------

    def _probe_hosts(self):

        hosts = []

        for _, source in self.sources:

            host = urlsplit(source).hostname

            if host:
                hosts.append(host)

        hosts.append("8.8.8.8")

        return hosts

    def _wait_ready(self, timeout=120.0):

        deadline = time.time() + timeout

        while not self._stop.is_set():

            if os.path.exists(
                os.path.join(self.hls_dir, "live.m3u8")
            ) and any(
                name.endswith(".m4s")
                for name in os.listdir(self.hls_dir)
            ):

                logger.info("playlist ready")

                return True

            if time.time() >= deadline:
                break

            time.sleep(0.5)

        logger.warning(
            "no HLS output yet (%.0fs); "
            "check camera logs in %s",
            timeout,
            self.work_dir,
        )

        return False

    def _compositor_loop(self):

        seq = 0

        while not self._stop.is_set():

            self._prune_hls()

            cmd = compositor_cmd(
                self._fifos,
                self.grid,
                self.frame_rate,
                self.hls_dir,
                self.base_url,
                seq,
                self.ffmpeg,
            )

            log_path = os.path.join(
                self.work_dir,
                "compositor.log",
            )

            logger.info("starting compositor (seq=%d)", seq)

            with open(log_path, "w") as logf:

                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=logf,
                )

                self._children.append(proc)
                proc.wait()

            if self._stop.is_set():
                return

            logger.warning(
                "compositor exited (rc=%d), restarting",
                proc.returncode,
            )

            seq += 1000

            time.sleep(3)

    def _prune_hls(self):

        cutoff = time.time() - 120

        try:
            names = os.listdir(self.hls_dir)
        except OSError:
            return

        for name in names:

            path = os.path.join(self.hls_dir, name)

            try:

                if os.path.getmtime(path) < cutoff:
                    os.remove(path)

            except OSError:

                pass

    def _open_fifo(self, fifo):

        try:
            return open(fifo, "wb", buffering=0)

        except OSError:
            return None

    def _camera_loop(self, index, source):

        fifo = self._fifos[index]

        last = bytes(self._frame_bytes)

        wfd = None

        while not self._stop.is_set():

            if wfd is None:

                wfd = self._open_fifo(fifo)

                if wfd is None:
                    time.sleep(0.5)
                    continue

            log_path = os.path.join(
                self.work_dir,
                f"camera{index}.log",
            )

            logf = open(log_path, "ab", buffering=0)

            proc = subprocess.Popen(
                feeder_cmd(
                    source,
                    self.grid,
                    self.frame_rate,
                    self.ffmpeg,
                ),
                stdout=subprocess.PIPE,
                stderr=logf,
            )

            self._children.append(proc)

            started = time.time()

            last, wfd = self._pump(
                proc,
                wfd,
                fifo,
                last,
            )

            try:
                proc.stdout.close()
            except OSError:
                pass

            logf.close()

            if proc.poll() is None:
                proc.terminate()

            if self._stop.is_set():
                break

            logger.warning(
                "camera %d feeder exited, reconnecting",
                index,
            )

            delay = 5 if time.time() - started < 15 else 2

            time.sleep(delay)

        if wfd is not None:

            try:
                wfd.close()

            except OSError:

                pass

    def _pump(self, proc, wfd, fifo, last):
        """Relay frames (wallclock-paced, newest wins) to the fifo.

        On camera silence the last frame is repeated so the grid
        timeline never stalls; on feeder death the next loop pass
        starts a fresh one.
        """

        frame_bytes = self._frame_bytes

        os.set_blocking(proc.stdout.fileno(), False)

        buf = bytearray()
        pending = None
        next_write = time.time()

        while not self._stop.is_set():

            if wfd is None:

                wfd = self._open_fifo(fifo)

                if wfd is None:
                    time.sleep(0.5)
                    continue

            try:

                chunk = proc.stdout.read(1 << 20)

            except (OSError, TypeError):

                chunk = None

            if chunk:

                buf += chunk

                while len(buf) >= frame_bytes:

                    pending = bytes(buf[:frame_bytes])
                    del buf[:frame_bytes]

            elif proc.poll() is not None:

                break

            now = time.time()

            if now < next_write:

                time.sleep(
                    min(0.02, next_write - now)
                )

                continue

            if pending is not None:
                frame, pending = pending, None
                last = frame
            else:
                frame = last

            if wfd is not None:

                try:

                    wfd.write(frame)

                except (BrokenPipeError, OSError):

                    try:
                        wfd.close()

                    except OSError:
                        pass

                    wfd = None

            next_write += 1.0 / self.frame_rate

            if next_write < now - 1.0:
                next_write = now + 1.0 / self.frame_rate

        return last, wfd

    # -- cast ------------------------------------------------------

    def _discover_cast(self):

        import pychromecast

        deadline = time.time() + CAST_TIMEOUT

        while not self._stop.is_set():

            if time.time() >= deadline:
                return None

            chromecasts, browser = (
                pychromecast.get_listed_chromecasts(
                    friendly_names=[self.tv_name],
                    timeout=10,
                )
            )

            if chromecasts:

                cast = chromecasts[0]

                try:
                    cast.wait(timeout=15)

                    browser.stop_discovery()

                    logger.info(
                        "cast connected: %s (%s)",
                        cast.name,
                        cast.cast_info.model_name,
                    )

                    return cast

                except Exception:

                    logger.exception(
                        "cast connect failed, retrying"
                    )

                    browser.stop_discovery()

                    continue

            browser.stop_discovery()

            logger.info(
                "waiting for cast device %r...",
                self.tv_name,
            )

        return None

    def _cast_and_watch(self, cast) -> bool:

        url = f"{self.base_url}/live.m3u8"

        media = cast.media_controller

        try:
            cast.quit_app()

        except Exception:

            logger.debug(
                "quit_app failed", exc_info=True
            )

        media.play_media(
            url,
            "application/x-mpegurl",
            stream_type="LIVE",
        )

        logger.info("loading %s", url)

        idle_since = None
        played = False

        while not self._stop.is_set():

            state = media.status.player_state

            if state in ("PLAYING", "BUFFERING"):

                if state == "PLAYING" and not played:

                    logger.info(
                        "playing on %s", cast.name
                    )

                    played = True

                idle_since = None

            elif state in ("IDLE", "UNKNOWN"):

                if idle_since is None:
                    idle_since = time.time()

                elif (
                    time.time() - idle_since
                    > RELOAD_AFTER_IDLE
                ):

                    logger.warning(
                        "player idle, reloading"
                    )

                    try:
                        media.play_media(
                            url,
                            "application/x-mpegurl",
                            stream_type="LIVE",
                        )

                    except Exception:

                        logger.exception(
                            "reload failed"
                        )

                    idle_since = None

                    time.sleep(10)

                    continue

            time.sleep(5)

        try:
            media.stop()

        except Exception:

            logger.debug(
                "stop failed", exc_info=True
            )

        try:
            cast.disconnect()

        except Exception:

            pass

        return played


def list_cast_devices():

    import pychromecast

    chromecasts, browser = (
        pychromecast.get_chromecasts(timeout=10)
    )

    browser.stop_discovery()

    if not chromecasts:
        print("no cast devices found")
        return 0

    for cast in sorted(
        chromecasts,
        key=lambda c: c.name,
    ):

        info = cast.cast_info

        print(
            f"{info.friendly_name}  "
            f"{info.model_name}  "
            f"{info.host}:{info.port}"
        )

    return 0


def main(argv=None) -> int:

    parser = argparse.ArgumentParser(
        description=(
            "Show live cameras on a Cast device (TV)"
        )
    )

    parser.add_argument(
        "--list",
        action="store_true",
        help="list cast devices on the network",
    )

    parser.add_argument(
        "--tv",
        default=None,
        help="cast device name (overrides tv_view.tv)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="HLS server port (overrides tv_view.http_port)",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logging.getLogger("pychromecast").setLevel(
        logging.WARNING
    )

    if args.list:
        return list_cast_devices()

    try:

        sources = resolve_cameras(
            TV_VIEW_CAMERAS,
            RTSP_CAMERAS,
            CAMERA_PASSWORD,
        )

        viewer = TvViewer(
            tv_name=args.tv or TV_VIEW_TV,
            sources=sources,
            http_port=(
                args.port
                if args.port is not None
                else TV_VIEW_HTTP_PORT
            ),
        )

    except (ValueError, RuntimeError) as exc:

        print(f"tv_view: {exc}", file=sys.stderr)

        return 1

    def handle_signal(*_):

        logger.info("stopping...")

        viewer.stop()

    signal.signal(signal.SIGTERM, handle_signal)

    try:

        ok = viewer.run()

    except KeyboardInterrupt:

        viewer.stop()

        print("tv_view: stopped")

        return 0

    return 0 if ok else 1


if __name__ == "__main__":

    sys.exit(main())
