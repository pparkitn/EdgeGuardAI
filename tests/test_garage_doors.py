import numpy as np
import pytest

from garage_doors import (
    _gray_mad,
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