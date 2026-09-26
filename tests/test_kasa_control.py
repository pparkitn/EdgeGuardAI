import pytest

from kasa_control import parse_action


@pytest.mark.parametrize(
    "payload,expected",
    [
        ("on", "on"),
        ("OFF", "off"),
        ("  toggle  ", "toggle"),
        ('{"action": "on"}', "on"),
        ('{"action": "state"}', "state"),
        ("unknown", None),
        ("", None),
        ("{}", None),
        ('{"action": "jump"}', None),
        (None, None),
    ],
)
def test_parse_action(payload, expected):

    assert parse_action(payload) == expected