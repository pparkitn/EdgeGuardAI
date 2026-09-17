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


def test_weekday_aliases():

    from voice.scheduler import WEEKDAYS

    assert WEEKDAYS["mon"] == "monday"
    assert WEEKDAYS["fri"] == "friday"