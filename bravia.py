"""Sony BRAVIA IP control (REST API) client.

Controls a Sony Bravia TV over its local REST API using a
pre-shared key (X-Auth-PSK). Supports power, volume/mute, input
switching and app launch.

    python -m bravia status
    python -m bravia power on
    python -m bravia power off
    python -m bravia volume 20
    python -m bravia mute on
    python -m bravia input hdmi:1
    python -m bravia apps
    python -m bravia app <app title>

Config: config.yaml -> bravia (host, port, psk), overridable with
EDGEGUARD_BRAVIA_HOST / EDGEGUARD_BRAVIA_PORT / EDGEGUARD_BRAVIA_PSK.
The PSK is a secret - keep it in the gitignored per-device
config.yaml (or an env var), never in config.yaml.example.
"""

import argparse
import json
import logging
import sys
from urllib import error as url_error
from urllib import request as url_request

from edgeguard_config import get, get_int

logger = logging.getLogger(__name__)

BRAVIA_HOST = get(
    "bravia",
    "host",
    env="EDGEGUARD_BRAVIA_HOST",
    default="",
)

BRAVIA_PORT = get_int(
    "bravia",
    "port",
    default=80,
)

BRAVIA_PSK = get(
    "bravia",
    "psk",
    env="EDGEGUARD_BRAVIA_PSK",
    default="",
)

# Bravia API error codes
ERR_AUTH = 403  # missing/wrong PSK
ERR_NOT_AVAILABLE = 40401  # operation impossible (e.g. TV in standby)
ERR_OPERATION = 40301  # operation not possible


class BraviaError(Exception):
    pass


class BraviaAuthError(BraviaError):
    pass


class BraviaStandbyError(BraviaError):
    pass


class BraviaClient:

    """Minimal Sony Bravia REST API client."""

    def __init__(
        self,
        host=BRAVIA_HOST,
        port=BRAVIA_PORT,
        psk=BRAVIA_PSK,
    ):

        self.host = host

        self.port = port

        self.psk = psk

    def _request(
        self,
        service: str,
        method: str,
        params=None,
        request_id: int = 1,
    ):

        if not self.host:

            raise BraviaError(
                "BRAVIA host not configured "
                "(config.yaml -> bravia.host)"
            )

        if not self.psk:

            raise BraviaError(
                "BRAVIA PSK not configured "
                "(config.yaml -> bravia.psk or "
                "EDGEGUARD_BRAVIA_PSK)"
            )

        payload = {
            "method": method,
            "id": request_id,
            "params": params or [],
            "version": "1.0",
        }

        url = (
            f"http://{self.host}:{self.port}"
            f"/sony/{service}"
        )

        request = url_request.Request(
            url,
            data=json.dumps(
                payload
            ).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "X-Auth-PSK": self.psk,
            },
            method="POST",
        )

        try:

            with url_request.urlopen(
                request,
                timeout=6,
            ) as response:

                body = json.loads(
                    response.read().decode(
                        "utf-8"
                    )
                )

        except url_error.HTTPError as exc:

            if exc.code == ERR_AUTH:

                raise BraviaAuthError(
                    "BRAVIA rejected the PSK "
                    "(HTTP %d); check bravia.psk"
                    % exc.code
                )

            raise BraviaError(
                "BRAVIA HTTP error %d" % exc.code
            )

        except url_error.URLError as exc:

            raise BraviaError(
                f"BRAVIA unreachable: {exc.reason}"
            )

        error = body.get("error")

        if error:

            code = error[0]

            if code == ERR_NOT_AVAILABLE:

                raise BraviaStandbyError(
                    f"{method} not possible: "
                    "TV in standby/off"
                )

            raise BraviaError(
                f"BRAVIA {method} failed: {error}"
            )

        return body.get("result", [])

    def system_information(self) -> dict:

        result = self._request(
            "system",
            "getSystemInformation",
        )

        return result[0]

    def power_status(self) -> str:

        result = self._request(
            "system",
            "getPowerStatus",
        )

        status = result[0]

        if isinstance(status, dict):

            return status.get(
                "status",
                str(status),
            )

        return str(status)

    def set_power(self, on: bool):

        # This TV (XBR-75X900H) requires the object form
        # [{"status": bool}]; the legacy [true] returns
        # "Illegal Argument".
        self._request(
            "system",
            "setPowerStatus",
            [{"status": bool(on)}],
        )

    def volume_info(self) -> list:

        result = self._request(
            "audio",
            "getVolumeInformation",
        )

        if not result:

            return []

        return result[0]

    def set_volume(self, volume: int):

        self._request(
            "audio",
            "setAudioVolume",
            ["speaker", int(volume)],
        )

    def set_mute(self, muted: bool):

        self._request(
            "audio",
            "setMute",
            ["speaker", bool(muted)],
        )

    def current_inputs(self) -> list:

        result = self._request(
            "avContent",
            "getCurrentExternalInputsStatus",
        )

        if not result:

            return []

        return result[0]

    def set_input(self, uri: str):

        self._request(
            "avContent",
            "setPlayContent",
            [{"uri": uri}],
        )

    def application_list(self) -> list:

        result = self._request(
            "appControl",
            "getApplicationList",
        )

        if not result:

            return []

        return result[0]

    def set_active_app(self, uri: str):

        self._request(
            "appControl",
            "setActiveApp",
            [{"uri": uri}],
        )


def _print_status(client):

    info = client.system_information()

    print(
        f"{info.get('name')} "
        f"{info.get('model')} "
        f"(serial {info.get('serial')})"
    )

    print(f"MAC: {info.get('macAddr')}")

    try:

        print(f"power: {client.power_status()}")

    except BraviaError:

        pass

    try:

        for entry in client.volume_info():

            print(
                f"volume: {entry.get('volume')}"
                f"/{entry.get('maxVolume')}"
                f" mute: {entry.get('mute')}"
            )

    except BraviaError:

        pass

    try:

        for entry in client.current_inputs():

            print(
                f"input: {entry.get('title')}"
                f" ({entry.get('uri')})"
                f" {'active' if entry.get('isActive') else ''}"
            )

    except BraviaError:

        pass


def main(argv=None):

    parser = argparse.ArgumentParser(
        prog="bravia",
        description=(
            "Send commands to a Sony BRAVIA TV "
            "over the REST API"
        ),
    )

    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    sub.add_parser(
        "status",
        help="TV info, power, volume, inputs",
    )

    power = sub.add_parser(
        "power",
        help="query or set power",
    )

    power.add_argument(
        "state",
        nargs="?",
        choices=["on", "off"],
    )

    volume = sub.add_parser(
        "volume",
        help="query or set volume (0-100)",
    )

    volume.add_argument(
        "level",
        nargs="?",
        type=int,
    )

    mute = sub.add_parser(
        "mute",
        help="set mute on/off",
    )

    mute.add_argument(
        "state",
        choices=["on", "off"],
    )

    sub.add_parser(
        "inputs",
        help="list current inputs",
    )

    input_parser = sub.add_parser(
        "input",
        help="switch input by uri, "
        "e.g. hdmi:1, tv, extInput:hdmi?port=2",
    )

    input_parser.add_argument("uri")

    sub.add_parser(
        "apps",
        help="list installed apps",
    )

    app = sub.add_parser(
        "app",
        help="launch app by title (substring)",
    )

    app.add_argument("title")

    args = parser.parse_args(argv)

    client = BraviaClient()

    try:

        if args.command == "status":

            _print_status(client)

        elif args.command == "power":

            if args.state is None:

                print(client.power_status())

            else:

                client.set_power(
                    args.state == "on"
                )

                print(
                    "power "
                    f"{args.state}"
                )

        elif args.command == "volume":

            if args.level is None:

                for entry in client.volume_info():

                    print(
                        f"volume: "
                        f"{entry.get('volume')}"
                        f"/{entry.get('maxVolume')}"
                    )

            else:

                client.set_volume(args.level)

                print(f"volume {args.level}")

        elif args.command == "mute":

            client.set_mute(
                args.state == "on"
            )

            print(f"mute {args.state}")

        elif args.command == "inputs":

            for entry in client.current_inputs():

                print(
                    f"{entry.get('title')}"
                    f" ({entry.get('uri')})"
                    f" {'active' if entry.get('isActive') else ''}"
                )

        elif args.command == "apps":

            for entry in client.application_list():

                print(
                    f"{entry.get('title')} "
                    f"({entry.get('uri')})"
                )

        elif args.command == "app":

            matches = [
                entry
                for entry in client.application_list()
                if args.title.lower()
                in entry.get("title", "").lower()
            ]

            if not matches:

                raise BraviaError(
                    f"no app matching {args.title!r}"
                )

            client.set_active_app(
                matches[0]["uri"]
            )

            print(
                f"launching: {matches[0]['title']}"
            )

    except BraviaAuthError as exc:

        print(f"auth error: {exc}", file=sys.stderr)

        return 2

    except (BraviaStandbyError, BraviaError) as exc:

        print(f"error: {exc}", file=sys.stderr)

        return 1

    return 0


if __name__ == "__main__":

    sys.exit(main())