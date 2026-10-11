import json
import time
from unittest import mock

import pytest

import voice.broadcaster as broadcaster
from voice.broadcaster import Broadcaster


def make_broadcaster():

    bc = Broadcaster.__new__(Broadcaster)

    bc.last_known_seen = {}

    bc.last_announcement = {}

    bc._pending_unknown = {}

    bc.last_garage_state = None

    bc.announce = mock.Mock()

    bc.say = mock.Mock()

    return bc


UNKNOWN = {
    "event_type": "unknown_person_detected",
    "camera_id": "garage",
}

RECOGNIZED = {
    "event_type": "person_recognized",
    "camera_id": "garage",
    "person_id": "piotr",
}


@pytest.fixture(autouse=True)
def fast_confirm_delay():

    original = broadcaster.UNKNOWN_CONFIRM_DELAY

    broadcaster.UNKNOWN_CONFIRM_DELAY = 0.1

    yield

    broadcaster.UNKNOWN_CONFIRM_DELAY = original


def test_unknown_not_announced_immediately():

    bc = make_broadcaster()

    bc.handle_event(UNKNOWN)

    bc.announce.assert_not_called()

    assert "garage" in bc._pending_unknown


def test_unknown_not_announced_when_disabled():

    original = broadcaster.ANNOUNCE_UNKNOWN

    broadcaster.ANNOUNCE_UNKNOWN = False

    try:

        bc = make_broadcaster()

        bc.handle_event(UNKNOWN)

        time.sleep(0.3)

        bc.announce.assert_not_called()

        assert "garage" not in bc._pending_unknown

    finally:

        broadcaster.ANNOUNCE_UNKNOWN = original


def test_unknown_announced_after_confirm_delay():

    bc = make_broadcaster()

    bc.handle_event(UNKNOWN)

    time.sleep(0.3)

    bc.announce.assert_called_once()

    text = bc.announce.call_args[0][1]

    assert "unknown" in text.lower()


def test_recognized_cancels_pending_unknown():

    bc = make_broadcaster()

    bc.handle_event(UNKNOWN)

    bc.handle_event(RECOGNIZED)

    bc.announce.assert_called_once()

    text = bc.announce.call_args[0][1]

    assert "piotr" in text

    assert "garage" not in bc._pending_unknown

    time.sleep(0.3)

    bc.announce.assert_called_once()


def test_duplicate_unknown_events_schedule_once():

    bc = make_broadcaster()

    bc.handle_event(UNKNOWN)

    bc.handle_event(UNKNOWN)

    bc.handle_event(UNKNOWN)

    time.sleep(0.3)

    assert bc.announce.call_count == 1


class FakeMsg:

    def __init__(self, topic, payload):

        self.topic = topic

        self.payload = payload


def test_say_command_json_payload():

    bc = make_broadcaster()

    msg = FakeMsg(
        broadcaster.SAY_TOPIC,
        json.dumps({"text": "hello"}).encode(),
    )

    bc._on_message(None, None, msg)

    bc.say.assert_called_once_with("hello")


def test_say_command_raw_text():

    bc = make_broadcaster()

    bc._on_message(
        None,
        None,
        FakeMsg(
            broadcaster.SAY_TOPIC,
            b"raw text message",
        ),
    )

    bc.say.assert_called_once_with("raw text message")


def test_say_command_ignores_empty():

    bc = make_broadcaster()

    bc._on_message(
        None,
        None,
        FakeMsg(
            broadcaster.SAY_TOPIC,
            b'{"text": "  "}',
        ),
    )

    bc.say.assert_not_called()


def test_say_command_does_not_touch_camera_events():

    bc = make_broadcaster()

    bc._on_message(
        None,
        None,
        FakeMsg(
            "edgeguard/camera/garage",
            json.dumps(RECOGNIZED).encode(),
        ),
    )

    bc.say.assert_not_called()

    assert bc.announce.call_count == 1


def garage_msg(states):

    return FakeMsg(
        broadcaster.GARAGE_DOORS_TOPIC,
        json.dumps(states).encode(),
    )


@pytest.fixture(autouse=True)
def garage_templates():

    original = broadcaster.GARAGE_DOORS_TEMPLATES

    broadcaster.GARAGE_DOORS_TEMPLATES = {
        "open": "The {side} garage door is open.",
        "closed": "The {side} garage door is closed.",
    }

    yield

    broadcaster.GARAGE_DOORS_TEMPLATES = original


def test_garage_doors_first_message_is_baseline():

    bc = make_broadcaster()

    bc._on_message(
        None,
        None,
        garage_msg(
            {"left": "closed", "right": "closed"}
        ),
    )

    bc.say.assert_not_called()

    assert bc.last_garage_state == {
        "left": "closed",
        "right": "closed",
    }


def test_garage_doors_announces_open_change():

    bc = make_broadcaster()

    bc.last_garage_state = {
        "left": "closed",
        "right": "closed",
    }

    bc._on_message(
        None,
        None,
        garage_msg(
            {"left": "open", "right": "closed"}
        ),
    )

    bc.say.assert_called_once()

    text = bc.say.call_args[0][0]

    assert "left" in text

    assert "open" in text


def test_garage_doors_local_only_by_default():

    original = broadcaster.GARAGE_DOORS_SPEAKERS

    broadcaster.GARAGE_DOORS_SPEAKERS = []

    try:

        bc = make_broadcaster()

        bc.last_garage_state = {
            "left": "closed",
            "right": "closed",
        }

        bc._on_message(
            None,
            None,
            garage_msg(
                {"left": "open", "right": "closed"}
            ),
        )

        bc.say.assert_called_once()

        assert (
            bc.say.call_args.kwargs["speakers"]
            == []
        )

        assert (
            bc.say.call_args.kwargs["local"]
            is True
        )

    finally:

        broadcaster.GARAGE_DOORS_SPEAKERS = original


def test_garage_doors_announces_both_changes():

    bc = make_broadcaster()

    bc.last_garage_state = {
        "left": "closed",
        "right": "closed",
    }

    bc._on_message(
        None,
        None,
        garage_msg(
            {"left": "open", "right": "open"}
        ),
    )

    text = bc.say.call_args[0][0]

    assert "left" in text

    assert "right" in text

    assert text.count("open") == 2


def test_garage_doors_no_announce_without_change():

    bc = make_broadcaster()

    bc.last_garage_state = {
        "left": "closed",
        "right": "closed",
    }

    bc._on_message(
        None,
        None,
        garage_msg(
            {"left": "closed", "right": "closed"}
        ),
    )

    bc.say.assert_not_called()


def test_garage_doors_malformed_payload_ignored():

    bc = make_broadcaster()

    bc.last_garage_state = {
        "left": "closed",
        "right": "closed",
    }

    bc._on_message(
        None,
        None,
        FakeMsg(
            broadcaster.GARAGE_DOORS_TOPIC,
            b"not json",
        ),
    )

    bc.say.assert_not_called()


def test_garage_doors_cooldown_suppresses_second_change():

    bc = make_broadcaster()

    bc.last_garage_state = {
        "left": "closed",
        "right": "closed",
    }

    broadcast_original = broadcaster.GARAGE_DOORS_COOLDOWN

    broadcaster.GARAGE_DOORS_COOLDOWN = 30.0

    try:

        bc._on_message(
            None,
            None,
            garage_msg(
                {"left": "open", "right": "closed"}
            ),
        )

        bc._on_message(
            None,
            None,
            garage_msg(
                {"left": "open", "right": "open"}
            ),
        )

    finally:

        broadcaster.GARAGE_DOORS_COOLDOWN = (
            broadcast_original
        )

    bc.say.assert_called_once()