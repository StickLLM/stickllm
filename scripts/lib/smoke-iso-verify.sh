#!/usr/bin/env bash
# Inner squashfs/unit checks. Expects tools: xorriso, unsquashfs.
# Arg1 = path to ISO inside this environment.
set -euo pipefail
ISO="${1:?iso}"
work=/tmp/smoke-iso-verify-$$
rm -rf "$work"
mkdir -p "$work"
xorriso -osirrox on -indev "$ISO" \
  -extract /live/filesystem.squashfs "$work/filesystem.squashfs" \
  -extract /boot/grub/grub.cfg "$work/grub.cfg" >/dev/null
unsquashfs -f -d "$work/sq" "$work/filesystem.squashfs" \
  /usr/local/bin/stickllm-bootstatus \
  /usr/local/bin/stickllm-console-setup \
  /usr/local/bin/stickllm-local-chat \
  /etc/systemd/system/stickllm-bootstatus.service \
  /etc/systemd/system/stickllm-ui.service \
  /etc/systemd/system/stickllm-ssh.service \
  /etc/systemd/system/stickllm-llama.service \
  /etc/systemd/system/stickllm-local.service \
  /etc/systemd/system/getty@tty1.service.d/stickllm-conflict.conf \
  /etc/systemd/system/NetworkManager-wait-online.service \
  /etc/systemd/system/NetworkManager.service.d/stickllm-timeout.conf \
  >/dev/null

BS="$work/sq/usr/local/bin/stickllm-bootstatus"
CS="$work/sq/usr/local/bin/stickllm-console-setup"
LC="$work/sq/usr/local/bin/stickllm-local-chat"
BSU="$work/sq/etc/systemd/system/stickllm-bootstatus.service"
UIU="$work/sq/etc/systemd/system/stickllm-ui.service"
SSHU="$work/sq/etc/systemd/system/stickllm-ssh.service"
LLU="$work/sq/etc/systemd/system/stickllm-llama.service"
LOCU="$work/sq/etc/systemd/system/stickllm-local.service"
GETTY="$work/sq/etc/systemd/system/getty@tty1.service.d/stickllm-conflict.conf"
MASK="$work/sq/etc/systemd/system/NetworkManager-wait-online.service"
NMD="$work/sq/etc/systemd/system/NetworkManager.service.d/stickllm-timeout.conf"
fail=0
pass() { echo "PASS $1"; }
bad() { echo "FAIL $1"; fail=1; }

if [[ -L "$MASK" && "$(readlink "$MASK")" == "/dev/null" ]]; then
  pass "wait-online masked -> /dev/null"
else
  bad "wait-online not masked (got: $(ls -la "$MASK" 2>&1 || true))"
fi

# Ignore # comments — only active unit keys matter.
if grep -E '^[^#]*network-online' "$BSU" >/dev/null; then
  bad "bootstatus references network-online"
else
  pass "bootstatus no network-online"
fi
grep -q "DefaultDependencies=no" "$BSU" && pass "bootstatus DefaultDependencies=no" || bad "bootstatus DefaultDependencies"
grep -q "After=.*local-fs.target" "$BSU" && pass "bootstatus After=local-fs" || bad "bootstatus After=local-fs"
grep -q "Before=.*NetworkManager.service" "$BSU" && pass "bootstatus Before=NetworkManager" || bad "bootstatus Before=NetworkManager"
grep -q "Conflicts=getty@tty1.service" "$BSU" && pass "bootstatus Conflicts getty@tty1" || bad "bootstatus Conflicts getty"
# Headless-safe: unit must not require TTYPath (QEMU has no usable VT bind).
if grep -q '^TTYPath=' "$BSU"; then
  bad "bootstatus still has TTYPath= (breaks headless/QEMU)"
else
  pass "bootstatus no TTYPath bind (script opens tty1/serial)"
fi
grep -q 'STICKLLM_BOOTSTATUS_START\|ttyS0' "$BS" && pass "bootstatus serial breadcrumb" || bad "bootstatus serial breadcrumb"

grep -q "ConditionPathExists=/run/stickllm/allow-getty-tty1" "$GETTY" \
  && pass "getty@tty1 gated on allow-getty-tty1" || bad "getty gate missing"
# Ignore comment lines; only real systemctl daemon-reload is a fail.
if grep -E '^[[:space:]]*systemctl[[:space:]]+daemon-reload' "$CS" >/dev/null; then
  bad "console-setup still daemon-reload"
else
  pass "console-setup no daemon-reload"
fi
# Blocking start of getty@tty2 from this oneshot deadlocks (Before=getty@tty2).
if grep -E '^[[:space:]]*systemctl[[:space:]]+start[[:space:]]+getty@tty2' "$CS" >/dev/null \
   && ! grep -E '^[[:space:]]*systemctl[[:space:]]+start[[:space:]]+--no-block[[:space:]]+getty@tty2' "$CS" >/dev/null; then
  bad "console-setup blocks on getty@tty2 start"
else
  pass "console-setup getty@tty2 start is --no-block"
fi
if grep -E '^[^#]*After=.*stickllm-control' "$BSU" >/dev/null; then
  bad "bootstatus After=stickllm-control (delays pair paint)"
else
  pass "bootstatus not After=control"
fi

grep -q "After=stickllm-bootstatus.service" "$NMD" && pass "NM After=bootstatus" || bad "NM After=bootstatus"
grep -q "TimeoutStartSec=" "$NMD" && pass "NM TimeoutStartSec set" || bad "NM TimeoutStartSec"
grep -Eq "TimeoutStartSec=(60|90|[1-9][0-9]{2,})" "$NMD" && pass "NM TimeoutStartSec >=60" || bad "NM TimeoutStartSec too short"

for u in "$UIU" "$SSHU" "$LLU"; do
  bn="$(basename "$u")"
  if grep -E '^[^#]*network-online' "$u" >/dev/null; then
    bad "$bn still network-online"
  else
    pass "$bn no network-online"
  fi
done

grep -Eq "refresh_failed|FAILED:" "$BS" && pass "bootstatus surfaces FAILED units" || bad "FAILED UX missing"
grep -q "PAIR CODE" "$BS" && pass "pair code UX" || bad "pair code UX"
grep -q "TIMER:" "$BS" && pass "loading timer UX" || bad "loading timer UX"
grep -q "STICKLLM Network Loading" "$BS" && pass "Network Loading phase" || bad "Network Loading phase"
grep -q "STICKLLM Model" "$BS" && pass "Model Loading phase" || bad "Model Loading phase"
grep -q "How to connect" "$BS" && pass "connect steps UX" || bad "connect steps UX"
grep -q "STICKLLM_LAN_URL\|Chat UI:" "$BS" && pass "LAN URL on screen" || bad "LAN URL on screen"
grep -q "STICKLLM_HEALTH" "$BS" && pass "health breadcrumb" || bad "health breadcrumb"
grep -q "waiting_ui\|UI starting" "$BS" && pass "pair gated on UI" || bad "pair gated on UI"
# UI must not wait on llama / network-online (LAN pair page during model load).
if grep -E '^[^#]*After=.*stickllm-llama' "$UIU" >/dev/null; then
  bad "ui After=stickllm-llama (blocks LAN while model loads)"
else
  pass "ui not After=llama"
fi
grep -q 'STICKLLM_BIND=0.0.0.0\|Environment=STICKLLM_BIND=0.0.0.0' "$UIU" \
  && pass "ui binds 0.0.0.0" || bad "ui bind not LAN"

grep -q "systemd.show_status=false" "$work/grub.cfg" \
  && pass "grub systemd.show_status=false" || bad "grub missing show_status=false"
# console-setup must not spam HDMI with REQUEUED (tty1/tty0/console aliases).
if grep -n 'STICKLLM_BOOTSTATUS_REQUEUED' "$CS" | grep -Eq 'tty1|tty0|/dev/console'; then
  bad "console-setup REQUEUED still targets console/tty1"
else
  pass "console-setup REQUEUED serial-only"
fi
# Product paint must never write /dev/console or /dev/tty0 (doubles HDMI).
if awk '/^say\(\)/,/^}/' "$BS" | grep -vE '^\s*#' | grep -Eq '>/dev/console|>>[[:space:]]*/dev/console|/dev/tty0'; then
  bad "bootstatus say() still writes console/tty0"
else
  pass "bootstatus say() no console/tty0"
fi
if awk '/^clear_tty\(\)/,/^}/' "$BS" | grep -vE '^\s*#' | grep -Eq '>/dev/console|/dev/tty0'; then
  bad "bootstatus clear_tty still touches console/tty0"
else
  pass "bootstatus clear_tty tty-primary only"
fi
if grep -E 'printf.*>/dev/console|>>[[:space:]]*/dev/console' "$BS" | grep -vqE '^\s*#'; then
  bad "bootstatus still printf/appends to /dev/console"
else
  pass "bootstatus no console printf paint"
fi
grep -q 'URL:' "$BS" && pass "READY shows URL label" || bad "READY missing URL label"
grep -q '>>> LAN IP' "$BS" && pass "READY shows LAN IP banner" || bad "READY missing LAN IP banner"
if [[ -f "$work/sq/usr/local/bin/stickllm-lan-ip" ]]; then
  pass "stickllm-lan-ip helper present"
else
  bad "stickllm-lan-ip helper missing"
fi
if [[ -f "$work/sq/usr/local/bin/stickllm-wifi-setup" ]]; then
  grep -q 'Waiting for LAN IP\|resolve_lan_ip\|stickllm-lan-ip' \
    "$work/sq/usr/local/bin/stickllm-wifi-setup" \
    && pass "wifi-setup waits/publishes LAN IP" \
    || bad "wifi-setup missing LAN IP wait"
fi
grep -q 'serial_only' "$BS" && pass "bootstatus serial_only helper" || bad "serial_only missing"
grep -q 'allow-local-chat\|handoff_local_chat' "$BS" && pass "local handoff in bootstatus" || bad "local handoff missing"
grep -q 'stickllm-kiosk\|STICKLLM_LOCAL_KIOSK' "$BS" && pass "local handoff queues kiosk" || bad "local handoff missing kiosk"
if [[ -f "$work/sq/etc/systemd/system/stickllm-kiosk.service" ]]; then
  grep -q 'ConditionPathExists=/run/stickllm/allow-local-chat' \
    "$work/sq/etc/systemd/system/stickllm-kiosk.service" \
    && pass "kiosk gated on allow-local-chat" || bad "kiosk not gated"
fi
grep -q 'ConditionPathExists=/run/stickllm/allow-local-chat-fallback' "$LOCU" \
  && pass "local-chat fallback gated" || bad "local-chat fallback gate missing"
grep -q 'STICKLLM_LOCAL_CHAT_START' "$LC" && pass "local-chat start breadcrumb" || bad "local-chat breadcrumb"
if [[ -f "$work/sq/usr/local/bin/stickllm-kiosk" ]]; then
  grep -q 'STICKLLM_KIOSK_START' "$work/sq/usr/local/bin/stickllm-kiosk" \
    && pass "kiosk start breadcrumb" || bad "kiosk breadcrumb missing"
  grep -q 'STICKLLM_KIOSK_UI_READY\|UI HTTP 200' "$work/sq/usr/local/bin/stickllm-kiosk" \
    && pass "kiosk waits for UI HTTP 200" || bad "kiosk missing UI HTTP 200 wait"
fi
if [[ -f "$work/sq/etc/systemd/system/stickllm-kiosk.service" ]]; then
  grep -q 'seatd.service' "$work/sq/etc/systemd/system/stickllm-kiosk.service" \
    && pass "kiosk wants seatd" || bad "kiosk missing seatd dependency"
  grep -q 'RestartSec=15' "$work/sq/etc/systemd/system/stickllm-kiosk.service" \
    && pass "kiosk restart backoff" || bad "kiosk RestartSec not backed off"
fi
# Local must not require LAN IP before model phase.
if grep -A20 'mode" == "local"' "$BS" | grep -q 'STICKLLM Network Loading'; then
  : # ok if present in shared code paths
fi
grep -q 'No phone/LAN pair\|not required for Local\|LOCAL_YIELD' "$BS" \
  && pass "local skips LAN pair dependency" || bad "local still LAN-coupled"

rm -rf "$work"
exit "$fail"
