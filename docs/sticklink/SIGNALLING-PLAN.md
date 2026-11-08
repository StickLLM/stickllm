# sticklink signalling server: build plan (for review)

Author: Grok Bot, 2026-10-29 (America/Toronto). **Status: plan only. Nothing here is built, deployed or committed.** Every deploy step below needs Nink's go-ahead at the time.
Inputs: DESIGN-NOTES.md, DESIGN-REVIEW.md, HOSTING-OPTIONS.md, RELAY-SETUP.md, `/workspace/sticklink-stick/` (netcheck + relay conf), `/workspace/sticklink/aikvm/lan_check.py`, Cloudflare DO pricing page (fetched 2026-10-29).

## Summary

- **What it is:** one small Hono (TypeScript) app at `wss://link.stickllm.com`. It introduces paired devices, passes their sealed connection offers back and forth, and issues relay permits. It never carries device traffic and never sees plaintext or the pinned keys.
- **Where it runs:** Cloudflare Workers plus one Durable Object (DO) per StickLLM "home". Small tables (devices, permits) live in D1. Free tier now, Workers Paid (US$5) at launch. The same code runs on Node/Bun with SQLite on a VPS. Moving off Cloudflare is a DNS change plus a data export.
- **Data path:** direct UDP first (IPv6, then IPv4 via STUN). Fallback is the live DERP relay `relay-tor1.stickllm.com`. Every path runs `Noise_IKpsk2_25519_ChaChaPoly_SHA256` with the peer key pinned at QR pairing. This is WireGuard's handshake with SHA-256 in place of BLAKE2s, which fits AI KVM's mbedTLS.
- **Relay access (option A):** a device registers a rotating relay node key over signalling. The Worker publishes an Ed25519-signed allowlist. A small Go sidecar on relay-tor1 replaces the deny-all stub on `127.0.0.1:9099` and answers derper's admission check. derper itself doesn't change.
- **Privacy:** offers, candidates and relay keys travel inside an envelope that only the paired peers can open. Signalling sees opaque ids, timing and connecting IPs. It keeps aggregate counters only.
- **Budget:** about 2,500 active sticks/day fit the free tier. DO requests are the binding limit, not GB-s. Launch cost is about US$8.50/month: Workers Paid plus the existing Luna Node m.1s.
- **First milestone:** AI KVM to StickLLM, end to end over relay-tor1, on Nink's LAN, with the relay path forced. Rough estimate: about 2 to 3 calendar weeks, with the server, StickLLM and AI KVM work running in parallel.

---

## 1. Components and responsibilities

| Component | Runs on | Does | Never does |
|---|---|---|---|
| **Hono app** (`sticklink/server`) | CF Worker, or Node/Bun on a VPS | Authenticates devices, routes `/v1/ws` to the right home, serves `/v1/relay/allowlist` to sidecars, `/healthz` | Store IPs, SDP, candidates or keys in clear; log per request |
| **Home DO** (one per StickLLM server device) | CF DO with Hibernatable WebSockets; in-memory `Map` on a VPS | Holds the stick's WS plus any client WS, verifies join MACs, forwards sealed `sig` blobs, tracks presence, stores pairing slots (SQLite, a few rows) | Decrypt anything, or wake on pings |
| **Directory** (D1 on CF, SQLite file on a VPS) | Shared | Device credentials (hashed), entitlements, live relay permits `{nk, exp, region}`, daily counters | Hold IPs or pairings |
| **Relay sidecar** `sticklink-admit` (Go, static binary) | relay-tor1, `127.0.0.1:9099/derp/admit` (same URL as today's stub) | Pulls the signed allowlist, verifies it against pinned Worker public keys, answers derper `{NodePublic, Source}` → `{Allow}`, keeps the last good list on disk | Call home for each connection; log keys or IPs |
| **StickLLM client** `sticklinkd` (Python) | The stick | Persistent WSS presence, pairing (shows the QR), direct UDP, DERP client (PyNaCl), WebRTC for browsers (aiortc), Noise responder | Trust anything the server or relay supplies |
| **AI KVM client** (C, ESP-IDF) | ESP32-P4 | Caller only: opens WSS on demand, then direct UDP or DERP via microlink, Noise initiator | Hold a persistent WSS (saves RAM, see §8) |
| **Phone/browser clients** | stickios, stickdroid, web | Join a home; browsers use WebRTC, with Noise inside the data channel | |

Why one DO per **home** rather than per pairing: the stick keeps one WebSocket, not one per paired device. Presence is local to the home. A home holds at most 16 pairing slots.

Why D1 for the directory: the relay allowlist is read every minute. Serving it from a DO would keep a single DO busy and burn GB-s. D1 has no duration billing and is plain SQLite, so it ports easily. Its limits match DO SQLite: 5M rows read and 100k rows written per day on the free tier.

## 2. Message protocol (v1)

Transport: `wss://link.stickllm.com/v1/ws`, subprotocol `sticklink.1`, UTF-8 JSON text frames. Every message has `t` (type). Requests carry `id`; replies echo it. Byte fields are base64url without padding. Unknown fields are ignored, and unknown `t` gets `err:unknown`.

**Connect and authenticate (server speaks first, so there is no replay):**
```json
S→C {"t":"welcome","v":1,"n":"<32B nonce>","now":1793270000}
C→S {"t":"hello","id":1,"dev":"<16B>","role":"client","sig":"<64B>"}      // stick: role "server" + "home":"<16B>"
    sig = Ed25519(auth_key, "sl1/dev-hello/v1" || 0x00 || n(32) || dev(16) || role(1) || home(16))
    // Updated 2026-10-29 4:12 PM ET (Nink): per-device Ed25519 server-auth key; the server stores only the public key.
          role byte 0x01 = server (stick), 0x02 = client; a client puts 16 zero bytes where home goes
S→C {"t":"ready","id":1,"v":1,"home":"<16B, stick only>","lim":{"frame":4096,"burst":20,"rate":1},
     "relays":[{"rg":"tor1","host":"relay-tor1.stickllm.com","stun":3478}],"now":1793270000}
```
*Update 2026-10-29 (reconciled with server/API.md §3.1, which is authoritative): `dev` is the raw 16-byte id in
base64url (no `kvm_` prefix). The MAC covers the role as one byte and always covers a 16-byte home (zeros for a
client), so every field is fixed-length. `caps` is **not** part of v1: it isn't MAC-covered, the server ignores it, and
clients should not send it (every v1 client must support both UDP and DERP). `ready` also returns `v`, `home` (stick),
`lim.rate` and `now`.*
A stick adds `"home":"<home id>"` with `role:"server"` and becomes that home's online endpoint. Phones and browsers have no device credential. They skip `hello` and authenticate with `join` (below), and the home's entitlement covers them.

**Pairing slots (stick only):**
```json
{"t":"slot.add","id":2,"slot":"<8B>","jk":"<32B join key>","exp":600}   // pending until first join
{"t":"slot.del","id":3,"slot":"<8B>"}                                    // revoke a paired device (stick or admin phone; audited)
S→stick {"t":"rev","rc":<n>,"slot":"<8B>","why":"del"|"exp"}             // pushed immediately on every revocation
```

**Join and presence:**
```json
C→S {"t":"join","id":2,"home":"<16B>","slot":"<8B>","mac":"<HMAC(jk,'sl1/join'|n|home|slot)>"}
S→C {"t":"joined","id":2,"conn":"c4","peer":"online"}     // or "offline"; no queueing in v1
S→stick {"t":"peer","conn":"c4","slot":"<8B>","state":"join"}   // later "leave"
```

**Offer, answer and candidate relay (opaque to the server):**
```json
C→S {"t":"sig","to":"stick","box":"<sealed>"}     S→stick {"t":"sig","from":"c4","box":"<sealed>"}
```
`box` = ChaCha20-Poly1305 under `env_k = HKDF-SHA256(ikm = P_slot, salt = empty, info = "sl1/env")`, with a 12-byte random nonce and AAD = `home|slot|direction`. *Update 2026-10-29 (PAIRING-SPEC v0.5 §4.6): `P_slot = HKDF-SHA256(ikm = pair_psk, salt = empty, info = "sl1/slot-secret")`, from the long-term pair PSK, not from a QR or pairing secret. The slot's join key is `jk = HKDF-SHA256(ikm = P_slot, salt = empty, info = "sl1/join")`.* Inside the box (the server can't read this):
```json
{"k":"cand","sid":"<session id>","seq":3,"c":[{"a":"[2001:db8::5]:41641","p":"v6"},{"a":"203.0.113.9:41641","p":"stun4"}]}
{"k":"derp","sid":"…","nk":"nodekey:<64 hex>","rg":"tor1"}
{"k":"offer"|"answer","sid":"…","sdp":"…"}       // WebRTC (browser) sessions only
{"k":"bye","sid":"…"}
```
Peers drop inner messages whose `sid`/`seq` they've already seen. *Update 2026-10-29 (server/API.md §4–4.1): `p` ∈
{`host`, `v6`, `stun4`, `stun6`, `cfg`}, and receivers ignore unknown values. `sid` belongs to the sender. `bye` means
the session is over for good: never send it on a path change, and send it only while the WSS is open.*

**Relay permits (option A):**
```json
C→S {"t":"relay.reg","id":5,"nk":"nodekey:<64 hex>","rg":"tor1"}
S→C {"t":"relay.ok","id":5,"exp":1793313200,"tok":"<≤512 B Ed25519-signed permit>"}
C→S {"t":"relay.del","id":6,"nk":"nodekey:…"}
```
The permit is `{v, kid, nk, rg, exp, cls}` plus a 64-byte signature, about 150 B in base64. The device stores it only so it knows when to refresh (at ⅔ of the TTL) and for future relays that might accept tokens directly. derper never sees it.

**Keepalive and errors:** use WebSocket **protocol** pings every 60 s. These aren't billed. As a fallback, `setWebSocketAutoResponse("ping","pong")`. `{"t":"err","id":n,"code":"rate|auth|size|offline|unknown","retry":30}`. Cloudflare drops sockets on runtime updates, so clients reconnect with jittered backoff (1 s up to 60 s).

**Limits (v1):** frame ≤ 4 KB, with AI KVM frames well under 1 KB. 20-message burst, 1 message/s sustained per socket. 16 slots per home, 8 concurrent clients per home. An unauthenticated socket is closed after 10 s.

## 3. Pairing via QR

> **Status (Nink, 2026-10-29 10:13 AM ET): QR pairing is on hold.** Nink isn't happy with the QR code idea because it doesn't cover all use cases, and wants to think about it further. Treat the QR design below as a draft only, not approved. See also §3a (USB pairing) and open decision 14.
>
> **Update 10:43 AM ET:** pairing is now specified in **PAIRING-SPEC.md (v0.2)**, which supersedes this section. It covers four methods: USB↔USB, AI KVM over USB with button approval, mobile QR (60 s), and desktop split code `RRRR-SSSSSS` with SPAKE2. Everything uses X25519 identities and Noise IKpsk2. The QR string format below is replaced by PAIRING-SPEC §4.C.

The stick shows the QR at "Add device":
```
sl1:H=<home 16B>&S=<slot 8B>&K=<stick Noise static pub 32B>&P=<pairing secret 32B>&E=<expiry>[&U=<signalling URL if not default>]
```
That's about 160 characters, a version 8 to 10 QR. The same string serves as a copy-paste code for devices without a camera. AI KVM gets it through its setup UI.

Bootstrap:
1. The stick generates `slot` and `P` and sends `slot.add` with `jk = HKDF(P,"sl1/join")` only. `P`, `env_k` and the Noise PSK never leave the two devices.
2. The client scans, opens WSS and `join`s with the MAC. The DO checks it against `jk`.
3. The peers swap sealed candidates and DERP keys, and pick a path (§ data path).
4. Noise `IKpsk2`: the client is the initiator and knows `K` from the QR. PSK = `HKDF(P,"sl1/psk")`. The stick pins the initiator's static key for that slot, and the client pins `K`. A first join after `E` (10 minutes) is refused.
5. On later sessions the stick rejects any initiator whose static key isn't the one pinned for the slot. Revoking = `slot.del` plus deleting the pin locally.
   *Update 2026-10-29 4:12 PM ET (Nink):* the network IKpsk2 prologue is fixed at 96 B: `"sl1/net" || ver 0x01 || home(16) || slot(8) || initiator_static_pub(32) || responder_static_pub(32)`, binding label, version, home, slot and both device identities (vectors v2). On a `rev` push the stick immediately rejects new sessions from the revoked peer and terminates its active session.

**What signalling learns:** the home id and that it belongs to a given stick device credential (billing needs this), the slot count, and join and leave times. It sees connecting IPs, because Cloudflare always does. It holds the relay node key ↔ device link only until the permit expires. **It does not learn:** either Noise key, the pairing secret, candidates (LAN, IPv6 and public addresses), SDP or DTLS fingerprints, device names, or anything the devices exchange. A fully compromised signalling server can deny service and see metadata. It can't pair or MITM, because that needs `P` and the pinned key.

**Data path order:** first the LAN or host candidates. Then IPv6 direct. Then IPv4 using the STUN-mapped address (the relay's STUN on 3478 or `stun.cloudflare.com`) with simultaneous sends. Start DERP **in parallel** after 1.5 s, switch to it if no direct path within 3 s, and keep probing direct to upgrade later. That's the Tailscale approach.

## 3a. USB pairing option for the Stick app (added at Nink's request, 2026-10-29)

Nink asked for this as a pairing option for the Stick app:

- The main StickLLM device boots from the **first USB slot**, the stick itself.
- A second USB key goes into the **second USB slot**.
- StickLLM writes the authentication material to that second USB key, which hard-links the two devices together.
- The pairing key **never travels over the network**. It moves only on the physical USB key.

How it fits the rest of this plan (draft, to confirm with Nink):
- The USB key would carry the same secrets the QR string carries today: home id, slot, the stick's Noise static public key and the pairing secret `P`. Signalling would still only ever see `jk = HKDF(P,"sl1/join")`, so nothing about the signalling server changes.
- Unlike the QR route, nothing secret is shown on screen or copied through a clipboard, chat or browser.
- Open questions: which devices read the USB key (AI KVM's ESP32-P4 board, phones, PCs), whether the key keeps the secret after pairing or is wiped, whether the key is encrypted or PIN-protected in case it's lost, and how re-pairing and revocation work if the key is lost.

## 4. Auth

**Devices to signalling:** *Update 2026-10-29 4:12 PM ET (Nink):* each StickLLM and AI KVM generates its own random **Ed25519 server-auth key** on the device; only the public key is registered (`devices.ak`, the verifier). Login is a signature over the server's nonce (§2). Device Noise private keys and pairing PSKs stay exclusively on their devices. There is no Worker master key (a derivation scheme may be reconsidered only if its security and operational benefits are demonstrated). The ESP32-P4 uses `espressif/libsodium` or Monocypher, since mbedTLS has no Ed25519. Revoking or disabling one device is a single row; rotation is in-band (`auth.rotate`). *Superseded:* HMAC `dev_secret` stored peppered.

**Entitlement:** a row `{dev_id, cls: stick|kvm, until}`. At launch it's set from (a) device-purchase serial lists for AI KVM and (b) StickLLM subscription activation codes, entered by hand or by script. A Stripe webhook can come later. No entitlement means signalling works for already-paired peers but `relay.reg` is refused (direct only). That choice is an open decision.

**Relay allowlist:**
- `GET /v1/relay/allowlist?rg=tor1&since=<seq>` with header `Authorization: Bearer <per-relay secret>`, so the list isn't public.
- Response: `{v:1, kid, rg, seq, iat, exp: iat+2h, full|delta, add:[{k,e}], del:[k]}` + an Ed25519 signature over the canonical bytes.
- The Worker signs with WebCrypto Ed25519, which works in both Workers and Node. It caches the signed doc per `seq` so it doesn't re-sign on every pull.
- Permit TTL defaults to 12 h (allowed range 1 h to 1 day). Devices rotate `nk` with each refresh.

**Sidecar behaviour:**
1. Pull a delta every 60 s, plus a full list every hour.
2. On an **unknown key**, do one extra pull (single-flight, at most one per 2 s) before answering. This stays inside derper's 5 s timeout, so a device that registers and then connects right away isn't rejected.
3. Answer `Allow` only if `k` is present, its `e` is in the future, and the doc's `exp` is in the future.
4. Reject docs with a lower `seq` or an unknown `kid`.
5. Persist the last good doc to `/var/lib/sticklink-admit`. If Cloudflare is down, the relay keeps admitting known keys until doc `exp` (2 h), then fails closed.
6. No logging except counters.
7. The systemd unit keeps today's sandbox but must allow outbound HTTPS. Today's stub has `IPAddressDeny=any`, so that needs to change.

The sidecar is written in Go because derper already uses that toolchain and Go has `crypto/ed25519` in its standard library. Python's standard library has no Ed25519.

**Known limit:** derper checks admission only when a client connects. A key that is revoked mid-session stays connected until it reconnects. If abuse happens, run `systemctl restart derper`; honest clients reconnect in seconds. *Update 2026-10-29 4:12 PM ET (Nink):* accepted: revoked devices are denied relay **admission**; existing relay connections may persist. Outage: the sidecar fails **closed for new admissions** after 15 min without fresh data; existing sessions continue.

**Worker signing key rotation:**
- The sidecar config `/etc/sticklink/admit-keys` pins a **set** `{kid: pubkey}`, normally "current" and "next".
- Routine rotation every 90 days:
  1. Generate the key offline.
  2. Add its public key to every sidecar as "next".
  3. Switch the Worker secret `SIGNING_KEY` and `kid`.
  4. After 2 h (doc TTL) + 24 h (max permit TTL), remove the old kid.
- If the key is compromised, remove the old kid from the sidecars **first**. That fails closed. Then deploy the new key.
- The private key lives only as a Worker secret (or a root-only `0600` env file on a VPS), plus an offline backup.
- The key set in this design is simple. The alternative, an offline root key that certifies online keys, is an open decision.

## 5. Cloudflare budget

Assumptions per **active stick per day**:
- 8 stick reconnects (network changes and runtime updates).
- 10 client sessions. AI KVM, phone and browser sessions count here.
- About 2 auth messages per connect and about 30 sealed `sig` messages per session.
- 2 permit refreshes.
- About 5 ms of handler time per event.

Protocol pings are free. Per the DO pricing page, idle hibernation-eligible DOs aren't billed for duration.

| Limit (free/day) | Use per stick/day | Fixed overhead/day | Sticks that fit |
|---|---|---|---|
| Workers requests 100,000 | 18 (WS upgrades; DO messages aren't Worker requests) | ~1,500 (sidecar pulls, health checks) | ~5,400 |
| Workers CPU 10 ms/request | Under 2 ms (HMAC, JSON, cached Ed25519 sign) | | Not binding |
| DO requests 100,000 | 18 upgrades + ~370 msgs ÷ 20 ≈ **37** | — | **~2,700 (binding)** |
| DO GB-s 13,000 | ~390 events × 5 ms × 0.128 GB ≈ 0.25 | — | ~50,000 |
| Rows written 100,000 (D1/DO) | ~4 (permits, counters) | ~50 | ~25,000 |

**What this means:**
- Plan on **about 2,500 active sticks** on the free tier, or about 1,000 if networks are flaky (5× reconnects).
- Idle connected sticks cost almost nothing. Reconnects and sessions are what use up the limits.

**Two design rules protect these numbers:**
- No `setTimeout` or outstanding `fetch` inside a DO, because that blocks hibernation and bills duration. Use alarms only if needed.
- Use protocol pings, not app-level message pings. Verify in M1 that the ESP-IDF and Python clients' pings aren't counted as messages.

**Workers Paid (US$5) at launch.** On the free plan, going over a cap is a hard failure until 00:00 UTC (20:00 EDT). That also means anyone can take the service down by flooding it.

At 5,000 sticks:
- Workers: about 2.7M requests/month, under the included 10M (figure from memory, verify).
- DO: about 5.6M requests, so about US$0.70 over the included 1M.
- GB-s: about 38k, under the included 400k.
- **Total ≈ US$5.70/month** plus Luna Node US$3.50.

**Self-host fallback:** the same app on Node/Bun with SQLite. It fits on relay-tor1 (1 GB RAM; a few thousand idle WS ≈ 50 to 100 MB, to be measured), so the extra cost is $0. A second Luna Node m.1s costs US$3.50/month if isolation is wanted.

## 6. Portability

**Code layout:**
- `app.ts` holds the pure Hono routes and protocol logic.
- Runtime-specific code sits behind three interfaces:
  - `HomeHub`: DO on Cloudflare, in-process `Map` on Node.
  - `Store`: D1 on Cloudflare, `bun:sqlite`/`better-sqlite3` on Node, same SQL migrations.
  - `RateLimiter`.
- Crypto is WebCrypto only.
- Entry points: `worker.ts` (wrangler) and `node.ts` (`@hono/node-server` + `ws`).
- **The same test suite runs against both** (vitest with the Workers pool, and Node).

**Co-hosting on relay-tor1:**
- derper keeps 80/443. Signalling listens on `:8443` with a Let's Encrypt cert via DNS-01, using a Cloudflare token scoped to the zone.
- `link.stickllm.com` stays **proxied** (orange cloud), and a free Origin Rule sends it to origin port 8443.
- Clients keep using `wss://link.stickllm.com`, with no app update. The sidecar pulls from `http://127.0.0.1:8443`.

**Migration steps (Cloudflare → VPS):**
1. Provision with `install.sh` plus a new `signalling.service` (systemd sandbox like derper's).
2. Export D1 and import it into SQLite. Copy `SIGNING_KEY`, or rotate via a new kid.
3. Run both in parallel and test with a staging hostname.
4. In Cloudflare, remove the Worker custom domain and add proxied A/AAAA records for `link` plus the Origin Rule.
5. Clients reconnect on their own. Homes are in-memory state that rebuilds when sticks reconnect.
6. Keep the Worker deployable for 30 days as the way back.

Nothing in the protocol or clients is Cloudflare-specific, except that Cloudflare's IP header becomes the socket's remote address.

## 7. Security and abuse

- **Rate limits:**
  - Per IP: 30 WS upgrades/min, using one free Cloudflare WAF rate-limit rule plus an in-code limiter.
  - Per device: 1 msg/s sustained, 10 `relay.reg`/day.
  - Per slot: 5 failed join MACs, then a 15 min lockout.
  - Per home: 8 concurrent clients.
  - Relay: `nftables` connlimit per IP and derper's `-accept-connection-burst`.
  - Watch transfer against Luna Node's 1 TB included (US$0.003/GB over).
- **Replay:**
  - A fresh server nonce on every connect binds `hello` and `join` MACs.
  - Inner `sid`/`seq` checks.
  - Allowlist `seq` + `exp`; permits carry `exp`.
  - Noise handles the data path.
  - Devices don't need a trusted clock. The server and sidecar check times. ESP32 time comes from `welcome.now`, used only for refresh scheduling.
- **DoS:**
  - Cloudflare absorbs floods.
  - Unauthenticated sockets close after 10 s.
  - Frame cap of 4 KB.
  - Per-home DOs isolate users from each other.
  - Sidecar pull-on-miss is rate-limited, so scanners can't hammer the Worker.
  - If signalling goes down, existing direct and relay sessions keep running. Only new sessions fail.
- **Trust failures:**
  - Compromised Worker: it can deny service, see metadata, and admit junk keys to the relay (bounded by relay limits). It can't read or MITM traffic.
  - Compromised relay: it can drop or delay traffic. It can't read it.
  - Leaked device auth key: disable or re-key one row (`devctl`). A full D1 leak exposes only public keys, which can't log in.
  - *Update 2026-10-29 4:12 PM ET (Nink):* every slot add/delete/rekey/expiry and device key change is authenticated, authorised and recorded in a D1 audit log (ids only, no secrets, 365 days) that the stick can read.
- **Logging policy:**
  - Workers request logs and observability off. No `console.log` of ids, keys or IPs. No IPs stored anywhere.
  - Only hourly aggregate counters in the directory (connects, joins, sessions, relay registrations, errors by code), kept 90 days.
  - derper still logs rejected connections with IP and node key. That's rate-limited, with 7-day journald retention today. Recommend cutting derper's retention to 24 h (open decision).
  - Cloudflare itself sees IPs. State this in the privacy policy.

## 8. Milestones, effort and tests

Effort is rough, in developer-days of focused work.

| # | Milestone | Server (this repo) | StickLLM team | AI KVM team |
|---|---|---|---|---|
| **M0** | Spec + test vectors | Protocol doc; vectors for HMAC hello/join, envelope, permit, allowlist signature, Noise IKpsk2-SHA256 (Python `noiseprotocol` as reference). Repo skeleton in `StickLLM/sticklink`, CI. **1–2 d** | Review the spec | Confirm microlink Noise with the SHA-256 swap; RAM budget for 1 TLS session at a time |
| **M1** | **AI KVM → StickLLM over relay-tor1 on Nink's LAN** | hello/auth with dev credentials loaded by hand, home DO, join, `sig`, `relay.reg`, allowlist endpoint; Go sidecar replacing `derp-admit` (same port, so derper is untouched); deploy to a **dev** Worker (`*.workers.dev`) **after Nink approves**. **6–9 d** | `sticklinkd`: WSS presence, envelope, DERP client (PyNaCl), Noise responder, pinning, `--force-relay`. Pairing by pasted `sl1:` string. **5–7 d** | WSS client (esp-tls, closes before DERP opens to save RAM), HMAC auth, envelope (mbedTLS ChaChaPoly), `relay.reg`, point microlink at tor1 (region 900, node 900a), Noise initiator. **6–10 d** |
| M2 | Direct path | Candidate message types are already opaque, so ~1 d (limits, counters) | UDP hole punching, IPv6 first, STUN via relay/Cloudflare, path race and upgrade; netcheck reuse. **4–6 d** | Same on lwIP. **6–10 d** |
| M3 | QR pairing, revocation, browsers/phones | `slot.add/del`, expiry, MAC lockout, 16-slot cap. **3–4 d** | QR UI, slot management, aiortc data channel with Noise inside. **5–8 d** | Setup-UI entry of the pairing code. **2–3 d** |
| M4 | Launch hardening | Entitlements + activation codes, rate limits, counters, key-rotation runbook, Workers Paid, link.stickllm.com custom domain, load test. **5–8 d** | Activation flow, permit refresh. **2 d** | Purchase-serial activation, permit refresh. **2–3 d** |
| M5 | Portability drill + IPv6 | Run Node build on relay-tor1 staging (`:8443`), full test suite on both runtimes, migrate-and-back drill; finish the paused external IPv6 test. **2–3 d** | — | — |

M1 exit criteria:
- AI KVM sends Noise-encrypted frames to StickLLM through relay-tor1 with both on Nink's LAN, with direct disabled.
- An unregistered key is still rejected (`derpdenytest`).
- An expired permit is rejected at reconnect.
- A captured signalling transcript contains no keys, candidates or plaintext.

**Test plan:**
- **Unit:** schema and limits, MACs, envelope, signer and verifier, rate limiter, sidecar decision table (unknown, expired, stale doc, rollback seq, bad kid, Worker unreachable → last good → fail closed).
- **Cross-implementation:** the same vectors pass in TypeScript, Python, Go and C/mbedTLS.
- **Runtime parity:** the full integration suite runs on the Workers pool and on Node.
- **LAN end to end (Nink's network):** forced relay; direct v4; direct v6; symmetric NAT simulated with a Linux netns + nftables random-port masquerade → relay; relay down → direct still works; signalling killed mid-session → session survives; WS drop/reconnect; permit expiry and refresh; slot revoke; join replay rejected; oversize frame and flood rejected.
- **Privacy:** `wrangler tail` and the Node logs show no ids, IPs or keys; journald on relay-tor1 is checked after a run.
- **Budget:** 50 simulated sticks for 24 h on the dev Worker. Compare Cloudflare analytics (requests, GB-s, rows) with §5 before launch.
- **Load:** 5,000 idle WS on the Node build on a test VM (not relay-tor1 in production).

**Risk to check early (AI KVM):** with ~111–132 KB internal RAM, two TLS sessions at once (WSS + DERP) may not fit. The plan therefore has AI KVM act as caller only and close WSS before it opens DERP. This needs the permit and peer DERP key to be fetched first, which the message order above allows.

## 9. Open decisions for Nink (recommended default in bold)

1. **M1 signalling host:** **dev Worker on workers.dev (free)**, or Node on a LAN PC plus a hand-copied signed allowlist file (no cloud deploy).
2. **Home granularity:** **one DO per StickLLM home with pairing slots**, or one DO per pairing.
3. **Directory store:** **D1**, or DO SQLite only.
4. **Seal offers and candidates from signalling:** **yes, envelope keyed from `P_slot`, which is derived from the pair's `pair_psk` (PAIRING-SPEC v0.5 §4.6; was "the QR secret" before 2026-10-29)**, or plain (simpler, but signalling then sees LAN and IPv6 addresses).
5. **Device auth:** ~~HMAC device secret now, ECDSA P-256 later~~. **Decided 2026-10-29 4:12 PM ET:** per-device random Ed25519 server-auth keys, server stores only public keys (libsodium/Monocypher on the ESP32-P4).
6. **Without an entitlement:** **direct-only signalling still works for paired devices; relay is refused**, or block signalling too.
7. **Entitlement source at launch:** **purchase-serial lists + activation codes loaded by script**, or Stripe integration now.
8. **Permit TTL / allowlist TTL / pull interval:** **12 h / 2 h / 60 s with pull-on-miss**. *Update 2026-10-29: PAIRING-SPEC v0.3 sets the allowlist fallback TTL to 15 min, with pull on change.*
9. **Signing-key scheme:** **pinned key set with 90-day rotation**, or an offline root key certifying online keys (no sidecar config change on rotation).
10. **Phone apps' transport:** **native UDP+DERP like AI KVM; WebRTC only for browsers**, or WebRTC everywhere.
11. **Browser relay fallback:** **none at launch (clear "can't connect directly" message)**, or a later JS DERP-over-WebSocket client. derper accepts WS on `/derp`.
12. **derper log retention:** **cut to 24 h**, or keep 7 days.
13. **Self-host target if/when needed:** **co-host on relay-tor1 (`:8443`, $0)**, or a second Luna Node m.1s (US$3.50, isolation).
14. **Pairing method:** see PAIRING-SPEC.md v0.2 (Nink's decisions 10:43 AM ET: Noise IKpsk2 only, split routing ID and secret, one attempt with 60 s expiry plus rate limits, X25519 identities). Earlier note: Nink is not happy with QR pairing because it doesn't meet all use cases and wants to think about it further. Options so far: USB key pairing (§3a), QR / paste-in code (§3), or both. Undecided.
15. **Decided 2026-10-29 4:12 PM ET:** desktop SPAKE2 code pairing stays **disabled** until it passes security review and testing. Slot removal by the stick and admin phones, all audited. Relay fail-closed for new admissions after 15 min of outage; existing sessions continue.

**Notes and conflicts found while reading:**
- HOSTING-OPTIONS.md recommended self-hosting signalling from day one. This plan follows the later approved Cloudflare-first choice and keeps that as the fallback.
- RELAY-SETUP.md's switch-over steps name `signal.stickllm.com` and a remote admit URL. Under option A the admit URL stays `http://127.0.0.1:9099/derp/admit`, now served by the sidecar. The hostname is `link.stickllm.com`.
- Workers Paid included-request figures are from memory; verify them before launch. DO and D1 figures are from the Cloudflare pricing page fetched 2026-10-29.
- The licence for derper (BSD-3-Clause per DESIGN-REVIEW) still needs verifying before shipping.
