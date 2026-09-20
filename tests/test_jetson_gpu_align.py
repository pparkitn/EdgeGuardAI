import numpy as np
import pytest

from jetson_gpu.align import ARCFACE_DST, estimate_norm, norm_crop


def test_estimate_norm_identity_landmarks():

    """When the landmarks already match the ArcFace template, the
    estimated similarity transform must be scale-only (ratio 1)."""

    M = estimate_norm(ARCFACE_DST, 112)

    scale = np.sqrt(M[0, 0] ** 2 + M[0, 1] ** 2)

    assert scale == pytest.approx(1.0)

    rotation = np.arctan2(M[0, 1], M[0, 0])

    assert abs(rotation) < 1e-9

    assert abs(M[0, 2]) < 1e-6

    assert abs(M[1, 2]) < 1e-6


def test_estimate_norm_double_size():

    """image_size=224 doubles the scale factor (ratio 2)."""

    M = estimate_norm(ARCFACE_DST, 224)

    scale = np.sqrt(M[0, 0] ** 2 + M[0, 1] ** 2)

    assert scale == pytest.approx(2.0)


def test_estimate_norm_translation_recovery():

    """A translated landmark set recovers the translation:
    M maps (template + shift) back onto the template."""

    shift = np.array([13.0, -7.0])

    M = estimate_norm(ARCFACE_DST + shift, 112)

    origin = np.array([38.2946, 51.6963])

    mapped = M @ np.append(origin + shift, 1.0)

    assert mapped[0] == pytest.approx(origin[0], abs=1e-3)

    assert mapped[1] == pytest.approx(origin[1], abs=1e-3)


def test_estimate_norm_matches_skimage():

    """Bit-for-bit parity with insightface's norm_crop backend
    (scikit-image SimilarityTransform). Skipped in CI where
    scikit-image is not installed."""

    pytest.importorskip("skimage.transform")

    import skimage.transform as trans

    rng = np.random.default_rng(7)

    for _ in range(5):

        lmk = ARCFACE_DST + rng.normal(
            scale=2.0,
            size=ARCFACE_DST.shape,
        )

        M = estimate_norm(lmk, 112)

        reference = trans.SimilarityTransform()

        reference.estimate(lmk, ARCFACE_DST)

        assert np.allclose(
            M,
            reference.params[0:2, :],
            atol=1e-5,
        )


def test_norm_crop_output_shape():

    pytest.importorskip("cv2")

    img = np.zeros((480, 640, 3), dtype=np.uint8)

    crop = norm_crop(img, ARCFACE_DST, 112)

    assert crop.shape == (112, 112, 3)