"""Garage door open/closed detection from the garage camera.

Uses the fixed garage Reolink camera: two door ROIs (percent-based)
are compared against a stored "closed" reference frame; a large mean
absolute difference means the door is open.

    python -m garage_doors reference     # capture reference (doors CLOSED)
    python -m garage_doors check         # one-shot: report door states
    python -m garage_doors calibrate     # still + ROI overlay + stats
    python -m garage_doors monitor       # loop: publish changes over MQTT

Config: config.yaml -> garage_doors:
  camera_id: garage            # which cameras.rtsp entry to read
  reference: data/garage_door_reference.jpg
  interval: 15                 # monitor loop seconds
  threshold: 25.0              # MAD -> open
  close_threshold: 12.0        # MAD below this -> closed (hysteresis)
  rois:                        # door ROIs as frame fractions (x,y,w,h)
    left:  {x: 0.05, y: 0.12, w: 0.42, h: 0.78}
    right: {x: 0.53, y: 0.12, w: 0.42, h: 0.78}

MQTT topic on state change: edgeguard/garage/doors
  payload {"left": "open|closed", "right": "open|closed"} (QoS 1)

CI-safe: cv2 is imported lazily; tests only exercise the pure math.
"""

import argparse
import json
import logging
from pathlib import Path
import subprocess
import sys
import time

from edgeguard_config import (
    get,
    get_bool,
    get_float,
    get_int,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent

DOORBELL_REFERENCE_DEFAULT = str(
    PROJECT_ROOT / "data" / "garage_door_reference.jpg"
)

CAMERA_ID = get(
    "garage_doors",
    "camera_id",
    default="garage",
)

REFERENCE_PATH = get(
    "garage_doors",
    "reference",
    default=DOORBELL_REFERENCE_DEFAULT,
)

MONITOR_INTERVAL = get_int(
    "garage_doors",
    "interval",
    default=15,
)

THRESHOLD = get_float(
    "garage_doors",
    "threshold",
    default=25.0,
)

CLOSE_THRESHOLD = get_float(
    "garage_doors",
    "close_threshold",
    default=12.0,
)

# While both doors stay closed, refresh the reference frame every
# this many monitor cycles so day/night lighting drift doesn't
# push the "closed" MAD floor up toward the open threshold.
REFRESH_REFERENCE = get_bool(
    "garage_doors",
    "refresh_reference",
    default=True,
)

REFRESH_CYCLES = get_int(
    "garage_doors",
    "refresh_cycles",
    default=40,
)

ROIS = get(
    "garage_doors",
    "rois",
    default={
        "left": {
            "x": 0.05,
            "y": 0.12,
            "w": 0.42,
            "h": 0.78,
        },
        "right": {
            "x": 0.53,
            "y": 0.12,
            "w": 0.42,
            "h": 0.78,
        },
    },
)

MQTT_TOPIC_PREFIX = get(
    "broker",
    "topic_prefix",
    default="edgeguard",
)

MQTT_HOST = get(
    "broker",
    "host",
    default="JETSON_IP",
)

MQTT_PORT = get_int(
    "broker",
    "port",
    default=1883,
)


def get_ffmpeg() -> str:

    configured = get(
        "vision",
        "ffmpeg_path",
        default="",
    )

    if configured:

        return configured

    try:

        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()

    except Exception:

        return "/usr/bin/ffmpeg"


def camera_rtsp_url() -> str:

    """Build the RTSP URL for the configured camera id."""

    from urllib.parse import quote

    cameras = get(
        "cameras",
        "rtsp",
        default=[],
    )

    camera = next(
        (
            c
            for c in cameras
            if c.get("id") == CAMERA_ID
        ),
        None,
    )

    if camera is None:

        raise ValueError(
            f"Camera id {CAMERA_ID!r} not found in "
            "config.yaml -> cameras.rtsp"
        )

    host = camera.get("host", "")

    port = camera.get("port", 554)

    user = camera.get("user", "")

    password = camera.get(
        "password",
        get(
            "cameras",
            "rtsp",
            "password",
            default="",
            env="EDGEGUARD_CAMERA_PASSWORD",
        ),
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


def capture_still(
    path: str,
    timeout: int = 20,
) -> bool:

    """Grab one frame from the garage camera into a JPEG file."""

    ffmpeg = get_ffmpeg()

    url = camera_rtsp_url()

    for attempt in range(2):

        try:

            subprocess.run(
                [
                    ffmpeg,
                    "-loglevel",
                    "error",
                    "-rtsp_transport",
                    "tcp",
                    "-i",
                    url,
                    "-frames:v",
                    "1",
                    "-f",
                    "image2",
                    "-y",
                    path,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                timeout=timeout,
            )

        except Exception:

            logger.exception(
                "ffmpeg still capture attempt %d failed",
                attempt + 1,
            )

        else:

            import os

            if (
                os.path.exists(path)
                and os.path.getsize(path) > 0
            ):
                return True

        time.sleep(2)

    return False


def _roi_slice(frame, roi):


    height, width = frame.shape[:2]

    x0 = int(roi["x"] * width)

    y0 = int(roi["y"] * height)

    x1 = int((roi["x"] + roi["w"]) * width)

    y1 = int((roi["y"] + roi["h"]) * height)

    return (
        frame[y0:y1, x0:x1]
        if (y1 > y0 and x1 > x0)
        else frame
    )


def _gray_mad(a, b):

    import numpy as np

    if a.shape != b.shape:

        raise ValueError(
            "ROI shapes differ: "
            f"{a.shape} vs {b.shape}"
        )

    diff = np.abs(
        a.astype(np.float32)
        - b.astype(np.float32)
    )

    return float(diff.mean())


def roi_mads(
    frame,
    reference,
    rois=None,
) -> dict:

    """Per-door mean absolute difference vs the reference frame.

    Both inputs are full-frame BGR arrays; ROIs are applied inside.
    """

    import cv2

    ref = cv2.cvtColor(
        cv2.resize(
            reference,
            (640, int(640 * reference.shape[0] / reference.shape[1])),
        ),
        cv2.COLOR_BGR2GRAY,
    )

    cur = cv2.cvtColor(
        cv2.resize(
            frame,
            (640, int(640 * frame.shape[0] / frame.shape[1])),
        ),
        cv2.COLOR_BGR2GRAY,
    )

    blur_kernel = (5, 5)

    ref = cv2.GaussianBlur(ref, blur_kernel, 0)

    cur = cv2.GaussianBlur(cur, blur_kernel, 0)

    return {
        name: _gray_mad(
            _roi_slice(ref, roi),
            _roi_slice(cur, roi),
        )
        for name, roi in (rois or ROIS).items()
    }


def classify(
    frame,
    reference,
    threshold=THRESHOLD,
    close_threshold=CLOSE_THRESHOLD,
    rois=None,
):

    """Return per-door states ('open'/'closed') from MAD values."""

    mads = roi_mads(frame, reference, rois)

    states = {
        name: (
            "open"
            if mad > threshold
            else "closed"
        )
        for name, mad in mads.items()
    }

    return states, mads


def hysteresis(
    states,
    previous,
    mads,
    threshold=THRESHOLD,
    close_threshold=CLOSE_THRESHOLD,
):

    """Apply a falling edge so brief flicker doesn't flip the state.

    open   requires mad > threshold
    closed requires mad < close_threshold (lower bar)
    """

    result = {}

    for name, mad in mads.items():

        last = (previous or {}).get(name, "closed")

        if last == "closed":

            result[name] = (
                "open"
                if mad > threshold
                else "closed"
            )

        else:

            result[name] = (
                "closed"
                if mad < close_threshold
                else "open"
            )

    return result


def load_reference(path=REFERENCE_PATH):

    import os

    import cv2

    if not os.path.exists(path):

        raise FileNotFoundError(
            f"Reference frame missing: {path} "
            "(run: python -m garage_doors reference)"
        )

    return cv2.imread(path)


def save_reference(path=REFERENCE_PATH, timeout=20) -> bool:

    """Capture the current camera view as the closed-door reference."""

    if capture_still(path, timeout=timeout):

        print(f"Reference saved: {path}")

        return True

    print(
        "Reference capture FAILED "
        "(check camera reachability)",
        file=sys.stderr,
    )

    return False


def check_once(path=REFERENCE_PATH):

    import os
    import tempfile

    import cv2

    fd, tmp = tempfile.mkstemp(suffix=".jpg")

    os.close(fd)

    try:

        if not capture_still(tmp):

            raise RuntimeError(
                "Could not capture a frame from the camera"
            )

        frame = cv2.imread(tmp)

        reference = load_reference(path)

        states, mads = classify(frame, reference)

        return states, mads

    finally:

        os.remove(tmp)


def should_refresh_reference(
    states,
    consecutive_closed,
    refresh_cycles=REFRESH_CYCLES,
) -> bool:

    """Refresh the closed-door baseline after enough quiet cycles."""

    if not REFRESH_REFERENCE or refresh_cycles <= 0:

        return False

    if any(
        state != "closed"
        for state in (states or {}).values()
    ):

        return False

    return consecutive_closed >= refresh_cycles


def publish_state(client, states, prefix=MQTT_TOPIC_PREFIX):

    topic = f"{prefix}/garage/doors"

    payload = json.dumps(states)

    client.publish(
        topic,
        payload,
        qos=1,
        retain=True,
    )


def monitor_loop(
    interval=MONITOR_INTERVAL,
    path=REFERENCE_PATH,
):

    import paho.mqtt.client as mqtt

    reference = load_reference(path)

    client = mqtt.Client()

    client.connect(MQTT_HOST, MQTT_PORT, 10)

    client.loop_start()

    previous = None

    consecutive_closed = 0

    logger.info(
        "Garage door monitor started "
        "(interval %d s, topic %s/garage/doors)",
        interval,
        MQTT_TOPIC_PREFIX,
    )

    while True:

        try:

            import os
            import tempfile

            import cv2

            fd, tmp = tempfile.mkstemp(suffix=".jpg")

            os.close(fd)

            try:

                if not capture_still(tmp):

                    logger.warning(
                        "Still capture failed; "
                        "skipping cycle"
                    )

                    continue

                frame = cv2.imread(tmp)

            finally:

                os.remove(tmp)

            mads = roi_mads(frame, reference)

            states = hysteresis(
                None,
                previous,
                mads,
            )

            if all(
                state == "closed"
                for state in states.values()
            ):

                consecutive_closed += 1

                if should_refresh_reference(
                    states,
                    consecutive_closed,
                ):

                    tmp_ref, fd2 = tempfile.mkstemp(
                        suffix=".jpg"
                    )

                    os.close(fd2)

                    try:

                        if capture_still(tmp_ref):

                            reference = cv2.imread(tmp_ref)

                            cv2.imwrite(path, reference)

                            consecutive_closed = 0

                            logger.info(
                                "Garage door reference "
                                "refreshed (both closed)"
                            )

                            continue

                    finally:

                        os.remove(tmp_ref)

            else:

                consecutive_closed = 0

            if states != previous:

                publish_state(client, states)

                logger.info(
                    "Garage doors changed: %s "
                    "(mads=%s)",
                    states,
                    {k: round(v, 1) for k, v in mads.items()},
                )

                previous = states

            else:

                logger.debug(
                    "Garage doors: %s (mads=%s)",
                    states,
                    {k: round(v, 1) for k, v in mads.items()},
                )

        except Exception:

            logger.exception(
                "Garage door monitor cycle failed"
            )

        time.sleep(interval)


def calibrate(path=REFERENCE_PATH):

    import os
    import tempfile

    import cv2

    fd, tmp = tempfile.mkstemp(suffix=".jpg")

    os.close(fd)

    try:

        if not capture_still(tmp):

            raise RuntimeError(
                "Could not capture a frame from the camera"
            )

        frame = cv2.imread(tmp)

        reference = load_reference(path)

        height, width = frame.shape[:2]

        annotated = frame.copy()

        for name, roi in ROIS.items():

            x0 = int(roi["x"] * width)

            y0 = int(roi["y"] * height)

            x1 = int((roi["x"] + roi["w"]) * width)

            y1 = int((roi["y"] + roi["h"]) * height)

            cv2.rectangle(
                annotated,
                (x0, y0),
                (x1, y1),
                (0, 0, 255),
                4,
            )

            cv2.putText(
                annotated,
                name,
                (x0, max(30, y0 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.2,
                (0, 0, 255),
                3,
            )

        out = str(
            PROJECT_ROOT / "data" / "garage_door_calibrate.jpg"
        )

        os.makedirs(os.path.dirname(out), exist_ok=True)

        cv2.imwrite(out, annotated)

        mads = roi_mads(frame, reference)

        print(f"Calibration frame + ROIs saved: {out}")

        print("Open it and adjust rois in config.yaml if the")
        print("red boxes don't sit on the two door panels.\n")

        print("Door ROIs (reference = closed):")

        for name, mad in mads.items():

            print(
                f"  {name}: MAD {mad:.1f} "
                f"(> threshold {THRESHOLD} = open)"
            )

        return mads

    finally:

        os.remove(tmp)


def main(argv=None):

    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s %(levelname)-7s "
            "%(name)s: %(message)s"
        ),
    )

    parser = argparse.ArgumentParser(
        description="Garage door open/closed detection"
    )

    subparsers = parser.add_subparsers(
        dest="command",
    )

    subparsers.add_parser(
        "reference",
        help="capture the closed-door reference frame",
    )

    subparsers.add_parser(
        "check",
        help="one-shot: report door states",
    )

    subparsers.add_parser(
        "calibrate",
        help="still + ROI overlay + stats for tuning",
    )

    subparsers.add_parser(
        "monitor",
        help="loop: publish state changes over MQTT",
    )

    args = parser.parse_args(argv)

    if args.command is None:

        parser.print_help()

        return 2

    if args.command == "reference":

        return 0 if save_reference() else 1

    if args.command == "check":

        try:

            states, mads = check_once()

        except Exception as exc:

            print(
                f"check FAILED: {exc}",
                file=sys.stderr,
            )

            return 1

        print(
            "Garage doors: "
            f"left={states.get('left')} "
            f"right={states.get('right')}"
        )

        print(
            "MADs: "
            + ", ".join(
                f"{k}={v:.1f}"
                for k, v in mads.items()
            )
        )

        return 0

    if args.command == "calibrate":

        try:

            calibrate()

        except Exception as exc:

            print(
                f"calibrate FAILED: {exc}",
                file=sys.stderr,
            )

            return 1

        return 0

    if args.command == "monitor":

        monitor_loop()

        return 0

    return 2


if __name__ == "__main__":

    sys.exit(main())