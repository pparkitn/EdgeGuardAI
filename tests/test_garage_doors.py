import numpy as np
import pytest

from garage_doors import (
    _gray_mad,
    decide_states,
    hysteresis,
    roi_mads,
    should_refresh_reference,
)


def test_gray_mad_zero_for_identical():

    a = np.zeros((10, 10), dtype=np.uint8)

    assert _gray_mad(a, a.copy()) == 0.0


def test_gray_mad_measures_difference():

    a = np.zeros((10, 10), dtype=np.uint8)

    b = np.full((10, 10), 100, dtype=np.uint8)

    assert _gray_mad(a, b) == pytest.approx(100.0)


def test_gray_mad_shape_mismatch_raises():

    with pytest.raises(ValueError):
        _gray_mad(
            np.zeros((5, 5), dtype=np.uint8),
            np.zeros((6, 6), dtype=np.uint8),
        )


def test_hysteresis_opens_above_threshold():

    mads = {"left": 40.0, "right": 5.0}

    states = hysteresis(
        None,
        {"left": "closed", "right": "closed"},
        mads,
        threshold=25.0,
        close_threshold=12.0,
    )

    assert states["left"] == "open"

    assert states["right"] == "closed"


def test_hysteresis_stays_open_below_threshold():

    mads = {"left": 20.0}  # above close (12), below open (25)

    states = hysteresis(
        None,
        {"left": "open"},
        mads,
        threshold=25.0,
        close_threshold=12.0,
    )

    assert states["left"] == "open"


def test_hysteresis_closes_below_close_threshold():

    mads = {"left": 5.0}

    states = hysteresis(
        None,
        {"left": "open"},
        mads,
        threshold=25.0,
        close_threshold=12.0,
    )

    assert states["left"] == "closed"


def test_hysteresis_defaults_to_closed():

    states = hysteresis(
        None,
        None,
        {"left": 1.0},
        threshold=25.0,
        close_threshold=12.0,
    )

    assert states["left"] == "closed"


def test_no_refresh_while_door_open():

    assert not should_refresh_reference(
        {"left": "open", "right": "closed"},
        consecutive_closed=999,
    )


def test_open_needs_confirm_cycles():

    counts = {}
    mads = {"left": 40.0}

    first = decide_states(
        {"left": "closed"},
        mads,
        counts,
        confirm_cycles=2,
    )

    assert first["left"] == "closed"

    second = decide_states(
        first,
        mads,
        counts,
        confirm_cycles=2,
    )

    assert second["left"] == "open"


def test_open_no_confirm_when_cycles_1():

    counts = {}

    states = decide_states(
        {"left": "closed"},
        {"left": 40.0},
        counts,
        confirm_cycles=1,
    )

    assert states["left"] == "open"


def test_transient_spike_never_announces_open():

    counts = {}
    previous = {"left": "closed"}

    for mad in (28.0, 8.0, 5.0):

        previous = decide_states(
            previous,
            {"left": mad},
            counts,
            confirm_cycles=2,
        )

    assert previous["left"] == "closed"


def test_dead_zone_stays_open_then_heals():

    counts = {}
    previous = {"left": "open"}

    for _ in range(5):

        previous = decide_states(
            previous,
            {"left": 16.0},
            counts,
            close_threshold=12.0,
            stuck_open_cycles=6,
        )

        assert previous["left"] == "open"

    healed = decide_states(
        previous,
        {"left": 16.0},
        counts,
        close_threshold=12.0,
        stuck_open_cycles=6,
    )

    assert healed["left"] == "closed"


def test_closed_below_close_threshold_immediately():

    counts = {}

    states = decide_states(
        {"left": "open"},
        {"left": 5.0},
        counts,
        close_threshold=12.0,
        stuck_open_cycles=6,
    )

    assert states["left"] == "closed"


def test_confirm_counter_resets_on_subthreshold():

    counts = {}

    decide_states(
        {"left": "closed"},
        {"left": 40.0},
        counts,
        confirm_cycles=2,
    )

    decide_states(
        {"left": "closed"},
        {"left": 10.0},
        counts,
        confirm_cycles=2,
    )

    states = decide_states(
        {"left": "closed"},
        {"left": 40.0},
        counts,
        confirm_cycles=2,
    )

    assert states["left"] == "closed"

    assert counts["confirm"]["left"] == 1


def test_refresh_after_quiet_cycles():

    assert should_refresh_reference(
        {"left": "closed", "right": "closed"},
        consecutive_closed=40,
        refresh_cycles=40,
    )


def test_no_refresh_before_quiet_cycles():

    assert not should_refresh_reference(
        {"left": "closed", "right": "closed"},
        consecutive_closed=39,
        refresh_cycles=40,
    )


def test_refresh_disabled():

    monkeypatch = __import__(
        "unittest.mock"
    ).mock.patch("garage_doors.REFRESH_REFERENCE", False)

    with monkeypatch:
        assert not should_refresh_reference(
            {"left": "closed", "right": "closed"},
            consecutive_closed=999,
        )


def test_roi_mads_synthetic_frames():

    pytest.importorskip("cv2")


    reference = np.zeros((480, 640, 3), dtype=np.uint8)

    # left ROI differs, right ROI identical
    frame = reference.copy()

    frame[100:400, 100:300] = (200, 200, 200)

    rois = {
        "left": {"x": 0.10, "y": 0.10, "w": 0.30, "h": 0.60},
        "right": {"x": 0.55, "y": 0.10, "w": 0.30, "h": 0.60},
    }

    mads = roi_mads(frame, reference, rois)

    assert mads["left"] > 25.0

    assert mads["right"] < 1.0


def test_roi_mads_lighting_shift_normalized():

    pytest.importorskip("cv2")

    import numpy as np

    reference = np.full((480, 640, 3), 100, dtype=np.uint8)

    frame = np.full((480, 640, 3), 160, dtype=np.uint8)

    rois = {
        "left": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0},
        "right": {"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0},
    }

    mads_aligned = roi_mads(
        frame,
        reference,
        rois,
        normalize_lighting=True,
    )

    assert mads_aligned["left"] < 2.0

    mads_raw = roi_mads(
        frame,
        reference,
        rois,
        normalize_lighting=False,
    )

    assert mads_raw["left"] > 50.0


def test_classify_opens_only_changed_door():

    pytest.importorskip("cv2")


    from garage_doors import classify

    reference = np.zeros((480, 640, 3), dtype=np.uint8)

    frame = reference.copy()

    frame[80:420, 200:380] = (150, 150, 150)

    rois = {
        "left": {"x": 0.20, "y": 0.10, "w": 0.30, "h": 0.70},
        "right": {"x": 0.60, "y": 0.10, "w": 0.30, "h": 0.70},
    }

    states, mads = classify(
        frame,
        reference,
        threshold=25.0,
        close_threshold=12.0,
        rois=rois,
    )

    assert states["left"] == "open"

    assert states["right"] == "closed"