#!/usr/bin/env bash
# Build llama-server with CUDA (sm_86 / RTX 3090) inside Docker — no GPU required to compile.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

OUT_BIN="overlay/opt/stickllm/bin/llama-server"
OUT_CPU="overlay/opt/stickllm/bin/llama-server-cpu"
OUT_VK="overlay/opt/stickllm/bin/llama-server-vulkan"
OUT_LIB="overlay/opt/stickllm/lib"
OUT_LIB_VK="overlay/opt/stickllm/lib-vulkan"
mkdir -p overlay/opt/stickllm/bin "$OUT_LIB" "$OUT_LIB_VK"

# On Windows/Git Bash, -x can be flaky for ELF binaries; size check is enough.
if [[ -f "$OUT_BIN" && -s "$OUT_BIN" && -f "$OUT_CPU" && -s "$OUT_CPU" \
  && -f "$OUT_VK" && -s "$OUT_VK" \
  && -f "$OUT_LIB/libllama-server-impl.so" \
  && ( -f "$OUT_LIB_VK/libggml-vulkan.so" || -f "$OUT_LIB_VK/libggml-vulkan.so.0" ) \
  && "${STICKLLM_FORCE_LLAMA_BUILD:-}" != "1" ]]; then
  echo "llama-server already built: $OUT_BIN (+ vulkan $OUT_VK + cpu $OUT_CPU)"
  exit 0
fi

echo "Building llama.cpp ${STICKLLM_LLAMA_TAG:-master} with CUDA arch 86 + Vulkan + CPU…"

# Git Bash on Windows rewrites Unix Docker paths; disable conversion.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

docker run --rm \
  -e "STICKLLM_LLAMA_TAG=${STICKLLM_LLAMA_TAG:-}" \
  -v "${ROOT}:/work" \
  -w //work \
  nvidia/cuda:12.4.1-devel-ubuntu22.04 \
  bash //work/scripts/lib/docker-build-llama.sh

echo "OK → $OUT_BIN"
ls -lh "$OUT_BIN"
ls -lh "$OUT_LIB" | head -n 40
