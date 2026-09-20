from pathlib import Path

from edgeguard_config import get, get_float, get_int

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# --- TensorRT engines ---

# Directory with the serialized engines built by
# scripts/convert_engines.sh (det_10g.trt, w600k_r50.trt)
ENGINE_DIR = PROJECT_ROOT / get(
    "jetson_gpu",
    "engine_dir",
    default="models/engines",
)

# Detection input size. The det_10g engine is built for exactly this
# size - changing it requires rebuilding the engine.
DET_SIZE = (
    get_int("jetson_gpu", "det_size", "width", default=640),
    get_int("jetson_gpu", "det_size", "height", default=640),
)

# Defaults mirror the CPU pipeline's effective behavior
# (insightface defaults; vision.detection_threshold is not applied there).
DET_THRESH = get_float(
    "jetson_gpu",
    "det_thresh",
    default=0.5,
)

NMS_THRESH = get_float(
    "jetson_gpu",
    "nms_thresh",
    default=0.4,
)

# Recognition crop size (ArcFace template; w600k_r50 is 112x112)
REC_SIZE = get_int(
    "jetson_gpu",
    "rec_size",
    default=112,
)