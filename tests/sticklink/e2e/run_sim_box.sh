#!/usr/bin/env bash
# TEST-ONLY, box: AI KVM's v2 sl1-kvm-sim (own build of aikvm-pair, IKpsk2 initiator) <-> sticklinkd (responder)
# through the box mock signaller (v2) + TLS derper. The pairing comes from a USB pairing over the Unix-socket
# backend (sl1-uhid-kvm + sl1-host-sim), imported with import-usb into a throwaway registry for fixture stick1.
#   AIKVM=<own copy of aikvm-pair with build-rel/>  SL_FIXTURES=<v2 dev-fixtures.json>  SL_SIGN_KEY=kid=pub  PY=<python>
#   SL_WS (mock)  SL_DERP_URL=https://derp.test:3443/derp  SL_DERP_PIN  SL_STUN=127.0.0.1:3479
# The derper's manual cert needs SNI derp.test; the sim is started through a tiny shim that only maps the
# connect address derp.test -> 127.0.0.1 (no change to AI KVM's files).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../../.." && pwd)"
PY="${PY:-/tmp/vv/bin/python}"; A="${AIKVM:?}"; FIX="${SL_FIXTURES:?}"
SL_WS="${SL_WS:-ws://127.0.0.1:8788/v1/ws}"; DURL="${SL_DERP_URL:-https://derp.test:3443/derp}"; PIN="${SL_DERP_PIN:?}"
STUN="${SL_STUN:-127.0.0.1:3479}"
export STICKLINK_TESTING=1 STICKLINK_FAST_KDF=1 SL1_LIB="$A/build-rel/components/sl1_pair/libsl1pair.so"
W="$(mktemp -d /tmp/sl-sim.XXXXXX)"; chmod 700 "$W"; cd "$W"; PIDS=(); FAIL=0
cleanup() { for p in "${PIDS[@]}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup EXIT
log() { echo "[$(date +%T)] $*"; }
read DEV HOMEB HOMEHEX < <("$PY" -c "import json,sys,base64;d=json.load(open(sys.argv[1]))['devices']['stick1'];h=d['home'];print(d['dev'],h,base64.urlsafe_b64decode(h+'='*(-len(h)%4)).hex())" "$FIX")
# 1. USB pairing (socket backend), stick side pairs as stick1's home
mkfifo kin; mkdir -m700 stick-state
"$A/build-rel/tools/sl1-uhid-kvm" --socket "$W/kvm.sock" --state "$W/kvm-state" --open --auto-accept < kin > kvm.log 2>&1 & PIDS+=($!)
(sleep 120 > kin &); for i in $(seq 50); do [ -S kvm.sock ] && break; sleep 0.1; done
if PYTHONPATH="$REPO/overlay/usr/local/lib" "$PY" "$A/tools/sl1-host-sim/sl1_host_sim.py" --socket "$W/kvm.sock" --state "$W/stick-state" --auto-accept --home "$HOMEHEX" > host.log 2>&1; then
  echo "PASS usb-pair v2 (socket): XX msg1 $(grep -m1 -oP '^\[\K[0-9:.]+(?=\] XX msg1 sent)' host.log) -> PAIRED $(grep -m1 -oP '^\[\K[0-9:.]+(?=\] PAIRED)' host.log); code $(grep -oP 'CODE  >>> \K[0-9]+' host.log) = KVM $(grep -oP 'SHOW_CODE  >>> \K[0-9]+' kvm.log)"
else echo "FAIL usb-pair"; tail -5 host.log kvm.log; exit 1; fi
# 2. throwaway registry = stick1 (static key from the pairing, fixture dev/home/auth seed), then import-usb
export PYTHONPATH="$REPO/overlay/usr/local/lib"
"$PY" - "$W" "$FIX" <<'PYEOF'
import json, os, sys, base64
from pathlib import Path
from sticklink import registry
w, fix = sys.argv[1:3]; d = json.load(open(fix))["devices"]["stick1"]; os.umask(0o077)
Path(w, "regkey").write_bytes(os.urandom(32))
reg = registry.Registry(Path(w, "reg"), Path(w, "regkey").read_bytes())
reg.init_dirs(); reg.create_identity(priv=bytes.fromhex(Path(w, "stick-state/stick_static.key").read_text().strip()))
reg.save_signal(d["dev"], d["home"]); s = d["auth_seed"]; reg.save_auth_seed(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))
PYEOF
D="$PY -m sticklink.daemon"; K=(--root "$W/reg" --registry-key-file "$W/regkey")
if OUT=$($D import-usb "${K[@]}" --record "$(ls stick-state/kvm-*.json)" 2>&1); then echo "PASS import-usb: $OUT"; else echo "FAIL import-usb: $OUT"; exit 1; fi
# 3. sim inputs (own dir): stack.json + the KVM's paired.json; the shim maps derp.test -> 127.0.0.1
"$PY" -c "import json,sys;json.dump({'ws':sys.argv[1],'rg':'tor1','derp':{'url':sys.argv[2],'cert_sha256':sys.argv[3],'stun':sys.argv[4]}},open('stack.json','w'))" "$SL_WS" "$DURL" "$PIN" "$STUN"
cat > simshim.py <<'PYEOF'
import asyncio, runpy, sys
_oc = asyncio.open_connection
async def oc(host=None, port=None, **kw):
    return await _oc("127.0.0.1" if host == "derp.test" else host, port, **kw)
asyncio.open_connection = oc
sys.argv = sys.argv[1:]; sys.path.insert(0, __import__("os").path.dirname(sys.argv[0]))
runpy.run_path(sys.argv[0], run_name="__main__")
PYEOF
SIM="$A/tools/sl1-kvm-sim/sl1_kvm_sim.py"
for MODE in ${SL_MODES:-direct kvm-force-relay stick-force-relay udp-blocked-fallback}; do
  SARGS=(); KARGS=(); EXP=direct
  case $MODE in kvm-force-relay) KARGS=(--force-relay); EXP=derp;; stick-force-relay) SARGS=(--force-relay); EXP=derp;;
                udp-blocked-fallback) KARGS=(--block-udp-rx); EXP=derp;; esac
  $D run "${K[@]}" --ws "$SL_WS" --derp "${SL_STICK_DERP:-https://127.0.0.1:3443/derp}" --derp-sni derp.test --derp-pin "$PIN" --stun "$STUN" ${SL_SIGN_KEY:+--sign-key "$SL_SIGN_KEY"} "${SARGS[@]}" > "stick-$MODE.log" 2>&1 & SP=$!; PIDS+=($SP)
  for i in $(seq 40); do grep -q "slot.add ok\|relay.ok\|relay permit" "stick-$MODE.log" 2>/dev/null && break; sleep 0.25; done; sleep 0.5
  S=$(date +%s%N); set +e
  timeout 60 "$PY" simshim.py "$SIM" --stack stack.json --pairing kvm-state/paired.json --id '' --state "$W/simstate" --pings 20 -v "${KARGS[@]}" > "kvm-$MODE.log" 2>&1; RC=$?
  set -e; MS=$(( ($(date +%s%N)-S)/1000000 )); kill $SP 2>/dev/null; wait $SP 2>/dev/null || true
  RES=$(grep 'RESULT' "kvm-$MODE.log" | tail -1 | cut -c1-300 || true)
  HS=$(grep -m1 -iE 'handshake (done|ok|complete)|RESP .*valid|session up' "kvm-$MODE.log" | cut -c1-160 || true)
  if [ $RC = 0 ] && grep -qi "path=$EXP" <<<"$RES"; then echo "PASS sim $MODE (${MS} ms total): $RES | $HS"
  else echo "FAIL sim $MODE rc=$RC (want path=$EXP): ${RES:-$(tail -3 "kvm-$MODE.log" | tr '\n' ' ' | cut -c1-300)}"; grep -iE "error|drop" "stick-$MODE.log" | tail -3; FAIL=1; fi
done
if grep -qiE '"pair_psk"|static_priv|auth_seed|dev_secret' *.log; then echo "FAIL secret-looking field in logs"; FAIL=1; else echo "PASS no secrets in logs"; fi
echo "logs: $W"; exit $FAIL
