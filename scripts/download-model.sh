#!/usr/bin/env bash
# Fetch pinned GGUFs into models/ (gitignored) with catalog sha256 verify.
# Default bake set: Qwen2.5-3B Q4_K_M (base) + Qwen2.5-7B Q5_K_M (also on ISO).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# id|hf_repo|filename|sha256
MODELS=(
  "qwen25-3b-q4km|Qwen/Qwen2.5-3B-Instruct-GGUF|qwen2.5-3b-instruct-q4_k_m.gguf|626b4a6678b86442240e33df819e00132d3ba7dddfe1cdc4fbb18e0a9615c62d"
  "qwen25-7b-q5km|Qwen/Qwen2.5-7B-Instruct-GGUF|qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf|42f6693004793ee6cf1b2b723f0273b10f86a3bb2a949bd9128d4cda5fb866cd"
  "qwen25-7b-q5km|Qwen/Qwen2.5-7B-Instruct-GGUF|qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf|beba9d4f2f5a1fe7d144dcae332e68b52c26705c5310dece2e5d1997e091e134"
)

hash_of() {
  local f="$1"
  if command -v sha256sum >/dev/null; then
    sha256sum "$f" | awk '{print $1}'
  elif command -v shasum >/dev/null; then
    shasum -a 256 "$f" | awk '{print $1}'
  else
    echo "ERROR: need sha256sum or shasum" >&2
    exit 1
  fi
}

mkdir -p models
for row in "${MODELS[@]}"; do
  IFS='|' read -r id repo file expect <<<"$row"
  DEST="models/${file}"
  URL="https://huggingface.co/${repo}/resolve/main/${file}"
  if [[ -f "$DEST" ]]; then
    got="$(hash_of "$DEST")"
    if [[ "$got" == "$expect" ]]; then
      echo "OK (cached+hash): $DEST"
      continue
    fi
    echo "WARN: hash mismatch for $DEST — re-downloading"
    rm -f "$DEST"
  fi
  echo "Downloading ${id}: ${file}…"
  TMP="${DEST}.partial"
  curl -L --fail --progress-bar -o "$TMP" "$URL"
  got="$(hash_of "$TMP")"
  if [[ "$got" != "$expect" ]]; then
    echo "ERROR: sha256 mismatch for ${file}" >&2
    echo "  expected: $expect" >&2
    echo "  got:      $got" >&2
    rm -f "$TMP"
    exit 1
  fi
  mv "$TMP" "$DEST"
  echo "OK (verified): $DEST"
done

{
  printf '%s  %s\n' "$(hash_of models/qwen2.5-3b-instruct-q4_k_m.gguf)" "models/qwen2.5-3b-instruct-q4_k_m.gguf"
  printf '%s  %s\n' "$(hash_of models/qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf)" "models/qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf"
  printf '%s  %s\n' "$(hash_of models/qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf)" "models/qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf"
} | tee models/baked-default.sha256

ls -lh \
  models/qwen2.5-3b-instruct-q4_k_m.gguf \
  models/qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf \
  models/qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf
echo "OK — default bake: 3B Q4_K_M; also included: 7B Q5_K_M"
