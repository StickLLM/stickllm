#!/usr/bin/env bash
# TEST-ONLY. AI KVM "Test 1" (virtual KVM over the Unix-socket backend + sl1-host-sim as the stick side),
# then import the stick-side record into a throwaway sticklinkd registry. Nothing touches real hardware.
#   VKVM=<sl1-uhid-kvm binary (own build)>  HOSTSIM=<aikvm-pair>/tools/sl1-host-sim/sl1_host_sim.py  PY=<python w/ noiseprotocol>
#   STICK_KEY_HEX/HOME_HEX optional: pair as an existing stick (static key + home), e.g. a fixture stick.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; PY="${PY:-/tmp/vv/bin/python}"
VKVM="${VKVM:?sl1-uhid-kvm}"; HOSTSIM="${HOSTSIM:-/workspace/aikvm-pair/tools/sl1-host-sim/sl1_host_sim.py}"
W="$(mktemp -d /tmp/sl-usb.XXXXXX)"; cd "$W"; mkfifo kin; FAIL=0
export STICKLINK_TESTING=1 PYTHONPATH="$REPO/overlay/usr/local/lib"
mkdir -m700 stick-state
[ -n "${STICK_KEY_HEX:-}" ] && (umask 077; echo "$STICK_KEY_HEX" > stick-state/stick_static.key)
"$VKVM" --socket "$W/kvm.sock" --state "$W/kvm-state" --open --auto-accept < kin > kvm.log 2>&1 & KP=$!
(sleep 60 > kin &) ; for i in $(seq 50); do [ -S kvm.sock ] && break; sleep 0.1; done
S=$(date +%s%N)
if "$PY" "$HOSTSIM" --socket "$W/kvm.sock" --state "$W/stick-state" --auto-accept ${HOME_HEX:+--home $HOME_HEX} > host.log 2>&1; then
  T0=$(grep -m1 -oP '^\[\K[0-9:.]+(?=\] XX msg1 sent)' host.log); T1=$(grep -m1 -oP '^\[\K[0-9:.]+(?=\] PAIRED)' host.log)
  echo "PASS usb-pair (socket backend): wall $(( ($(date +%s%N)-S)/1000000 )) ms incl. python start; XX msg1 $T0 -> PAIRED $T1; code $(grep -oP 'CODE  >>> \K[0-9]+' host.log) = KVM $(grep -oP 'SHOW_CODE  >>> \K[0-9]+' kvm.log)"
else echo "FAIL usb-pair"; tail -5 host.log kvm.log; exit 1; fi
kill $KP 2>/dev/null || true
REC="$(ls stick-state/kvm-*.json)"
"$PY" - "$REC" kvm-state/paired.json <<'PYEOF' && echo "PASS records agree (home, slot, pair_psk, both static keys)" || { echo "FAIL records differ"; FAIL=1; }
import json, sys
s, k = (json.load(open(p)) for p in sys.argv[1:3])
keys = ("home", "slot", "pair_psk", "kvm_static_pub", "stick_static_pub")
bad = [x for x in keys if s.get(x) != k.get(x)]
print("  differing:", bad or "none", "| KVM export fields:", sorted(k))
sys.exit(1 if bad else 0)
PYEOF
# throwaway registry = this stick: static key + home from the record (dev is a dummy; auth seed generated)
"$PY" - "$W/reg" "$W/stick-state/stick_static.key" "$REC" <<'PYEOF'
import json, os, sys
from pathlib import Path
from sticklink import registry
from sticklink.util import b64u
root, keyf, rec = sys.argv[1:4]
os.umask(0o077)
Path(root).parent.joinpath("regkey").write_bytes(os.urandom(32))
reg = registry.Registry(Path(root), Path(root).parent.joinpath("regkey").read_bytes())
reg.init_dirs(); reg.create_identity(priv=bytes.fromhex(open(keyf).read().strip()))
reg.save_signal(b64u(os.urandom(16)), b64u(bytes.fromhex(json.load(open(rec))["home"]))); reg.save_auth_seed()
PYEOF
D="$PY $REPO/overlay/usr/local/bin/sticklinkd"; K=(--root "$W/reg" --registry-key-file "$W/regkey")
if OUT=$($D import-usb "${K[@]}" --record "$REC" 2>&1); then echo "PASS import-usb: $OUT"; else echo "FAIL import-usb: $OUT"; FAIL=1; fi
$D list "${K[@]}" | sed 's/^/  list: /'
if $D import-usb "${K[@]}" --record "$REC" >/dev/null 2>&1; then echo "FAIL duplicate slot accepted"; FAIL=1; else echo "PASS duplicate slot refused"; fi
"$PY" -c "import json,sys;d=json.load(open(sys.argv[1]));d['slot_jk']='00'*32;json.dump(d,open(sys.argv[2],'w'))" "$REC" bad.json
if $D import-usb "${K[@]}" --record bad.json >/dev/null 2>&1; then echo "FAIL tampered slot_jk accepted"; FAIL=1; else echo "PASS tampered slot_jk refused"; fi
if grep -qiE "pair_psk|priv" kvm.log host.log; then echo "FAIL secret-looking words in tool logs"; FAIL=1; fi
echo "workdir: $W"; exit $FAIL
