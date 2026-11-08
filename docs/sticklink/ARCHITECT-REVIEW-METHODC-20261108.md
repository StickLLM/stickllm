# Architect review — StickLink Method C (LTE accepted)

**Date:** 2026-11-08  
**Audience:** StickLLM architect  
**Author context:** End-of-job preserve + v0.7.2 test ISO bake after iPhone LTE acceptance  
**Branch:** `feature/sticklink-browser-lab`  
**Status:** Method C phone path accepted on real LTE; shipping ISO tag `v0.7.2` **not** cut yet

---

## 1. Executive summary

StickLink **Method C only** (rendezvous → WebRTC → Noise → Agent Zero over DataChannel) passed **real iPhone LTE** acceptance with multiple Agent Zero chat exchanges.

The known-good tree is **committed, tagged, and pushed**. A clean **v0.7.2 test ISO** bake is in progress for boot + flash + stick e2e. Morning’s pre-Method-C `StickLLM-v0.7.2.iso` was parked, not deleted.

**Ask of architect:** confirm this path is the product enrolment direction for cellular Agent Zero; confirm whether `RELEASE-0.7.2.md` should be rewritten to include Method C (it currently still lists Method C as “not in this ship”); confirm LAN/desktop pairing breakage (ISS-033 class) remains deferred.

---

## 2. Architecture (locked path)

```text
iPhone (LTE)
  → Cloudflare trycloudflare URL  [JOIN PAGE + static SW assets ONLY]
  → wss://link.stickllm.com/v1/ws  [rendezvous / pair.open → sl1: QR]
  → WebRTC + Noise (IKpsk2 / pair_psk)  [lab ICE measured direct; TURN/DERP browser fallback not claimed without evidence]
  → DataChannel app-mux v1
       • HTTP tunnel (gzip x-sticklink-ce, concurrency 8)
       • WS constructor patch → Socket.IO over DC
  → Agent Zero on stick/lab peer
```

### Hard invariants

| Rule | Status |
|------|--------|
| Cloudflare never proxies Agent Zero traffic | Enforced: bootstrap HTTP returns `404 a0_via_sticklink_dc_only` for `/agent-zero`, `/api/csrf*`, `/public/*`, etc. |
| Method C only — no alternate connection methods added | Held through LTE accept |
| Static assets cacheable; authenticated API not cached | Lab verified: static HIT/HIT; API MISS/MISS |
| Stick Devices & Pairing shows StickLink join QR | Gateway `/api/pair/sticklink-join` + remint `/api/pair/sticklink-join-refresh` |

### Split of responsibility

| Layer | Lives where | Notes |
|-------|-------------|--------|
| Join HTML, SW, mux, perf HUD | Lab phone-join host (`lab-browser-e2e`, CF tunnel) | Build id `methodc-lte-accept-20261108.1` |
| `pair.open` / mailbox / WebRTC answer / Noise / A0 bridge | Lab `kiosk_agent_session` + `app_mux_bridge` (today) | Phase 2 target: peer on stick `sticklinkd` (out of Phase 1 scope per APP-MUX-V1) |
| QR publish + remint API | Stick overlay gateway + `stickllm-sticklink-join-publish` | What the **ISO** must carry for kiosk UX |
| Signalling | `link.stickllm.com` | Homes / pair; not baked into ISO |
| DERP (native StickLink clients) | `relay-tor1.stickllm.com` | derper relay path — distinct from Method C browser ICE |
| Lab browser ICE | STUN (+ optional elixir TURN fetch) | Measured accept gate: **direct**; no TURN-saved claim |

---

## 3. Known-good preserve (immutable rollback)

| Field | Value |
|-------|--------|
| Join build id | `methodc-lte-accept-20261108.1` |
| Git tag | `methodc-lte-accept-20261108.1` (**pushed** to github) |
| Commit | `860ea3ccd6ed1b5bee6c587317eba1435420f646` |
| Prior tip | `412113d` (Devices & Pairing QR for v0.7.2 WIP) |
| Rollback doc | `docs/sticklink/METHODC-LTE-ACCEPT-KNOWN-GOOD.md` |
| Lab file snapshot | `sticklink-server/lab-browser-e2e/_rollback_baseline_20261108/` |

```text
git fetch github tag methodc-lte-accept-20261108.1
git switch --detach methodc-lte-accept-20261108.1
```

Do **not** force-move this tag. Shipping tag `v0.7.2` is separate and waits for HW confirm after flash/e2e.

---

## 4. Acceptance evidence

### 4.1 Operator (authoritative)

- **iPhone over LTE:** PASS (operator statement) — multiple Agent Zero chat exchanges.
- Phone ICE type on LTE: recorded as operator-pass; lab ICE instrumentation was LAN **direct** only.

### 4.2 Lab browser gate (pre-handoff, not a substitute for phone)

Frozen build `methodc-lte-accept-20261108.1`:

| Metric | Result |
|--------|--------|
| ICE (lab) | **direct** (`prflx` / `host`, udp) |
| Cold → chat interactive | ~**6965 ms** |
| Warm reload → interactive | ~**7 ms** |
| Static cache | HIT / HIT |
| Auth API cache | MISS / MISS |
| Send button | PASS (`BUTTON_OK`) |
| Enter + search | PASS (search + answer in rendered UI) |
| Send again after response | **FAIL** in automation timeout (`AGAIN_OK` not observed) — operator LTE chats still succeeded |

### 4.3 Known non-blockers / noise

- Agent Zero `syncStore` `NO_HANDLERS` / handshake retries in console (chat path still worked).
- Occasional `ERR_ABORTED` on plugin discovery thumbs / poll during load.
- `/lab/ready` is **503 until peer session** exists (`http_proxy_a0: false`) — expected pre-pair.
- APP-MUX-V1.md still says “at most **4** concurrent HTTP streams”; implementation uses **8** (`HTTP_MAX` / `asyncio.Semaphore(8)`). Doc should be updated to match ship intent.

---

## 5. Performance posture (LTE-oriented)

Bottleneck addressed on DC path (not by proxying A0 through CF):

- **Gzip** on mux responses (`x-sticklink-ce: gzip`)
- **Concurrency 8** on client + bridge
- **SW static cache** `sticklink-a0-static-v1`
- Visible **perf HUD** on join page (cold/warm, request count, bytes, interactive mark)

Lab cold load still ~215 HTTP ops / ~4.3 MiB uncompressed over DC with p95 ~338 ms after optimizations. Further wins are incremental; architecture does not need a second transport.

---

## 6. Release / ISO posture (in flight)

| Item | State |
|------|--------|
| Default bake version | `0.7.2` → `out/v0.7.2/StickLLM-v0.7.2.iso` |
| Morning pre-Method-C ISO | Parked: `StickLLM-v0.7.2-pre-methodc-20261108am.iso` (hash `5a6d09df…`) |
| New Method-C bake | **In progress** (live-build); not flashable until complete |
| Checksum in git | Old `checksums/v0.7.2.sha256` left **untracked/stale** until new bake finishes — do not treat as Method-C ship hash |
| Tag `v0.7.2` | **Not created** — wait for boot + stick e2e confirm |
| Flash | Deferred until Samsung USB inserted after bake |

### What the ISO must prove on stick e2e

1. Boot / kiosk READY  
2. Devices & Pairing shows StickLink join QR (publish + remint)  
3. Phone LTE: scan → Method C → Agent Zero chat (same path as accepted lab build)  
4. Confirm CF still join-only (no A0 over CF)

Lab Method C browser assets remain on the **lab join host** for this phase; stick carries gateway/UI/publish. Architect should treat “peer on stick” as Phase 2, not this bake’s success criterion.

---

## 7. Open product / architecture decisions

1. **Release note drift:** `docs/sticklink/RELEASE-0.7.2.md` still says Method C `sl1:` is *not* in this ship and “needs native VT approval.” Operator LTE accept used Method C via Devices & Pairing QR. Decide: update 0.7.2 scope to “Method C lab enrolment via StickLink QR” vs hold Method C as lab-only until VT-native.
2. **LAN / desktop Agent Zero pairing** remains broken after phone-join work — deferred; do not block Method C cellular ship if architect still agrees.
3. **Mailbox TTL ~60s** (server clamp) — UX: remint/refresh required; confirm acceptable for product QR.
4. **Doc sync:** raise APP-MUX concurrency note from 4 → 8 (or revert code — not recommended after LTE accept).
5. **Phase 2:** move Noise/WebRTC peer + app-mux bridge from lab PC onto stick `sticklinkd` without changing the phone wire protocol.

---

## 8. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Bake finishes with hash ≠ parked morning ISO; accidental publish of wrong checksum | Med | Only commit `checksums/v0.7.2.sha256` after Method-C bake + HW confirm |
| Lab join host required for phone session (not yet on-stick peer) | Med | Documented Phase 1; stick e2e still needs lab publisher for QR |
| `syncStore` errors confuse support | Low | Non-fatal today; track as A0 embed hygiene |
| Short mailbox TTL causes “QR dead” reports | Med | Remint API + UI refresh already wired |

---

## 9. Recommended architect actions

1. **Approve** Method C LTE path as the cellular Agent Zero enrolment architecture for this line.  
2. **Clarify** v0.7.2 release text: Method C in / out / lab-only.  
3. **Defer** LAN pairing fix explicitly (ISS note).  
4. **Hold** `v0.7.2` git tag until flash + stick e2e PASS.  
5. **Keep** `methodc-lte-accept-20261108.1` as permanent rollback for this accept tree.

---

## 10. Pointers

| Doc / artifact | Path |
|----------------|------|
| Known-good + rollback | `docs/sticklink/METHODC-LTE-ACCEPT-KNOWN-GOOD.md` |
| App-mux v1 | `docs/sticklink/APP-MUX-V1.md` |
| Release draft (stale vs accept) | `docs/sticklink/RELEASE-0.7.2.md` |
| Lab LTE report JSON | `sticklink-server/lab-browser-e2e/state/logs/lte-acceptance-report.json` |
| Handoff notes | `sticklink-server/lab-browser-e2e/state/logs/LTE-ACCEPT-HANDOFF.md` |
| Preserve commit | `860ea3ccd6ed1b5bee6c587317eba1435420f646` |
| Preserve tag | `methodc-lte-accept-20261108.1` |
