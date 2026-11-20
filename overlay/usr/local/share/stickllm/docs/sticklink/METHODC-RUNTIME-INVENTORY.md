# Method C runtime inventory (Milestone A)

Evidence date: **2026-11-08**. Running stick probed at `192.168.72.50` (USB already flashed for LTE accept). Package list from `live-build/package-lists/stickllm.list.chroot`.

## Protocol freeze (do not change)

| Artifact | Value |
|----------|-------|
| Tag | `methodc-lte-accept-20261108.1` → commit `860ea3ccd6ed1b5bee6c587317eba1435420f646` |
| Join build id | `methodc-lte-accept-20261108.1` |
| Mux | `docs/sticklink/APP-MUX-V1.md` (gzip, HTTP_MAX/Semaphore **8**) |
| Lab reference tree | `sticklink-server/lab-browser-e2e/` (retained; not deleted) |

## Lab PC roles today (must leave the PC)

| Component | Path / process | Stick replacement |
|-----------|----------------|-------------------|
| Join static host | `run_phone_join_lab` + cloudflared → trycloudflare | Public HTTPS host (Worker/Pages); **not** lab PC; **not** A0 proxy |
| Method C peer | `kiosk_agent_session.py` (aiortc + Noise) | Stick runtime service |
| App-mux bridge | `app_mux_bridge.py` → stick LAN HTTPS | Same bridge → **localhost** A0 on stick |
| QR publisher | lab writes JSON → `stickllm-sticklink-join-publish` | Stick peer writes `/run/stickllm/sticklink-join.json` directly |
| Dev authorization | SSH `stickllm-sticklink-lab-grant` + `/api/pair/sticklink-lab` | Same grant class, **local** mint on stick (Milestone A only) |

## Already on stick image / live USB

| Item | Evidence |
|------|----------|
| `python3-cryptography` 38.0.4 | `dpkg` ii + import OK |
| `python3-nacl` 1.5.0 | `dpkg` ii + import OK |
| `python3-websockets` 10.4 | `dpkg` ii + import OK |
| `sticklink` library (`overlay/usr/local/lib/sticklink`) | present (`noise`, `pair_qr`, `crypto`, …) |
| `stickllm-sticklink-join-publish` | `/usr/local/bin/…` |
| `stickllm-sticklink-lab-grant` | on live USB (`GRANT_ON_STICK`); **not** yet in all ISO package paths — bake into next TEST image |
| Gateway StickLink join APIs | `/api/pair/sticklink-join`, remint, `sticklink-lab` |
| Agent Zero | `stickllm-agent.service` active (loopback UI) |
| StickLink apt pins in image list | `stickllm.list.chroot` lines 93–97 |

## Missing on stick (blockers for Milestone A peer)

| Item | Status | Notes |
|------|--------|-------|
| **`aiortc`** | **MISSING** (`ModuleNotFoundError`) | Lab peer depends on it for RTCPeerConnection |
| **`av`** (PyAV) | **MISSING** | Typical aiortc dependency |
| Native media libs for aiortc | Not inventoried in image yet | Expect `libavformat` / opus / vpx family via apt when wheels are baked |
| `python3-pip` | Not installed on live USB | Prefer **bake wheels in chroot** (same pattern as pinned attach requirements), not runtime pip |
| On-stick Method C peer unit | None | Need `stickllm-methodc-peer.service` (name TBD) |
| Public join host independent of lab PC | Lab trycloudflare only today | Milestone A requires Worker/Pages (or USB-local cloudflared **on the stick**, PC off) |

## Phone join assets (contract UI — host may move, bytes stay)

Under `sticklink-server/lab-browser-e2e/browser/`:

- `agent_join.html`, `agent_join_client.js`, `sticklink_app_mux.js`, `sticklink_asset_sw.js`, `a0_ws_bridge.js`, `sticklink_perf.js`, `noise_ikpsk2.js`, `a0_frame_boot.html`, …

Serve these from the public HTTPS join host. Do not change wire behavior.

## Milestone A package / bake checklist

Add to next **new** TEST ISO (name ≠ `v0.7.2`):

1. **Dedicated venv** `/opt/stickllm/methodc-venv` from `overlay/usr/local/lib/stickllm-methodc-requirements.txt`.  
   Do **not** pip-install into system site-packages: Debian `python3-cryptography` is **38.x**; aiortc 1.16 wants **≥44**.
2. Apt runtime libs for PyAV/aiortc (record exact `dpkg -l` after chroot): expect `ffmpeg`/`libav*`/`libopus`/`libsrtp` family as required by the pinned wheels.
3. Overlay already started: `sticklink/methodc_peer.py`, `sticklink/app_mux_bridge.py`, `stickllm-methodc-peer.service`.
4. `stickllm-sticklink-lab-grant` in overlay + `sudo -n` for the peer unit (isolated A auth).
5. Peer publishes join JSON to `/run/stickllm/` (no lab publisher).
6. Join static assets on public HTTPS host (`SL_JOIN_PUBLIC_BASE`); stick only emits `sl1:` + that URL.

### Scaffold status (2026-11-08)

| Piece | Status |
|-------|--------|
| `overlay/.../sticklink/methodc_peer.py` | Port of lab peer → localhost A0 + local grant |
| `overlay/.../sticklink/app_mux_bridge.py` | Stick copy; lab HTML injects are no-ops |
| `stickllm-methodc-peer.service` | Present; needs venv + `SL_JOIN_PUBLIC_BASE` |
| `stickllm-methodc-requirements.txt` | Pinned from LTE-accept lab PC |
| Public join host (Worker/Pages) | **Not deployed yet** — next incremental step |
| aiortc on live USB | **Missing** — needs venv bake or hotfix install |

## Milestone A proof checklist (PC offline)

- [ ] Lab / development PC powered off
- [ ] Fresh USB boot (TEST ISO under new version name)
- [ ] Devices & Pairing shows Method C QR from stick-published JSON
- [ ] iPhone LTE → chat over Method C
- [ ] CF/bootstrap A0 paths still `a0_via_sticklink_dc_only`
- [ ] `aiortc` import OK on stick; peer unit active; mux GETs on localhost A0
