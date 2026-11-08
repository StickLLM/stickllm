<!-- Copyright (c) 2026 Nink Inc. All rights reserved. -->
# Open questions and the decisions taken

Wherever PAIRING-SPEC v0.9 and SIGNALLING-PLAN were silent or ambiguous, the build takes the
**conservative** option (fail closed, reveal less, keep less). Each one can be changed. An item marked
**needs Nink** changes the security posture or needs agreement between teams.

## Spec gaps for the device teams (StickLLM and AI KVM)

| # | Question | Decision / proposal | Owner |
|---|---|---|---|
| Q-N1 | Prologue for the **network** IKpsk2 session. | **Decided by Nink, 2026-10-29 4:12 PM ET.** Fixed-length 96 B: `"sl1/net"(7) \|\| ver(1)=0x01 \|\| home_id(16) \|\| slot_id(8) \|\| initiator_static_pub(32) \|\| responder_static_pub(32)` (initiator = AI KVM/phone, responder = stick). Binds protocol label, version, home, slot and both authenticated device identities. Vectors `vectors/*-v2.json` (v1 withdrawn); any mismatch makes msg1 fail (vector + slpeer self-test). The server doesn't see it. | StickLLM + AI KVM must implement (see ENDPOINTS.md §8) |
| Q-N2 | `sig` box framing and AAD bytes: SIGNALLING-PLAN says "AAD = home\|slot\|direction" with no encoding. | Proposal: `nonce(12)\|\|ct\|\|tag(16)`, AAD `"sl1/box"\|\|home(16)\|\|slot(8)\|\|dir(1)`, with 0x01 for client→stick and 0x02 for stick→client. There's a vector. The server treats it as opaque. | StickLLM + AI KVM |
| Q-N3 | KVM receive buffer: the server allows `box` up to 3072 chars. | StickLLM keeps KVM-bound boxes ≤ 700 B (one inner message per box), so a 1 KB buffer is enough. The server won't enforce a per-peer cap unless asked. | StickLLM + AI KVM |
| Q-N4 | How the KVM learns `home_id`/`slot_id`. | USB 0x07 HOME_SLOT, per PAIRING-SPEC §4.B.5. The server never issues a `slot_id`: the stick picks it randomly, and the server checks it's unique and not revoked. `home_id` is issued at stick provisioning. | settled by spec |
| Q-N5 | SPAKE2 `code` mode (desktop). | **Decided by Nink, 2026-10-29 4:12 PM ET.** Stays **disabled** until it passes security review and testing. Implemented behind `FEATURE_SPAKE2_CODE`, off: `pair.open{m:"code"}` gives `err{disabled}`, and `?rid=` lookups give 404. | decided; enable only after review |
| Q-N6 | Two-slot USB pairing. | Deferred (§8b(c)). Nothing on the server. | deferred |
| Q-N7 | Datagram framing for Noise over UDP/DERP isn't in any spec. | **Adopted StickLLM's `link.py` layout** (already implemented and tested there; AI KVM had none): `0x01 INIT slot‖sidx‖msg1`, `0x02 RESP sidx‖ridx‖msg2`, `0x04 DATA ridx‖ctr(LE)‖ct` (nonce = ctr, 64-entry replay window), `0x05 PUNCH`; data `type‖body`. slpeer was switched to it, and the three implementations now interoperate (ENDPOINTS.md §2.3, §8). | proposal; AI KVM to implement |
| Q-N8 | `sid` in `cand`/`derp`: whose is it? | **Each sender owns its sid.** A receiver must not require the peer's sid to equal its own. The stick sends its `cand`+`derp` on `peer join`. Matches sticklinkd. | proposal |
| Q-N9 | Candidate `p` values: slpeer/sticklinkd send `host`/`stun4`, AI KVM sends `lan4`, ENDPOINTS said `lan4`. | **Canonical set = what `sticklinkd` sends:** `host`, `v6`, `stun4`, `stun6`, `cfg`. `p` is only a hint, so receivers try every candidate and ignore unknown values. `lan4` is dropped. | **AI KVM to change** `lan4` → `host` (`sl1_kvm_sim.py`, `test_framing.py`, `tests/test_net.c`, the `sl1_net.h` comment). StickLLM: no change. |
| Q-N10 | When to send `bye` after moving to DERP; what to do with the WSS. | No `bye` on a path change. `bye` = session over for good, sent only while the WSS is open (never reconnect for it). A client may close the WSS once it has the stick's `cand`+`derp` (the KVM does). Reconnect only for the permit refresh or to re-signal. `peer leave` ≠ session end, and each side relies on its own idle timeout. | Matches today's behaviour of all three implementations. Documented in API §4.1. |
| Q-N11 | Firmware notes from AI KVM: max datagram, INIT slot privacy, replay-window order. | ≤ 1280 B per datagram; the window commits only after the tag verifies (slpeer checked and self-tested); the clear-text INIT slot is accepted for now (a rotating tag is possible later). | accepted; revisit the slot tag before GA |

## Server decisions (Worker)

| # | Topic | Decision | Why |
|---|---|---|---|
| Q-S1 | Device server-auth | **Decided by Nink, 2026-10-29 4:12 PM ET.** Each device generates its own random **Ed25519 server-auth key**; D1 stores only the public key (`devices.ak`, the verifier). `hello` carries `sig` over the welcome nonce (API §2). `DEV_MASTER` and HMAC hellos are **removed**. Rotation: `auth.rotate` (signed by old session + PoP by new key); lost key: ops `devctl setak`. Noise private keys and pairing PSKs never reach the server. A master-key derivation scheme may be reconsidered only if its security and operational benefits are demonstrated. | Signatures beat a hashed bearer secret: the private key never leaves the device, and nothing the server, D1, a backup or a TLS terminator holds can be replayed to log in. Fits ESP32-P4 (libsodium/Monocypher, 32 B seed). |
| Q-S2 | Mailbox grace after expiry | `MBX_GRACE_S=0` | Strict 60 s, per spec. |
| Q-S3 | Bad QR join MACs | Count as failed lookups for the IP (100/h then a 1 h block), and drop the connection. They don't use up the invitation. | §4.6 says a bad MAC "isn't an attempt". Counting per IP still stops brute force. |
| Q-S4 | Relay entitlement | The device's own `cls` if it said `hello` and is entitled, otherwise the home owner's. 2 node keys per holder, 10 `relay.reg`/day. | The KVM pays for its own relay where it can, and phones ride on the stick. |
| Q-S5 | A node key claimed by a second holder | `err{auth}`, and the first holder keeps it. | Nobody can steal a key's allowlist slot. |
| Q-S6 | Revocation | **Decided by Nink, 2026-10-29 4:12 PM ET.** Relay admission is denied for revoked devices at once (allowlist delta + feed); **existing relay connections may persist** (derper can't drop them). The server pushes `rev{rc,slot,why}` to the stick **immediately** and closes the revoked device's WSS (4403). StickLLM must immediately reject new authenticated sessions from the revoked peer and terminate active sessions where possible (slpeer's stick role does this). | The peers' Noise pinning + the stick's kill stop the data; residual DERP use is accepted. |
| Q-S7 | Signing keys | One Ed25519 key (`SIGNING_KEY`, `kid`) for allowlist, permit and revoked set, with domain separation (`sl1/allowlist/v1`…). `/v1/keys` publishes it. | Fewer secrets. Domain tags stop cross-use (tested). Rotation: publish the new kid in admit-keys and firmware before switching. |
| Q-S8 | Allowlist paging | Not paged: a full doc is one JSON. | At about 100 B per key, 10k keys is ~1 MB. Revisit beyond that. |
| Q-S9 | Framework | Plain Workers + Durable Objects, no Hono, no Node entry point. | Smaller surface. |
| Q-S10 | IP data | The client IP is used only as `HMAC(IP_PEPPER, bucket)`, where the bucket is IPv4 or an IPv6 /64 (`src/ipbucket.ts`), to key a Limiter DO. Its counters lapse with their windows. The raw IP is never stored in D1, DO storage or logs. | Privacy, plus /64 bucketing so one subscriber can't rotate addresses past the brute-force limits. |
| Q-S11 | Pending slots that expire | **Revoked** (added to the revoked set, permits withdrawn), not just deleted. | A half-done pairing can't be revived later with the same id. |
| Q-S12 | Who may `slot.del` | **Decided by Nink, 2026-10-29 4:12 PM ET.** The stick and admin phones (slot `adm:1`). Every operation is authenticated, authorised and **recorded** in the D1 `audit` table (actor, op, target, result; no secrets), which the stick reads with `audit.get` (API §2.3). Denied attempts are recorded too. | A lost device can be removed while the stick is remote, with a trail. |
| Q-S13 | Two stick connections | The newest wins, and the old one gets 4009. | Reconnect after a network change shouldn't wait for the old socket to time out. |
| Q-S14 | Revoked set freshness | Signed pages carry the socket's `welcome` nonce, so a replayed page fails. | Stops a man in the middle from hiding new revocations. TLS already does that, but this is defence in depth. |
| Q-S15 | Feed | Every allowlist change pushes `chg{seq}`. There's no debounce. | Lowest revocation latency. Volume is tiny. |
| Q-S16 | Blocked IP | Gets **404** on `rid`/`mbx` lookups, the same as unknown. | No oracle. |
| Q-S17 | Upgrade rate limit | 429 + `retry-after`. | It reveals rate limiting, but not whether a mailbox exists, since the 429 is applied before any lookup. |
| Q-S18 | Change-log pruning | The hourly cron drops expired permits and trims `al_log`, keeping each region's newest row so `seq` never goes backwards. | The sidecar rejects a lower seq. |
| Q-S19 | Mailbox connection | Doesn't use up the invitation (settled). Up to 4 connections per mailbox. Joiners must `pair.join` within 5 s. | Per the settled decisions. |
| Q-S20 | Routing IDs | 4 digits, server-assigned, unique while live, a 10 min global hold after release, no reuse for 24 h for the same home. | Per spec §5. A smaller space means a shorter code, and rate limits carry the weight. |
| Q-S21 | Repeated local E2E runs hit `relay.reg` 10/day/holder (`err{rate}`). | Optional var `TEST_RELAY_REG_PER_DAY`, honoured **only** with a `test-` signing kid (so a stray var can't loosen production). The e2e stack sets 1000. Unit-tested. | Test-only. Remove it if Nink prefers no knob at all. |
| Q-S22 | An audit-row write fails (D1 error). | The operation (especially a revocation) is **never blocked or rolled back** by it; the write is retried once in `waitUntil` and the failure logged (no secrets). | Revocation must not fail open because logging failed. Gap risk is tiny and visible in logs. |
| Q-S23 | Audit retention | 365 days, pruned by the hourly cron. Rows hold no secrets or IPs: actor id, op, target id, result. | Long enough for disputes; bounded storage. Change `L.AUDIT_KEEP_S` if Nink wants otherwise. |

## Sidecar decisions (`sticklink-admit`)

| # | Decision | Why |
|---|---|---|
| Q-R1 | Freshness is measured on the **relay's local clock** from when a document was accepted, capped at min(`exp−iat`, 15 min). | Skew-proof: a wrong VPS clock can't make old data look fresh. |
| Q-R2 | A lower `seq` than held is rejected. | Rollback protection. **Ops consequence:** if D1 is ever reset, the sidecar state (`/var/lib/sticklink-admit`) must be cleared by hand. |
| Q-R3 | An empty delta refreshes freshness. | Otherwise a quiet relay would go stale every 15 min. |
| Q-R4 | Unknown key: at most one pull per 2 s, and a caller waits up to 3 s. | A just-registered key works on the first try, without letting attackers make the sidecar hammer the Worker. |
| Q-R5 | State is persisted (0600, atomic) and reloaded on restart, but **never with extra freshness**. | A restart within the TTL keeps serving. After that it fails closed. |
| Q-R6 | **Decided by Nink, 2026-10-29 4:12 PM ET.** Fail **closed for new admissions** after 15 min stale/unreachable (`{"Allow":false}`; derper `-verify-client-url-fail-open=false`); **existing sessions continue**. | A revoked key can't get in on stale data; accepted availability cost. |
| Q-R7 | `/healthz` gives 503 when stale. GET on `/derp/admit` gets 200 `{"Allow":false}`. | Monitoring signal. Nothing to learn by probing. |
| Q-R8 | Logs show counters only: no node keys, IPs or tokens (checked by `run.sh`). | Privacy. |
