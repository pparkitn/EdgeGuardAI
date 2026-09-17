from events import MqttPublisher, build_event


def test_build_event_schema():

    event = build_event(
        "person_recognized",
        0.93,
        "piotr",
        camera_id="garage",
    )

    assert event["event_type"] == "person_recognized"
    assert event["camera_id"] == "garage"
    assert event["person_id"] == "piotr"
    assert event["confidence"] == 0.93
    assert event["source"] == "camera"
    assert event["event_id"].startswith("evt_")
    assert "timestamp" in event


def test_build_event_unknown_has_no_person_id():

    event = build_event(
        "unknown_person_detected",
        0.41,
        camera_id="back_yard",
    )

    assert "person_id" not in event


def test_build_event_default_camera_id():

    event = build_event(
        "unknown_person_detected",
        0.5,
    )

    assert isinstance(event["camera_id"], str)
    assert event["camera_id"]


def test_publisher_topic_uses_camera_id():

    assert (
        MqttPublisher(camera_id="front_entrance").topic
        == "edgeguard/camera/front_entrance"
    )

    assert (
        MqttPublisher(camera_id="garage").topic
        == "edgeguard/camera/garage"
    )


def test_publish_returns_false_when_disconnected():

    publisher = MqttPublisher(
        host="127.0.0.1",
        port=9,
    )

    assert publisher.publish({"test": True}) is False