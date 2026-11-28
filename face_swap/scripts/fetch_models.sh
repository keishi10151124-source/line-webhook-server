#!/usr/bin/env bash
# Downloads the two OpenCV Model Zoo face models (YuNet: MIT, SFace: Apache 2.0).
set -euo pipefail
DIR="${FACE_MODELS_DIR:-$(dirname "$0")/../models}"
mkdir -p "$DIR"
BASE="https://github.com/opencv/opencv_zoo/raw/main/models"
fetch() {
  local url="$1" out="$2"
  if [ -s "$out" ] && [ "$(stat -c%s "$out")" -gt 10000 ]; then echo "have $out"; return; fi
  curl -fsSL --retry 3 -o "$out" "$url"
  [ "$(stat -c%s "$out")" -gt 10000 ] || { echo "download looks wrong: $out" >&2; exit 1; }
  echo "got $out"
}
fetch "$BASE/face_detection_yunet/face_detection_yunet_2023mar.onnx" "$DIR/face_detection_yunet_2023mar.onnx"
fetch "$BASE/face_recognition_sface/face_recognition_sface_2021dec.onnx" "$DIR/face_recognition_sface_2021dec.onnx"
