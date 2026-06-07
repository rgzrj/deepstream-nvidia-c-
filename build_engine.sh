#!/bin/bash
# =============================================================================
# Build TensorRT engine from ONNX model (one-time setup)
# Run this once on Jetson before starting the DeepStream app.
# Do not rely on the app to auto-build the engine: building inside the live
# GStreamer pipeline can exhaust Jetson NvMap memory.
# =============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MODEL_DIR="${SCRIPT_DIR}/fd_lpd_model"
ONNX_FILE="${MODEL_DIR}/fd_lpd.onnx"
ENGINE_FILE="${MODEL_DIR}/fd_lpd.onnx_b1_gpu0_fp16.engine"

echo "=== Build TensorRT Engine ==="
echo "  ONNX:   ${ONNX_FILE}"
echo "  Engine: ${ENGINE_FILE}"

if [ -f "${ENGINE_FILE}" ]; then
    echo ""
    echo "Engine file already exists: ${ENGINE_FILE}"
    echo "Delete it first if you want to rebuild."
    echo "Now you can run: cd ${SCRIPT_DIR}/build && ./show"
    exit 0
fi

if [ ! -f "${ONNX_FILE}" ]; then
    echo "ERROR: ONNX model not found: ${ONNX_FILE}"
    exit 1
fi

echo ""
echo "Building engine (may take 5-10 minutes)..."

/usr/src/tensorrt/bin/trtexec \
    --onnx="${ONNX_FILE}" \
    --saveEngine="${ENGINE_FILE}" \
    --fp16

echo ""
echo "Done! Engine saved to: ${ENGINE_FILE}"
echo "Now you can run: cd ${SCRIPT_DIR}/build && ./show"
