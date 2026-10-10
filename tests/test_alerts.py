import time
from unittest import mock

import pytest

import voice.broadcaster as broadcaster
from voice.config import _slot_minutes, time_in_slots


def make_broadcaster():

    bc = broadcaster.Broadcaster.__new__(
        broadcaster.Broadcaster
    )

    bc.last_alert_time = {}

    bc.say = mock.Mock()

    return bc


ALL_DAY = [{"start": "00:00", "end": "23:59"}]

RULE = {
    "id": "night_front_door",
    "camera": "front_door",
    "event": "multiple_faces_detected",
    "min_faces": 2,
    "time_slots": ALL_DAY,
    "speakers": ["Bedroom  speaker"],
    "local": False,
    "cooldown": 600,
    "message": "Multiple people detected at the front door.",
}

MULTI = {
    "event_type": "multiple_faces_detected",
    "camera_id": "front_door",
    "face_count": 2,
}


@pytest.fixture(autouse=True)
def empty_alerts():

    original = broadcaster.ALERTS

    broadcaster.ALERTS = []

    yield

    broadcaster.ALERTS = original


def test_slot_minutes_parses():

    assert _slot_minutes("01:30") == 90

    assert _slot_minutes("23:59") == 1439


def test_slot_minutes_rejects_bad():

    with pytest.raises(ValueError):
        _slot_minutes("nope")


def test_time_in_slot_simple():

    slot = [{"start": "01:00", "end": "05:00"}]

    assert time_in_slots(time.localtime(0), []) is True

    inside = time.struct_time(
        (2026, 1, 1, 3, 30, 0, 3, 1, -1)
    )

    outside = time.struct_time(
        (2026, 1, 1, 6, 0, 0, 3, 1, -1)
    )

    assert time_in_slots(inside, slot) is True

    assert time_in_slots(outside, slot) is False


def test_time_in_slot_overnight():

    slot = [{"start": "23:00", "end": "05:00"}]

    late = time.struct_time(
        (2026, 1, 1, 23, 30, 0, 3, 1, -1)
    )

    early = time.struct_time(
        (2026, 1, 1, 2, 0, 0, 3, 1, -1)
    )

    noon = time.struct_time(
        (2026, 1, 1, 12, 0, 0, 3, 1, -1)
    )

    assert time_in_slots(late, slot) is True

    assert time_in_slots(early, slot) is True

    assert time_in_slots(noon, slot) is False


def test_alert_fires():

    broadcaster.ALERTS = [RULE]

    bc = make_broadcaster()

    bc._check_alerts(MULTI)

    bc.say.assert_called_once_with(
        RULE["message"],
        speakers=["Bedroom  speaker"],
        local=False,
    )


def test_alert_ignored_for_other_camera():

    broadcaster.ALERTS = [RULE]

    bc = make_broadcaster()

    bc._check_alerts(
        {**MULTI, "camera_id": "garage"}
    )

    bc.say.assert_not_called()


def test_alert_ignored_for_other_event():

    broadcaster.ALERTS = [RULE]

    bc = make_broadcaster()

    bc._check_alerts(
        {**MULTI, "event_type": "person_recognized"}
    )

    bc.say.assert_not_called()


def test_alert_ignored_below_min_faces():

    broadcaster.ALERTS = [RULE]

    bc = make_broadcaster()

    bc._check_alerts(
        {**MULTI, "face_count": 1}
    )

    bc.say.assert_not_called()


def test_alert_ignored_outside_time_slot():

    rule = {
        **RULE,
        "time_slots": [{"start": "01:00", "end": "05:00"}],
    }

    broadcaster.ALERTS = [rule]

    bc = make_broadcaster()

    with mock.patch(
        "voice.broadcaster.time.localtime",
        return_value=time.struct_time(
            (2026, 1, 1, 12, 0, 0, 3, 1, -1)
        ),
    ):

        bc._check_alerts(MULTI)

    bc.say.assert_not_called()


def test_alert_respects_cooldown():

    broadcaster.ALERTS = [RULE]

    bc = make_broadcaster()

    bc._check_alerts(MULTI)

    bc._check_alerts(MULTI)

    bc.say.assert_called_once()


def test_alert_fires_again_after_cooldown():

    rule = {**RULE, "cooldown": 0}

    broadcaster.ALERTS = [rule]

    bc = make_broadcaster()

    bc._check_alerts(MULTI)

    bc._check_alerts(MULTI)

    assert bc.say.call_count == 2


def test_alert_no_message_skipped():

    broadcaster.ALERTS = [{**RULE, "message": ""}]

    bc = make_broadcaster()

    bc._check_alerts(MULTI)

    bc.say.assert_not_called()
