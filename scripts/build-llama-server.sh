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

# Always create SONAME symlinks even when reusing a prior llama tree.
# v0.8.3 bake skipped rebuild (binaries already present) and never ran
# docker-build-llama.sh link_soname → shipping ISO missing .so.1 / .so.0 → Vulkan on RTX.
ensure_overlay_cuda_sonames() {
  local lib="$OUT_LIB"
  [[ -d "$lib" ]] || return 0
  _link() {
    local ver="$1" link="$2"
    if [[ -f "$lib/$ver" ]]; then
      ln -sfn "$ver" "$lib/$link"
    fi
  }
  _link libllama.so.1.0.0 libllama.so.1
  _link libllama-common.so.1.0.0 libllama-common.so.1
  _link libggml.so.1.0.0 libggml.so.1
  _link libggml-base.so.1.0.0 libggml-base.so.1
  _link libmtmd.so.1.0.0 libmtmd.so.1
  _link libllama.so.1.0.0 libllama.so
  _link libllama-common.so.1.0.0 libllama-common.so
  _link libggml.so.1.0.0 libggml.so
  _link libggml-base.so.1.0.0 libggml-base.so
  _link libmtmd.so.1.0.0 libmtmd.so
  if [[ -f "$lib/libggml-cuda.so" && ! -e "$lib/libggml-cuda.so.0" ]]; then
    ln -sfn libggml-cuda.so "$lib/libggml-cuda.so.0"
  fi
  if [[ ! -e "$lib/libggml-cpu.so" ]]; then
    local cand
    for cand in libggml-cpu-x64.so libggml-cpu-haswell.so libggml-cpu-zen4.so libggml-cpu-sse42.so; do
      if [[ -f "$lib/$cand" ]]; then
        ln -sfn "$cand" "$lib/libggml-cpu.so"
        break
      fi
    done
  fi
}

# On Windows/Git Bash, -x can be flaky for ELF binaries; size check is enough.
if [[ -f "$OUT_BIN" && -s "$OUT_BIN" && -f "$OUT_CPU" && -s "$OUT_CPU" \
  && -f "$OUT_VK" && -s "$OUT_VK" \
  && -f "$OUT_LIB/libllama-server-impl.so" \
  && ( -f "$OUT_LIB_VK/libggml-vulkan.so" || -f "$OUT_LIB_VK/libggml-vulkan.so.0" ) \
  && "${STICKLLM_FORCE_LLAMA_BUILD:-}" != "1" ]]; then
  echo "llama-server already built: $OUT_BIN (+ vulkan $OUT_VK + cpu $OUT_CPU)"
  ensure_overlay_cuda_sonames
  echo "ensured CUDA SONAME symlinks under $OUT_LIB"
  exit 0
fi

# Resume after Vulkan-only failure: keep intact CUDA, rebuild Vulkan+CPU.
SKIP_CUDA="${STICKLLM_SKIP_CUDA_BUILD:-0}"
vk_missing=0
if [[ ! -s "$OUT_VK" ]] \
  || { [[ ! -e "$OUT_LIB_VK/libggml-vulkan.so" ]] && [[ ! -e "$OUT_LIB_VK/libggml-vulkan.so.0" ]]; }; then
  vk_missing=1
fi
if [[ "$SKIP_CUDA" != "1" ]] \
  && [[ -s "$OUT_BIN" ]] \
  && [[ -f "$OUT_LIB/stickllm-cuda-register.so" ]] \
  && { [[ -e "$OUT_LIB/libggml-cuda.so" ]] || [[ -e "$OUT_LIB/libggml-cuda.so.0" ]] || [[ -e "$OUT_LIB/libggml-cuda.so.0.26.0" ]]; } \
  && { [[ -e "$OUT_LIB/libllama-server-impl.so" ]] || [[ -e "$OUT_LIB/libllama.so.0" ]]; } \
  && [[ "$vk_missing" -eq 1 ]]; then
  SKIP_CUDA=1
  echo "Resuming llama build: CUDA intact → Vulkan+CPU only"
fi

echo "Building llama.cpp ${STICKLLM_LLAMA_TAG:-master} with CUDA arch 86 + Vulkan + CPU…"

# Git Bash on Windows rewrites Unix Docker paths; disable conversion.
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

docker run --rm \
  -e "STICKLLM_LLAMA_TAG=${STICKLLM_LLAMA_TAG:-}" \
  -e "STICKLLM_SKIP_CUDA_BUILD=${SKIP_CUDA}" \
  -e "STICKLLM_FORCE_LLAMA_BUILD=${STICKLLM_FORCE_LLAMA_BUILD:-}" \
  -v "${ROOT}:/work" \
  -w //work \
  nvidia/cuda:12.4.1-devel-ubuntu22.04 \
  bash //work/scripts/lib/docker-build-llama.sh

echo "OK → $OUT_BIN"
ls -lh "$OUT_BIN"
ls -lh "$OUT_LIB" | head -n 40
