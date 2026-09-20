"""GpuFaceDetector resolution in environments without TensorRT or
insightface (CI) - must degrade gracefully, never raise on import."""

import numpy as np
import pytest

from jetson_gpu.detector import GpuFaceDetector


def test_detector_degrades_without_engines(tmp_path):

    detector = GpuFaceDetector(engine_dir=tmp_path)

    assert detector.provider in ("cpu", "unavailable")

    faces = detector.detect(
        np.zeros((720, 960, 3), dtype=np.uint8)
    )

    assert isinstance(faces, list)


def test_detector_missing_engine_file(tmp_path):

    (tmp_path / "det_10g.trt").write_bytes(b"x")

    detector = GpuFaceDetector(engine_dir=tmp_path)

    assert detector.provider in ("cpu", "unavailable")


def test_detector_default_provider_reported():

    detector = GpuFaceDetector()

    assert isinstance(detector.provider, str)


def test_face_container_attributes():

    from jetson_gpu.face import Face

    face = Face(
        bbox=np.array([1.0, 2.0, 3.0, 4.0]),
        det_score=0.9,
    )

    face.embedding = np.ones(512, dtype=np.float32)

    assert face.bbox.shape == (4,)

    assert face.det_score == 0.9

    assert face.embedding.shape == (512,)

    assert face.missing_attr is None

    normed = face.normed_embedding

    assert normed.shape == (512,)

    assert np.linalg.norm(normed) == pytest.approx(1.0)