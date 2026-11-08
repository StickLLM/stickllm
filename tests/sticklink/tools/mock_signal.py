#!/usr/bin/env python3
"""TEST-ONLY local mock of the sticklink signalling Worker (server/API.md subset):
welcome, ping, hello(server|client; v2 Ed25519 sig), join, sig, slot.add/del/list, relay.reg/del,
peer join/leave, rev{rc,slot,why} push, revoked.get (signed pages, kid test-1 = the public
TEST signing key from signalling-v2.json), auth.rotate. In-memory state; no persistence; no rate limits. Use the real
Worker (wrangler dev) when available -- this exists so the stick side can be
built and tested before the real endpoints are handed over.

  mock_signal.py --listen 0.0.0.0:8788 --fixtures dev-fixtures.json
"""
import argparse
import asyncio
import hashlib
import hmac
import json
import secrets
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "overlay/usr/local/lib"))
from cryptography.exceptions import InvalidSignature  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: E402

from sticklink import crypto, sigcrypto as sc  # noqa: E402
from sticklink.util import b64u, unb64u  # noqa: E402

DEVICES = {}   # dev b64 -> {"ak": Ed25519 pub, "home": b64|None, "gen": int}
SIGN = {"kid": "test-1", "seed": None}
HOMES = {}     # home b64 -> {"stick": ws|None, "slots": {slot: {"jk","adm","st"}}, "clients": {conn: (ws, slot)}}
RELAY = {}     # nk -> exp
CONN_IDS = iter(range(1, 1 << 30))


def home_state(h):
    return HOMES.setdefault(h, {"stick": None, "slots": {}, "clients": {}})


async def send(ws, m):
    try:
        await ws.send(json.dumps(m, separators=(",", ":")))
    except websockets.ConnectionClosed:
        pass


def _ed_ok(pub, sig, msg):
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, msg)
        return True
    except (InvalidSignature, ValueError):
        return False


def revoked_page(hs, home, n, after):
    lst = hs.get("revoked", [])
    s = lst[after:after + 64]
    nxt = after + len(s)
    body = json.dumps({"v": 1, "home": home, "n": b64u(n), "after": after, "next": nxt, "more": nxt < len(lst),
                       "rc": hs.get("rc", 0), "iat": int(time.time()), "s": s}, separators=(",", ":")).encode()
    return {"kid": SIGN["kid"], "body": b64u(body), "sig": b64u(crypto.ed25519_sign(SIGN["seed"], b"sl1/revoked/v1\x00" + body))}


async def revoke_slot(hs, slot, why):
    hs["slots"].pop(slot, None)
    if slot not in hs.setdefault("revoked", []):
        hs["revoked"].append(slot)
    hs["rc"] = hs.get("rc", 0) + 1
    for c, (w, sl) in list(hs["clients"].items()):
        if sl == slot:
            await w.close(4403, "revoked")
    if hs["stick"]:
        await send(hs["stick"], {"t": "rev", "rc": hs["rc"], "slot": slot, "why": why})


def err(mid, code):
    return {"t": "err", **({"id": mid} if mid is not None else {}), "code": code}


async def handler(ws, path):
    q = parse_qs(urlsplit(path).query)
    if not urlsplit(path).path.endswith("/v1/ws") or ws.subprotocol != "sticklink.1":
        await ws.close(4400, "bad")
        return
    n = secrets.token_bytes(32)
    await send(ws, {"t": "welcome", "v": 1, "n": b64u(n), "now": int(time.time())})
    role = None
    my_dev = None
    home = None
    conn = None
    my_slot = None
    try:
        async for raw in ws:
            m = json.loads(raw)
            t, mid = m.get("t"), m.get("id")
            if t == "ping":
                await send(ws, {"t": "pong"})
                continue
            if role is None and t == "hello" and "dev" in q:
                d = DEVICES.get(q["dev"][0])
                if not d or m.get("dev") != q["dev"][0]:
                    await send(ws, err(mid, "auth")); await ws.close(4401, "auth"); return
                is_srv = m.get("role") == "server"
                try:
                    msg = sc.hello_input(n, unb64u(m["dev"], 16), sc.ROLE_SERVER if is_srv else sc.ROLE_CLIENT,
                                         unb64u(m["home"], 16) if is_srv else None)
                    good = "mac" not in m and _ed_ok(d["ak"], unb64u(m.get("sig", ""), 64), msg)
                except (ValueError, KeyError):
                    good = False
                if not good or (is_srv and m.get("home") != d["home"]):  # v1 HMAC `mac` is refused (v2)
                    await send(ws, err(mid, "auth")); await ws.close(4401, "auth"); return
                role, home, my_dev = "server", d["home"], m["dev"]
                d.setdefault("socks", set()).add(ws)
                hs = home_state(home)
                if hs["stick"] is not None:
                    await hs["stick"].close(4009, "replaced")
                hs["stick"] = ws
                await send(ws, {"t": "ready", "id": mid, "v": 1, "home": home,
                                "lim": {"frame": 4096, "burst": 20, "rate": 1},
                                "relays": [{"rg": "tor1", "host": "127.0.0.1", "stun": 3479}], "now": int(time.time())})
                continue
            if role is None and t == "_mock.revoke":  # MOCK-ONLY test control: revoke slots, push rev{rc,set} to the stick
                hs = HOMES.get(m.get("home"))
                if not hs:
                    await send(ws, err(mid, "nf")); continue
                for e in m.get("set", []):  # v2 shape: one rev{rc,slot,why} push per slot
                    await revoke_slot(hs, e.get("slot"), "del")
                await send(ws, {"t": "ok", "id": mid, "rc": hs.get("rc", 0)})
                continue
            if role is None and t == "join" and "home" in q:
                hs = HOMES.get(q["home"][0])
                s = hs and hs["slots"].get(m.get("slot"))
                if not s or m.get("home") != q["home"][0] or not hmac.compare_digest(
                        sc.join_mac(s["jk"], n, unb64u(m["home"], 16), unb64u(m["slot"], 8)), unb64u(m.get("mac", ""), 32)):
                    await send(ws, err(mid, "auth")); await ws.close(4401, "auth"); return
                role, home, my_slot = "client", q["home"][0], m["slot"]
                for c, (w, sl) in list(hs["clients"].items()):
                    if sl == my_slot:
                        await w.close(4009, "replaced")
                conn = f"c{next(CONN_IDS)}"
                hs["clients"][conn] = (ws, my_slot)
                s["st"] = "act"
                await send(ws, {"t": "joined", "id": mid, "conn": conn, "peer": "online" if hs["stick"] else "offline"})
                if hs["stick"]:
                    await send(hs["stick"], {"t": "peer", "conn": conn, "slot": my_slot, "state": "join"})
                continue
            if role is None:
                await send(ws, err(mid, "unknown")); continue
            hs = home_state(home)
            if t == "sig":
                box = m.get("box", "")
                if len(box) > 3072:
                    await send(ws, err(mid, "size")); continue
                if role == "client":
                    if hs["stick"] is None:
                        await send(ws, err(mid, "offline")); continue
                    await send(hs["stick"], {"t": "sig", "from": conn, "box": box})
                else:
                    c = hs["clients"].get(m.get("to"))
                    if not c:
                        await send(ws, err(mid, "offline")); continue
                    await send(c[0], {"t": "sig", "from": "stick", "box": box})
            elif t == "slot.add" and role == "server":
                if m["slot"] in hs.get("revoked", []):
                    await send(ws, err(mid, "auth")); continue
                if m["slot"] in hs["slots"]:
                    await send(ws, err(mid, "busy")); continue
                hs["slots"][m["slot"]] = {"jk": unb64u(m["jk"], 32), "adm": m.get("adm", 0), "st": "pend" if m.get("exp") else "act"}
                await send(ws, {"t": "ok", "id": mid})
            elif t == "slot.list" and role == "server":
                await send(ws, {"t": "slots", "id": mid, "s": [{"slot": k, "adm": v["adm"], "st": v["st"]} for k, v in hs["slots"].items()]})
            elif t == "slot.del" and role == "server":
                if m.get("slot") not in hs["slots"]:
                    await send(ws, err(mid, "nf")); continue
                await send(ws, {"t": "ok", "id": mid, "rc": hs.get("rc", 0) + 1})
                await revoke_slot(hs, m["slot"], "del")
            elif t == "revoked.get" and role == "server":
                await send(ws, {"t": "revoked", "id": mid, **revoked_page(hs, home, n, int(m.get("after", 0)))})
            elif t == "auth.rotate" and role == "server":
                d = DEVICES[my_dev]
                new = unb64u(m.get("ak", ""), 32)
                if not _ed_ok(new, unb64u(m.get("pop", ""), 64),
                              b"sl1/dev-rotate/v1\x00" + n + unb64u(my_dev, 16) + new + d["ak"]):
                    await send(ws, err(mid, "auth")); continue
                d["ak"], d["gen"] = new, d.get("gen", 1) + 1
                await send(ws, {"t": "ok", "id": mid, "gen": d["gen"]})
                for w in list(d.get("socks", ())):
                    if w is not ws:
                        await w.close(4401, "rotated")
            elif t == "relay.reg":
                exp = int(time.time()) + 43200
                RELAY[m.get("nk")] = exp
                await send(ws, {"t": "relay.ok", "id": mid, "exp": exp, "tok": "mock.mock"})
            elif t == "relay.del":
                RELAY.pop(m.get("nk"), None)
                await send(ws, {"t": "ok", "id": mid})
            else:
                await send(ws, err(mid, "unknown"))
    except (websockets.ConnectionClosed, ValueError, KeyError):
        pass
    finally:
        if home and home in HOMES:
            hs = HOMES[home]
            if my_dev in DEVICES:
                DEVICES[my_dev].get("socks", set()).discard(ws)
            if role == "server" and hs["stick"] is ws:
                hs["stick"] = None
            if role == "client" and conn in hs["clients"]:
                del hs["clients"][conn]
                if hs["stick"]:
                    await send(hs["stick"], {"t": "peer", "conn": conn, "slot": my_slot, "state": "leave"})


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="0.0.0.0:8788")
    ap.add_argument("--fixtures")
    ap.add_argument("--e2e", nargs=2, metavar=("PAIRING", "STICK_ID"), help="also accept the e2e fixture stick")
    ap.add_argument("--signing-vectors", default=str(Path(__file__).resolve().parents[4] / "vectors-v2/signalling-v2.json"),
                    help="signalling-v2.json: its public TEST signing seed (kid test-1) signs revoked pages")
    a = ap.parse_args()
    sg = json.loads(Path(a.signing_vectors).read_text())["signing"]
    SIGN.update(kid=sg["kid"], seed=bytes.fromhex(sg["seed"]))
    if a.fixtures:
        fx = json.loads(Path(a.fixtures).read_text())
        for d in fx["devices"].values():
            DEVICES[d["dev"]] = {"ak": unb64u(d["ak"], 32), "home": d.get("home")}
    if a.e2e:
        p, i = (json.loads(Path(x).read_text()) for x in a.e2e)
        DEVICES[i["dev"]] = {"ak": crypto.ed25519_public(unb64u(i["auth_seed"], 32)), "home": p["home"]}
    host, port = a.listen.rsplit(":", 1)
    async with websockets.serve(handler, host, int(port), subprotocols=["sticklink.1"], max_size=8192):
        print(f"mock signalling on ws://{a.listen}/v1/ws ({len(DEVICES)} devices)", flush=True)
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
