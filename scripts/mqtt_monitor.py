import argparse
import json
import signal
import sys

import paho.mqtt.client as mqtt

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
GRAY = "\033[90m"
BOLD = "\033[1m"
RESET = "\033[0m"

COLORS = {
    "person_recognized": GREEN,
    "unknown_person_detected": RED,
}

stats = {
    "total": 0,
    "by_type": {},
    "people": {},
}


def colorize(text, color):

    if not sys.stdout.isatty():
        return text

    return f"{color}{text}{RESET}"


def format_event(event):

    event_type = event.get(
        "event_type",
        "unknown",
    )

    color = COLORS.get(
        event_type,
        BLUE,
    )

    person = event.get(
        "person_id",
        "?",
    )

    if event_type == "unknown_person_detected":
        person = "UNKNOWN"

    confidence = event.get(
        "confidence",
        float("nan"),
    )

    timestamp = event.get(
        "timestamp",
        "-",
    )

    source = event.get(
        "source",
        "-",
    )

    camera = event.get(
        "camera_id",
        "-",
    )

    event_id = event.get(
        "event_id",
        "-",
    )

    line = (
        f"{colorize(timestamp, GRAY)} "
        f"{colorize(event_type, color):24s} "
        f"{colorize(person, BOLD):10s} "
        f"{colorize(f'{confidence:.3f}', color):8s} "
        f"src={source} cam={camera} "
        f"{colorize(event_id, GRAY)}"
    )

    return line


def record(event):

    stats["total"] += 1

    event_type = event.get(
        "event_type",
        "unknown",
    )

    stats["by_type"][event_type] = (
        stats["by_type"].get(event_type, 0)
        + 1
    )

    person = event.get("person_id")

    if person is not None:

        stats["people"][person] = (
            stats["people"].get(person, 0)
            + 1
        )


def print_summary():

    print()
    print(
        colorize(
            "--- summary ---",
            BOLD,
        )
    )

    print(
        f"Total events: {stats['total']}"
    )

    for event_type, count in sorted(
        stats["by_type"].items()
    ):
        print(f"  {event_type}: {count}")

    if stats["people"]:

        print("Recognized people:")

        for name, count in sorted(
            stats["people"].items()
        ):
            print(f"  {name}: {count}")


def on_message(client, userdata, msg):

    try:

        event = json.loads(
            msg.payload.decode()
        )

    except (json.JSONDecodeError, UnicodeDecodeError):

        print(
            f"{colorize('RAW', YELLOW)} "
            f"{msg.topic}: "
            f"{msg.payload.decode(errors='replace')}"
        )

        return

    record(event)

    print(
        f"{colorize(msg.topic, BLUE)}\n"
        f"  {format_event(event)}"
    )


def main():

    parser = argparse.ArgumentParser(
        description=(
            "EdgeGuard AI - live MQTT event monitor"
        ),
    )

    parser.add_argument(
        "--host",
        default="JETSON_IP",
        help="MQTT broker host (default: JETSON_IP)",
    )

    parser.add_argument(
        "--port",
        type=int,
        default=1883,
        help="MQTT broker port (default: 1883)",
    )

    parser.add_argument(
        "--topic",
        default="edgeguard/#",
        help="Topic filter (default: edgeguard/#)",
    )

    args = parser.parse_args()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
    )

    client.on_message = on_message

    def on_disconnect(client, userdata, flags, reason_code, properties=None):
        print(
            colorize(
                "[broker disconnected - "
                "retrying...]",
                YELLOW,
            )
        )

    client.on_disconnect = on_disconnect

    def handle_sigint(sig, frame):

        client.disconnect()

        client.loop_stop()

        print_summary()

        sys.exit(0)

    signal.signal(
        signal.SIGINT,
        handle_sigint,
    )

    print(
        colorize(
            "EdgeGuard AI - MQTT monitor",
            BOLD,
        )
    )

    print(
        f"Connecting to "
        f"{args.host}:{args.port} "
        f"subscribing to '{args.topic}'"
    )

    print(
        "Press Ctrl+C for summary and exit"
    )

    client.connect(
        args.host,
        args.port,
    )

    client.subscribe(
        args.topic,
        qos=1,
    )

    try:

        client.loop_forever()

    except KeyboardInterrupt:

        handle_sigint(None, None)


if __name__ == "__main__":
    main()