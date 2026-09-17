import os
from pathlib import Path

import yaml

CONFIG_PATH = Path(
    os.environ.get(
        "EDGEGUARD_CONFIG",
        Path(__file__).resolve().parent
        / "config.yaml",
    )
)

# If the real config.yaml is absent (repo only ships the example),
# fall back to it so imports/checks still work.
if not CONFIG_PATH.exists():

    CONFIG_PATH = (
        Path(__file__).resolve().parent
        / "config.yaml.example"
    )

_CONFIG = None


def load() -> dict:

    global _CONFIG

    if _CONFIG is None:

        with open(CONFIG_PATH) as f:

            _CONFIG = yaml.safe_load(f)

    return _CONFIG


def get(*path, default=None, env=None):

    """config.get('broker', 'host')

    Returns the value from config.yaml at the given path.
    An environment variable overrides the file:
      - explicit: env="EDGEGUARD_CAMERA_PASSWORD" is checked first
      - full path form: EDGEGUARD_BROKER_HOST
      - last segment form: EDGEGUARD_HOST
    """

    candidates = []

    if env is not None:
        candidates.append(env)

    candidates.append(
        "EDGEGUARD_" + "_".join(
            str(part).upper() for part in path
        )
    )

    candidates.append(
        "EDGEGUARD_"
        + str(path[-1]).upper()
    )

    for candidate in candidates:

        env_value = os.environ.get(candidate)

        if env_value is not None and env_value != "":
            return env_value

    node = load()

    try:

        for part in path:
            node = node[part]

    except (KeyError, TypeError):

        return default

    return node


def get_int(*path, default: int = 0) -> int:

    value = get(*path, default=default)

    return int(value)


def get_float(*path, default: float = 0.0) -> float:

    value = get(*path, default=default)

    return float(value)


def get_bool(*path, default: bool = False) -> bool:

    value = get(*path, default=default)

    if isinstance(value, bool):
        return value

    return str(value).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def get_list(*path, default=None) -> list:

    value = get(*path, default=default)

    if isinstance(value, list):
        return value

    if isinstance(value, str):

        return [
            item.strip()
            for item in value.split(",")
            if item.strip()
        ]

    return list(default or [])