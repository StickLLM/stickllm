#!/usr/bin/env bash
# TEST-ONLY end-to-end connectivity on one host (box pass 1 / no VM):
# stick responder (sticklinkd) <-> test peer (initiator) through a signalling
# server (mock or real wrangler dev) and a derper. Writes only under $W.
#   SL_WS=ws://127.0.0.1:8788/v1/ws SL_DERP=http://127.0.0.1:3341/derp SL_STUN=127.0.0.1:3479 \
#   SL_FIXTURES=.../dev-fixtures.json PY=python3 ./run_box.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../../.." && pwd)"
PY="${PY:-python3}"; SL_WS="${SL_WS:-ws://127.0.0.1:8788/v1/ws}"; SL_DERP="${SL_DERP:-http://127.0.0.1:3341/derp}"
SL_STUN="${SL_STUN:-127.0.0.1:3479}"; SL_FIXTURES="${SL_FIXTURES:-/workspace/sticklink/server/worker/fixtures/dev-fixtures.json}"
PIN_ARGS=(); [ -n "${SL_DERP_PIN:-}" ] && PIN_ARGS+=(--derp-pin "$SL_DERP_PIN"); [ -n "${SL_DERP_SNI:-}" ] && PIN_ARGS+=(--derp-sni "$SL_DERP_SNI")
export STICKLINK_TESTING=1 STICKLINK_FAST_KDF=1 PYTHONPATH="$REPO/overlay/usr/local/lib"
W="$(mktemp -d /tmp/sl-e2e.XXXXXX)"; chmod 700 "$W"; PIDS=()
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup EXIT
D="$PY -m sticklink.daemon"; K=(--root "$W/sticklink" --registry-key-file "$W/regkey")
head -c 32 /dev/urandom > "$W/regkey"; chmod 600 "$W/regkey"
"$PY" - "$SL_FIXTURES" "$W" <<'PYEOF'
import json, sys, os
d = json.load(open(sys.argv[1]))["devices"]["stick1"]
fd = os.open(sys.argv[2] + "/authseed", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.write(fd, d["auth_seed"].encode()); os.close(fd)
open(sys.argv[2] + "/ids", "w").write(d["dev"] + " " + d["home"] + "\n")
PYEOF
read DEV HOME_ID < "$W/ids"
$D init "${K[@]}" --dev "$DEV" --home "$HOME_ID" --auth-seed-file "$W/authseed" >/dev/null; rm -f "$W/authseed"
# revoked pages: pin the server's signing key (mock: public TEST key kid test-1 from signalling-v2.json)
SIGN_ARGS=(); [ -n "${SL_SIGN_KEY:-}" ] && SIGN_ARGS+=(--sign-key "$SL_SIGN_KEY")
$D pair-offer "${K[@]}" --out "$W/offer.json"
$PY "$REPO/tests/sticklink/tools/sl_testpeer.py" pair --offer "$W/offer.json" --state "$W/peer.json" --answer "$W/answer.json"
$D pair-accept "${K[@]}" --in "$W/answer.json"
rm -f "$W/offer.json" "$W/answer.json"
FAIL=0
for MODE in ${SL_MODES:-direct stick-force-relay peer-force-relay fallback reconnect bye revoke revoke-cli}; do
  echo "== $MODE"
  SARGS=(); PARGS=(); EXP=direct; PSTATE="$W/peer.json"
  if [ "${MODE#revoke}" != "$MODE" ]; then  # revocation deletes the record: use a peer paired just for this mode
    PSTATE="$W/peer-$MODE.json"
    $D pair-offer "${K[@]}" --out "$W/offer.json"
    $PY "$REPO/tests/sticklink/tools/sl_testpeer.py" pair --offer "$W/offer.json" --state "$PSTATE" --answer "$W/answer.json" --name "rv-$MODE"
    $D pair-accept "${K[@]}" --in "$W/answer.json"; rm -f "$W/offer.json" "$W/answer.json"
    PARGS=(--duration 7 --revoke-at 3 --min-echo 0.9); EXP=any
    [ "$MODE" = revoke-cli ] && PARGS+=(--revoke-via external)
  fi
  [ "$MODE" = stick-force-relay ] && { SARGS=(--force-relay); EXP=derp; }
  [ "$MODE" = peer-force-relay ] && { PARGS=(--force-relay); EXP=derp; }
  # direct, then direct blocked mid-session (-> DERP), then restored (-> direct again)
  [ "$MODE" = fallback ] && { PARGS=(--duration 22 --block-direct-at 4 --unblock-direct-at 13 --expect-paths udp,derp --min-echo 0.6); EXP=direct; }
  $D run "${K[@]}" --ws "$SL_WS" --derp "$SL_DERP" "${PIN_ARGS[@]}" "${SIGN_ARGS[@]}" --stun "$SL_STUN" "${SARGS[@]}" > "$W/stick-$MODE.log" 2>&1 &
  SP=$!; PIDS+=($SP); sleep 2
  if [ "$MODE" = revoke-cli ]; then  # local CLI: the operator revokes the peer by name while its session is up
    ( sleep 4.5; $D revoke "${K[@]}" --peer "rv-$MODE" > "$W/revoke-cli.out" 2>&1 ) & PIDS+=($!)
  fi
  if [ "$MODE" = bye ]; then  # stale bye mid-session is ignored; a bye for the current sid drops state
    PARGS=(--duration 6 --stale-bye-at 2 --bye --min-echo 0.9)
  fi
  if [ "$MODE" = reconnect ]; then  # same stick process: direct session, then an immediate new session over DERP
    $PY "$REPO/tests/sticklink/tools/sl_testpeer.py" connect --state "$PSTATE" --ws "$SL_WS" --derp "$SL_DERP" \
       "${PIN_ARGS[@]}" --stun "$SL_STUN" --duration 3 --expect direct > "$W/peer-reconnect-1.log" 2>&1 || { echo "FAIL reconnect (first)"; FAIL=1; }
    PARGS=(--force-relay); EXP=derp
  fi
  if $PY "$REPO/tests/sticklink/tools/sl_testpeer.py" connect --state "$PSTATE" --ws "$SL_WS" --derp "$SL_DERP" \
       "${PIN_ARGS[@]}" --stun "$SL_STUN" --duration "${SL_DURATION:-6}" --expect "$EXP" "${PARGS[@]}" > "$W/peer-$MODE.log" 2>&1; then
    echo "PASS $MODE: $(grep '^RESULT' "$W/peer-$MODE.log")"
  else echo "FAIL $MODE"; tail -15 "$W/peer-$MODE.log"; tail -15 "$W/stick-$MODE.log"; FAIL=1; fi
  kill $SP; wait $SP 2>/dev/null || true
  if [ "${MODE#revoke}" != "$MODE" ]; then
    if grep -q "REVOKED: active session terminated" "$W/stick-$MODE.log" && grep -q "refused" "$W/stick-$MODE.log" \
       && ! $D list "${K[@]}" 2>/dev/null | grep -q "rv-$MODE"; then
      echo "PASS $MODE (stick): session terminated, record deleted, new msg1 refused: $(grep -m1 'revoked set from' "$W/stick-$MODE.log" | sed 's/^.*revoked set/revoked set/')"
    else echo "FAIL $MODE (stick)"; grep -iE "revok|refused" "$W/stick-$MODE.log" | tail -8; FAIL=1; fi
    if grep -qE "revoked set in sync \(rc [1-9]" "$W/stick-$MODE.log" && ! grep -q "not verified" "$W/stick-$MODE.log"; then
      echo "PASS $MODE (stick): signed revoked.get page verified + cursor persisted: $(grep -m1 'revoked set in sync' "$W/stick-$MODE.log" | sed 's/^.*revoked set/revoked set/')"
    else echo "FAIL $MODE (stick): revoked.get page not pulled/verified"; grep -iE "revoked" "$W/stick-$MODE.log" | tail -5; FAIL=1; fi
  fi
  if [ "$MODE" = bye ]; then
    if grep -q "bye for an old sid ignored" "$W/stick-bye.log" && grep -q "session state dropped" "$W/stick-bye.log"; then
      echo "PASS bye: old-sid bye ignored (echoes continued), current-sid bye dropped the session"
    else echo "FAIL bye: stick log lacks the expected bye handling"; grep -i bye "$W/stick-bye.log"; FAIL=1; fi
  fi
done
if grep -rqiE "pair_psk|dev_secret|auth_seed|nodekey:[0-9a-f]{64}" "$W"/*.log; then echo "FAIL secrets/full keys in logs"; FAIL=1; else echo "PASS no secrets or full keys in logs"; fi
echo "logs: $W"; exit $FAIL
