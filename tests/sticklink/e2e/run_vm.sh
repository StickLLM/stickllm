#!/usr/bin/env bash
# TEST-ONLY: stick responder inside the QEMU test VM (sticklinkd installed from the overlay),
# test peer on the host. Signalling/DERP/STUN on the host, reached from the guest via slirp 10.0.2.2.
# Modes: direct | flag-relay (sticklinkd --force-relay) | nft-relay (guest nftables drops all UDP
# except to the host's STUN port; no flag) | fallback (direct, then guest nft blocks UDP mid-session).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../../.." && pwd)"
VMSSH="${VMSSH:-$REPO/../vm/ssh.sh}"; PY="${PY:-python3}"
HOSTWS_PORT="${HOSTWS_PORT:-8788}"; DERP_PORT="${DERP_PORT:-3341}"; STUN_PORT="${STUN_PORT:-3479}"
SL_FIXTURES="${SL_FIXTURES:-/workspace/sticklink/server/worker/fixtures/dev-fixtures.json}"
export STICKLINK_TESTING=1 STICKLINK_FAST_KDF=1 PYTHONPATH="$REPO/overlay/usr/local/lib"
W="$(mktemp -d /tmp/sl-vme2e.XXXXXX)"; chmod 700 "$W"
G="export STICKLINK_TESTING=1 STICKLINK_FAST_KDF=1 STICKLINK_DEBUG_PKT=${SL_DEBUG_PKT:-0}; R=/home/tester/slroot; "'K="--root $R/sticklink --registry-key-file $R/regkey"'
vm() { timeout 120 "$VMSSH" "$G; $1"; }
unblock() { vm 'sudo /usr/sbin/nft delete table inet sltest 2>/dev/null || true'; }
cleanup() { vm 'pkill -f "[s]ticklinkd run" || true' || true; unblock || true; }
trap cleanup EXIT
"$PY" - "$SL_FIXTURES" "$W" <<'PYEOF'
import json, sys, os
d = json.load(open(sys.argv[1]))["devices"]["stick1"]
fd = os.open(sys.argv[2] + "/authseed", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600); os.write(fd, d["auth_seed"].encode()); os.close(fd)
open(sys.argv[2] + "/ids", "w").write(d["dev"] + " " + d["home"] + "\n")
PYEOF
read DEV HOME_ID < "$W/ids"
vm 'rm -rf $R && mkdir -m 700 $R && head -c 32 /dev/urandom > $R/regkey && chmod 600 $R/regkey && umask 077 && cat > $R/authseed' < "$W/authseed"
vm "sticklinkd init \$K --dev $DEV --home $HOME_ID --auth-seed-file \$R/authseed >&2 && rm -f \$R/authseed && sticklinkd pair-offer \$K --out \$R/offer.json >/dev/null && cat \$R/offer.json && rm -f \$R/offer.json" > "$W/offer.json"
rm -f "$W/authseed"
$PY "$REPO/tests/sticklink/tools/sl_testpeer.py" pair --offer "$W/offer.json" --state "$W/peer.json" --answer "$W/answer.json" >/dev/null
rm -f "$W/offer.json"
vm 'umask 077; cat > $R/answer.json && sticklinkd pair-accept $K --in $R/answer.json && rm -f $R/answer.json' < "$W/answer.json"
NFT_BLOCK="table inet sltest { chain out { type filter hook output priority 0; udp dport $STUN_PORT accept; meta l4proto udp drop; }; chain in { type filter hook input priority 0; udp sport $STUN_PORT accept; meta l4proto udp drop; }; }"
SIGN_ARGS=""; [ -n "${SL_SIGN_KEY:-}" ] && SIGN_ARGS="--sign-key '$SL_SIGN_KEY'"
FAIL=0
for MODE in ${SL_MODES:-direct flag-relay nft-relay fallback}; do
  echo "== VM $MODE"; SARGS=""; PARGS=(--duration "${SL_DURATION:-8}"); EXP=direct
  case $MODE in
    flag-relay) SARGS=--force-relay; EXP=derp;;
    nft-relay) vm "echo '$NFT_BLOCK' | sudo /usr/sbin/nft -f -"; EXP=derp;;
    fallback) PARGS=(--duration 24 --expect-paths udp,derp --min-echo 0.5); EXP=derp;;
  esac
  vm "nohup sticklinkd run \$K --ws ws://10.0.2.2:$HOSTWS_PORT/v1/ws --derp http://10.0.2.2:$DERP_PORT/derp --stun 10.0.2.2:$STUN_PORT $SARGS $SIGN_ARGS > \$R/stick-$MODE.log 2>&1 &"
  sleep 4
  if [ "$MODE" = fallback ]; then ( sleep 9; vm "echo '$NFT_BLOCK' | sudo /usr/sbin/nft -f -"; echo "[nft block on]" ) & fi
  if $PY "$REPO/tests/sticklink/tools/sl_testpeer.py" connect --state "$W/peer.json" --ws "ws://127.0.0.1:$HOSTWS_PORT/v1/ws" \
       --derp "http://127.0.0.1:$DERP_PORT/derp" --stun "127.0.0.1:$STUN_PORT" --expect "$EXP" "${PARGS[@]}" > "$W/peer-$MODE.log" 2>&1; then
    echo "PASS VM $MODE: $(grep '^RESULT' "$W/peer-$MODE.log")"
  else echo "FAIL VM $MODE"; tail -12 "$W/peer-$MODE.log"; vm "tail -12 \$R/stick-$MODE.log"; FAIL=1; fi
  wait || true
  vm 'pkill -f "[s]ticklinkd run" || true; sleep 1'; unblock
  vm "cat \$R/stick-$MODE.log" > "$W/stick-$MODE.log" || true
done
if grep -rqiE "pair_psk|dev_secret|auth_seed|nodekey:[0-9a-f]{64}" "$W"/*.log; then echo "FAIL secrets/full keys in logs"; FAIL=1; else echo "PASS no secrets or full keys in logs"; fi
echo "logs: $W"; exit $FAIL
