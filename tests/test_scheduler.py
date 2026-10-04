from voice.scheduler import Scheduler


def test_load_accepts_daily_weekly_interval():

    definitions = [
        {"time": "07:00", "text": "daily"},
        {
            "time": "16:20",
            "days": ["tue", "thu"],
            "text": "weekly",
        },
        {"every": 3600, "text": "interval"},
    ]

    scheduler = Scheduler(say=lambda text, **kwargs: None)

    scheduler.load(definitions)

    scheduler.stop()


def test_fire_passes_text_and_targets():

    calls = []

    def say(text, speakers=None, local=True):
        calls.append((text, speakers, local))

    scheduler = Scheduler(say)

    scheduler._fire(
        "hello",
        {"speakers": ["Natalia speaker"], "local": False},
    )

    assert calls == [
        ("hello", ["Natalia speaker"], False)
    ]


def test_fire_defaults_to_all_speakers_local():

    calls = []

    def say(text, speakers=None, local=True):
        calls.append((text, speakers, local))

    scheduler = Scheduler(say)

    scheduler._fire("hello", {})

    assert calls == [("hello", None, True)]


def test_add_ignores_definition_without_text():

    scheduler = Scheduler(say=lambda text, **kwargs: None)

    scheduler.add({"time": "07:00"})


def test_add_accepts_action_only_definition():

    scheduler = Scheduler(
        say=lambda text, **kwargs: None,
        actions={"tv_off": lambda: None},
    )

    scheduler.add({"time": "01:00", "action": "tv_off"})


def test_fire_runs_action_then_announcement():

    calls = []

    def say(text, speakers=None, local=True):
        calls.append(("say", text, speakers, local))

    def tv_off():
        calls.append(("action", "tv_off"))

    scheduler = Scheduler(say, actions={"tv_off": tv_off})

    scheduler._fire(
        "hello",
        {"action": "tv_off", "speakers": ["Kitchen speaker"]},
    )

    assert calls == [
        ("action", "tv_off"),
        ("say", "hello", ["Kitchen speaker"], True),
    ]


def test_fire_action_only_skips_say():

    calls = []

    scheduler = Scheduler(
        say=lambda text, **kwargs: calls.append(text),
        actions={"tv_off": lambda: calls.append("tv_off")},
    )

    scheduler._fire(None, {"action": "tv_off"})

    assert calls == ["tv_off"]


def test_fire_unknown_action_logs_and_continues():

    calls = []

    scheduler = Scheduler(
        say=lambda text, **kwargs: calls.append(text),
        actions={},
    )

    scheduler._fire("hello", {"action": "nope"})

    assert calls == ["hello"]


def test_weekday_aliases():

    from voice.scheduler import WEEKDAYS

    assert WEEKDAYS["mon"] == "monday"
    assert WEEKDAYS["fri"] == "friday"