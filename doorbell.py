"""Reolink doorbell alarm/siren control (HTTP CGI API).

Triggers the built-in siren of a Reolink doorbell (e.g. the D340W
Video Doorbell) over its local HTTP API.

    python -m doorbell siren on
    python -m doorbell siren off

Config: config.yaml -> doorbell (host, port, user, password),
overridable with EDGEGUARD_DOORBELL_HOST / EDGEGUARD_DOORBELL_PORT /
EDGEGUARD_DOORBELL_USER / EDGEGUARD_DOORBELL_PASSWORD.
The password is a secret - keep it in the gitignored per-device
config.yaml (or an env var), never in config.yaml.example.

Note: the RTSP password can differ from the web/admin password on
Reolink doorbells; the HTTP API needs the web/admin one. The siren
is controlled with the AudioAlarmPlay command (manual switch).
"""

import argparse
import json
import logging
import sys
from urllib import error as url_error
from urllib import request as url_request

from edgeguard_config import get, get_int

logger = logging.getLogger(__name__)

DOORBELL_HOST = get(
    "doorbell",
    "host",
    env="EDGEGUARD_DOORBELL_HOST",
    default="",
)

DOORBELL_PORT = get_int(
    "doorbell",
    "port",
    default=80,
)

DOORBELL_USER = get(
    "doorbell",
    "user",
    env="EDGEGUARD_DOORBELL_USER",
    default="admin",
)

DOORBELL_PASSWORD = get(
    "doorbell",
    "password",
    env="EDGEGUARD_DOORBELL_PASSWORD",
    default="",
)


class DoorbellError(Exception):
    pass


class DoorbellAuthError(DoorbellError):
    pass


class DoorbellClient:

    """Minimal Reolink doorbell HTTP CGI API client."""

    def __init__(
        self,
        host=DOORBELL_HOST,
        port=DOORBELL_PORT,
        user=DOORBELL_USER,
        password=DOORBELL_PASSWORD,
    ):

        self.host = host
        self.port = port
        self.user = user
        self.password = password

        self.token = None

    def _api_url(self, cmd: str) -> str:

        token = self.token or "null"

        return (
            f"http://{self.host}:{self.port}"
            f"/cgi-bin/api.cgi?cmd={cmd}&token={token}"
        )

    def _post(self, cmd: str, body: list, url=None):

        if not self.host:

            raise DoorbellError(
                "Doorbell host not configured "
                "(config.yaml -> doorbell.host)"
            )

        if not self.password:

            raise DoorbellError(
                "Doorbell password not configured "
                "(config.yaml -> doorbell.password or "
                "EDGEGUARD_DOORBELL_PASSWORD)"
            )

        request = url_request.Request(
            url or self._api_url(cmd),
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:

            with url_request.urlopen(
                request,
                timeout=6,
            ) as response:

                return json.loads(
                    response.read().decode(
                        "utf-8"
                    )
                )

        except url_error.HTTPError as exc:

            raise DoorbellError(
                "Doorbell HTTP error %d" % exc.code
            )

        except url_error.URLError as exc:

            raise DoorbellError(
                f"Doorbell unreachable: {exc.reason}"
            )

    def login(self) -> str:

        """Log in and return the session token ('' on failure)."""

        body = [
            {
                "cmd": "Login",
                "action": 0,
                "param": {
                    "User": {
                        "userName": self.user,
                        "password": self.password,
                    }
                },
            }
        ]

        response = self._post(
            "Login",
            body,
            url=(
                f"http://{self.host}:{self.port}"
                f"/cgi-bin/api.cgi?cmd=Login&token=null"
            ),
        )

        try:

            entry = response[0]

            if entry.get("code") == 0:

                self.token = entry["value"][
                    "Token"
                ]["name"]

                return self.token

            logger.warning(
                "Doorbell login failed: %s",
                entry.get("error", {}).get(
                    "detail"
                ),
            )

        except (KeyError, IndexError, TypeError):

            logger.exception(
                "Unexpected doorbell login response"
            )

        return ""

    def trigger_siren(
        self,
        enable: bool = True,
        times: int = 2,
    ) -> bool:

        """Start/stop the doorbell siren (AudioAlarmPlay)."""

        if self.token is None and not self.login():

            raise DoorbellAuthError(
                "Doorbell login failed; check "
                "doorbell.user / doorbell.password"
            )

        body = [
            {
                "cmd": "AudioAlarmPlay",
                "action": 0,
                "param": {
                    "alarm_mode": "manul",
                    "manual_switch": 1 if enable else 0,
                    "times": times,
                    "channel": 0,
                },
            }
        ]

        response = self._post("AudioAlarmPlay", body)

        try:

            entry = response[0]

            return (
                entry.get("code") == 0
                and entry.get("value", {}).get(
                    "rspCode"
                )
                == 200
            )

        except (KeyError, IndexError, TypeError):

            logger.exception(
                "Unexpected doorbell siren response"
            )

            return False


def main(argv=None):

    parser = argparse.ArgumentParser(
        description="Reolink doorbell control"
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    siren = subparsers.add_parser(
        "siren",
        help="trigger or stop the doorbell siren",
    )

    siren.add_argument(
        "state",
        choices=["on", "off"],
        help="on = sound the siren, off = stop it",
    )

    args = parser.parse_args(argv)

    client = DoorbellClient()

    if args.command == "siren":

        ok = client.trigger_siren(
            args.state == "on"
        )

        print(
            "doorbell siren: "
            f"{'ON' if args.state == 'on' else 'OFF'} "
            f"({'ok' if ok else 'FAILED'})"
        )

        return 0 if ok else 1

    return 2


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
    )

    sys.exit(main())