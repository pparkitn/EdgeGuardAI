"""Face alignment (norm_crop), ported from insightface without skimage.

Insightface's `face_align.norm_crop` depends on scikit-image for the
SimilarityTransform estimate (Umeyama). The Jetson py38env may not have
scikit-image, so the exact same math is reimplemented here with numpy
+ cv2 only, producing byte-identical warped crops (and therefore
identical embeddings) to the CPU pipeline.
"""

import cv2
import numpy as np

ARCFACE_DST = np.array(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


def _umeyama(src, dst, estimate_scale):

    """Least-squares similarity transform (Umeyama 1991).

    Port of `skimage.transform._geometric._umeyama` - keep in sync.
    """

    src = np.asarray(src, dtype=np.float64)

    dst = np.asarray(dst, dtype=np.float64)

    num = src.shape[0]

    dim = src.shape[1]

    src_mean = src.mean(axis=0)

    dst_mean = dst.mean(axis=0)

    src_demean = src - src_mean

    dst_demean = dst - dst_mean

    # Eq. (38).
    A = dst_demean.T @ src_demean / num

    # Eq. (39).
    d = np.ones((dim,), dtype=np.float64)

    if np.linalg.det(A) < 0:
        d[dim - 1] = -1

    T = np.eye(dim + 1, dtype=np.float64)

    U, S, V = np.linalg.svd(A)

    tol = S.max() * np.max(A.shape) * np.finfo(float).eps

    rank = np.count_nonzero(S > tol)

    if rank == 0:
        return np.nan * T

    if rank == dim - 1:

        if np.linalg.det(U) * np.linalg.det(V) > 0:
            T[:dim, :dim] = U @ V
        else:

            s = d[dim - 1]

            d[dim - 1] = -1

            T[:dim, :dim] = U @ np.diag(d) @ V

            d[dim - 1] = s

    else:

        T[:dim, :dim] = U @ np.diag(d) @ V

    if estimate_scale:

        scale = 1.0 / src_demean.var(axis=0).sum() * (S @ d)

    else:

        scale = 1.0

    T[:dim, dim] = dst_mean - scale * (T[:dim, :dim] @ src_mean.T)

    T[:dim, :dim] *= scale

    return T


def estimate_norm(lmk, image_size=112):

    assert lmk.shape == (5, 2)

    assert image_size % 112 == 0 or image_size % 128 == 0

    if image_size % 112 == 0:

        ratio = float(image_size) / 112.0

        diff_x = 0

    else:

        ratio = float(image_size) / 128.0

        diff_x = 8.0 * ratio

    dst = ARCFACE_DST * ratio

    dst[:, 0] += diff_x

    tform = _umeyama(lmk, dst, True)

    return tform[0:2, :]


def norm_crop(img, landmark, image_size=112):

    """Align and crop a face to the ArcFace template.

    Identical to `insightface.utils.face_align.norm_crop`.
    """

    M = estimate_norm(landmark, image_size)

    warped = cv2.warpAffine(
        img,
        M,
        (image_size, image_size),
        borderValue=0.0,
    )

    return warped