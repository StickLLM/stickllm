#!/usr/bin/env bash
# TEST-ONLY, pass 2: Sticklink's real e2e stack (Worker + sidecar + derper, from the desktop bundle) runs in a
# "stack VM"; the stick (sticklinkd) runs in a separate "stick VM"; the KVM side is sl_testpeer in the stack VM.
# The two VMs share a private L2 link (QEMU socket netdev) 192.168.77.1 (stack) <-> 192.168.77.2 (stick).
# Identity: the stack's own seeded fixture (e2e/state/{pairing,stick.id,kvm.id}.json) via import-e2e.
# Modes: direct | flag-relay | nft-relay | midblock (UDP blocked mid-session) | failback (block, then unblock)
#        | wrongpin (bad DERP pin + force-relay: must fail closed) | reconnect.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../../.." && pwd)"
STATE="${SL_STATE_DIR:?path to the bundle e2e/state}"; STACK="$STATE/stack.json"
STICK="${STICK_SSH:-tester@192.168.77.2}"; KEY="${STICK_KEY:-$HOME/kit/vmkey}"; PY="${PY:-python3}"
export STICKLINK_TESTING=1 PYTHONPATH="$REPO/overlay/usr/local/lib"
W="$(mktemp -d /tmp/sl-p2.XXXXXX)"; chmod 700 "$W"
G="export STICKLINK_TESTING=1 STICKLINK_DEBUG_PKT=${SL_DEBUG_PKT:-0}; R=/home/tester/slroot; "'K="--root $R/sticklink --registry-key-file $R/regkey"'
vm() { timeout 120 ssh -q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -i "$KEY" "$STICK" "$G; $1"; }
NFT_BLOCK="table inet sltest { chain out { type filter hook output priority 0; udp dport != 53 drop; }; chain in { type filter hook input priority 0; udp sport != 53 drop; }; }"
block() { vm "echo '$NFT_BLOCK' | sudo /usr/sbin/nft -f -"; echo "[$(date +%T) stick-VM UDP block ON]"; }
unblock() { vm 'sudo /usr/sbin/nft delete table inet sltest 2>/dev/null || true'; echo "[$(date +%T) stick-VM UDP block OFF]"; }
cleanup() { vm 'pkill -f "[s]ticklinkd run" || true' || true; unblock >/dev/null || true; }
trap cleanup EXIT
# stick VM: import the fixture stick (copies go over ssh stdin into a 0700 dir; nothing printed)
vm 'sudo rm -rf $R && mkdir -m 700 $R && head -c 32 /dev/urandom > $R/regkey && chmod 600 $R/regkey'
vm 'umask 077; cat > $R/pairing.json' < "$STATE/pairing.json"
vm 'umask 077; cat > $R/stick.id.json' < "$STATE/stick.id.json"
vm 'umask 077; cat > $R/stack.json' < "$STACK"
vm 'sticklinkd import-e2e $K --pairing $R/pairing.json --identity $R/stick.id.json && rm -f $R/pairing.json $R/stick.id.json'
PIN=$("$PY" -c 'import json,sys;print(json.load(open(sys.argv[1]))["derp"]["cert_sha256"])' "$STACK")
echo "stack: $("$PY" -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["ws"],d["derp"]["url"],d["derp"]["stun"])' "$STACK") pin ${PIN:0:16}…"
SIGN_ARGS=""; [ -n "${SL_SIGN_KEY:-}" ] && SIGN_ARGS="--sign-key '$SL_SIGN_KEY'"
FAIL=0
for MODE in ${SL_MODES:-direct flag-relay nft-relay midblock failback wrongpin reconnect bye}; do
  echo "== P2 $MODE"; SARGS=""; PARGS=(--duration "${SL_DURATION:-8}"); EXP=direct; WANT=ok
  case $MODE in
    flag-relay) SARGS=--force-relay; EXP=derp;;
    nft-relay) block; EXP=derp;;
    midblock) PARGS=(--duration 24 --expect-paths udp,derp --min-echo 0.5); EXP=derp;;
    failback) PARGS=(--duration 30 --expect-paths udp,derp --min-echo 0.5); EXP=direct;;
    bye) PARGS=(--duration 6 --stale-bye-at 2 --bye --min-echo 0.9);;
    wrongpin) SARGS="--force-relay --derp-pin $(printf '0%.0s' {1..64})"; PARGS=(--duration 8 --force-relay); WANT=fail;;
  esac
  vm "nohup sticklinkd run \$K --stack \$R/stack.json $SARGS $SIGN_ARGS > \$R/stick-$MODE.log 2>&1 &"
  sleep 4
  case $MODE in
    midblock) ( sleep 9; block ) & ;;
    failback) ( sleep 8; block; sleep 9; unblock ) & ;;
  esac
  if [ "$MODE" = reconnect ]; then
    "$PY" "$REPO/tests/sticklink/tools/sl_testpeer.py" connect --pairing "$STATE/pairing.json" --identity "$STATE/kvm.id.json" \
      --stack "$STACK" --duration 3 --expect direct > "$W/peer-reconnect-1.log" 2>&1 || { echo "FAIL P2 reconnect (first)"; FAIL=1; }
    PARGS=(--duration 6 --force-relay); EXP=derp
  fi
  set +e
  "$PY" "$REPO/tests/sticklink/tools/sl_testpeer.py" connect --pairing "$STATE/pairing.json" --identity "$STATE/kvm.id.json" \
     --stack "$STACK" --expect "$EXP" "${PARGS[@]}" > "$W/peer-$MODE.log" 2>&1; RC=$?
  set -e
  wait || true
  vm 'pkill -f "[s]ticklinkd run" || true; sleep 1'; unblock >/dev/null
  vm "cat \$R/stick-$MODE.log" > "$W/stick-$MODE.log" || true
  if [ "$MODE" = bye ] && ! { grep -q "bye for an old sid ignored" "$W/stick-bye.log" && grep -q "session state dropped" "$W/stick-bye.log"; }; then
    RC=99; echo "(bye: stick log lacks old-sid-ignored / session-dropped)"; fi
  if [ "$WANT" = ok ] && [ $RC = 0 ]; then echo "PASS P2 $MODE: $(grep '^RESULT' "$W/peer-$MODE.log" | cut -c1-400)"
  elif [ "$WANT" = fail ] && [ $RC != 0 ] && grep -qi "pin" "$W/stick-$MODE.log"; then
    echo "PASS P2 $MODE (failed closed): stick: $(grep -i -m1 pin "$W/stick-$MODE.log" | cut -c1-200)"
  else echo "FAIL P2 $MODE (rc=$RC)"; tail -12 "$W/peer-$MODE.log"; tail -12 "$W/stick-$MODE.log"; FAIL=1; fi
done
if grep -rqiE "pair_psk|dev_secret|auth_seed|static_priv|nodekey:[0-9a-f]{64}" "$W"/*.log; then echo "FAIL secrets/full keys in logs"; FAIL=1; else echo "PASS no secrets or full keys in logs"; fi
echo "logs: $W"; exit $FAIL
