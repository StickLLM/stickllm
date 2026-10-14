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

# Skip CUDA rebuild when binaries already present (Vulkan-only resume).
# STICKLLM_SKIP_CUDA_BUILD=1 wins even with FORCE (resume after Vulkan fail).
SKIP_CUDA=0
if [[ "${STICKLLM_SKIP_CUDA_BUILD:-}" == "1" ]] \
  && [[ -s "$OUT_BIN" ]] \
  && [[ -f "$OUT_LIB/stickllm-cuda-register.so" ]] \
  && { [[ -f "$OUT_LIB/libggml-cuda.so" ]] || [[ -f "$OUT_LIB/libggml-cuda.so.0" ]] || [[ -f "$OUT_LIB/libggml-cuda.so.0.26.0" ]]; }; then
  SKIP_CUDA=1
  echo "[stickllm] skipping CUDA rebuild (STICKLLM_SKIP_CUDA_BUILD=1; artifacts present)"
elif [[ -s "$OUT_BIN" && -f "$OUT_LIB/stickllm-cuda-register.so" \
  && ( -f "$OUT_LIB/libggml-cuda.so" || -f "$OUT_LIB/libggml-cuda.so.0" ) \
  && "${STICKLLM_FORCE_LLAMA_BUILD:-}" != "1" ]]; then
  SKIP_CUDA=1
  echo "[stickllm] skipping CUDA rebuild (existing $OUT_BIN + libggml-cuda)"
fi

if [[ "$SKIP_CUDA" -eq 0 ]]; then
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
fi

# Vulkan binary for AMD/Intel (and NVIDIA fallback). Separate tree + lib-vulkan/
# so CUDA libggml* is never overwritten. CUDA remains default on NVIDIA hosts.
echo "[stickllm] building Vulkan llama-server…"
# CUDA devel image is Ubuntu jammy (main only by default). Enable universe for
# glslang/vulkan/SPIRV. ggml-vulkan needs glslc at build time — jammy has no
# glslc package; pull LunarG shaderc (~6MB) for /usr/bin/glslc.
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  software-properties-common curl gnupg ca-certificates >/dev/null
add-apt-repository -y universe >/dev/null 2>&1 || true
install -d -m 0755 /usr/share/keyrings
curl -fsSL https://packages.lunarg.com/lunarg-signing-key-pub.asc \
  | gpg --dearmor -o /usr/share/keyrings/lunarg.gpg
echo "deb [signed-by=/usr/share/keyrings/lunarg.gpg] https://packages.lunarg.com/vulkan jammy main" \
  >/etc/apt/sources.list.d/lunarg-vulkan.list
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  libvulkan-dev glslang-tools glslang-dev spirv-tools spirv-headers \
  vulkan-tools pkg-config shaderc
command -v glslc >/dev/null || {
  echo "docker-build-llama: glslc missing after LunarG shaderc install" >&2
  exit 1
}
glslc --version | head -1
# Prefer apt SPIRV-HeadersConfig.cmake; else install Khronos headers to /usr/local.
SPIRV_HEADERS_DIR=""
if [[ -f /usr/share/cmake/SPIRV-Headers/SPIRV-HeadersConfig.cmake ]]; then
  SPIRV_HEADERS_DIR=/usr/share/cmake/SPIRV-Headers
else
  echo "[stickllm] installing Khronos SPIRV-Headers (CMake config)"
  rm -rf /tmp/SPIRV-Headers
  git clone --depth 1 https://github.com/KhronosGroup/SPIRV-Headers.git /tmp/SPIRV-Headers
  cmake -S /tmp/SPIRV-Headers -B /tmp/SPIRV-Headers/build -DCMAKE_INSTALL_PREFIX=/usr/local
  cmake --install /tmp/SPIRV-Headers/build
  SPIRV_HEADERS_DIR=/usr/local/share/cmake/SPIRV-Headers
fi
test -f "$SPIRV_HEADERS_DIR/SPIRV-HeadersConfig.cmake"
GLSLC_BIN="$(command -v glslc)"
OUT_LIB_VK="/work/overlay/opt/stickllm/lib-vulkan"
mkdir -p "$OUT_LIB_VK"
rm -rf /tmp/llama.cpp-vulkan
if [[ -n "$TAG" ]]; then
  git clone --depth 1 --branch "$TAG" https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp-vulkan
else
  git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /tmp/llama.cpp-vulkan
fi
cmake -S /tmp/llama.cpp-vulkan -B /tmp/llama.cpp-vulkan/build \
  -DGGML_VULKAN=ON \
  -DGGML_CUDA=OFF \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_PREFIX_PATH=/usr/local \
  -DSPIRV-Headers_DIR="$SPIRV_HEADERS_DIR" \
  -DVulkan_GLSLC_EXECUTABLE="$GLSLC_BIN"
cmake --build /tmp/llama.cpp-vulkan/build --target llama-server -j"$(nproc)"
VK_BIN=""
for c in /tmp/llama.cpp-vulkan/build/bin/llama-server /tmp/llama.cpp-vulkan/build/llama-server; do
  if [[ -x "$c" ]]; then VK_BIN="$c"; break; fi
done
test -n "$VK_BIN"
OUT_VK="/work/overlay/opt/stickllm/bin/llama-server-vulkan"
install -m 755 "$VK_BIN" "$OUT_VK"
find /tmp/llama.cpp-vulkan/build -type f \( -name 'libggml*.so*' -o -name 'libllama*.so*' \) \
  -exec cp -a {} "$OUT_LIB_VK/" \; 2>/dev/null || true
cp -a /tmp/llama.cpp-vulkan/build/bin/*.so* "$OUT_LIB_VK/" 2>/dev/null || true
find "$OUT_LIB_VK" -type l ! -exec test -e {} \; -delete 2>/dev/null || true
LD_LIBRARY_PATH="$OUT_LIB_VK" "$OUT_VK" --version || true
ls -lh "$OUT_VK" "$OUT_LIB_VK" | head -n 30
test -f "$OUT_LIB_VK/libggml-vulkan.so" || test -f "$OUT_LIB_VK/libggml-vulkan.so.0" || {
  echo "docker-build-llama: missing libggml-vulkan after Vulkan build" >&2
  exit 1
}

# CPU-only binary for no-GPU hosts (ISS-018). Separate tree + lib-cpu/ —
# never overwrite CUDA/Vulkan libggml*.so (that dropped backend NEEDED and left
# --list-devices with CPU only while STICKLLM_BACKEND=cuda/vulkan).
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
  -DGGML_VULKAN=OFF \
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
# Sanity: CUDA + Vulkan libs must still be present and not replaced by CPU.
test -f "$OUT_LIB/libggml-cuda.so" || test -f "$OUT_LIB/libggml-cuda.so.0" || {
  echo "docker-build-llama: missing libggml-cuda after CPU build" >&2
  exit 1
}
test -f "$OUT_LIB_VK/libggml-vulkan.so" || test -f "$OUT_LIB_VK/libggml-vulkan.so.0" || {
  echo "docker-build-llama: missing libggml-vulkan after CPU build" >&2
  exit 1
}
echo "docker-build-llama: OK (cuda lib/ + vulkan lib-vulkan/ + cpu lib-cpu/ + register shim)"
