"""SCRFD detection decode, ported from insightface's model_zoo.scrfd.

Detection itself runs on a TensorRT engine; everything downstream of
the raw network outputs (anchor decoding, distance-to-bbox/kps, NMS)
is the same numpy math insightface applies, so boxes and landmarks are
identical to the CPU pipeline.

The inference backend is any object exposing an onnxruntime-like
interface:

    session.run(output_names, {input_name: blob}) -> list of ndarray

The TensorRT wrapper in .trt provides exactly that.
"""

import cv2
import numpy as np


def blob_from_image(
    img,
    scalefactor,
    size,
    mean,
    swap_rb=True,
):

    """Replacement for cv2.dnn.blobFromImage.

    OpenCV 3.2 (Jetson system python) predates the dnn module;
    this replicates its math: resize -> BGR/RGB -> (x - mean) * scale
    -> NCHW float32 blob.
    """

    resized = cv2.resize(img, tuple(int(v) for v in size))

    if swap_rb:
        resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)

    blob = resized.astype(np.float32)

    mean_arr = np.array(mean, dtype=np.float32)

    blob = (blob - mean_arr) * scalefactor

    return np.ascontiguousarray(
        blob.transpose(2, 0, 1)[np.newaxis],
    )


def distance2bbox(points, distance, max_shape=None):

    x1 = points[:, 0] - distance[:, 0]

    y1 = points[:, 1] - distance[:, 1]

    x2 = points[:, 0] + distance[:, 2]

    y2 = points[:, 1] + distance[:, 3]

    if max_shape is not None:

        x1 = np.clip(x1, 0, max_shape[1])
        y1 = np.clip(y1, 0, max_shape[0])
        x2 = np.clip(x2, 0, max_shape[1])
        y2 = np.clip(y2, 0, max_shape[0])

    return np.stack([x1, y1, x2, y2], axis=-1)


def distance2kps(points, distance, max_shape=None):

    preds = []

    for i in range(0, distance.shape[1], 2):

        px = points[:, i % 2] + distance[:, i]

        py = points[:, i % 2 + 1] + distance[:, i + 1]

        if max_shape is not None:

            px = np.clip(px, 0, max_shape[1])

            py = np.clip(py, 0, max_shape[0])

        preds.append(px)

        preds.append(py)

    return np.stack(preds, axis=-1)


def nms(dets, thresh):

    """Greedy NMS over (x1, y1, x2, y2, score) rows."""

    x1 = dets[:, 0]

    y1 = dets[:, 1]

    x2 = dets[:, 2]

    y2 = dets[:, 3]

    scores = dets[:, 4]

    areas = (x2 - x1 + 1) * (y2 - y1 + 1)

    order = np.argsort(-scores, kind="stable")

    keep = []

    while order.size > 0:

        i = order[0]

        keep.append(i)

        xx1 = np.maximum(x1[i], x1[order[1:]])

        yy1 = np.maximum(y1[i], y1[order[1:]])

        xx2 = np.minimum(x2[i], x2[order[1:]])

        yy2 = np.minimum(y2[i], y2[order[1:]])

        w = np.maximum(0.0, xx2 - xx1 + 1)

        h = np.maximum(0.0, yy2 - yy1 + 1)

        inter = w * h

        ovr = inter / (areas[i] + areas[order[1:]] - inter)

        inds = np.where(ovr <= thresh)[0]

        order = order[inds + 1]

    return keep


class SCRFD:

    """det_10g-style detector with a pluggable inference backend.

    Mirrors insightface's SCRFD for a fixed input size (the TensorRT
    engine is built for exactly one det_size, default 640x640).
    """

    STRIDES = (8, 16, 32)

    NUM_ANCHORS = 2

    def __init__(
        self,
        session,
        det_size=(640, 640),
        det_thresh=0.5,
        nms_thresh=0.4,
        input_mean=127.5,
        input_std=128.0,
    ):

        self.session = session

        self.input_name = session.input_names[0]

        self.output_names = list(session.output_names)

        assert len(self.output_names) == 9, (
            f"det_10g engine must expose 9 outputs, "
            f"got {len(self.output_names)}"
        )

        self.det_size = tuple(int(v) for v in det_size)

        self.det_thresh = det_thresh

        self.nms_thresh = nms_thresh

        self.input_mean = input_mean

        self.input_std = input_std

        self._center_cache = {}

        self._output_map = self._map_outputs()

    def _map_outputs(self):

        """Identify each stride's score/bbox/kps outputs by shape.

        TRT reorders the engine bindings (stride-grouped instead of
        component-grouped), so positional indexing is not safe; the
        shapes (N, 1), (N, 4), (N, 10) with N = anchors per stride
        uniquely identify every output.
        """

        shapes = getattr(self.session, "output_shapes", None)

        assert shapes is not None, (
            "SCRFD session must expose output_shapes"
        )

        mapping = []

        for stride in self.STRIDES:

            height = self.det_size[1] // stride

            width = self.det_size[0] // stride

            num = height * width * self.NUM_ANCHORS

            indices = {"score": None, "bbox": None, "kps": None}

            for index, name in enumerate(self.output_names):

                shape = tuple(shapes[name])

                if shape == (num, 1):
                    indices["score"] = index
                elif shape == (num, 4):
                    indices["bbox"] = index
                elif shape == (num, 10):
                    indices["kps"] = index

            assert all(
                value is not None
                for value in indices.values()
            ), f"could not map outputs for stride {stride}"

            mapping.append(
                (
                    stride,
                    indices["score"],
                    indices["bbox"],
                    indices["kps"],
                )
            )

        return mapping

    def _prepare_input_blob(self, img):

        return blob_from_image(
            img,
            1.0 / self.input_std,
            self.det_size,
            (self.input_mean, self.input_mean, self.input_mean),
            swap_rb=True,
        )

    def _anchor_centers(self, height, width, stride):

        key = (height, width, stride)

        if key in self._center_cache:
            return self._center_cache[key]

        anchor_centers = np.stack(
            np.mgrid[:height, :width][::-1],
            axis=-1,
        ).astype(np.float32)

        anchor_centers = (anchor_centers * stride).reshape(-1, 2)

        anchor_centers = np.stack(
            [anchor_centers] * self.NUM_ANCHORS,
            axis=1,
        ).reshape(-1, 2)

        self._center_cache[key] = anchor_centers

        return anchor_centers

    def forward(self, img, threshold):

        """Run the engine and decode per-stride candidates.

        Returns (scores_list, bboxes_list, kpss_list) where each entry
        holds the threshold-passed candidates of one feature stride.
        """

        blob = self._prepare_input_blob(img)

        net_outs = self.session.run(
            self.output_names,
            {self.input_name: blob},
        )

        input_height = blob.shape[2]

        input_width = blob.shape[3]

        scores_list = []

        bboxes_list = []

        kpss_list = []

        for stride, score_idx, bbox_idx, kps_idx in (
            self._output_map
        ):

            scores = net_outs[score_idx]

            bbox_preds = net_outs[bbox_idx] * stride

            kps_preds = net_outs[kps_idx] * stride

            height = input_height // stride

            width = input_width // stride

            anchor_centers = self._anchor_centers(
                height,
                width,
                stride,
            )

            pos_inds = np.where(scores >= threshold)[0]

            if pos_inds.size == 0:

                continue

            bboxes = distance2bbox(
                anchor_centers,
                bbox_preds,
            )

            kpss = distance2kps(
                anchor_centers,
                kps_preds,
            ).reshape(-1, 5, 2)

            scores_list.append(scores[pos_inds])

            bboxes_list.append(bboxes[pos_inds])

            kpss_list.append(kpss[pos_inds])

        return scores_list, bboxes_list, kpss_list

    def detect(self, img, max_num=0):

        """Detect faces; returns (bboxes, kpss) like insightface.

        bboxes: (N, 5) [x1, y1, x2, y2, score] in image pixels.
        kpss:   (N, 5, 2) 5-point landmarks in image pixels.
        """

        input_w, input_h = self.det_size

        im_ratio = float(img.shape[0]) / img.shape[1]

        model_ratio = float(input_h) / input_w

        if im_ratio > model_ratio:

            new_height = input_h

            new_width = int(new_height / im_ratio)

        else:

            new_width = input_w

            new_height = int(new_width * im_ratio)

        det_scale = float(new_height) / img.shape[0]

        resized_img = cv2.resize(img, (new_width, new_height))

        det_img = np.zeros(
            (input_h, input_w, 3),
            dtype=np.uint8,
        )

        det_img[:new_height, :new_width, :] = resized_img

        scores_list, bboxes_list, kpss_list = self.forward(
            det_img,
            self.det_thresh,
        )

        if not scores_list:

            return (
                np.empty((0, 5), dtype=np.float32),
                np.empty((0, 5, 2), dtype=np.float32),
            )

        scores = np.vstack(scores_list)

        scores_ravel = scores.ravel()

        order = np.argsort(-scores_ravel, kind="stable")

        bboxes = np.vstack(bboxes_list) / det_scale

        kpss = np.vstack(kpss_list) / det_scale

        pre_det = np.hstack((bboxes, scores)).astype(
            np.float32,
            copy=False,
        )

        pre_det = pre_det[order, :]

        kpss = kpss[order, :, :]

        keep = nms(pre_det, self.nms_thresh)

        det = pre_det[keep, :]

        kpss = kpss[keep, :, :]

        if max_num > 0 and det.shape[0] > max_num:

            area = (det[:, 2] - det[:, 0]) * (
                det[:, 3] - det[:, 1]
            )

            img_center = (
                img.shape[0] // 2,
                img.shape[1] // 2,
            )

            offsets = np.vstack(
                [
                    (det[:, 0] + det[:, 2]) / 2 - img_center[1],
                    (det[:, 1] + det[:, 3]) / 2 - img_center[0],
                ]
            )

            offset_dist_squared = np.sum(
                np.power(offsets, 2.0),
                0,
            )

            values = area - offset_dist_squared * 2.0

            bindex = np.argsort(values)[::-1][0:max_num]

            det = det[bindex, :]

            kpss = kpss[bindex, :, :]

        return det, kpss