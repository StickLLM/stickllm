#!/usr/bin/env bash
# Build a docker data-root that already contains the pinned Agent Zero image.
# Used at ISO build time so the stick ships A0 installed (no docker load on first run).
# Usage: a0_seed.sh <pin-file> <bundle-dir-with-parts> <out-seed-dir>
set -euo pipefail
PIN="${1:?pin}"
BUNDLE="${2:?bundle}"
OUT="${3:?out}"
SOCK="${A0_SEED_SOCK:-/tmp/stickllm-a0-seed.sock}"
PIDFILE="${A0_SEED_PID:-/tmp/stickllm-a0-seed.pid}"
WORK="${A0_SEED_WORK:-/tmp/stickllm-a0-seed-work}"

rm -rf "$WORK" "$OUT"
mkdir -p "$WORK" "$OUT"
command -v dockerd >/dev/null
command -v docker >/dev/null
command -v python3 >/dev/null

dockerd --data-root "$WORK" --host "unix://$SOCK" --pidfile "$PIDFILE" \
  --iptables=false --ip-forward=false --bridge=none \
  --log-level=warn >/tmp/stickllm-a0-seed-dockerd.log 2>&1 &
for i in $(seq 1 60); do
  docker -H "unix://$SOCK" info >/dev/null 2>&1 && break
  sleep 1
done
docker -H "unix://$SOCK" info >/dev/null

python3 - "$BUNDLE" "$SOCK" <<'PY'
import json, sys, subprocess
from pathlib import Path
bundle = Path(sys.argv[1])
sock = sys.argv[2]
doc = json.loads((bundle / "bundle.json").read_text())
parts = [bundle / p["name"] for p in doc["parts"]]
for p in parts:
    if not p.is_file():
        raise SystemExit(f"missing part {p}")
proc = subprocess.Popen(
    ["docker", "-H", f"unix://{sock}", "load"],
    stdin=subprocess.PIPE,
)
assert proc.stdin is not None
for p in parts:
    with p.open("rb") as f:
        while True:
            chunk = f.read(8 * 1024 * 1024)
            if not chunk:
                break
            proc.stdin.write(chunk)
proc.stdin.close()
rc = proc.wait()
if rc != 0:
    raise SystemExit(f"docker load failed rc={rc}")
print(f"a0_seed: loaded {doc.get('tar_size', 0)} bytes", flush=True)
PY

CFG=$(grep -E '^config_digest=' "$PIN" | cut -d= -f2- | tr -d '\r')
VER=$(grep -E '^version=' "$PIN" | cut -d= -f2- | tr -d '\r')
CFG="${CFG#sha256:}"
docker -H "unix://$SOCK" tag "$CFG" "stickllm/agent-zero:${VER}" 2>/dev/null || \
  docker -H "unix://$SOCK" tag "sha256:$CFG" "stickllm/agent-zero:${VER}" 2>/dev/null || true
docker -H "unix://$SOCK" images

kill "$(cat "$PIDFILE")" 2>/dev/null || true
for i in $(seq 1 30); do
  kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null || break
  sleep 1
done
shopt -s dotglob nullglob
mv "$WORK"/* "$OUT"/
rm -rf "$WORK"
python3 - "$OUT" "$PIN" <<'PY'
import json, sys
from pathlib import Path
out, pin = Path(sys.argv[1]), Path(sys.argv[2])
meta = {}
for line in pin.read_text().splitlines():
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        meta[k.strip()] = v.strip()
doc = {
  "format": 1,
  "kind": "docker-data-root",
  "image": meta.get("image"),
  "version": meta.get("version"),
  "config_digest": meta.get("config_digest"),
  "amd64_digest": meta.get("amd64_digest"),
}
(out / "stickllm-seed.json").write_text(json.dumps(doc, indent=1) + "\n")
print("a0_seed: wrote", out / "stickllm-seed.json", flush=True)
PY
echo "a0_seed: OK -> $OUT ($(du -sh "$OUT" | awk '{print $1}'))"
