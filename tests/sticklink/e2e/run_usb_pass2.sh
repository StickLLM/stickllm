#!/usr/bin/env bash
# TEST-ONLY, desktop pass 2: virtual-KVM USB pairing over a real uhid HID device in the stick VM, then
# AI KVM's sl1-kvm-sim (IKpsk2 initiator, stack VM) connects to sticklinkd (stick VM) through Sticklink's
# real stack using the pairing that the USB exchange produced. Runs in the stack VM.
#   SL_STATE_DIR=<bundle e2e/state>   USBKIT=<dir: sl1-uhid-kvm, libsl1pair.so, sl1_host_sim.py, kvm-sim/*.py, py/noise>
# The stick VM gets the fixture stick identity (import-e2e) so its static key + home are the ones the stack knows;
# the USB pairing then adds a NEW kvm slot to that stick. Nothing here touches real USB hardware.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$HERE/../../.." && pwd)"
STATE="${SL_STATE_DIR:?}"; STACK="$STATE/stack.json"; KIT="${USBKIT:?}"
STICK="${STICK_SSH:-tester@192.168.77.2}"; KEY="${STICK_KEY:-$HOME/kit/vmkey}"
W="$(mktemp -d /tmp/sl-usb2.XXXXXX)"; chmod 700 "$W"; FAIL=0
G="export STICKLINK_TESTING=1; R=/home/tester/slroot; U=/home/tester/usbkit; "'K="--root $R/sticklink --registry-key-file $R/regkey"'
SSHO=(-q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=10 -i "$KEY")
vm() { local rc=0; timeout 120 ssh "${SSHO[@]}" "$STICK" "$G; $1" || rc=$?; [ $rc = 124 ] && echo "[$(date +%T)] vm: ssh timed out (120 s): ${1:0:80}" >&2; return $rc; }
cleanup() { vm 'pkill -f "[s]ticklinkd run" || true; sudo pkill -f "[s]l1-uhid-kvm" || true; pkill -f "^sleep 300$" || true' || true; }
trap cleanup EXIT
log() { echo "[$(date +%T)] $*"; }
# kit to the stick VM
vm 'rm -rf $U && mkdir -p $U'; tar cf - -C "$KIT" . | vm 'tar xf - -C $U'
# stick VM: fixture stick identity (stdin copies into a 0700 dir; nothing printed)
vm 'sudo rm -rf $R && mkdir -m 700 $R && head -c 32 /dev/urandom > $R/regkey && chmod 600 $R/regkey'
for f in pairing.json stick.id.json stack.json; do vm "umask 077; cat > \$R/$f" < "$STATE/$f"; done
vm 'sticklinkd import-e2e $K --pairing $R/pairing.json --identity $R/stick.id.json >/dev/null && rm -f $R/pairing.json $R/stick.id.json'
# host-sim state = this stick: stick_static.key (hex, 0600) from the registry; home (not secret) to stdout
HOME_HEX=$(vm 'mkdir -m 700 $R/usb $R/usb/stick-state && cd $R/usb && PYTHONPATH=/usr/local/lib python3 -c "
import os,sys; from pathlib import Path; from sticklink import registry; from sticklink.util import unb64u
reg=registry.Registry(Path(\"$R/sticklink\"), Path(\"$R/regkey\").read_bytes()); os.umask(0o077)
Path(\"stick-state/stick_static.key\").write_text(reg.static_priv().hex()+chr(10)); print(unb64u(reg.load_signal()[\"home\"],16).hex())"')
log "stick home (fixture) ${HOME_HEX:0:8}…"
# uhid: test-only udev rule so the (non-root) stick side may open the virtual KVM's hidraw node
vm 'sudo modprobe uhid && sudo modprobe hid-generic 2>/dev/null; printf "%s\n" "# TEST-ONLY (sticklink USB pairing test): virtual AI KVM made by sl1-uhid-kvm over uhid" "SUBSYSTEM==\"hidraw\", KERNELS==\"0003:303A:4012.*\", OWNER=\"tester\", MODE=\"0600\"" | sudo tee /etc/udev/rules.d/99-sl1-uhid-test.rules >/dev/null && sudo udevadm control --reload'
# launched fully detached (no fd may stay tied to the ssh session, or ssh waits for it)
# (only the setsid is backgrounded: backgrounding the whole && list leaves a subshell holding the ssh fds)
vm 'cd $R/usb && mkfifo kin && { setsid bash -c "sleep 300 > kin & sudo $U/sl1-uhid-kvm --uhid --state $R/usb/kvm-state --open --auto-accept < kin > kvm.log 2>&1" < /dev/null > /dev/null 2>&1 & }'
HR=$(vm 'for i in $(seq 50); do for d in /sys/class/hidraw/hidraw*; do grep -qs "HID_ID=0003:0000303A:00004012" $d/device/uevent && { echo /dev/$(basename $d); exit 0; }; done; sleep 0.1; done; exit 1') \
  || { echo "FAIL usb-uhid: no hidraw node for 303A:4012"; vm 'sudo cat $R/usb/kvm.log' | tail -5; exit 1; }
sleep 0.5; log "uhid device $HR: $(vm "ls -l $HR | cut -d' ' -f1,3,4")"
if vm "cd \$R/usb && S=\$(date +%s%N) && PYTHONPATH=\$U/py python3 \$U/sl1_host_sim.py --hidraw $HR --state \$R/usb/stick-state --auto-accept --home $HOME_HEX > host.log 2>&1; rc=\$?; echo WALL_MS=\$(( (\$(date +%s%N)-S)/1000000 )) >> host.log; exit \$rc"; then
  vm 'cat $R/usb/host.log' > "$W/host.log"; vm 'sudo cat $R/usb/kvm.log' > "$W/kvm.log"
  echo "PASS usb-pair (uhid, hidraw as tester via udev rule): XX msg1 $(grep -oP '^\[\K[0-9:.]+(?=\] XX msg1 sent)' "$W/host.log") -> PAIRED $(grep -oP '^\[\K[0-9:.]+(?=\] PAIRED)' "$W/host.log"), wall $(grep -oP 'WALL_MS=\K[0-9]+' "$W/host.log") ms incl. python start; code $(grep -oP 'CODE  >>> \K[0-9]+' "$W/host.log") = KVM $(grep -oP 'SHOW_CODE  >>> \K[0-9]+' "$W/kvm.log")"
else vm 'tail -5 $R/usb/host.log; sudo tail -5 $R/usb/kvm.log'; echo "FAIL usb-pair (uhid)"; exit 1; fi
vm 'umask 077; sudo cat $R/usb/kvm-state/paired.json' > "$W/paired.json"
if OUT=$(vm 'sticklinkd import-usb $K --record $(ls $R/usb/stick-state/kvm-*.json)' 2>&1); then echo "PASS import-usb: $OUT"; else echo "FAIL import-usb: $OUT"; exit 1; fi
vm 'sticklinkd list $K' | sed 's/^/  list: /'
export SL1_LIB="$KIT/libsl1pair.so"
for MODE in ${SL_MODES:-direct kvm-force-relay stick-force-relay udp-blocked-fallback}; do
  SARGS=""; KARGS=(); EXP=direct
  case $MODE in kvm-force-relay) KARGS=(--force-relay); EXP=derp;; stick-force-relay) SARGS=--force-relay; EXP=derp;; udp-blocked-fallback) KARGS=(--block-udp-rx); EXP=derp;; esac
  vm "nohup sticklinkd run \$K --stack \$R/stack.json $SARGS > \$R/stick-usb-$MODE.log 2>&1 < /dev/null &"; sleep 4
  S=$(date +%s%N); set +e
  timeout 90 python3 "$KIT/kvm-sim/sl1_kvm_sim.py" --stack "$STACK" --pairing "$W/paired.json" --id '' --pings 20 -v "${KARGS[@]}" > "$W/kvm-$MODE.log" 2>&1; RC=$?
  set -e; MS=$(( ($(date +%s%N)-S)/1000000 ))
  vm 'pkill -f "[s]ticklinkd run" || true; sleep 1'; vm "cat \$R/stick-usb-$MODE.log" > "$W/stick-usb-$MODE.log" || true
  RES=$(grep '^RESULT\|RESULT path' "$W/kvm-$MODE.log" | tail -1 | cut -c1-300 || true)
  if [ $RC = 0 ] && grep -qi "path=$EXP" <<<"$RES"; then echo "PASS usb-connect $MODE (${MS} ms total): $RES"
  else echo "FAIL usb-connect $MODE rc=$RC (want path=$EXP): ${RES:-$(tail -3 "$W/kvm-$MODE.log" | tr '\n' ' ' | cut -c1-300)}"; FAIL=1; fi
done
if grep -qiE '"pair_psk"|static_priv|dev_secret|auth_seed' "$W"/*.log; then echo "FAIL secret-looking field in logs"; FAIL=1; else echo "PASS no secrets in logs"; fi
echo "logs: $W"; exit $FAIL
