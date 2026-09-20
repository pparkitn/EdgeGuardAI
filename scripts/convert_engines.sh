#!/usr/bin/env bash
#
# Convert the insightface buffalo_l ONNX models to fixed-shape
# TensorRT engines for the Jetson (JetPack 4.4, TensorRT 7.1).
#
# Requires: trtexec (ships with JetPack, /usr/bin/trtexec) and the
# buffalo_l ONNX files (~/.insightface/models/buffalo_l).
#
# Usage:
#   ./scripts/convert_engines.sh                          # default paths
#   MODEL_DIR=/path/to/buffalo_l ENGINE_DIR=/out ./scripts/convert_engines.sh
#   FP16=0 ./scripts/convert_engines.sh                   # fp32 engines
#
# The det engine is built for exactly 640x640 (matching the service
# det_size). Recognition is the w600k_r50 ArcFace model.

set -euo pipefail

MODEL_DIR="${MODEL_DIR:-$HOME/.insightface/models/buffalo_l}"
ENGINE_DIR="${ENGINE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/models/engines}"
TRTEXEC="${TRTEXEC:-/usr/bin/trtexec}"
FP16="${FP16:-1}"

if [ ! -f "$MODEL_DIR/det_10g.onnx" ]; then
    echo "error: $MODEL_DIR/det_10g.onnx not found" >&2
    exit 1
fi

if [ ! -x "$TRTEXEC" ]; then
    echo "error: $TRTEXEC not found (run this on the Jetson)" >&2
    exit 1
fi

mkdir -p "$ENGINE_DIR"

convert() {
    local name="$1" input="$2" shape="$3"

    if [ -f "$ENGINE_DIR/$name.trt" ]; then
        echo "==> $ENGINE_DIR/$name.trt exists, skipping"
        return
    fi

    echo "==> Building $name.trt ($shape)..."

    local args=(
        --onnx="$MODEL_DIR/$name.onnx"
        --minShapes="$input:$shape"
        --optShapes="$input:$shape"
        --maxShapes="$input:$shape"
        --workspace=1024
        --saveEngine="$ENGINE_DIR/$name.trt"
    )

    if [ "$FP16" = "1" ]; then
        args+=(--fp16)
    fi

    "$TRTEXEC" "${args[@]}"

    echo "==> Built $ENGINE_DIR/$name.trt"
}

convert det_10g input.1 1x3x640x640
convert w600k_r50 input.1 1x3x112x112

echo "==> Done. Engines in $ENGINE_DIR"