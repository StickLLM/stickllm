#!/bin/bash
# Runs inside nvidia/cuda devel container. Repo mounted at /work.
set -euo pipefail

TAG="${STICKLLM_LLAMA_TAG:-}"
OUT_BIN="/work/overlay/opt/stickllm/bin/llama-server"
OUT_LIB="/work/overlay/opt/stickllm/lib"
mkdir -p "$(dirname "$OUT_BIN")" "$OUT_LIB"

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  git cmake build-essential curl ca-certificates

rm -rf /tmp/llama.cpp
if [[ -n "$TAG" ]]; then
  git clone --depth 1 --branch "$TAG" https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp
else
  git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp
fi

# Devel images ship libcuda stubs only (no GPU driver).
export LIBRARY_PATH=/usr/local/cuda/lib64/stubs:${LIBRARY_PATH:-}
export LD_LIBRARY_PATH=/usr/local/cuda/lib64/stubs:${LD_LIBRARY_PATH:-}
ln -sf /usr/local/cuda/lib64/stubs/libcuda.so /usr/lib/x86_64-linux-gnu/libcuda.so
ln -sf /usr/local/cuda/lib64/stubs/libcuda.so /usr/lib/x86_64-linux-gnu/libcuda.so.1

cmake -S /tmp/llama.cpp -B /tmp/llama.cpp/build \
  -DGGML_CUDA=ON \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_CUDA_ARCHITECTURES=86 \
  -DCMAKE_EXE_LINKER_FLAGS='-L/usr/local/cuda/lib64/stubs -Wl,-rpath-link,/usr/local/cuda/lib64/stubs' \
  -DCMAKE_SHARED_LINKER_FLAGS='-L/usr/local/cuda/lib64/stubs -Wl,-rpath-link,/usr/local/cuda/lib64/stubs'

cmake --build /tmp/llama.cpp/build --target llama-server -j"$(nproc)"

BIN=""
for c in /tmp/llama.cpp/build/bin/llama-server /tmp/llama.cpp/build/llama-server; do
  if [[ -x "$c" ]]; then BIN="$c"; break; fi
done
test -n "$BIN"

install -m 755 "$BIN" "$OUT_BIN"

# Bundle all llama.cpp shared objects (thin llama-server links to these).
find /tmp/llama.cpp/build -type f \( -name '*.so' -o -name '*.so.*' \) -exec cp -a {} "$OUT_LIB/" \;
# Also from bin/ for versioned names produced there
cp -a /tmp/llama.cpp/build/bin/*.so* "$OUT_LIB/" 2>/dev/null || true

cp -a /usr/local/cuda/lib64/libcudart.so* "$OUT_LIB/" 2>/dev/null || true
cp -a /usr/local/cuda/lib64/libcublas.so* "$OUT_LIB/" 2>/dev/null || true
cp -a /usr/local/cuda/lib64/libcublasLt.so* "$OUT_LIB/" 2>/dev/null || true
# NCCL is pulled in by recent ggml-cuda builds
cp -aL /usr/lib/x86_64-linux-gnu/libnccl.so* "$OUT_LIB/" 2>/dev/null || true
cp -aL /usr/local/cuda/lib64/libnccl.so* "$OUT_LIB/" 2>/dev/null || true

# Drop broken absolute symlinks that point outside the stick
find "$OUT_LIB" -type l ! -exec test -e {} \; -delete 2>/dev/null || true

# Preload shim: register ggml_backend_cuda_reg when libggml does not NEEDED cuda
# (shared-backend builds export ggml_backend_cuda_reg, not ggml_backend_init).
REGISTER_SRC="/work/overlay/opt/stickllm/lib/stickllm-cuda-register.c"
if [[ -f "$REGISTER_SRC" ]]; then
  gcc -shared -fPIC -o "$OUT_LIB/stickllm-cuda-register.so" "$REGISTER_SRC" -ldl
  chmod 755 "$OUT_LIB/stickllm-cuda-register.so"
fi

LD_LIBRARY_PATH="$OUT_LIB" "$OUT_BIN" --version
ls -lh "$OUT_BIN" "$OUT_LIB" | head -n 50

# CPU-only binary for no-NVIDIA hosts (ISS-018). Separate tree + lib-cpu/ —
# never overwrite CUDA libggml*.so (that dropped libggml-cuda NEEDED and left
# --list-devices with CPU only while STICKLLM_BACKEND=cuda).
echo "[stickllm] building CPU llama-server…"
OUT_LIB_CPU="/work/overlay/opt/stickllm/lib-cpu"
mkdir -p "$OUT_LIB_CPU"
rm -rf /tmp/llama.cpp-cpu
if [[ -n "$TAG" ]]; then
  git clone --depth 1 --branch "$TAG" https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp-cpu
else
  git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp-cpu
fi
cmake -S /tmp/llama.cpp-cpu -B /tmp/llama.cpp-cpu/build \
  -DGGML_CUDA=OFF \
  -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/llama.cpp-cpu/build --target llama-server -j"$(nproc)"
CPU_BIN=""
for c in /tmp/llama.cpp-cpu/build/bin/llama-server /tmp/llama.cpp-cpu/build/llama-server; do
  if [[ -x "$c" ]]; then CPU_BIN="$c"; break; fi
done
test -n "$CPU_BIN"
OUT_CPU="/work/overlay/opt/stickllm/bin/llama-server-cpu"
install -m 755 "$CPU_BIN" "$OUT_CPU"
find /tmp/llama.cpp-cpu/build -type f \( -name 'libggml*.so*' -o -name 'libllama*.so*' \) \
  -exec cp -a {} "$OUT_LIB_CPU/" \; 2>/dev/null || true
cp -a /tmp/llama.cpp-cpu/build/bin/*.so* "$OUT_LIB_CPU/" 2>/dev/null || true
find "$OUT_LIB_CPU" -type l ! -exec test -e {} \; -delete 2>/dev/null || true
# CPU binary must use lib-cpu at runtime (stickllm-llama-start sets this on CPU path
# only when needed; default rpath/LD path still OK if libs are self-contained).
LD_LIBRARY_PATH="$OUT_LIB_CPU" "$OUT_CPU" --version || true
ls -lh "$OUT_CPU" "$OUT_LIB_CPU" | head -n 30
# Sanity: CUDA libggml must still be present and must not have been replaced by CPU.
test -f "$OUT_LIB/libggml-cuda.so" || test -f "$OUT_LIB/libggml-cuda.so.0" || {
  echo "docker-build-llama: missing libggml-cuda after CPU build" >&2
  exit 1
}
echo "docker-build-llama: OK (cuda lib/ + cpu lib-cpu/ + register shim)"
