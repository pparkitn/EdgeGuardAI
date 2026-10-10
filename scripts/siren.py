#!/usr/bin/env python3
"""Trigger the Reolink doorbell siren (HTTP API).

    python scripts/siren.py on
    python scripts/siren.py off

Reads the doorbell host/user/password from config.yaml -> doorbell
(or EDGEGUARD_DOORBELL_* env vars); uses the same AudioAlarmPlay
API as `python -m doorbell siren on|off`.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent),
)

from doorbell import (  # noqa: E402
    DoorbellClient,
    DoorbellError,
)


def main():

    parser = argparse.ArgumentParser(
        description="Trigger the Reolink doorbell siren"
    )

    parser.add_argument(
        "state",
        choices=["on", "off"],
        help="on = sound the siren, off = stop it",
    )

    args = parser.parse_args()

    try:

        ok = DoorbellClient().trigger_siren(
            args.state == "on"
        )

    except DoorbellError as exc:

        print(
            f"siren FAILED: {exc}",
            file=sys.stderr,
        )

        return 1

    print(
        f"doorbell siren: "
        f"{'ON' if args.state == 'on' else 'OFF'} "
        f"({'ok' if ok else 'FAILED'})"
    )

    return 0 if ok else 1


if __name__ == "__main__":

    sys.exit(main())