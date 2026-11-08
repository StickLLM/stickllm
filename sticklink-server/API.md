<!-- Copyright (c) 2026 Nink Inc. All rights reserved. -->
# sticklink signalling API — `sl1` (v1)

Status: **local build only, not deployed.** Implements PAIRING-SPEC v0.9 (authoritative) and
SIGNALLING-PLAN where the spec is silent. Decisions the specs leave open are in
[OPEN-QUESTIONS.md](OPEN-QUESTIONS.md). Vectors: [`vectors/`](vectors/).

Contents: 1 Transport · 2 Encoding · 3 Auth (`hello`, `join`) · 4 Signalling (`sig`) ·
5 Slots and the revoked-peer API · 6 Pairing: routing IDs and mailboxes · 7 Relay permits ·
8 Relay HTTP API (allowlist, feed) · 9 Errors, close codes, limits · 10 AI KVM profile ·
11 Local dev and fixtures · 12 Vectors

---

> **E2E testing:** runbook in [E2E.md](E2E.md); live local endpoints, framing (Q-N7), fixtures and the desktop bundle in [ENDPOINTS.md](ENDPOINTS.md).

## 1. Transport

| | |
|---|---|
| Prod URL (planned) | `wss://link.stickllm.com/v1/ws` |
| Local URL | `ws://<host>:8787/v1/ws` (wrangler dev listens on `0.0.0.0:8787`) |
| Subprotocol | `Sec-WebSocket-Protocol: sticklink.1` (**required**) |
| Frames | text, one JSON object per frame, ≤ 4096 bytes |

The route is picked by one query parameter. If several are given, the first in this order wins: `dev`, `home`, `rid`, `mbx`.

| Query | Who | Next message |
|---|---|---|
| `?dev=<dev b64u>` | the stick (StickLLM server) | `hello` role `server` |
| `?home=<home b64u>` | a paired client (phone, desktop, AI KVM) | `join`, optionally after `hello` role `client` |
| `?mbx=<mbx b64u>` | QR joiner during pairing | `pair.join{mbx,mac}` |
| `?rid=NNNN` | code joiner (only when `FEATURE_SPAKE2_CODE=1`; off by default, §8b(a)) | `pair.join{rid}` |

HTTP replies before the upgrade:

| Status | When |
|---|---|
| 426 | not a WebSocket upgrade |
| 400 | no `sticklink.1` subprotocol |
| 404 | no route param, malformed id, unknown home or dev, expired or closed mailbox, unknown routing ID, **or** (on `rid`/`mbx`) the IP is blocked for failed lookups. All of these look the same. |
| 429 + `retry-after` | more than 30 upgrades/min from the IP, or more than 10 mailbox connections/min |

On connect the server sends `{"t":"welcome","v":1,"n":"<32B nonce>","now":<unix s>}`. `n` is fresh
for every socket and goes into every MAC on that socket, so MACs can't be replayed.

Keepalive: send `{"t":"ping"}` (answered with `{"t":"pong"}` without waking the Durable Object) or
WebSocket protocol pings. Reconnect with jittered backoff from 1 s up to 60 s. Cloudflare drops
sockets on runtime updates.

## 2. Encoding

* Byte fields are **base64url without padding**: 16 B → 22 chars, 8 B → 11, 32 B → 43, 64 B → 86.
* `id` is an optional client request id (a non-negative integer) echoed in the reply.
* Unknown `t` gives `err{code:"unknown"}`. Field order doesn't matter. The examples use the
  order a fixed-layout encoder should emit.
* Times are unix seconds (`now`, `exp`, `iat`).
* Signed documents (allowlist, permit, revoked set) use one Ed25519 key with domain separation:
  `sig = Ed25519(SIGNING_KEY, domain || 0x00 || body_bytes)`. The envelope is
  `{"kid","body":"<b64u of the JSON body bytes>","sig":"<b64u 64B>"}`. Verify **the bytes in
  `body`**, then parse them. Never re-serialise. Domains: `sl1/allowlist/v1`, `sl1/permit/v1`,
  `sl1/revoked/v1`. Public keys: `GET /v1/keys` → `{"v":1,"keys":[{"kid","alg":"Ed25519","pub"}]}`.
  Firmware should pin the key and not fetch it at run time.

## 3. Authentication

### 3.1 `hello`: a device with a provisioned credential

```
C→S {"t":"hello","id":1,"dev":"<16B>","role":"server"|"client","home":"<16B>","sig":"<64B>"}
sig = Ed25519(auth_key, "sl1/dev-hello/v1" || 0x00 || n(32) || dev(16) || role(1) || home(16))
      role 0x01 = server (stick; home required, must be its own home)
      role 0x02 = client (home omitted; 16 zero bytes in the signed body)
S→C {"t":"ready","id":1,"v":1,"home":"<16B, stick only>","lim":{"frame":4096,"burst":20,"rate":1},
     "relays":[{"rg":"tor1","host":"relay-tor1.stickllm.com","stun":3478}],"now":<s>}
```

**Device server-auth key (Nink, 2026-10-29; Q-S1).** Each device (stick, AI KVM, desktop) generates its
own random Ed25519 key pair (`auth_key`, 32 B seed) on the device, from its own RNG, and keeps the
private half there. Only the **public key** `ak` goes to the server at provisioning
(`worker/scripts/provision.mjs --ak <b64u>`), stored in D1 `devices.ak` as the verifier. There is
no server master key (`DEV_MASTER` and the v1 HMAC `mac` hello are **removed**; a v1 `mac` hello gets
`err{auth}` + 4401). A failed or missing signature, an unknown/disabled device, or a device with no `ak`
gives `err{auth}` and close 4401.

> **Never sent to the server:** device Noise static private keys, pairing PSKs (`pair_psk`) and
> anything derived from them except `jk` (the slot join key). The `auth_key` private seed never
> leaves the device either. The server can't impersonate a device or decrypt a Noise session.

Why a signature and not a hashed bearer secret: with a bearer secret (even stored hashed) the device
must send the secret itself, so anything that sees it in transit (a TLS terminator, a logging bug, a
compromised Worker) can replay it. With Ed25519 the device proves possession over a fresh server
nonce; the server, D1, backups and logs hold only public keys, so a full server-side leak gives an
attacker nothing that logs in as a device. A per-device key also limits a device leak to that device.

**Rotation.** `{"t":"auth.rotate","id","ak":"<32B new pub>","pop":"<64B>"}` on an authenticated
(`hello`) socket, where `pop = Ed25519(NEW auth_key, "sl1/dev-rotate/v1" || 0x00 || n(32) || dev(16) || new_ak(32) || old_ak(32))`.
Reply `{"t":"ok","id","gen":<n>}`. The server swaps `ak` atomically (only if it is still `old_ak`),
bumps `gen`, records `auth.rotate` in the audit log and closes the device's other sockets (4401 `rotated`).
Errors: `bad` (malformed, same key, key used by another device), `auth` (bad PoP, raced, no device key,
phones). The device must keep the old seed until it sees `ok`, then reconnect with the new key to
confirm. A **lost** key cannot be rotated in-band: ops sets a new public key with `scripts/devctl.mjs setak`
(audited) after the device generates one, or disables the device (`devctl disable`).

**ESP32-P4 fit (AI KVM).** ESP-IDF's mbedTLS 3.6 has no EdDSA. Use the ESP Component Registry
`espressif/libsodium` (`crypto_sign_ed25519_seed_keypair`, `crypto_sign_ed25519_detached`) or
Monocypher (`crypto_eddsa_*`, ~a few KB of flash). State is a 32 B seed (store in encrypted NVS /
eFuse-protected flash), a 32 B public key, 64 B signatures, no heap. One sign per connection (a few ms
at 360 MHz). Fallback if neither can be shipped: ECDSA P-256 via mbedTLS would need a protocol change (ask first).

* A stick with a newer connection replaces the old one (close **4009** `replaced`). The newest stick wins.
* There is no `caps` field in v1 (SIGNALLING-PLAN's early draft had one). Unknown fields are ignored and are not
  signature-covered. Every v1 client supports both UDP and DERP.
* A client `hello` is **optional**. It identifies the device (AI KVM, desktop) so it can use its
  own relay entitlement (§7). Phones that have no credential just `join`.

### 3.2 `join`: client into a home slot

```
C→S {"t":"join","id":2,"home":"<16B>","slot":"<8B>","mac":"<32B>"}
mac = HMAC-SHA256(jk, "sl1/join" || n(32) || home(16) || slot(8))
S→C {"t":"joined","id":2,"conn":"c4","peer":"online"|"offline"}
S→stick {"t":"peer","conn":"c4","slot":"<8B>","state":"join"}       (later "leave")
```

* `jk` is the slot's join key (§5). The server stores `jk` only. It never sees `pair_psk`,
  `P_slot`, `env_k` or a Noise key.
* Each slot allows one live connection. A newer join replaces the older one (4009).
* 5 bad MACs on a slot lock that slot for 15 min (`err{rate,retry}`, close 4429). A bad
  MAC closes with 4401.
* A home allows at most 8 concurrent clients (`err{busy}`, close 4503).
* There is no queueing. `peer:"offline"` means the stick isn't connected. Retry later, or wait for the next `peer`.

## 4. Signalling: `sig` (opaque to the server)

```
client→S {"t":"sig","id":7,"to":"stick","box":"<b64u>"}     S→stick  {"t":"sig","from":"c4","box":"<b64u>"}
stick→S  {"t":"sig","to":"c4","box":"<b64u>"}               S→client {"t":"sig","from":"stick","box":"<b64u>"}
```

* `box` is at most **3072 b64u chars** (2304 bytes). The server forwards it byte-for-byte and doesn't parse it.
* Contents (between the peers): ChaCha20-Poly1305 under
  `env_k = HKDF-SHA256(P_slot, salt=∅, info="sl1/env")`, with inner messages `cand`, `derp`, `offer`/`answer`, `bye`
  (SIGNALLING-PLAN §2). The exact box framing and AAD byte layout are not pinned in either spec. The
  **proposal** with vectors is `nonce(12) || ct || tag(16)`, AAD
  `"sl1/box" || home(16) || slot(8) || dir(1: 0x01 client→stick, 0x02 stick→client)`, in
  `vectors/ikpsk2-v2.json` → `box`. See OPEN-QUESTIONS Q-N2.
* If the target isn't connected, the sender gets `err{offline}`.
* `cand.c[].p` (Q-N9): `host` (local IPv4 interface), `v6` (local IPv6 interface), `stun4` / `stun6` (STUN-mapped
  address), `cfg` (configured by hand). Receivers must try every candidate whatever its `p`, and must accept (ignore)
  unknown values. **`lan4` is not part of the set.**

### 4.1 Session lifecycle, `bye`, datagram limits and privacy

**`bye` and the WSS after the path is up (Q-N10).** A path change (direct → DERP, or back) is **not** the end of a
session. Never send `bye` for it. `bye` means "this session is over for good" (user disconnect, unpair, shutdown). Send
it only if the WSS is still open; never reconnect just to send `bye`. A client may close the WSS (code 1000) once it
holds the stick's `cand`+`derp`, and the KVM profile does exactly that to save RAM. Clients reconnect
(`hello`/`join`) only to refresh the relay permit (at ⅔ TTL) or to re-signal after the Noise session is lost. On the
stick side, `peer leave` only means "off signalling". It does **not** end the Noise session. Receivers must not rely
on `bye`: each side drops a session after its own idle timeout, and on `bye` it drops only that `sid`'s state.

* Datagrams (UDP or DERP, framing in ENDPOINTS.md §2.3, Q-N7) are at most **1280 B**, ciphertext and tag included.
* The replay window (64 entries) advances only after the AEAD tag verifies.
* **Privacy notes.** (1) The server sees `home`, `slot`, timing, IPs and box sizes, but no candidate addresses or keys,
  because those travel in the sealed box. (2) The INIT datagram carries `slot(8)` in clear, so an on-path observer or the
  DERP operator can link sessions of one pairing across networks. **Accepted for now** (Q-N11). A later version could
  send a rotating `HMAC(P_slot, epoch)` tag instead. (3) DERP sees both node keys and the timing, as with any relay.

## 5. Slots and the revoked-peer API (StickLLM item 1)

Slot messages are **stick-only**, except that an admin client (`adm:1`) may send `slot.del` (Nink, Q-S12).
Every slot operation (add, del, rekey, pending expiry) and every `auth.rotate` is authenticated,
authorised and **recorded** in the audit log (§5.1), including denied attempts.

| Request | Reply | Notes |
|---|---|---|
| `{"t":"slot.add","id","slot":"<8B>","jk":"<32B>","adm":0\|1,"exp":≤600}` | `ok` | `exp` makes the slot *pending*: if it isn't joined within `exp` s it is **revoked**, not just dropped. Errors: a slot id already in the revoked set gives `auth`; a duplicate or the 16-slot cap gives `busy`. |
| `{"t":"slot.del","id","slot"}` | `{"t":"ok","id","rc":<n>}`; the stick also gets `{"t":"rev","rc":<n>,"slot":"<8B>","why":"del"}` | Revokes immediately: closes the slot's live sockets **and the revoked device's other sockets in the home** (4403 `revoked`), withdraws its relay permits (allowlist delta and feed `chg` go out right away, so relay admission is denied; already-open relay connections may persist, Q-S6), and appends the slot to the revoked set. The `rev` push goes to the stick whoever asked (stick or admin phone). Unknown slot gives `nf`. |
| `{"t":"slot.rekey","id","slot","jk","cmp":true?}` | `ok` | Replaces `jk` (pair_psk rotation, §6). With `cmp` (compromise) it also closes the slot's live clients (4403 `rekeyed`) and withdraws their permits. |
| `{"t":"slot.list","id"}` | `{"t":"slots","id","s":[{"slot","adm","st":"pend"\|"act"}]}` | |

**The revoked set** is remove-only, server-signed, paged, and read over the stick's authenticated session:

```
stick→S {"t":"revoked.get","id":9,"after":0}
S→stick {"t":"revoked","id":9,"kid":"…","body":"<b64u>","sig":"<b64u>"}       domain "sl1/revoked/v1"
body = {"v":1,"home":"<16B>","n":"<this socket's welcome nonce>","after":0,"next":12,"more":false,
        "rc":12,"iat":<s>,"s":["<slot 8B>", …]}                                   ≤ 64 slots per page
```

* **Paging.** Request `after = next` while `more` is true. `next` is a cursor into the server's
  append-only log. `rc` is the current revocation counter. Store `rc` and refetch from your last
  cursor whenever a `rev{rc}` push shows a larger value, or on every (re)connect.
* **Binding.** `home` must equal your home, and `n` must equal the nonce from this socket's
  `welcome`. That stops a replayed old page from hiding newer revocations. `iat` is informational.
* **Semantics.** The stick deletes every listed slot locally and **never re-adds** one: the server
  refuses `slot.add` for a revoked id. There is no un-revoke. Pair again with a fresh slot id.
* **Auth.** Only a socket that completed `hello` as `server` for that home can call it. Over HTTP it isn't reachable at all.
* **`rev` push (Nink, Q-S6).** `{"t":"rev","rc","slot","why":"del"|"exp"}` reaches the stick the moment a
  slot is revoked (stick or admin `slot.del`, or a pending slot expiring). The stick **must at once
  reject new Noise sessions (msg1/INIT) for that slot or its pinned static key and terminate any live session**
  for it, then persist via `revoked.get` (the signed page is the durable record; the push is the trigger).
  Acting on an unsigned push is safe: it can only remove access.

### 5.1 Audit log (stick read-only)

```
stick→S {"t":"audit.get","id":5,"after":0,"limit":50}               limit 1..100 (default 100)
S→stick {"t":"audit","id":5,"next":42,"more":false,
         "rows":[{"seq":41,"ts":<s>,"by":"stick"|"admin"|"device"|"system"|"ops",
                  "actor":"<dev or slot id>","op":"slot.add"|"slot.del"|"slot.rekey"|"slot.rekey.cmp"|
                  "slot.expire"|"auth.rotate"|"dev.provision"|"dev.disable"|"dev.enable"|"dev.setak",
                  "target":"<slot or dev id>","res":"ok"|"auth"|"nf"|"busy"|"bad"}]}
```

Rows hold ids only: no keys, MACs, IPs or tokens. Only this home's rows are returned, including ops rows about the stick
itself (KVM/desktop devices have no home, so their ops rows are filed under `-` for ops only). Page with `after = next` while `more`. Kept 365 days (Q-S23).
A failed audit write never blocks a revocation (Q-S22). Clients get `err{auth}`.

## 6. Pairing: routing IDs and mailboxes (StickLLM item 2)

```
stick→S {"t":"pair.open","id":3,"m":"qr","jk":"<32B jk_qr>","exp":60}
S→stick {"t":"pair.ok","id":3,"mbx":"<8B>","exp":60}                  (+ "rid":"0427" in code mode)
```

* `m:"code"` gives `err{disabled}` unless `FEATURE_SPAKE2_CODE=1` (off by default, §8b(a)).
* `exp` is capped at **60 s**. When it runs out, the mailbox closes and the stick gets
  `{"t":"pair.closed","mbx","why":"exp"}`.
* **Routing ID** (code mode): 4 digits `RRRR`, assigned by the server, unique among live mailboxes.
  After release it is held for 10 min globally, and it isn't reused for the same home for 24 h. If
  none is free the reply is `err{busy,retry:10}`. **The server only ever sees `RRRR`.** A
  `pair.join` whose `rid` isn't exactly 4 digits matching the URL (for example a pasted
  `RRRR-SSSSSS`) is refused and not stored.
* **Rate limits:** per home, 5 `pair.open`/10 min and 20/day, then a 1 h lock (`err{rate,retry}`).
  Per IP: 10 mailbox connections/min, and 100 failed lookups/h then a 1 h block (404).
* Joiner side:
  ```
  QR:   GET /v1/ws?mbx=<mbx>    J→S {"t":"pair.join","mbx":"<8B>","mac":"<32B>"}
        mac = HMAC-SHA256(jk_qr, "sl1/qr-join-mac" || n(32) || mbx(8))
  code: GET /v1/ws?rid=0427     J→S {"t":"pair.join","rid":"0427"}
  S→J   {"t":"pair.joined","id","conn":"c7","home":"<16B>"}
  S→stick {"t":"peer","conn":"c7","mbx":"<8B>","state":"join"}
  ```
  Unknown, expired, closed, wrong-mode and bad-MAC joins all give `err{nf}` + close 4404, and
  count as a failed lookup for the IP. A joiner must send `pair.join` within 5 s.
* **One attempt.** A mailbox takes up to 4 connections (§5), but **connecting doesn't use up the
  invitation**. The attempt is the cryptographic exchange, which the stick ends with
  `{"t":"pair.close","mbx","why":"done"|"fail"|"cancel"}`. On close, joiners get
  `pair.closed{why}` + close 4000, and the routing ID is released. Closing is final.
* Between joiner and stick: `J→S {"t":"pmsg","body":"<b64u ≤3072>"}` → `S→stick {"t":"pmsg","from":"c7","body"}`;
  `stick→S {"t":"pmsg","to":"c7","body"}` → `S→J {"t":"pmsg","body"}`. The body is opaque: `env_qr`
  sealed Noise messages, or SPAKE2 `pA/pB/cA/cB`.
* After success, the stick picks a fresh 8-byte `slot_id` and derives
  `P_slot = HKDF(pair_psk,"sl1/slot-secret")`, `jk = HKDF(P_slot,"sl1/join")`. It sends `slot.add`,
  then `pair.close{done}` (PAIRING-SPEC §4.6).

## 7. Relay permits (option A)

```
C→S {"t":"relay.reg","id":5,"nk":"nodekey:<64 hex>","rg":"tor1"}
S→C {"t":"relay.ok","id":5,"exp":<iat+43200>,"tok":"<b64u body>.<b64u sig>"}    domain "sl1/permit/v1"
    tok body = {"v":1,"kid","nk","rg","exp","cls"}
C→S {"t":"relay.del","id":6,"nk":"nodekey:…"}     S→C {"t":"ok","id":6}
```

* Allowed for the stick and for clients after `join`. A client's `hello` alone isn't enough. **Entitlement:** the device's own `cls` (if it sent
  `hello` and is entitled), otherwise the home owner's (the stick's). With neither, the reply is `err{auth}`.
* TTL 12 h. Refresh at ⅔ of the TTL with the same `nk` (this re-registers and moves `exp`).
* Each holder (device or slot) gets 2 node keys. Registering a third withdraws the oldest.
  `relay.reg` is limited to 10/day per holder (`err{rate}`). A `nk` already held by someone else gives `err{auth}`.
* The `tok` isn't needed by derper today. Keep it only to time the refresh.

## 8. Relay HTTP API (served to `sticklink-admit` on the relay)

All are `GET`, with `Authorization: Bearer <token>` for region `rg`. Tokens are 16–256 chars, checked
against the secret `RELAY_TOKENS = {"<rg>":"<sha256 hex of token>"}`. A bad or missing token gives 401.

| Endpoint | Reply |
|---|---|
| `/v1/relay/allowlist?rg=tor1&since=0` | full signed allowlist |
| `/v1/relay/allowlist?rg=tor1&since=<seq>` | delta from `seq` (full if `seq` is too old) |
| `/v1/relay/rev?rg=tor1` | `{"rg","seq"}`, the cheap change check |
| `/v1/relay/feed?rg=tor1` (WS) | push `{"t":"chg","rg","seq"}` on every change; `{"t":"ping"}`→`{"t":"pong"}` |

Allowlist body (domain `sl1/allowlist/v1`, in the envelope from §2):

```
{"v":1,"kid":"…","rg":"tor1","seq":42,"since":40,"iat":<s>,"exp":<iat+900>,"full":false,
 "add":[{"k":"nodekey:<64 hex>","e":<permit exp>}], "del":["nodekey:<64 hex>"]}
```

**Allowlist entry for a KVM key (AI KVM item 7):** the same as any other: `{"k":"nodekey:<64 lowercase hex>","e":<unix s>}`.
`k` is the Tailscale-style node public key the KVM uses toward DERP (derper's `NodePublic`). Class
doesn't appear in the allowlist: it's in the permit (`cls:"kvm"`), so derper's view is minimal. A KVM key gets in only by
`relay.reg` on a joined session (a `hello` before `join` makes the KVM's own `cls` apply). It leaves on `relay.del`, permit expiry, `slot.del`/`slot.rekey{cmp}`
of its slot, or device revocation.

Sidecar behaviour (`sidecar/`): it pulls on change (feed) with a 60 s delta and 1 h full poll, and
pulls once on an unknown key (rate-limited to once per 2 s). If its copy is older than 15 min it
**fails closed**: derper `{"Allow":false}`. A revoked key is denied once the delta lands, which is
seconds with the feed. derper can't drop a session that's already open (OPEN-QUESTIONS Q-S6).

## 9. Errors, close codes, limits

`{"t":"err","id":<n>,"code":"…","retry":<s>}`, where `retry` is present only when waiting helps.

| code | meaning |
|---|---|
| `rate` | per-socket bucket, slot lock, pairing or relay quota |
| `auth` | bad signature, MAC or credential, not allowed, revoked id, no entitlement |
| `size` | frame > 4096 (then close 1009) or box > 3072 |
| `offline` | `sig`/`pmsg` target not connected |
| `unknown` | unknown `t` for this socket's state |
| `busy` | slot cap, duplicate slot, 8 clients, no free routing ID |
| `bad` | malformed field |
| `nf` | not found (slot, mailbox) |
| `disabled` | code pairing flag is off |

| Close | Reason |
|---|---|
| 1009 | frame too large |
| 4000 | pairing mailbox closed (`why` in reason) |
| 4009 | replaced by a newer connection |
| 4400 | malformed input on a mailbox socket |
| 4401 | authentication failed, or `rotated` (the device's key was rotated on another socket) |
| 4403 | slot revoked or rekeyed |
| 4404 | mailbox or routing ID not found |
| 4408 | no `hello`/`join` within 10 s (mailbox joiner: 5 s) |
| 4429 | slot locked after 5 bad join MACs |
| 4503 | home full (8 clients) |

Per-socket: burst 20, then 1 msg/s. 16 slots per home, with pending slots lasting ≤ 600 s. Full table in `worker/src/config.ts`.

## 10. AI KVM profile (items 5–7): small frames with fixed-length fields

Every KVM-facing field is fixed-length, so a static buffer works:

| Frame | Bytes (exact, from vectors) | Fixed fields |
|---|---|---|
| `welcome` (in) | 88 (with `now` 10 digits) | `n` 43 chars |
| `hello` client (out) | 162 | `dev` 22, `sig` 86 |
| `ready` (in) | ~154 with one relay (grows ~60 B per extra relay) | |
| `join` (out) | **124** | `home` 22, `slot` 11, `mac` 43 |
| `joined` (in) | 49–51 | `conn` ≤ 4 |
| `sig` with one `derp` hint (out) | **243** (box 152 B → 203 chars) | |
| `relay.reg` (out) | 116 | `nk` 72 |
| `relay.ok` (in) | 330 | `tok` 281 (body length varies slightly with `kid`/`cls`) |
| `err` (in) | ≤ 60 | |

A 1 KB receive buffer is enough for every frame a KVM gets, provided the stick keeps its `sig` boxes under ~700 B.
The server allows up to 3072, so the KVM firmware should set its own cap and **ask StickLLM to keep
KVM-bound boxes ≤ 700 B** (one inner message per box). That needs agreement between the device teams. The server
has no say in it (Q-N3).

**Sequence for the KVM as network initiator:**

1. TLS to `link.stickllm.com`, WS upgrade `?home=<home_id>` with subprotocol `sticklink.1`; receive `welcome`.
2. Optional `hello` role `client` (so it uses its own `cls:"kvm"` entitlement). Then `join` with
   `jk = HKDF(HKDF(pair_psk,"sl1/slot-secret"),"sl1/join")`.
3. `relay.reg{nk,rg:"tor1"}`, then send `sig{to:"stick"}` with sealed `cand`/`derp` hints. The stick replies with its own `sig`.
4. Close the WS before opening DERP to save RAM (SIGNALLING-PLAN M1). Reconnect only to refresh the permit (at ⅔ of 12 h) or re-signal.
   No `bye` on this close (§4.1). Datagrams ≤ 1280 B (§4.1).
5. Noise `Noise_IKpsk2_25519_ChaChaPoly_SHA256` over UDP/DERP. The KVM is the initiator, `rs` = the
   stick's static key pinned during USB XX pairing, and `psk` = `pair_psk` (PAIRING-SPEC §4.5).
   msg1 is **96 B** with an empty payload (`e 32 || s 32+16 || payload+16`), and msg2 is **48 B**
   (`e 32 || payload+16`). Transport messages add 16 B. Vectors: `vectors/ikpsk2-v2.json`, including the
   wrong-psk case. psk2 means a wrong psk fails when the **initiator reads msg2**, not at msg1.
   **Prologue (v2, Nink 2026-10-29, Q-N1), exactly 96 B:**
   `"sl1/net"(7) || 0x01(ver) || home_id(16) || slot_id(8) || initiator_static_pub(32) || responder_static_pub(32)`,
   initiator = KVM/phone, responder = stick. Any difference (other slot, swapped keys, other version,
   the old 31-byte form) makes the responder reject msg1 (`prologue_mismatch_*` in the vectors).

**How `home_id` and `slot_id` are issued (item 6):**
* `home_id` (16 B) is created by the server at **stick provisioning** (`provision.mjs --kind stick`)
  and stored with the stick's credential. It never changes for that stick. Factory reset means a new provisioning.
* `slot_id` (8 B, random) is chosen **by the stick** for each paired peer, and registered with `slot.add`. The server
  only checks it's unique within the home and not in the revoked set.
* The KVM learns both from the stick over USB in frame **0x07 HOME_SLOT** = `home_id(16) || slot_id(8)` (PAIRING-SPEC §4.B.5).
  The KVM's own `dev` credential, used for `hello`, is optional: the KVM generates its Ed25519 auth key at first boot
  (TRNG) and exports only the public key, which manufacturing registers with `provision.mjs --kind kvm --ak <pub>`.

## 11. Local dev and fixtures (StickLLM item 3)

> **StickLLM: please test inside a VM, not on a real stick or your workstation's host OS.** (Request from Nink.)
> A QEMU guest using user-mode networking reaches the host's dev server at **`ws://10.0.2.2:8787/v1/ws`**
> and the dev relay at `http://10.0.2.2:3340/derp` (integration/run.sh), or the e2e stack's TLS derper per `stack.qemu.json` (ENDPOINTS.md). Bridged or other VMs use the host's LAN IP.

```
cd server/worker && npm ci
node scripts/dev-vars.mjs              # writes .dev.vars (public TEST secrets, mode 0600)
node scripts/seed-dev.mjs --apply      # local D1 migrations + fixtures; writes fixtures/dev-fixtures.json
npm run dev                            # wrangler dev --local on 0.0.0.0:8787
SL_CODE_FLAG=1 node scripts/dev-vars.mjs   # optional: enable code pairing locally
```

Full stack with relay (sidecar on `127.0.0.1:9099` and `derper -dev` on `:3340`): `server/integration/run.sh`.
Read it for the exact commands to start each piece by hand.

`worker/fixtures/dev-fixtures.json` (deterministic, **test only**) gives:
* `stick1`: a stick, home `_nxk9U2anZkKu0-p6YJ05w`, entitled (`cls:"stick"`). `stick2_noent` has no relay entitlement.
* `kvm1`: an AI KVM device credential with `cls:"kvm"`. `kvm2_noent` has none.
* Peers in stick1's home: `phone_admin` (adm 1), `laptop`, `kvm1_slot`, each with `slot`, `jk` and a pre-added slot.
* Relay test token, signing kid and public key. Per-device TEST `auth_seed` (Ed25519 seed) and `ak` for signing `hello`.

## 12. Vectors (StickLLM item 4)

| File | Covers |
|---|---|
| `vectors/signalling-v2.json` | device Ed25519 auth key, signed `hello` (both roles, wire frames), `auth.rotate` PoP, slot derivation from `kvm-usb-v1` pair_psk, `join` MAC and the wire frame, QR join MAC, Ed25519 domain-separated signing, permit, allowlist full and delta, revoked page |
| `vectors/ikpsk2-v2.json` | Noise IKpsk2-SHA256 handshake with the 96 B v2 prologue (KVM initiator, stick responder, fixed keys, psk from the vector chain), transport, wrong psk, prologue-mismatch rejection, proposed `sig` box seal |

Generated independently in Python (`gen_signalling_vectors.py`, `gen_ikpsk2_vectors.py` using
`cryptography` and `noiseprotocol` 0.3.1). They are checked by the Worker (vitest) and the sidecar (go test). The pairing-side vectors
(`../vectors/kvm-usb-v1*.json`, `qr-v1.json`) are unchanged. The v1 server vectors are withdrawn (HMAC hello, 31 B prologue).
