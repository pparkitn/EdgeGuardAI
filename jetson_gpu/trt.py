"""TensorRT engine wrapper exposing an onnxruntime-like interface.

Loads a serialized TensorRT engine (built by `convert_engines.sh`) and
executes it with pycuda. The public surface mirrors the parts of
onnxruntime used by .scrfd.SCRFD:

    engine.input_names   -> list of str
    engine.output_names  -> list of str
    engine.run(output_names, {input_name: ndarray}) -> list of ndarray

Binding memory is allocated in the engine's native dtype (fp16 engines
use fp16 IO); inputs are converted on upload, outputs are returned as
float32 so downstream decode math matches the CPU pipeline bit-for-bit.

Targets JetPack 4.4 (TensorRT 7.1). The legacy `ICudaEngine(serialized)`
constructor used here was removed in TensorRT 9; TensorRT 8 is handled
via the new Runtime API.

IMPORTANT (TRT 7 + pycuda): the CUDA context must exist before the
TensorRT engine/execution context is created, otherwise cuDNN fails at
first inference with CUDNN_STATUS_MAPPING_ERROR. pycuda.autoinit is
therefore imported at the top of __init__.
"""

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def _volume(shape):

    size = 1

    for dim in shape:
        size *= int(dim)

    return size


class TensorRtEngine:

    def __init__(self, engine_path):

        self.engine_path = Path(engine_path)

        # CUDA context first (see module docstring).
        import pycuda.autoinit  # noqa: F401
        import pycuda.driver as cuda

        self._cuda = cuda

        self._stream = cuda.Stream()

        self._device_buffers = {}

        self._buffers_by_index = []

        self._engine = self._load_engine()

        self._context = self._engine.create_execution_context()

        self.input_names = []

        self.output_names = []

        self._bindings = {}

        for index in range(self._engine.num_bindings):

            name = self._engine.get_binding_name(index)

            shape = self._binding_shape(index)

            if self._engine.binding_is_input(index):
                self.input_names.append(name)
            else:
                self.output_names.append(name)

            dtype = self._binding_dtype(index)

            self._bindings[name] = {
                "shape": tuple(shape),
                "dtype": dtype,
                "size": _volume(shape)
                * np.dtype(dtype).itemsize,
            }

            device = cuda.mem_alloc(
                self._bindings[name]["size"]
            )

            self._device_buffers[name] = device

            self._buffers_by_index.append(
                (index, name, device)
            )

        self.output_shapes = {
            name: self._bindings[name]["shape"]
            for name in self.output_names
        }

    def _load_engine(self):

        import tensorrt as trt

        self._trt = trt

        logger_local = trt.Logger(trt.Logger.WARNING)

        serialized = self.engine_path.read_bytes()

        try:

            return trt.ICudaEngine(serialized)

        except (AttributeError, TypeError):

            pass

        # TensorRT 8+: new Runtime API.
        runtime = trt.Runtime(logger_local)

        return runtime.deserialize_cuda_engine(serialized)

    def _binding_shape(self, index):

        if hasattr(self._context, "get_binding_dimensions"):

            dims = self._context.get_binding_dimensions(index)

            return tuple(dims[i] for i in range(len(dims)))

        return tuple(self._engine.get_binding_shape(index))

    def _binding_dtype(self, index):

        """numpy dtype of a binding, with TRT 7/8 API fallbacks."""

        engine = self._engine

        getter = getattr(
            engine,
            "get_binding_dtype",
            None,
        )

        if getter is None:
            getter = getattr(
                engine,
                "get_binding_data_type",
                None,
            )

        if getter is not None:

            import tensorrt as trt

            try:

                return np.dtype(
                    trt.nptype(getter(index))
                )

            except Exception:

                logger.debug(
                    "Binding dtype lookup failed; "
                    "assuming float32",
                    exc_info=True,
                )

        return np.dtype(np.float32)

    def run(self, output_names, feed):

        cuda = self._cuda

        for name, array in feed.items():

            host = np.ascontiguousarray(
                array,
                dtype=self._bindings[name]["dtype"],
            )

            cuda.memcpy_htod(
                self._device_buffers[name],
                host,
            )

        bindings = [
            int(
                self._buffers_by_index[index][2]
            )
            for index in range(
                self._engine.num_bindings
            )
        ]

        self._context.execute_async(
            bindings=bindings,
            stream_handle=self._stream.handle,
        )

        self._stream.synchronize()

        results = []

        for name in output_names:

            shape = self._bindings[name]["shape"]

            dtype = self._bindings[name]["dtype"]

            host = np.empty(shape, dtype=dtype)

            cuda.memcpy_dtoh(
                host,
                self._device_buffers[name],
            )

            if dtype is np.dtype(np.float32):
                results.append(host)
            else:
                results.append(
                    host.astype(np.float32)
                )

        return results