# Lab: browser ↔ aiortc Method C against local wrangler

Isolated E2E only. Does not deploy or touch live Cloudflare / relay.

**Lab bypass:** skips native VT approval and `approve_local` — see `LAB-BYPASS.md`.

```powershell
cd sticklink-server\lab-browser-e2e
$env:SL_PORT_WORKER='8800'; $env:SL_PORT_HTTP='8770'
python run_e2e.py          # Method C + Noise + pair_psk/confirm + chat cancel + revoke (local wrangler)
python run_negatives.py    # wrong_pin, wrong_psk, tamper, revoked reconnect

# Live signalling (lab stick provision; no wrangler):
$env:SL_LAB_PROV='C:\Users\peter\sticklink-secrets\lab-stick-prov'
$env:SL_WS='wss://link.stickllm.com/v1/ws'
$env:SL_PORT_HTTP='8782'
python run_e2e_live.py
```

Requires: Node worker deps, Python `aiortc`, `websockets`, `playwright` + Chromium, `npm` packages under this folder (`@noble/*`). Live run also needs the offline lab stick provision dir.
