#!/usr/bin/env python3
"""Broadcast a voice announcement through the EdgeGuard MQTT bus.

    python scripts/say.py "Michael, its time to get ready for swimming."

Publishes {"text": ...} to edgeguard/command/say (config: broker.say_topic);
the voice broadcaster on the Pi synthesizes it with AWS Polly and plays
it on the local speaker and all Google Cast speakers.
"""

import argparse
import json
from pathlib import Path
import sys
import time

import paho.mqtt.client as mqtt

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent),
)

from edgeguard_config import get, get_int  # noqa: E402

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

MQTT_TOPIC_PREFIX = get(
    "broker",
    "topic_prefix",
    default="edgeguard",
)


def main():

    parser = argparse.ArgumentParser(
        description="Broadcast a voice announcement via MQTT"
    )

    parser.add_argument(
        "text",
        nargs="+",
        help="message to speak (multiple words are joined)",
    )

    args = parser.parse_args()

    text = " ".join(args.text)

    topic = f"{MQTT_TOPIC_PREFIX}/command/say"

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2
    )

    client.connect(MQTT_HOST, MQTT_PORT, 10)

    client.publish(
        topic,
        json.dumps({"text": text}),
        qos=1,
    )

    client.loop_start()

    time.sleep(1)

    client.loop_stop()

    client.disconnect()

    print(
        f"sent to {topic}: {text}",
        file=sys.stderr,
    )

    return 0


if __name__ == "__main__":

    sys.exit(main())