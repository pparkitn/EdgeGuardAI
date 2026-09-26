#!/usr/bin/env python3
"""Send a command to a Kasa plug over the EdgeGuard MQTT bus.

    python scripts/plug.py <name> on|off|toggle|state

State is published by the kasa controller to
edgeguard/status/plug/<name>; this script waits briefly for it.
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
        description="Control a Kasa plug via MQTT"
    )

    parser.add_argument("name")

    parser.add_argument(
        "action",
        choices=["on", "off", "toggle", "state"],
    )

    args = parser.parse_args()

    status_topic = (
        f"{MQTT_TOPIC_PREFIX}/status/plug/{args.name}"
    )

    result = {}

    def on_message(client, userdata, message):

        if message.topic == status_topic:

            result.update(
                json.loads(
                    message.payload.decode("utf-8")
                )
            )

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2
    )

    client.on_message = on_message

    client.connect(MQTT_HOST, MQTT_PORT, 10)

    client.subscribe(status_topic, qos=1)

    client.publish(
        (
            f"{MQTT_TOPIC_PREFIX}/command/plug/"
            f"{args.name}"
        ),
        json.dumps({"action": args.action}),
        qos=1,
    )

    client.loop_start()

    deadline = time.time() + 15

    while time.time() < deadline and not result:

        time.sleep(0.2)

    client.loop_stop()

    client.disconnect()

    if not result:

        print(
            "no status received (is the kasa "
            "controller running?)",
            file=sys.stderr,
        )

        return 1

    print(json.dumps(result))

    return 0


if __name__ == "__main__":

    sys.exit(main())