import numpy as np
import pytest

from jetson_gpu.scrfd import (
    SCRFD,
    distance2bbox,
    distance2kps,
    nms,
)


def test_distance2bbox_centered():

    points = np.array([[100.0, 100.0]])

    distance = np.array([[20.0, 20.0, 20.0, 20.0]])

    bbox = distance2bbox(points, distance)

    assert bbox.shape == (1, 4)

    assert np.array_equal(
        bbox[0],
        [80.0, 80.0, 120.0, 120.0],
    )


def test_distance2kps_offsets():

    points = np.array([[100.0, 100.0]])

    distance = np.array(
        [[10.0, 5.0, -3.0, 7.0, 2.0, -1.0, 4.0, 6.0, -2.0, 8.0]]
    )

    kps = distance2kps(points, distance)

    assert kps.shape == (1, 10)

    assert np.array_equal(
        kps[0],
        [110.0, 105.0, 97.0, 107.0, 102.0, 99.0, 104.0, 106.0, 98.0, 108.0],
    )


def test_nms_keeps_best_of_overlap():

    dets = np.array(
        [
            [10, 10, 60, 60, 0.9],
            [12, 12, 58, 58, 0.8],
            [100, 100, 150, 150, 0.7],
        ],
        dtype=np.float32,
    )

    keep = nms(dets, 0.4)

    assert keep == [0, 2]


def test_nms_keeps_both_disjoint():

    dets = np.array(
        [
            [10, 10, 60, 60, 0.5],
            [100, 100, 150, 150, 0.7],
        ],
        dtype=np.float32,
    )

    keep = nms(dets, 0.4)

    assert sorted(keep) == [0, 1]


def test_anchor_center_count():

    detector = SCRFD.__new__(SCRFD)

    detector._center_cache = {}

    centers = detector._anchor_centers(80, 80, 8)

    assert centers.shape == (12800, 2)

    assert np.array_equal(centers[0], [0.0, 0.0])

    assert np.array_equal(centers[1], [0.0, 0.0])


def test_forward_decodes_synthetic_model():

    """Full detect() round-trip with a fake engine.

    The fake engine returns one strong candidate at the center of
    the 80x80 stride-8 grid and garbage elsewhere.
    """

    pytest.importorskip("cv2")

    size = 640

    height = size // 8

    width = size // 8

    num = height * width * 2

    scores = np.zeros((num, 1), dtype=np.float32)

    bbox_preds = np.zeros((num, 4), dtype=np.float32)

    kps_preds = np.zeros((num, 10), dtype=np.float32)

    center_index = (height // 2) * width + (width // 2)

    # 2 anchors at each cell: indices 2*i, 2*i+1
    for anchor in (0, 1):

        idx = center_index * 2 + anchor

        scores[idx] = 0.99

        bbox_preds[idx] = [20, 20, 20, 20]

        # 5 landmarks around the face center
        kps_preds[idx] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

    class FakeEngine:

        input_names = ["input.1"]

        output_names = [
            "s0", "s1", "s2",
            "b0", "b1", "b2",
            "k0", "k1", "k2",
        ]

        output_shapes = {
            "s0": (12800, 1), "s1": (3200, 1), "s2": (800, 1),
            "b0": (12800, 4), "b1": (3200, 4), "b2": (800, 4),
            "k0": (12800, 10), "k1": (3200, 10), "k2": (800, 10),
        }

        def __init__(self):
            self.sessions = {}

        def run(self, output_names, feed):

            blob = feed["input.1"]

            assert blob.shape == (1, 3, 640, 640)

            assert blob.dtype == np.float32

            return [scores, np.zeros_like(scores), np.zeros_like(scores),
                    bbox_preds, np.zeros_like(bbox_preds),
                    np.zeros_like(bbox_preds), kps_preds,
                    np.zeros_like(kps_preds), np.zeros_like(kps_preds)]

    detector = SCRFD(
        FakeEngine(),
        det_size=(640, 640),
        det_thresh=0.5,
    )

    img = np.zeros((720, 960, 3), dtype=np.uint8)

    bboxes, kpss = detector.detect(img)

    assert bboxes.shape[0] == 1

    assert bboxes[0, 4] == pytest.approx(0.99)

    # 720x960 letterboxed into 640x640: det_scale = 480/720.
    # Anchor (row 40, col 40) sits at (320, 320) in det_img coords,
    # i.e. (480, 480) in the original frame.
    det_scale = 480.0 / 720.0

    x1, y1, x2, y2 = bboxes[0, 0:4]

    assert (x1 + x2) / 2 == pytest.approx(
        320.0 / det_scale,
        abs=0.01,
    )

    assert (y1 + y2) / 2 == pytest.approx(
        320.0 / det_scale,
        abs=0.01,
    )

    assert kpss.shape == (1, 5, 2)