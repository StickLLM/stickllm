<!-- Copyright (c) 2026 Nink Inc. All rights reserved. -->
# sl1 end-to-end connectivity test (local only, nothing deployed)

Two peers in one home: the **stick** (Noise responder, `hello` as server) and the **AI KVM**
(Noise initiator, `join` into a slot). The test covers rendezvous, sealed signalling,
**direct UDP first, then fallback to a local DERP relay** that admits node keys through the
`sticklink-admit` sidecar (fail-closed).

```
 slpeer -role kvm ─┐  ws /v1/ws  ┌─ wrangler dev (Worker + DO + D1, local) ──feed/allowlist──┐
                   ├────────────►│                                                           ▼
 slpeer -role stick┘             └─ relay.reg → permit → allowlist ──► sticklink-admit :9099 ◄─ derper verify-client
        ▲   UDP 0x01..0x05 (direct, Q-N7 framing)   ▲                       derper :8443 TLS (self-signed) + STUN :3478
        └──────────────── same packets inside DERP ─┘
```

## Run it (one command each)

```
e2e/start-stack.sh --detach   # build bins if needed, npm ci if needed, seed, start Worker + sidecar + derper
e2e/smoke.sh                  # 8 cases; prints PASS/FAIL and a RESULT JSON per case; SMOKE OK at the end
e2e/smoke.sh --serve          # same, and leaves a stick responder running for an external KVM
e2e/interop-stickllm.sh       # cross-check against StickLLM's Python sticklink lib (both directions)
e2e/stop-stack.sh
```

The defaults are ports 8787/8443/3478/9099 and state in `e2e/state/`. Several stacks can share a host with
`SL_STATE=… SL_PORT_WORKER=… SL_PORT_DERP=… SL_PORT_STUN=… SL_PORT_ADMIT=…`. Each stack has its own D1
(`$SL_STATE/d1`) and vars file (`$SL_STATE/dev.vars`), so none of them touches `worker/.wrangler` or
`worker/.dev.vars`. **The box instance right now** runs with `SL_STATE=e2e/state-box` and ports
8797/8453/3488/9109, because another agent's `wrangler dev` holds 8787 (see ENDPOINTS.md §0).

Other env vars: `SL_HOST` (the address written into stack.json and the cert SAN), `SL_CERT_IPS` (extra SANs),
`SL_BIND` (default 0.0.0.0), `SL_WORKER_TLS=1` (wss with the same self-signed cert), `SL_RESET=1` (wipes D1 and
the sidecar state), `SL_RELAY_REG_PER_DAY` (test quota, default 1000; see Q-S21).

## Smoke cases (`e2e/smoke.sh`)

| case | what | expect |
|---|---|---|
| selftest | slpeer against `vectors/*.json` (14 checks: KDFs, MACs, box, IK msg1/msg2, transport) | all match |
| direct | `-role both`: stick + KVM in one process, UDP allowed | `path:"direct"` |
| force-relay | `-force-relay`: no candidates, no STUN, no UDP sends | `path:"derp"` |
| block-udp | KVM drops all UDP (simulates a firewall) | `path:"derp"` after ~1.5 s |
| bad-psk | KVM uses a wrong psk | `msg2 auth failed` (IKpsk2 fails at msg2) |
| bad-static | KVM's static key isn't pinned | stick drops msg1 → timeout |
| split-direct / split-relay | separate stick process, separate KVM process | direct / derp |

Last run on the box (2026-10-29, 3:20 PM ET): **8/8 PASS**. Direct: signalling ~35 ms, handshake ~1 ms.
block-udp: handshake 1505 ms through DERP.

`interop-stickllm.sh`, same run: **5/5 PASS**. StickLLM `sl_testpeer` → slpeer stick (direct, derp), and
slpeer kvm → StickLLM `sticklinkd` (direct, derp, block-udp), using sticklinkd's own offer/answer pairing.

## Test client: `e2e/bin/slpeer` (Go, `e2e/slpeer/`)

```
slpeer -role both  -stack stack.json -ids DIR [-force-relay] [-block-udp] [-bad-psk] [-bad-static]
slpeer -role stick -stack stack.json -pair pairing.json -id stick.id.json [-force-relay]
slpeer -role kvm   -stack stack.json -pair pairing.json -id kvm.id.json  [-force-relay] [-block-udp]
slpeer -selftest -vectors ../vectors
```
The last stdout line is `RESULT {json}` with `ok`, `path` (direct|derp), `via`, `signalling_ms`, `handshake_ms`,
`pings`, `pongs` and `rtt_ms`, or `{"ok":false,"error":…}`. The exit code is 0 only if ok.

Flow (KVM): WS `?home=`, then `welcome`, `hello`(client, kvm1), `join`(slot MAC), `relay.reg`, DERP connect, sealed `cand`+`derp`
→ stick. In parallel it waits for the stick's sealed `cand`+`derp`. The stick sends them on `peer join` under its own `sid`
(Q-N8). It sends INIT to every candidate every 0.5 s, plus to peer-reflexive sources learnt from the stick's PUNCH packets,
and also over DERP after 1.5 s (immediately if forced or there are no candidates). The first valid RESP wins.
Then 5 PING/PONG round trips.

Stick on `{"k":"bye","sid"}` (API.md §4.1, Q-N10): if `sid` is the KVM's current sid (from its `cand`/`derp`), or none is
known yet, it drops the Noise session (and its replay window), the duplicate-INIT cache, the KVM's candidates and any
pending punches, then logs `peer <conn> bye (sid …): dropped …`. A `bye` for another sid is stale and is ignored.
`peer leave` drops nothing. The self-test covers both cases.

**Non-root and multi-NIC hosts.** slpeer calls `netns.SetEnabled(false)` at startup, so DERP (and any other
tailscale dial) uses plain kernel-routed sockets. Without it, a non-root slpeer cannot set `SO_MARK`, and tailscale's
netns falls back to `SO_BINDTODEVICE` on the default-route NIC. A derper on a private link that is not the default
route (for example the QEMU 192.168.77.0/24 link next to the NAT card) then fails with `derp connect … context deadline
exceeded`; loopback addresses are exempt, which is why the box stack never showed it. Reproduced as uid 1000 with
derper at a non-default-route local IP: the old build failed and the fixed build passed. The real derper and sticklinkd
are not affected (sticklinkd does not use tailscale's netns).
Packet framing (Q-N7, the same as StickLLM `link.py`, the same over UDP and inside DERP) is in ENDPOINTS.md §2.3.

## In a VM (StickLLM, AI KVM on the desktop)

See ENDPOINTS.md §1 (addresses), §5 (forcing the relay) and §7 (desktop bundle).
