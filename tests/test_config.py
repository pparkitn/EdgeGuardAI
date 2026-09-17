import edgeguard_config
from edgeguard_config import get, get_bool, get_int, get_list


def test_config_file_found():

    assert edgeguard_config.CONFIG_PATH.exists()


def test_core_sections_load():

    assert get_int("broker", "port") == 1883

    assert len(get_list("speakers")) >= 3

    assert len(get("cameras", "rtsp")) >= 1

    assert len(get("schedule")) >= 1

    assert len(get("zigbee", "devices")) >= 1


def test_unknown_path_returns_default():

    assert get("nope", "missing", default="fallback") == "fallback"
    assert get_int("nope", default=42) == 42
    assert get_bool("nope", default=True) is True


def test_env_override_short_form(monkeypatch):

    monkeypatch.setenv("EDGEGUARD_POLLY_VOICE", "Joanna")

    assert get("voice", "polly_voice") == "Joanna"


def test_env_override_full_path_form(monkeypatch):

    monkeypatch.setenv(
        "EDGEGUARD_VOICE_HTTP_PORT",
        "9000",
    )

    assert get_int("voice", "http_port") == 9000


def test_env_override_comma_list(monkeypatch):

    monkeypatch.setenv(
        "EDGEGUARD_SPEAKERS",
        "Speaker A, Speaker B",
    )

    assert get_list("speakers") == [
        "Speaker A",
        "Speaker B",
    ]


def test_camera_password_not_in_repo():

    assert get(
        "cameras",
        "rtsp",
        "password",
        default="",
        env="EDGEGUARD_CAMERA_PASSWORD",
    ) == ""