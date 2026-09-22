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

    bc.announce = mock.Mock()

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