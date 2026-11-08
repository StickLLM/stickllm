# StickLink browser lab (`feature/sticklink-browser-lab`)

Local / isolated VM work only. **No push, merge, deploy, spend, or real-stick
changes** without a separate approval.

## Scope locked in

| Topic | Decision |
|---|---|
| Signalling host | Keep Cloudflare Workers design; do not start Go/SQLite rewrite |
| CA metadata residency | **Not required** (control plane may live on CF; see CF-CANADIAN-RESIDENCY.md) |
| Canadian relay | Stay on `relay-tor1.stickllm.com`; preserve portability to move signalling later |
| Deploy / live | Still gated — see DEPLOY-PREP.md for missing auth |
| Enrolment | Method C (QR) lab; shipping uses native VT overlay |
| Lab approval bypass | Browser/aiortc harness skips `approve_local` + native overlay — see `sticklink-server/lab-browser-e2e/LAB-BYPASS.md` |
| SPAKE2 | Disabled (`FEATURE_SPAKE2_CODE=0`) |
| Base | Current StickLLM `main` (`f244eb4`) |
| Pairing source | Inventory sticklink (newer than `feature/sticklink-pairing`); original branch preserved |

## Layout

- `overlay/usr/local/lib/sticklink/` — ported stick + Method C (`pair_qr.py`, `pair_qr_lab.py`)
- `overlay/usr/local/bin/sticklinkd` — daemon CLI
- `overlay/usr/local/bin/stickllm-pair` — **unchanged** legacy LAN pair from main
- `overlay/usr/local/bin/stickllm-pair-sticklink` — inventory sticklink pair CLI (not wired to shipping)
- `sticklink-server/` — vendored Worker + vectors for `wrangler dev --local` only
- `ui/sticklink-lab/pair-c.html` — browser QR parse stub
- `overlay/usr/local/lib/sticklink/webrtc_lab.py` — Noise-over-DataChannel framing + loopback (aiortc optional; not installed on this host yet)
- `docs/sticklink/CF-CANADIAN-RESIDENCY.md` — residency gaps before CF deploy
- `docs/sticklink/LAB-INVENTORY-20261107.md` — read-only live inventory notes

## Tests (host)

```powershell
cd C:\Users\peter\stickllm-sticklink-wt
$env:STICKLINK_TESTING=1; $env:STICKLINK_FAST_KDF=1; $env:STICKLINK_LAB=1
python -m pytest tests/sticklink/test_pair_qr.py tests/sticklink/test_webrtc_lab.py tests/sticklink/test_noise.py tests/sticklink/test_sigcrypto.py -q
```


## Shipping pairing policy (2026-11-07)

| Path | Status |
|---|---|
| Legacy LAN `stickllm-pair` | **Keep** until Method C + native VT + `sticklinkd` is HW-validated shipping default |
| StickLink Method C (QR) | Lab-proven; wire to live `link.stickllm.com` next; shipping UI still needs native VT |
| `stickllm-pair-sticklink` | Inventory CLI only — not shipping |
| SPAKE2 / Method D | **Off** (`FEATURE_SPAKE2_CODE=0`) |

Production stick endpoints (overlay): `overlay/etc/sticklink/sticklinkd.json` → `wss://link.stickllm.com/v1/ws`, DERP `https://relay-tor1.stickllm.com/derp`, pinned `sign_keys` kid `prod-1`. Lab/QEMU keeps explicit `--ws`/`--derp` or DEFAULTS at `10.0.2.2`.

## Still gated

- Push / merge to `main`
- Real USB stick flash / shipping ISO / replacing LAN pair as default
- Production native approval overlay (lab harness bypasses it — LAB-BYPASS.md)
- DNS Zone Edit token (optional polish only; custom domain already attached)
- SPAKE2 enable
- This PC still has no `sticklink_relay` SSH key (Sticklink operator runs relay cmds)
