#!/bin/bash
# Image-build only. Copies pinned speech files into the live-build tree and
# compiles whisper.cpp v1.8.7 (CPU) on bookworm. The running stick does not
# download these. Voice files land in /opt/stickllm/speech, a normal folder.
# They are not copied into stickllm-vault.img or the USB settings partition.
set -euo pipefail

PIN="/stickllm/overlay/usr/local/lib/stickllm-speech.pin"
SRC="/stickllm/models/speech"
ROOT="${1:-/work}"
DEST="$ROOT/config/includes.chroot/opt/stickllm/speech"
BIN_DIR="$ROOT/config/includes.chroot/usr/local/bin"

pin_value() {
  local key="$1"
  awk -F' = ' -v k="$key" '$1 == k { print $2; exit }' "$PIN"
}

require_sha() {
  local file="$1" expect="$2"
  local got
  got="$(sha256sum "$SRC/$file" | awk '{print $1}')"
  if [[ -z "$expect" || "$got" != "$expect" ]]; then
    echo "ERROR: $file sha256 mismatch" >&2
    echo "  expected: ${expect:-<missing pin>}" >&2
    echo "  got:      $got" >&2
    exit 1
  fi
  echo "OK $file"
}

WHISPER_SHA="$(pin_value model_sha256)"
# The first model_sha256 in the pin is the whisper model. Kitten has its own.
# Read section-aware values so the kitten hash is not used for whisper.
read_section_key() {
  local section="$1" key="$2"
  awk -v section="$section" -v key="$key" '
    $0 ~ "^\\[" { in_s = ($0 == "[" section "]"); next }
    in_s && $0 ~ "^" key " = " { sub("^" key " = ", ""); print; exit }
  ' "$PIN"
}

WHISPER_SHA="$(read_section_key stt model_sha256)"
KITTEN_SHA="$(read_section_key tts model_sha256)"
VOICES_SHA="$(read_section_key tts voices_sha256)"
CONFIG_SHA="$(read_section_key tts config_sha256)"
SOURCE_SHA="$(read_section_key stt source_sha256)"
ONNX_SHA="$(read_section_key onnx sha256)"
ONNX_NAME="$(read_section_key onnx wheel)"

require_sha "ggml-tiny.en.bin" "$WHISPER_SHA"
require_sha "kitten_tts_mini_v0_8.onnx" "$KITTEN_SHA"
require_sha "voices.npz" "$VOICES_SHA"
require_sha "config.json" "$CONFIG_SHA"
require_sha "whisper.cpp-v1.8.7.tar.gz" "$SOURCE_SHA"
require_sha "$ONNX_NAME" "$ONNX_SHA"

mkdir -p "$DEST/py" "$BIN_DIR"
cp -f "$SRC/ggml-tiny.en.bin" "$DEST/ggml-tiny.en.bin"
cp -f "$SRC/kitten_tts_mini_v0_8.onnx" "$DEST/kitten_tts_mini_v0_8.onnx"
cp -f "$SRC/voices.npz" "$DEST/voices.npz"
cp -f "$SRC/config.json" "$DEST/config.json"
chmod 644 "$DEST/ggml-tiny.en.bin" "$DEST/kitten_tts_mini_v0_8.onnx" "$DEST/voices.npz" "$DEST/config.json"

python3 -m zipfile -e "$SRC/$ONNX_NAME" "$DEST/py"
test -f "$DEST/py/onnxruntime/__init__.py"

rm -rf /tmp/whisper-src /tmp/whisper-build
mkdir -p /tmp/whisper-src
tar -xzf "$SRC/whisper.cpp-v1.8.7.tar.gz" -C /tmp/whisper-src --strip-components=1
if [[ ! -f /tmp/whisper-src/ggml/CMakeLists.txt ]]; then
  echo "ERROR: whisper.cpp v1.8.7 tarball has no ggml sources" >&2
  exit 1
fi
cmake -S /tmp/whisper-src -B /tmp/whisper-build \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_NATIVE=OFF \
  -DGGML_CUDA=OFF \
  -DWHISPER_SDL2=OFF \
  -DWHISPER_BUILD_TESTS=OFF \
  -DBUILD_SHARED_LIBS=OFF
cmake --build /tmp/whisper-build --target whisper-cli -j"$(nproc)"
WHISPER_BIN="$(find /tmp/whisper-build -type f -name whisper-cli | head -1)"
if [[ -z "$WHISPER_BIN" || ! -f "$WHISPER_BIN" ]]; then
  echo "ERROR: whisper-cli was not produced" >&2
  exit 1
fi
install -m 0755 "$WHISPER_BIN" "$BIN_DIR/whisper-cli"

# Voice-on keeps whisper-server resident (stickllm-whisper.service).
# Bake the host binary from out/whisper-srv when the image build produced it.
WHISPER_SRV=""
for candidate in \
  /stickllm/out/whisper-srv/whisper-server \
  /stickllm-out/whisper-srv/whisper-server
do
  if [[ -f "$candidate" ]]; then
    WHISPER_SRV="$candidate"
    break
  fi
done
if [[ -z "$WHISPER_SRV" ]]; then
  echo "ERROR: whisper-server missing (expected out/whisper-srv/whisper-server)" >&2
  exit 1
fi
install -m 0755 "$WHISPER_SRV" "$BIN_DIR/whisper-server"
echo "bake-speech: installed whisper-server from $WHISPER_SRV"

test -x "$BIN_DIR/whisper-cli"
test -x "$BIN_DIR/whisper-server"
test -f "$DEST/ggml-tiny.en.bin"
test -f "$DEST/kitten_tts_mini_v0_8.onnx"
test -f "$DEST/voices.npz"
# The 3B GGUF bake is separate and must still be present.
test -f "$ROOT/config/includes.chroot/opt/stickllm/models/qwen2.5-3b-instruct-q4_k_m.gguf"
echo "bake-speech: OK (/opt/stickllm/speech, not the vault)"
