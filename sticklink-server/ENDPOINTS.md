<!-- Copyright (c) 2026 Nink Inc. All rights reserved. -->
# sl1 local test endpoints: answers for StickLLM and AI KVM

TEST ONLY. Everything here runs locally (`wrangler dev --local`, a local derper, a local sidecar).
Nothing is deployed, and none of these values work against production. Full protocol: API.md.
Runbook: E2E.md.

## 0. What is running on the shared box right now

| piece | address | notes |
|---|---|---|
| Worker (signalling) | `ws://127.0.0.1:8797/v1/ws` (bound 0.0.0.0) | subprotocol `sticklink.1` |
| derper (DERP over TLS) | `https://127.0.0.1:8453/derp` (bound 0.0.0.0) | self-signed, SHA-256 below, region 900 / rg `tor1` |
| STUN | `127.0.0.1:3488/udp` | served by derper |
| sidecar (`sticklink-admit`) | `127.0.0.1:9109` | derper `-verify-client-url http://127.0.0.1:9109/derp/admit`, fail-closed |
| stick responder | `slpeer -role stick` (fixture `stick_e2e`) | left running for AI KVM by `smoke.sh --serve` |

* Derper cert SHA-256 (DER): **`3bc4dc97007c1b6314856ead527f2cb18bcaa5f8c6c682d5b0d2e2caf1996479`**
* Machine-readable: `server/e2e/state-box/stack.json` (and `stack.qemu.json` with host `10.0.2.2` for a QEMU SLIRP guest).
* These ports are **not** the defaults. `:8787` on the box is held by another agent's `wrangler dev` (it runs this
  worker dir, probably StickLLM's; left untouched), so this stack runs on alternate ports with its own state (`SL_STATE=e2e/state-box`).
  Default ports (8787/8443/3478/9099) apply to any fresh `start-stack.sh`. **Always read `stack.json`
  rather than hard-coding ports.**
* Restart: `cd server/e2e && SL_STATE=$PWD/state-box SL_PORT_WORKER=8797 SL_PORT_DERP=8453 SL_PORT_STUN=3488 SL_PORT_ADMIT=9109 ./start-stack.sh --detach && ./smoke.sh --serve`.
  Stop: `SL_STATE=$PWD/state-box ./stop-stack.sh`.

## 1. Base URL, port, bind address (StickLLM 1, AI KVM 1)

| where the peer runs | Worker WS | derper | STUN |
|---|---|---|---|
| same host as the stack | `ws://127.0.0.1:<W>/v1/ws` | `https://127.0.0.1:<D>/derp` | `127.0.0.1:<S>` |
| QEMU guest, user-mode net (SLIRP) | `ws://10.0.2.2:<W>/v1/ws` | `https://10.0.2.2:<D>/derp` | `10.0.2.2:<S>` |
| bridged VM / other LAN host | `ws://<host LAN IP>:<W>/v1/ws` | `https://<host LAN IP>:<D>/derp` | `<host LAN IP>:<S>` |

Defaults: W=8787, D=8443, S=3478. On the box now: W=8797, D=8453, S=3488.
Everything except the sidecar binds `0.0.0.0` (`SL_BIND`). The cert SANs always include 127.0.0.1, 10.0.2.2,
localhost, `derp.sl1.test` and `SL_HOST`. Add more with `SL_CERT_IPS="192.168.1.20 …"`. The cert is regenerated
(new fingerprint) only when the SAN set changes. `SL_WORKER_TLS=1` serves the Worker as `wss://` with the same cert.

The box isn't reachable from Nink's LAN. For the desktop (DESKTOP-65FCPD4) use the bundle (§7).

## 2. Message shapes and what authenticates what (StickLLM 2)

### 2.1 Signalling WS (JSON text frames; binary fields base64url without padding)

| step | frame | authenticated by |
|---|---|---|
| connect | `GET /v1/ws?dev=<dev>` (stick) or `?home=<home>` (client), `Sec-WebSocket-Protocol: sticklink.1` | — |
| S→ | `{"t":"welcome","n":"<32B>","now":<s>}` | — |
| stick → | `{"t":"hello","id":1,"dev","role":"server","home","sig"}` | `Ed25519(auth_key, "sl1/dev-hello/v1"‖0x00‖n‖dev‖0x01‖home)`, verified against the device's public `ak` in D1 (v2, Q-S1; the v1 HMAC `mac` is refused) |
| KVM → (optional) | `{"t":"hello","id":1,"dev","role":"client","sig"}` | same with role 0x02 and 16 zero bytes for home |
| S→ | `{"t":"ready","id":1,"v":1,"home"?,"lim":{…},"relays":[{"rg","host","stun","derp"}],"now"}` | — |
| stick → | `{"t":"slot.add","id","slot","jk","adm":0\|1[,"exp"]}` → `ok` | stick's hello |
| KVM → | `{"t":"join","id":2,"home","slot","mac"}` → `{"t":"joined","id":2,"conn":"c4","peer":"online"\|"offline"}` | `HMAC-SHA256(jk, "sl1/join"‖n‖home‖slot)` |
| S→stick | `{"t":"peer","conn":"c4","slot","state":"join"\|"leave"}` | — |
| S→stick | `{"t":"rev","rc","slot","why":"del"\|"exp"}` the moment a slot is revoked | the stick's session. **Stick must kill that slot's live Noise session and refuse new INIT/msg1 for it at once** (Q-S6); the revoked device's WSS is closed by the server (4403) |
| stick/KVM → | `{"t":"auth.rotate","id","ak","pop"}` → `{"t":"ok","id","gen"}` | the device's hello + PoP by the new key (API §3.1) |
| stick → | `{"t":"audit.get","id","after","limit"}` → `{"t":"audit","id","next","more","rows"}` | stick's hello; ids only, no secrets (API §5.1) |
| either → | `{"t":"sig","to":"stick"\|"c4","box"}` → arrives as `{"t":"sig","from":…,"box"}` | the box (§2.2); the server can't read it |
| either → | `{"t":"relay.reg","id","nk":"nodekey:<64hex>","rg":"tor1"}` → `{"t":"relay.ok","id","exp","tok"}` | the hello/join session; `tok` is Ed25519-signed by the server (kid `test-1`) |

Keys: `P_slot = HKDF-SHA256(pair_psk, salt=∅, "sl1/slot-secret")`, `jk = HKDF(P_slot,"sl1/join")`,
`env_k = HKDF(P_slot,"sl1/env")`. The server only ever holds `jk`.

### 2.2 Sealed box (peer ↔ peer, opaque to the server)

`box = b64u(nonce(12) ‖ ChaCha20-Poly1305(env_k, nonce, json, AAD) ‖ tag(16))`,
`AAD = "sl1/box" ‖ home(16) ‖ slot(8) ‖ dir`, with dir 0x01 client→stick and 0x02 stick→client.

Inner JSON: `{"k":"cand","sid","seq","c":[{"a":"ip:port","p":"host|v6|stun4|stun6|cfg"}]}`,
`{"k":"derp","sid","nk":"nodekey:<64hex>","rg":"tor1"}` and `{"k":"bye","sid"}`.
**`sid` belongs to the sender** (Q-N8). Each side picks its own random 8-byte sid. A receiver must not require the peer's
sid to equal its own. The stick sends its `cand`+`derp` on `peer join` (and to any conn it hasn't answered yet).

`p` is a hint from a fixed set (Q-N9, matches what StickLLM's `sticklinkd` sends): `host` (local IPv4 interface),
`v6` (local IPv6 interface), `stun4` / `stun6` (STUN-mapped address), `cfg` (configured by hand). Receivers must try
every candidate whatever its `p`, and must accept (ignore) unknown values. **`lan4` is not part of the set.**

**`bye` and the WSS after the path is up (Q-N10).** A path change (direct → DERP, or back) is **not** the end of a
session. Never send `bye` for it. `bye` means "this session is over for good" (user disconnect, unpair, shutdown). Send
it only if the WSS is still open; never reconnect just to send `bye`. A client may close the WSS (code 1000) once it
holds the stick's `cand`+`derp`, and the KVM profile does exactly that to save RAM. Clients reconnect
(`hello`/`join`) only to refresh the relay permit (at ⅔ TTL) or to re-signal after the Noise session is lost. On the
stick side, `peer leave` only means "off signalling". It does **not** end the Noise session. Receivers must not rely
on `bye`: each side drops a session after its own idle timeout, and on `bye` it drops only that `sid`'s state.

### 2.3 Datagrams: the same bytes over UDP and inside DERP (Q-N7, adopted from StickLLM `link.py`)

| type | layout | size |
|---|---|---|
| `0x01` INIT | `slot(8) ‖ sidx(u32 BE) ‖ msg1(96)` | 109 B |
| `0x02` RESP | `sidx(u32 BE, responder's) ‖ ridx(u32 BE, = initiator's sidx) ‖ msg2(48)` | 57 B |
| `0x04` DATA | `ridx(u32 BE, receiver's index) ‖ ctr(u64 LE) ‖ ChaChaPoly(k, nonce=ctr, AD=∅, pt)` | ≥ 29 B |
| `0x05` PUNCH | 8 random bytes | 9 B |

Noise: `Noise_IKpsk2_25519_ChaChaPoly_SHA256`, prologue **v2 (96 B, Q-N1)** `"sl1/net" ‖ 0x01 ‖ home(16) ‖ slot(8) ‖ kvm_static_pub(32) ‖ stick_static_pub(32)`
(initiator's static first, responder's second; the old 31 B form is refused), psk = `pair_psk`,
the KVM is the initiator, and `rs` = the stick's pinned static key. Data plaintext is `type(1) ‖ body`: `0x01` PING id(8),
`0x02` PONG (echoes the body), `0x10` ECHO_REQ, `0x11` ECHO_REP, `0x20` APP. Rules: the responder drops INIT for a
different slot or an unpinned static key, answers on the path the INIT arrived on, and resends the cached RESP for a duplicate
msg1 (so INIT may be sent on every path at once). The receiver keeps a 64-entry replay window on `ctr`. **AI KVM:** `sl1_net.h` has the crypto but no
framing. Please implement exactly this table.

Firmware limits and rules (AI KVM, adopted for every implementation):
* **Max datagram 1280 B**, header + ciphertext + tag included, on UDP and inside DERP. A sender must not exceed it, and
  a receiver may drop anything larger. The largest DATA plaintext is therefore 1280 − 29 = 1251 B (type byte included).
  slpeer drops oversized DATA and never replies above 1280 B (self-test: the largest ECHO_REQ is exactly 1280 B).
* **The replay window advances only after the AEAD tag verifies.** Check the window first (read-only), decrypt, then mark
  `ctr` as seen. A forged packet with a high `ctr` must not shift the window. slpeer does this (`openData` →
  `replayOK(ctr,false)`, decrypt, `replayOK(ctr,true)`; self-test "forged DATA … does not advance the replay window").
* **Privacy:** the INIT `slot` (8 B) travels in clear, so anyone on the UDP path or the DERP operator can see it. It is a
  stable pseudonymous id for the pairing, which links sessions of that pairing across networks. **Accepted for now**
  (Q-N11; see API.md §4.1).

## 3. derper, STUN, cert pinning (StickLLM 3, AI KVM 1)

* URL `https://<host>:<D>/derp`, region id 900, region code `tor1`. The hostname is an IP, so there's no SNI check. Use
  `--derp-sni derp.sl1.test` if your client insists on a name.
* Pin the leaf cert: SHA-256 of the DER = `stack.json → derp.cert_sha256`, which is printed by `start-stack.sh` as
  `derper cert SHA-256 …`. The PEM is at `stack.json → derp.cert_pem`.
  - Tailscale DERPMap: `DERPNode{HostName:"<ip>", DERPPort:<D>, STUNPort:<S>, CertName:"sha256-raw:<hex>"}`
  - StickLLM `link.Endpoint`: `--derp-pin <hex>` (verified working, see §8).
* STUN is derper's built-in server on `<S>/udp`. **It answers only Tailscale-style requests.** A Binding Request must
  carry the SOFTWARE attribute (0x8022) with the value `tailnode` (8 B, so no padding) and must end with FINGERPRINT
  (0x8028 = CRC-32 of the message so far XOR 0x5354554e). Anything else is silently dropped. The answer carries
  XOR-MAPPED-ADDRESS (0x0020). See `relay/ts/net/stun/stun.go` (`Request`, `ParseBindingRequest`). A generic RFC 5389
  client with no SOFTWARE attribute gets no answer, so it never learns its `stun4` candidate.
* Admission: derper asks the sidecar for every client node key, and the sidecar allows only keys in the Worker's signed
  allowlist. A peer must therefore `relay.reg` its DERP node key **before** connecting to DERP, and allow about 1 s for the
  sidecar to pull it. A first connect before that is refused, which is expected (fail-closed). derper logs it as
  `rejected: admission controller … not allowed`. `sticklinkd` currently dials DERP once before `relay.reg` and
  succeeds on its retry about 1 s later. That's harmless, but registering first avoids the log line.

## 4. Test peer, pairing file and identity file (StickLLM 4, AI KVM 2)

Fixture pair (deterministic, public test values, from `vectors/`, which are **frozen and unchanged**):

| | stick (`stick_e2e`) | KVM (`kvm1`) |
|---|---|---|
| dev | `K1K-6g67fvK0xtrqKYAdRA` | `DrZAMLbX5cMTxTnX-wZXjg` |
| home | `3eIldt_LyZEp0XzkDI1Uog` (the vector home) | — |
| slot | `PTqAZFSNjug`, already added (the seed does `slot.add`) | — |
| static pub | `7b0d47d9…1b14` (priv 32×0x33) | `7b4e909b…3f13` (priv 32×0x11) |

Files (mode 600, written by `seed-dev.mjs` to `worker/fixtures/e2e/` and copied into `$SL_STATE`):

`pairing.json`, which pins **both** X25519 static keys:
```json
{"format":"sl1-e2e-pairing/1","home":"<b64u 16>","slot":"<b64u 8>","pair_psk":"<hex 32>",
 "stick":{"static_pub":"<hex 32>"},"kvm":{"static_pub":"<hex 32>"},
 "derived":{"P_slot":"<hex>","jk":"<hex>","env_k":"<hex>","prologue":"<hex 96>"}}
```
`stick.id.json` / `kvm.id.json`, one per peer:
```json
{"format":"sl1-e2e-identity/2","role":"stick|kvm","dev":"<b64u 16>","auth_seed":"<b64u 32>","static_priv":"<hex 32>"}
```
`auth_seed` is the device's TEST Ed25519 server-auth seed (D1 holds only its public key `ak`). On real devices the
seed is generated on the device and never exported; only `ak` goes to provisioning.
`derived` is informative: implementations must recompute it and compare. **For AI KVM:** this pairing file is the
stand-in for what USB XX pairing produces (pair_psk, the stick's static key, home and slot). `sl1-kvm-sim` can load it
directly and use `kvm.id.json` for `hello` (optional) and the static key. **For StickLLM:** sticklinkd keeps its own
offer/answer pairing (`sl1-testpair-offer/answer`, gated by `STICKLINK_TESTING=1`). Both work against this server. The
interop script shows how to convert a sticklinkd pairing into this format (§8).

**Slot assignment when pairing over USB (AI KVM 2):** the stick picks a random 8-byte `slot_id`, registers it with
`slot.add{slot, jk}` on its own signalling session, and gives the KVM `home_id(16) ‖ slot_id(8)` in USB frame
**0x07 HOME_SLOT**. The KVM never talks to the server about slots. It only `join`s with the MAC. The server only
checks that the slot is unique within the home and not revoked. In the e2e fixture, the seed has already done the stick's
`slot.add`, so a KVM can join even when no real stick has paired.

**Test peer:** `server/e2e/bin/slpeer` (Go, static linux/amd64). It plays the stick, the KVM, or both (E2E.md).
The stick responder is already running on the box (§0). To test `sl1-kvm-sim`, connect it as the KVM with
`stack.json` + `pairing.json` + `kvm.id.json`. Success means `joined.peer:"online"`, a RESP to your INIT and PONGs.

## 5. Forcing the relay (StickLLM 5)

1. **Flag:** `slpeer -force-relay` / sticklinkd `--force-relay` / sl_testpeer `--force-relay`. With it, no candidates
   are advertised and there's no STUN and no UDP. INIT goes straight over DERP. Forcing either side is enough, because the
   other side then has no candidates to try.
2. **Block UDP in the VM** (Debian guest, nftables):
   ```
   nft add table inet sltest
   nft add chain inet sltest out '{ type filter hook output priority 0; }'
   nft add rule inet sltest out udp dport != 53 drop      # DERP is TCP/TLS, so it still works
   # undo: nft delete table inet sltest
   ```
   Expect the handshake on DERP after ~1.5 s (INIT retries on UDP every 0.5 s, then DERP starts).
   `slpeer -block-udp` simulates the same thing in-process. Windows host: block outbound UDP for qemu.exe in Windows Defender Firewall.
3. Note that with QEMU SLIRP, the direct path works through the stick's PUNCH (peer-reflexive), so a "direct" result from
   inside SLIRP is real. To exercise only the relay path, use (1) or (2).

## 6. Local relay admission (AI KVM 3)

* The sidecar runs with **public test keys** (`admit-token`, `admit-keys` = kid `test-1` + its Ed25519 public key),
  generated by `start-stack.sh` from `worker/scripts/dev-vars.mjs`. It pulls the signed allowlist from the local Worker
  (`/v1/relay/allowlist`, `/v1/relay/feed`) and answers derper's `/derp/admit`.
* How `relay.reg` works: after `join` (or `hello`), send `{"t":"relay.reg","id":N,"nk":"nodekey:<64 lowercase hex of
  your DERP node public key>","rg":"tor1"}`. The server checks entitlement (the KVM's own `cls:"kvm"` if it sent
  `hello`, otherwise the stick owner's), stores a 12 h permit, bumps the allowlist and pushes a feed `chg`. The sidecar
  pulls the delta within milliseconds. Reply: `{"t":"relay.ok","id":N,"exp":<s>,"tok":"…"}`. Keep `tok` only to time the
  refresh (⅔ of 12 h). Then connect to DERP with that node key.
* Quota: 10 `relay.reg` per holder per day in production. The local stack sets a test override of 1000 (Q-S21, honoured only
  with a `test-` signing kid) so repeated runs don't hit `err{rate}`.

## 7. Desktop bundle (StickLLM: the VM on DESKTOP-65FCPD4)

**Built:** `/workspace/sticklink/server/dist/sticklink-e2e-bundle.tar.gz` (27 MB; sha256 in
`sticklink-e2e-bundle.tar.gz.sha256` next to it). Rebuild with `e2e/bundle.sh`.
It contains `e2e/bin/` (slpeer, derper, sticklink-admit; linux/amd64 static), the Worker sources + lockfile (no
node_modules), the e2e scripts, `vectors/`, the four docs and a top-level `README.md`. Requirements: bash, node ≥ 22 +
npm (internet for `npm ci` on the first start), openssl, python3, iproute2. Run it on Linux: WSL2, the VM host, or a
second Linux VM. **Verified:** a fresh extract to /tmp on the box (third port set) gave start-stack OK and **smoke 8/8**.

```
tar xzf sticklink-e2e-bundle.tar.gz && cd sticklink-e2e/server
SL_HOST=<address the VM uses to reach this machine> e2e/start-stack.sh --detach   # needs node ≥ 22 + npm (npm ci on first run)
e2e/smoke.sh --serve
```
Then point the VM at `e2e/state/stack.json` (bridged/LAN) or `stack.qemu.json` (SLIRP, 10.0.2.2).
WSL2 caveat: default NAT networking forwards only **TCP** on localhost to Windows, so WS and DERP work but
STUN and direct UDP don't. Use `networkingMode=mirrored` in `.wslconfig`, or run the bundle in a second Linux VM.

## 8. Interop status

`e2e/interop-stickllm.sh` (read-only use of StickLLM's tree, commit `cca59b9`), last run 2026-10-29 4:23 PM ET:
**FAIL, expected** until StickLLM implements the v2 changes below. (A) `sl_testpeer` → slpeer stick, direct and DERP:
the stick rejects msg1 (`msg1 auth failed`) because `noise.py` still uses the 31 B prologue. (B) slpeer kvm →
`sticklinkd`: skipped, `sticklinkd init` has no `--auth-seed-file` and `sigcrypto.py` still sends the HMAC `mac` hello,
which the Worker refuses (4401). Before v2 (3:21 PM ET) all 5 cases passed.

**StickLLM changes needed (v2, Nink 2026-10-29):**
1. Device auth key: generate an Ed25519 seed on the stick (OS RNG), store it 0600 next to the registry, export only the
   public key for `provision.mjs --ak`. Test-only: `sticklinkd init --auth-seed-file F` (replaces `--dev-secret-file`).
2. `sigcrypto.py`: `hello` sends `sig = Ed25519(seed, b"sl1/dev-hello/v1\0" + n + dev + role + home)` instead of `mac`.
3. `noise.py:43` (`link.py`, `sl_testpeer.py`): prologue = `b"sl1/net" + b"\x01" + home + slot + kvm_static_pub + stick_static_pub` (96 B).
4. `daemon.py` `rev` handler: on `{"t":"rev","slot"}` call `link.apply_revocation(slot)` **immediately** (kill the
   live session, refuse msg1 for that slot/key), then pull `revoked.get` to persist. Today it only logs when `set` is absent.
5. Treat `slot.add` → `err{auth}` as "revoked": drop the slot locally, don't retry.
6. Optional: `auth.rotate` and `audit.get` (API §3.1, §5.1). Update `mock_signal.py` to the new `rev` shape.
7. Re-run its tests against `vectors/*-v2.json`.

**AI KVM changes needed (v2):**
1. Add Ed25519: `espressif/libsodium` (ESP Component Registry) or Monocypher; mbedTLS 3.6 has none.
2. First boot: generate the 32 B auth seed from the TRNG, keep it in encrypted NVS, export only the public key for
   `provision.mjs --kind kvm --ak`. Never export the seed, the Noise static key or `pair_psk`.
3. `hello` (optional for the KVM) sends `sig` (64 B, 86 chars; the frame is 162 B) instead of `mac`.
4. `sl1_noise`/`sl1_net` and `sl1-kvm-sim`/tests: 96 B prologue as above (initiator = KVM).
5. Handle close **4403** (revoked: delete the pairing, stop reconnecting) and **4401 `rotated`**.
6. Optional: `auth.rotate`. Re-run against `vectors/*-v2.json`.

## 9. Frozen? (AI KVM 4)

**v2 (2026-10-29 4:12 PM ET, Nink's decisions):** `vectors/signalling-v2.json` and `vectors/ikpsk2-v2.json` replace the
v1 files (signed hello, 96 B prologue). Everything else in them (slot derivation, join MAC, box, permits, allowlist,
revoked page) is byte-identical to v1. v2 is now frozen; any further change gets `-v3`.
