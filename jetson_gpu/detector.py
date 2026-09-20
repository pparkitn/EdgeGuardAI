"""Face detector for the Jetson: TensorRT first, CPU fallback.

Drop-in replacement for `face_recognition.detector.FaceDetector`
(same `detect(frame) -> [Face-like]` contract), used by the
`jetson_gpu.main` camera service.

Provider resolution at init:

- ``tensorrt``: engines exist and tensorrt/pycuda importable ->
  all inference runs on a dedicated GPU worker thread (CUDA
  contexts are thread-bound in pycuda 2020.1 / TensorRT 7, so the
  context, engine buffers and streams are created inside that thread
  and every inference is serialized through it)
- ``cpu``: TensorRT path unusable -> insightface buffalo_l on
  onnxruntime (exactly the CPU pipeline behavior)
- ``unavailable``: neither works (e.g. CI without the heavy deps);
  `detect()` returns an empty list

The recognition preprocessing (norm_crop + mean/std) replicates the
CPU pipeline bit-for-bit, so GPU-produced embeddings match the
enrolled face database.
"""

import logging
import queue
import threading
import time

from .align import norm_crop
from .config import (
    DET_SIZE,
    DET_THRESH,
    ENGINE_DIR,
    NMS_THRESH,
    REC_SIZE,
)
from .face import Face
from .scrfd import SCRFD, blob_from_image
from .trt import TensorRtEngine

logger = logging.getLogger(__name__)

REC_MEAN = 127.5

REC_STD = 127.5

GPU_TIMEOUT = 30.0


class GpuFaceDetector:

    def __init__(
        self,
        engine_dir=None,
        det_size=DET_SIZE,
        det_thresh=DET_THRESH,
        nms_thresh=NMS_THRESH,
        rec_size=REC_SIZE,
    ):

        self.engine_dir = (
            engine_dir or ENGINE_DIR
        )

        self.det_size = tuple(det_size)

        self.rec_size = rec_size

        self.provider = "unavailable"

        self.app = None

        self.scrfd = None

        self.rec_engine = None

        self._gpu_queue = None

        self._gpu_thread = None

        self._gpu_ready = None

        self._gpu_error = None

        if self._probe_tensorrt():
            self._start_gpu_thread(det_thresh, nms_thresh)
        else:
            self._init_cpu_fallback()

    def _probe_tensorrt(self):

        det_path = self.engine_dir / "det_10g.trt"

        rec_path = self.engine_dir / "w600k_r50.trt"

        if not det_path.exists() or not rec_path.exists():

            logger.warning(
                "TensorRT engines missing (%s); "
                "run scripts/convert_engines.sh on the Jetson",
                self.engine_dir,
            )

            return False

        try:

            import pycuda.driver  # noqa: F401
            import tensorrt  # noqa: F401

        except ImportError:

            logger.warning(
                "tensorrt/pycuda not importable; "
                "TensorRT disabled"
            )

            return False

        return True

    def _start_gpu_thread(self, det_thresh, nms_thresh):

        self._gpu_queue = queue.Queue()

        self._gpu_ready = threading.Event()

        self._gpu_thread = threading.Thread(
            target=self._gpu_worker,
            args=(det_thresh, nms_thresh),
            name="jetson-gpu",
            daemon=True,
        )

        self._gpu_thread.start()

    def _gpu_worker(self, det_thresh, nms_thresh):

        print("GPU worker: starting", flush=True)

        try:

            # CUDA context must be created in THIS thread (pycuda 2020.1
            # refuses cross-thread context use).
            import pycuda.autoinit  # noqa: F401

            print("GPU worker: cuda context ok", flush=True)

            det_engine = TensorRtEngine(
                self.engine_dir / "det_10g.trt"
            )

            print("GPU worker: det engine ok", flush=True)

            self.rec_engine = TensorRtEngine(
                self.engine_dir / "w600k_r50.trt"
            )

            print("GPU worker: rec engine ok", flush=True)

            self.scrfd = SCRFD(
                det_engine,
                det_size=self.det_size,
                det_thresh=det_thresh,
                nms_thresh=nms_thresh,
            )

            self.provider = "tensorrt"

            print("GPU worker ready", flush=True)

            logger.info(
                "GPU worker ready: det_10g + w600k_r50"
            )

        except Exception as exc:

            self._gpu_error = exc

            print(
                "GPU worker init failed: "
                f"{exc}",
                flush=True,
            )

            logger.exception(
                "GPU worker init failed"
            )

        finally:

            self._gpu_ready.set()

        if self._gpu_error is not None:
            return

        while True:

            frame, result, done = self._gpu_queue.get()

            started = time.monotonic()

            try:

                result["faces"] = self._detect_gpu(frame)

            except Exception:

                logger.exception(
                    "GPU inference failed"
                )

                result["faces"] = []

            finally:

                done.set()

            print(
                "GPU inference: %.1f ms"
                % ((time.monotonic() - started) * 1000),
                flush=True,
            )

    def _init_cpu_fallback(self):

        try:

            from insightface.app import FaceAnalysis

        except ImportError:

            logger.warning(
                "insightface unavailable; "
                "detection disabled"
            )

            return

        self.app = FaceAnalysis(
            name="buffalo_l",
            providers=[
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ],
        )

        self.app.prepare(
            ctx_id=0,
            det_size=self.det_size,
        )

        self.provider = "cpu"

        logger.info(
            "CPU face detector ready (insightface)"
        )

    def _embedding(self, frame, kps):

        aimg = norm_crop(
            frame,
            kps,
            image_size=self.rec_size,
        )

        blob = blob_from_image(
            aimg,
            1.0 / REC_STD,
            (self.rec_size, self.rec_size),
            (REC_MEAN, REC_MEAN, REC_MEAN),
            swap_rb=True,
        )

        out = self.rec_engine.run(
            self.rec_engine.output_names,
            {self.rec_engine.input_names[0]: blob},
        )[0]

        return out.flatten()

    def _detect_gpu(self, frame):

        bboxes, kpss = self.scrfd.detect(frame)

        faces = []

        for index in range(bboxes.shape[0]):

            face = Face(
                bbox=bboxes[index, 0:4],
                kps=kpss[index],
                det_score=bboxes[index, 4],
            )

            face.embedding = self._embedding(
                frame,
                kpss[index],
            )

            faces.append(face)

        return faces

    def detect(self, frame):

        if self.provider == "cpu":
            return self.app.get(frame)

        if self.provider != "tensorrt":
            return []

        self._gpu_ready.wait(timeout=GPU_TIMEOUT)

        if self._gpu_error is not None:

            logger.error(
                "GPU unavailable: %s",
                self._gpu_error,
            )

            return []

        result = {}

        done = threading.Event()

        self._gpu_queue.put((frame, result, done))

        done.wait(timeout=GPU_TIMEOUT)

        return result.get("faces", [])