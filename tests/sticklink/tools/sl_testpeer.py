#!/usr/bin/env python3
"""TEST-ONLY sticklink client (plays the AI KVM / phone role).

  sl_testpeer.py pair    --offer offer.json --state peer.json --answer answer.json [--name kvm-sim --kind kvm]
  sl_testpeer.py connect --state peer.json --ws URL [--derp URL] [--derp-ca F] [--stun H:P]
                         [--force-relay] [--duration 10] [--expect direct|derp|any]

connect: join the stick's home slot, exchange sealed cand/derp boxes, Noise
IKpsk2 handshake as initiator (direct first, DERP after 1.5 s), then echo
traffic for --duration seconds. Prints one JSON summary line last; exit 0 only
if the handshake finished, echoes came back and --expect holds at the end.
"""
import argparse
import asyncio
import json
import os
import secrets
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
for cand in (HERE.parents[3] / "overlay/usr/local/lib", Path("/usr/local/lib")):
    if (cand / "sticklink").is_dir():
        sys.path.insert(0, str(cand))
        break
os.environ.setdefault("STICKLINK_TESTING", "1")

from sticklink import crypto, link, pairfile, sigcrypto as sc  # noqa: E402
from sticklink.derp import nodekey_str, parse_nodekey  # noqa: E402
from sticklink.sigclient import SigClient, SigError  # noqa: E402
from sticklink.util import b64u, unb64u  # noqa: E402


def log(m):
    print(f"{time.strftime('%H:%M:%S')} testpeer: {m}", flush=True)


def cmd_pair(a):
    offer = json.loads(Path(a.offer).read_text())
    priv = crypto.x25519_generate()
    ans = pairfile.make_answer(offer, priv, a.name, a.kind)
    st = {"v": 1, "priv": b64u(priv), "stick_pub": offer["stick_pub"], "pair_psk": offer["pair_psk"],
          "home": offer["home"], "slot": offer["slot"], "derp_priv": b64u(crypto.x25519_generate())}
    pairfile.dump(st, a.state)
    pairfile.dump(ans, a.answer)
    print(json.dumps({"answer": a.answer, "my_key_fp": link.fp(crypto.x25519_public(priv))}))


def state_from_e2e(pairing, identity):
    """Sticklink fixture files (pairing.json + kvm.id.json) -> our peer state (test-only)."""
    from sticklink import e2einterop
    p, i = e2einterop.load_pairing(pairing), e2einterop.load_identity(identity, "kvm")
    if crypto.x25519_public(i["static_priv"]) != p["kvm_pub"]:
        raise SystemExit("kvm static_priv does not match pairing kvm.static_pub")
    return {"priv": b64u(i["static_priv"]), "stick_pub": b64u(p["stick_pub"]), "pair_psk": b64u(p["pair_psk"]),
            "home": b64u(p["home"]), "slot": b64u(p["slot"]), "derp_priv": b64u(crypto.x25519_generate())}


async def mock_revoke(ws_url, home, slot):
    """MOCK-ONLY: ask mock_signal to revoke our slot and push rev{set} to the stick."""
    import websockets
    async with websockets.connect(ws_url, subprotocols=["sticklink.1"]) as w:
        await w.recv()  # welcome
        await w.send(json.dumps({"t": "_mock.revoke", "id": 1, "home": home, "set": [{"slot": slot}]}))
        log(f"mock revoke -> {await w.recv()}")


async def connect(a):
    if a.stack:
        from sticklink import e2einterop
        for k, v in e2einterop.load_stack(a.stack).items():
            if getattr(a, k, None) is None:
                setattr(a, k, v)
    if not a.ws:
        raise SystemExit("need --ws or --stack")
    a.rg = a.rg or "tor1"
    st = state_from_e2e(a.pairing, a.identity) if a.pairing else json.loads(Path(a.state).read_text())
    psk, home, slot = unb64u(st["pair_psk"], 32), unb64u(st["home"], 16), unb64u(st["slot"], 8)
    envk = sc.env_key(psk)
    ep = link.Endpoint(derp_url=a.derp, derp_priv=unb64u(st["derp_priv"], 32), derp_cafile=a.derp_ca, derp_pin=a.derp_pin, derp_sni=a.derp_sni,
                       stun_addr=a.stun, force_relay=a.force_relay, extra_cands=a.extra_cand, log=log)
    await ep.start()
    ini = link.Initiator(ep, unb64u(st["priv"], 32), unb64u(st["stick_pub"], 32), psk, home, slot, log=log)
    peer = ini.peer
    echoes = {}
    sent = {}

    def on_data(typ, body, path):
        if typ == link.D_ECHO_REP and len(body) >= 4:
            seq = int.from_bytes(body[:4], "big")
            if seq in sent and seq not in echoes:
                echoes[seq] = (path[0], (time.monotonic() - sent[seq]) * 1000)
    peer.on_data = on_data

    cl = SigClient(a.ws, log=log)
    await cl.connect({"home": st["home"]})
    for attempt in range(30):
        try:
            j = await cl.request({"t": "join", "home": st["home"], "slot": st["slot"],
                                  "mac": b64u(sc.join_mac(sc.join_key(psk), cl.nonce, home, slot))})
        except SigError as e:
            log(f"join failed: {e.code}")
            return 2
        if j.get("peer") == "online":
            break
        log("stick offline; retrying join in 2 s")
        await cl.close()
        await asyncio.sleep(2)
        cl = SigClient(a.ws, log=log)
        await cl.connect({"home": st["home"]})
    log(f"joined as {j.get('conn')}, stick online")
    if a.derp:
        try:
            await cl.request({"t": "relay.reg", "nk": nodekey_str(ep.derp_pub), "rg": a.rg})
            log(f"relay.reg ok ({link.fp(ep.derp_pub)})")
        except SigError as e:
            log(f"relay.reg failed: {e.code}")
        if not await ep.wait_derp(10):
            log("DERP not connected (relay fallback unavailable)")
    sid = b64u(secrets.token_bytes(8))
    cands = await ep.candidates(probe_host=a.stun.rsplit(":", 1)[0] if a.stun else None)
    for inner in ({"k": "cand", "sid": sid, "seq": 1, "c": cands},
                  {"k": "derp", "sid": sid, "nk": nodekey_str(ep.derp_pub), "rg": a.rg} if a.derp else None):
        if inner:
            await cl.send({"t": "sig", "to": "stick", "box": sc.seal_box(envk, home, slot, sc.DIR_C2S, inner)})
    log(f"sent {len(cands)} candidates{' (force-relay)' if a.force_relay else ''}")
    got = {"cand": False, "derp": False}
    end = time.monotonic() + 5
    while time.monotonic() < end and not (got["cand"] and (got["derp"] or not a.derp)):
        try:
            m = await asyncio.wait_for(cl.events.get(), end - time.monotonic())
        except asyncio.TimeoutError:
            break
        if m.get("t") == "sig":
            inner = sc.open_box(envk, home, slot, sc.DIR_S2C, m["box"])
            if inner["k"] == "cand":
                peer.set_cands(inner.get("c") or [])
                got["cand"] = True
            elif inner["k"] == "derp":
                peer.derp_key = parse_nodekey(inner["nk"])
                got["derp"] = True
                peer.note(f"stick derp key {link.fp(peer.derp_key)}")
        elif m.get("t") == "err":
            log(f"signalling err {m.get('code')}")
    t0 = time.monotonic()
    ok = await ini.handshake()
    hs_ms = (time.monotonic() - t0) * 1000
    result = {"handshake": ok, "handshake_ms": round(hs_ms), "first_path": ini.first_path[0] if ini.first_path else None}
    if ok:
        mt = asyncio.create_task(ini.maintain())
        seq = 0
        t_end = time.monotonic() + a.duration
        t_start = time.monotonic()
        stale_sent = False
        revoke_t = None
        while time.monotonic() < t_end:
            el = time.monotonic() - t_start
            if a.block_direct_at is not None and el >= a.block_direct_at and not ep.force_relay and \
                    (a.unblock_direct_at is None or el < a.unblock_direct_at):
                ep.force_relay = True  # test: direct UDP now dropped both ways on this side
                peer.note("test: direct UDP blocked")
            if a.stale_bye_at is not None and el >= a.stale_bye_at and not stale_sent:
                stale_sent = True  # a bye for a sid that is not our current one: the stick must ignore it
                await cl.send({"t": "sig", "to": "stick", "box": sc.seal_box(envk, home, slot, sc.DIR_C2S,
                                                                            {"k": "bye", "sid": b64u(secrets.token_bytes(8))})})
                peer.note("test: sent bye for an old sid")
            if a.revoke_at is not None and el >= a.revoke_at and revoke_t is None:
                revoke_t = time.monotonic()
                if a.revoke_via == "mock":
                    await mock_revoke(a.ws, st["home"], st["slot"])
                peer.note(f"test: revocation issued ({a.revoke_via})")
            if a.unblock_direct_at is not None and el >= a.unblock_direct_at and ep.force_relay and not a.force_relay:
                ep.force_relay = False
                peer.note("test: direct UDP unblocked")
            seq += 1
            sent[seq] = time.monotonic()
            peer.send_data(link.D_ECHO_REQ, seq.to_bytes(4, "big") + secrets.token_bytes(32))
            await asyncio.sleep(0.25)
        await asyncio.sleep(1)
        mt.cancel()
        by_path = {}
        for p, rtt in echoes.values():
            by_path.setdefault(p, []).append(rtt)
        last = max(echoes) if echoes else None
        result.update({"sent": seq, "echoed": len(echoes),
                       "by_path": {k: {"n": len(v), "rtt_ms_median": round(sorted(v)[len(v) // 2], 1)} for k, v in by_path.items()},
                       "final_path": echoes[last][0] if last else None,
                       "events": [e for _, e in peer.events if "path" in e or "handshake" in e or "test:" in e]})
        if revoke_t is not None:
            before = [q for q, t in sent.items() if t < revoke_t]
            after = [q for q, t in sent.items() if t > revoke_t + 1.5]
            result["revoke"] = {"echoed_before": sum(q in echoes for q in before), "sent_before": len(before),
                                "echoed_after": sum(q in echoes for q in after), "sent_after": len(after)}
            # a brand-new handshake (fresh ephemeral, same paths) must get no reply
            ini._hs, ini._msg2, ini._init = None, None, None
            ini.established.clear()
            peer.session = None
            result["revoke"]["rehandshake_ok"] = await ini.handshake(timeout=5)
    if a.bye:
        await cl.send({"t": "sig", "to": "stick", "box": sc.seal_box(envk, home, slot, sc.DIR_C2S, {"k": "bye", "sid": sid})})
        await asyncio.sleep(0.5)
    await cl.close()
    await ep.close()
    exp_ok = a.expect == "any" or result.get("final_path") == {"direct": "udp", "derp": "derp"}[a.expect]
    if a.expect_paths:
        exp_ok = exp_ok and all(x in result.get("by_path", {}) for x in a.expect_paths.split(","))
    if "revoke" in result:
        r = result["revoke"]
        result["pass"] = bool(ok and r["sent_before"] and r["echoed_before"] >= r["sent_before"] * a.min_echo
                              and r["sent_after"] and r["echoed_after"] == 0 and not r["rehandshake_ok"])
    else:
        result["pass"] = bool(ok and result.get("echoed", 0) >= max(1, result.get("sent", 0) * a.min_echo) and exp_ok)
    print("RESULT " + json.dumps(result), flush=True)
    return 0 if result["pass"] else 1


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair")
    p.add_argument("--offer", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--answer", required=True)
    p.add_argument("--name", default="kvm-sim")
    p.add_argument("--kind", default="kvm")
    p = sub.add_parser("connect")
    p.add_argument("--state", help="our own pairing state (from 'pair')")
    p.add_argument("--pairing", help="Sticklink sl1-e2e-pairing/1 file (with --identity kvm.id.json)")
    p.add_argument("--identity")
    p.add_argument("--stack", help="Sticklink sl1-e2e-stack/1 (ws, derp + pin, stun); flags override")
    p.add_argument("--ws")
    p.add_argument("--derp")
    p.add_argument("--derp-ca")
    p.add_argument("--derp-pin")
    p.add_argument("--derp-sni")
    p.add_argument("--rg")
    p.add_argument("--stun")
    p.add_argument("--extra-cand", action="append", default=[])
    p.add_argument("--force-relay", action="store_true")
    p.add_argument("--duration", type=float, default=8)
    p.add_argument("--block-direct-at", type=float, help="test: drop direct UDP after N s of traffic")
    p.add_argument("--unblock-direct-at", type=float, help="test: restore direct UDP after N s")
    p.add_argument("--expect-paths", help="comma list of paths that must have carried echoes, e.g. udp,derp")
    p.add_argument("--bye", action="store_true", help="send a bye for our current sid before leaving")
    p.add_argument("--stale-bye-at", type=float, help="test: send a bye with a different (old) sid after N s")
    p.add_argument("--min-echo", type=float, default=0.8)
    p.add_argument("--revoke-at", type=float, help="test: revocation happens after N s (pass = echoes stop, rehandshake refused)")
    p.add_argument("--revoke-via", choices=["mock", "external"], default="mock")
    p.add_argument("--expect", choices=["direct", "derp", "any"], default="any")
    a = ap.parse_args()
    if a.cmd == "pair":
        cmd_pair(a)
    else:
        sys.exit(asyncio.run(connect(a)))


if __name__ == "__main__":
    main()
