# Hardware boot checklist (after QEMU PASS)

QEMU with user-net hostfwd proves **guest userspace network + gateway bind on :80**.
It does **not** prove real NIC drivers, Wi‑Fi association, or NVIDIA GPU load.

## Before flash

1. `out/ISO-READY.txt` must contain `SCREENSHOT_PROOF=PASS` (and hostfwd/UI proof lines as applicable).
2. Listed `SCREENSHOT_PATH` / `SCREENSHOT_PATHS` PNG files must exist and have been reviewed.
3. If `out/ISO-NOT-READY.txt` exists → do not flash.
4. Flash a spare stick only. Never overwrite Drive golden / Samsung shipping v0.2 with a different digest under the same name.

## On real hardware

### Term / Server

1. HDMI shows network loading until a LAN IP exists, then **READY** + pair + URL.
2. From another device: open `http://IP/` and `/api/health`.
3. `nvidia-persistenced` must not dominate as a fatal FAILED (optional daemon).

### Local (checkpoint ISO)

1. Cage + Chromium paints the chat UI on the **NVIDIA** monitor.
2. USB keyboard types in the kiosk (DRM + libinput).
3. Screenshot / eyeball proof beats serial breadcrumbs.

## In-guest proof (tty2 / SSH)

```bash
nmcli -t -f DEVICE,TYPE,STATE device
ip -4 -o addr show scope global
ss -lntp | grep -E ':80\b'
curl -fsS http://127.0.0.1/api/health
curl -fsS "http://$(hostname -I | awk '{print $1}')/api/health"
```

## Not covered by QEMU

- Real Ethernet/Wi‑Fi PHY drivers and DHCP on your LAN
- NVIDIA modules, CUDA, llama VRAM load
- Local DRM + keyboard on real HDMI
- Phone browser UX on real Wi‑Fi
