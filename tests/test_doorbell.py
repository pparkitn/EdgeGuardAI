import io
import json
from unittest import mock

import pytest

from doorbell import (
    DoorbellAuthError,
    DoorbellClient,
    DoorbellError,
)


def _response(payload):
    return io.BytesIO(
        json.dumps(payload).encode("utf-8")
    )


class FakeResponse:

    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return json.dumps(
            self._payload
        ).encode("utf-8")


def test_login_sets_token():

    client = DoorbellClient(
        host="192.168.2.32",
        port=80,
        user="admin",
        password="secret",
    )

    with mock.patch(
        "doorbell.url_request.urlopen",
        return_value=_response(
            [
                {
                    "cmd": "Login",
                    "code": 0,
                    "value": {
                        "Token": {
                            "leaseTime": 3600,
                            "name": "abc123",
                        }
                    },
                }
            ]
        ),
    ):

        token = client.login()

    assert token == "abc123"

    assert client.token == "abc123"


def test_login_failure_returns_empty():

    client = DoorbellClient(
        host="192.168.2.32",
        user="admin",
        password="wrong",
    )

    with mock.patch(
        "doorbell.url_request.urlopen",
        return_value=_response(
            [
                {
                    "cmd": "Login",
                    "code": 1,
                    "error": {
                        "detail": "password wrong",
                        "rspCode": -502,
                    },
                }
            ]
        ),
    ):

        assert client.login() == ""


def test_siren_on_sends_manual_switch_1():

    client = DoorbellClient(
        host="192.168.2.32",
        user="admin",
        password="secret",
    )

    client.token = "tok"

    captured = {}

    def fake_urlopen(request, **kwargs):

        captured["url"] = request.full_url

        captured["body"] = json.loads(
            request.data.decode("utf-8")
        )

        return FakeResponse(
            [
                {
                    "cmd": "AudioAlarmPlay",
                    "code": 0,
                    "value": {"rspCode": 200},
                }
            ]
        )

    with mock.patch(
        "doorbell.url_request.urlopen",
        side_effect=fake_urlopen,
    ):

        assert client.trigger_siren(True) is True

    assert "cmd=AudioAlarmPlay" in captured["url"]

    param = captured["body"][0]["param"]

    assert param["manual_switch"] == 1

    assert param["alarm_mode"] == "manul"


def test_siren_off_sends_manual_switch_0():

    client = DoorbellClient(
        host="192.168.2.32",
        user="admin",
        password="secret",
    )

    client.token = "tok"

    captured = {}

    def fake_urlopen(request, **kwargs):

        captured["body"] = json.loads(
            request.data.decode("utf-8")
        )

        return FakeResponse(
            [
                {
                    "cmd": "AudioAlarmPlay",
                    "code": 0,
                    "value": {"rspCode": 200},
                }
            ]
        )

    with mock.patch(
        "doorbell.url_request.urlopen",
        side_effect=fake_urlopen,
    ):

        assert client.trigger_siren(False) is True

    assert (
        captured["body"][0]["param"]["manual_switch"]
        == 0
    )


def test_siren_raises_when_login_fails():

    client = DoorbellClient(
        host="192.168.2.32",
        user="admin",
        password="wrong",
    )

    with mock.patch(
        "doorbell.url_request.urlopen",
        return_value=_response(
            [
                {
                    "cmd": "Login",
                    "code": 1,
                    "error": {"detail": "password wrong"},
                }
            ]
        ),
    ):

        with pytest.raises(DoorbellAuthError):
            client.trigger_siren(True)


def test_missing_config_raises():

    client = DoorbellClient(host="", password="")

    with pytest.raises(DoorbellError):
        client.trigger_siren(True)
