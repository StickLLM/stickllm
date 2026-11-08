#!/usr/bin/env bash
# Copyright (c) 2026 Nink Inc. All rights reserved.
#
# Local integration test: wrangler dev --local + sticklink-admit + derper -dev.
# Nothing remote is touched (no deploy, no Cloudflare resources, no live relay).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SERVER="$(dirname "$HERE")"
ROOT="$(dirname "$SERVER")"
RELAY="$ROOT/relay"
W="$(mktemp -d /tmp/sl-int.XXXXXX)"
PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup EXIT
waitport() { for _ in $(seq 1 120); do (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && return 0; sleep 0.5; done; echo "port $1 never opened"; return 1; }

# Ports are overridable (another wrangler may hold 8787). derper -dev always binds :3340.
PW=${SL_INT_PORT_WORKER:-8787}; PA=${SL_INT_PORT_ADMIT:-9099}
# Fail fast if a previous run (or anything else) still holds a port we need.
for p in $PW $PA 3340; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$p") 2>/dev/null; then echo "port $p is busy (stale wrangler/derper/sidecar or e2e/start-stack.sh running?); stop it first"; exit 1; fi
done

echo "== build sidecar + probe"
(cd "$SERVER/sidecar" && go build -o "$W/sticklink-admit" ./cmd/sticklink-admit)
printf '{"Replace":{"%s":"%s"}}\n' "$RELAY/ts/cmd/sldprobe/main.go" "$HERE/derpprobe/main.go" > "$W/overlay.json"
(cd "$RELAY/ts" && GOFLAGS=-mod=mod GOPROXY=off go build -buildvcs=false -overlay "$W/overlay.json" -o "$W/sldprobe" ./cmd/sldprobe)

echo "== worker: .dev.vars, local D1 migrations + fixtures"
cd "$SERVER/worker"
# Isolated state: D1 and .dev.vars live in $W, never in worker/.wrangler or worker/.dev.vars.
export SL_PERSIST="$W/d1" SL_DEV_VARS_OUT="$W/dev.vars"
node scripts/dev-vars.mjs
node scripts/seed-dev.mjs --apply
export WRANGLER_SEND_METRICS=false
npx wrangler dev --local --ip 0.0.0.0 --port "$PW" --inspector-port $((PW+1500)) --persist-to "$W/d1" --env-file "$W/dev.vars" >"$W/wrangler.log" 2>&1 &
PIDS+=($!)
waitport "$PW"

echo "== sidecar (test token + test signing pubkey)"
node --input-type=module -e 'import {DEV} from "./scripts/dev-vars.mjs"; process.stdout.write(DEV.RELAY_TOKEN)' >"$W/token"
chmod 600 "$W/token"
node --input-type=module -e 'import {DEV} from "./scripts/dev-vars.mjs"; console.log(DEV.SIGNING_KID+" "+DEV.SIGNING_PUB)' >"$W/keys"
mkdir -p "$W/state"
"$W/sticklink-admit" -listen 127.0.0.1:$PA -base http://127.0.0.1:$PW -region tor1 \
  -token-file "$W/token" -keys "$W/keys" -state "$W/state" -stats 5s >"$W/admit.log" 2>&1 &
ADMIT=$!; PIDS+=($ADMIT)
waitport "$PA"

echo "== derper -dev (fail-closed admission)"
"$RELAY/derper" -dev -verify-client-url http://127.0.0.1:$PA/derp/admit -verify-client-url-fail-open=false >"$W/derper.log" 2>&1 &
PIDS+=($!)
waitport 3340

echo "== e2e"
SL_BASE="ws://127.0.0.1:$PW" SL_PROBE="$W/sldprobe" SL_LAST_KEY_FILE="$W/lastkey" node "$HERE/e2e.mjs"

echo "== fail closed when the sidecar is down"
kill "$ADMIT"; wait "$ADMIT" 2>/dev/null || true
if "$W/sldprobe" -url http://127.0.0.1:3340/derp -key "$(cat "$W/lastkey")" | grep -q ADMITTED; then
  echo "FAIL admitted with sidecar down"; exit 1
else echo "PASS derper rejects a registered key while sidecar is down"; fi

echo "== sidecar restart restores persisted state (no network needed for the first answer)"
"$W/sticklink-admit" -listen 127.0.0.1:$PA -base http://127.0.0.1:1 -region tor1 \
  -token-file "$W/token" -keys "$W/keys" -state "$W/state" >>"$W/admit.log" 2>&1 &
PIDS+=($!)
waitport "$PA"
if "$W/sldprobe" -url http://127.0.0.1:3340/derp -key "$(cat "$W/lastkey")" | grep -q ADMITTED; then
  echo "PASS restored state admits the still-valid key"
else echo "FAIL restored state"; exit 1; fi

echo "== sidecar log (counters only):"; tail -3 "$W/admit.log"
grep -q nodekey: "$W/admit.log" && { echo "FAIL node keys in sidecar log"; exit 1; } || echo "PASS no keys/IPs in sidecar log"
echo "INTEGRATION OK  (logs: $W)"
