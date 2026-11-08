#!/usr/bin/env python3
"""Phase 4: outside-network force-relay + revocation against live link + relay-tor1.

Uses lab stick provision (secrets offline). Stick registers both DERP nodekeys
(peer has no device auth for relay.reg). --force-relay on both sides; expect
echoes only via derp. Then relay.del both keys and prove DERP re-admit fails.

Does not touch relay host config. STICKLINK_TESTING=1 for registry/pairing shims.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import time
import urllib.request
from pathlib import Path

os.environ["STICKLINK_TESTING"] = "1"
os.environ.setdefault("STICKLINK_FAST_KDF", "1")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "overlay/usr/local/lib"))

from sticklink import crypto, link, pairfile, registry, sigcrypto as sc  # noqa: E402
from sticklink.daemon import Stick, DEFAULTS  # noqa: E402
from sticklink.derp import DerpClient, nodekey_str, parse_nodekey  # noqa: E402
from sticklink.sigclient import SigClient, SigError  # noqa: E402
from sticklink.util import b64u, unb64u  # noqa: E402

PROV = Path(os.environ.get("SL_LAB_PROV", r"C:\Users\peter\sticklink-secrets\lab-stick-prov"))
STATE = Path(__file__).resolve().parent / "state" / "phase4"
WS = "wss://link.stickllm.com/v1/ws"
DERP = "https://relay-tor1.stickllm.com/derp"
STUN = "relay-tor1.stickllm.com:3478"
RG = "tor1"


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} phase4: {msg}", flush=True)


def public_egress() -> dict:
    out = {}
    for url, key in (
        ("https://api.ipify.org", "ip"),
        ("https://ifconfig.me/ip", "ip_alt"),
    ):
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                out[key] = r.read().decode().strip()
                break
        except Exception as e:
            out.setdefault("egress_err", str(e)[:80])
    try:
        with urllib.request.urlopen("https://link.stickllm.com/healthz", timeout=8) as r:
            out["link_healthz"] = r.status
        with urllib.request.urlopen("https://relay-tor1.stickllm.com/", timeout=8) as r:
            out["relay_https"] = r.status
    except Exception as e:
        out["probe_err"] = str(e)[:80]
    return out


def load_ids():
    ids = json.loads(next(PROV.glob("*.ids.json")).read_text(encoding="utf-8"))
    seed_raw = (PROV / "device-auth-seed").read_text(encoding="utf-8").strip()
    return ids, seed_raw


def setup_stick(root: Path, key_path: Path, ids: dict, seed_raw: str) -> registry.Registry:
    key_path.write_bytes(secrets.token_bytes(32))
    # Windows host lab: mode bits are not POSIX; Registry takes key bytes directly.
    rk = key_path.read_bytes()
    seed_path = root / "auth-seed.txt"
    seed_path.write_text(seed_raw + "\n", encoding="utf-8")
    reg = registry.Registry(root, rk)
    reg.init_dirs()
    reg.create_identity()
    reg.save_signal(ids["dev"], ids["home"])
    seed = unb64u(seed_raw, 32)
    reg.save_auth_seed(seed)
    return reg


class Phase4Stick(Stick):
    """Registers peer DERP nk after own relay.reg (lab shortcut; peer is slot-only)."""

    def __init__(self, reg, cfg, peer_nk: str, ready: asyncio.Event):
        super().__init__(reg, cfg)
        self.peer_nk = peer_nk
        self.ready = ready

    async def relay_reg(self):
        await super().relay_reg()
        try:
            await self.cl.request({"t": "relay.reg", "nk": self.peer_nk, "rg": self.cfg["rg"]})
            log(f"peer nk relay.reg ok ({self.peer_nk[8:20]}…)")
        except SigError as e:
            log(f"peer nk relay.reg failed: {e.code}")
            raise
        self.ready.set()


async def peer_force_relay(st: dict, duration: float = 8.0) -> dict:
    psk, home, slot = unb64u(st["pair_psk"], 32), unb64u(st["home"], 16), unb64u(st["slot"], 8)
    envk = sc.env_key(psk)
    ep = link.Endpoint(
        derp_url=DERP,
        derp_priv=unb64u(st["derp_priv"], 32),
        stun_addr=STUN,
        force_relay=True,
        log=lambda m: log(f"peer {m}"),
    )
    await ep.start(connect_derp=True)
    if not await ep.wait_derp(20):
        await ep.close()
        return {"handshake": False, "error": "peer DERP not connected (admit lag or deny)"}
    log(f"peer derp connected as {link.fp(ep.derp_pub)}")

    ini = link.Initiator(ep, unb64u(st["priv"], 32), unb64u(st["stick_pub"], 32), psk, home, slot, log=lambda m: log(f"peer {m}"))
    peer = ini.peer
    echoes, sent = {}, {}

    def on_data(typ, body, path):
        if typ == link.D_ECHO_REP and len(body) >= 4:
            seq = int.from_bytes(body[:4], "big")
            if seq in sent and seq not in echoes:
                echoes[seq] = (path[0], (time.monotonic() - sent[seq]) * 1000)

    peer.on_data = on_data

    cl = SigClient(WS, log=lambda m: log(f"peer-sig {m}"))
    await cl.connect({"home": st["home"]})
    for _ in range(30):
        try:
            j = await cl.request(
                {
                    "t": "join",
                    "home": st["home"],
                    "slot": st["slot"],
                    "mac": b64u(sc.join_mac(sc.join_key(psk), cl.nonce, home, slot)),
                }
            )
        except SigError as e:
            await cl.close()
            await ep.close()
            return {"handshake": False, "error": f"join {e.code}"}
        if j.get("peer") == "online":
            break
        log("stick offline; retry join")
        await cl.close()
        await asyncio.sleep(2)
        cl = SigClient(WS, log=lambda m: log(f"peer-sig {m}"))
        await cl.connect({"home": st["home"]})
    else:
        await cl.close()
        await ep.close()
        return {"handshake": False, "error": "stick never online"}

    # Peer nk already on allowlist via stick; skip relay.reg (would need device hello).
    sid = b64u(secrets.token_bytes(8))
    for inner in (
        {"k": "cand", "sid": sid, "seq": 1, "c": []},
        {"k": "derp", "sid": sid, "nk": nodekey_str(ep.derp_pub), "rg": RG},
    ):
        await cl.send({"t": "sig", "to": "stick", "box": sc.seal_box(envk, home, slot, sc.DIR_C2S, inner)})

    got = {"cand": False, "derp": False}
    end = time.monotonic() + 8
    while time.monotonic() < end and not (got["cand"] and got["derp"]):
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
                log(f"stick derp key {link.fp(peer.derp_key)}")

    t0 = time.monotonic()
    ok = await ini.handshake()
    hs_ms = (time.monotonic() - t0) * 1000
    result = {
        "handshake": ok,
        "handshake_ms": round(hs_ms),
        "first_path": ini.first_path[0] if ini.first_path else None,
        "got_cand": got["cand"],
        "got_derp": got["derp"],
    }
    if ok:
        mt = asyncio.create_task(ini.maintain())
        seq = 0
        t_end = time.monotonic() + duration
        while time.monotonic() < t_end:
            seq += 1
            sent[seq] = time.monotonic()
            peer.send_data(link.D_ECHO_REQ, seq.to_bytes(4, "big") + secrets.token_bytes(32))
            await asyncio.sleep(0.25)
        await asyncio.sleep(1)
        mt.cancel()
        by_path: dict = {}
        for p, rtt in echoes.values():
            by_path.setdefault(p, []).append(rtt)
        last = max(echoes) if echoes else None
        result.update(
            {
                "sent": seq,
                "echoed": len(echoes),
                "by_path": {
                    k: {"n": len(v), "rtt_ms_median": round(sorted(v)[len(v) // 2], 1)} for k, v in by_path.items()
                },
                "final_path": echoes[last][0] if last else None,
            }
        )
    await cl.close()
    await ep.close()
    result["pass"] = bool(
        ok
        and result.get("final_path") == "derp"
        and result.get("echoed", 0) >= max(1, int(result.get("sent", 0) * 0.7))
        and "udp" not in result.get("by_path", {})
    )
    return result


async def try_derp_connect(priv: bytes, label: str, timeout: float = 12.0) -> dict:
    c = DerpClient(DERP, priv, log=lambda m: log(f"{label} {m}"))
    try:
        await asyncio.wait_for(c.connect(), timeout=timeout)
        await c.close()
        return {"ok": True, "nk": nodekey_str(crypto.x25519_public(priv))}
    except Exception as e:
        try:
            await c.close()
        except Exception:
            pass
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:100]}"}


async def amain() -> int:
    STATE.mkdir(parents=True, exist_ok=True)
    egress = public_egress()
    log(f"egress {egress}")

    ids, seed_raw = load_ids()
    root = STATE / "stick-root"
    if root.exists():
        import shutil

        shutil.rmtree(root)
    root.mkdir(parents=True)
    key_path = STATE / "registry.key"
    reg = setup_stick(root, key_path, ids, seed_raw)

    offer = pairfile.make_offer(reg)
    peer_priv = crypto.x25519_generate()
    derp_priv = crypto.x25519_generate()
    ans = pairfile.make_answer(offer, peer_priv, "phase4-peer", "kvm")
    rec = pairfile.accept_answer(reg, ans)
    peer_st = {
        "v": 1,
        "priv": b64u(peer_priv),
        "stick_pub": offer["stick_pub"],
        "pair_psk": offer["pair_psk"],
        "home": offer["home"],
        "slot": offer["slot"],
        "derp_priv": b64u(derp_priv),
    }
    (STATE / "peer.json").write_text(json.dumps(peer_st), encoding="utf-8")
    peer_nk = nodekey_str(crypto.x25519_public(derp_priv))
    log(f"paired slot={rec['slot'][:8]}… peer_nk={peer_nk[8:20]}…")

    cfg = dict(DEFAULTS)
    cfg.update(
        {
            "ws": WS,
            "derp": DERP,
            "stun": STUN,
            "rg": RG,
            "derp_ca": None,
            "derp_pin": None,
            "derp_sni": None,
            "udp_port": 0,
            "force_relay": True,
            "extra_cand": [],
            "revoked_file": None,
            "sign_keys": None,
        }
    )
    ready = asyncio.Event()
    stick = Phase4Stick(reg, cfg, peer_nk, ready)
    stick.load_records()
    stick_task = asyncio.create_task(stick.run())

    report: dict = {"egress": egress, "ws": WS, "derp": DERP, "force_relay": True}
    try:
        await asyncio.wait_for(ready.wait(), 45)
        log("allowlist registered; waiting stick DERP + admit pull")
        if not await stick.ep.wait_derp(45):
            report["ok"] = False
            report["error"] = "stick DERP not connected after relay.reg"
            return 1
        stick_nk = nodekey_str(stick.ep.derp_pub)
        report["stick_nk_fp"] = link.fp(stick.ep.derp_pub)
        report["peer_nk_fp"] = link.fp(crypto.x25519_public(derp_priv))
        log(f"stick derp ok {report['stick_nk_fp']}")

        # Brief settle for admit unknown-key pull / feed chg
        await asyncio.sleep(3)
        peer_result = await peer_force_relay(peer_st, duration=8.0)
        report["force_relay_chat"] = peer_result
        log(f"force-relay result pass={peer_result.get('pass')} {json.dumps({k: peer_result.get(k) for k in ('handshake','final_path','echoed','sent','by_path','error')})}")

        if not peer_result.get("pass"):
            report["ok"] = False
            return 1

        # Withdraw both permits
        assert stick.cl is not None
        for nk, label in ((stick_nk, "stick"), (peer_nk, "peer")):
            try:
                await stick.cl.request({"t": "relay.del", "nk": nk})
                log(f"relay.del ok ({label})")
            except SigError as e:
                log(f"relay.del {label}: {e.code}")
                report[f"relay_del_{label}"] = e.code

        await asyncio.sleep(3)  # admit refresh on next connect

        # Existing DERP may linger (Q-S6); cancel loop and re-admit on fresh connect.
        if stick.ep._derp_task:
            stick.ep._derp_task.cancel()
            try:
                await stick.ep._derp_task
            except (asyncio.CancelledError, Exception):
                pass
            stick.ep._derp_task = None
            stick.ep.derp = None
        stick.ep.start_derp()
        stick_re = await stick.ep.wait_derp(18)
        report["stick_derp_after_del"] = bool(stick_re)
        log(f"stick DERP after del: connected={stick_re}")

        peer_re = await try_derp_connect(derp_priv, "peer-re")
        report["peer_derp_after_del"] = peer_re
        log(f"peer DERP after del: {peer_re}")

        unknown = await try_derp_connect(crypto.x25519_generate(), "unknown")
        report["unknown_derp"] = unknown
        log(f"unknown nk DERP: {unknown}")

        report["ok"] = bool(
            peer_result.get("pass")
            and not stick_re
            and not peer_re.get("ok")
            and not unknown.get("ok")
        )
        report["proven"] = {
            "outside_egress": bool(egress.get("ip") or egress.get("ip_alt")),
            "force_relay_derp_chat": bool(peer_result.get("pass")),
            "relay_del_denies_new_derp": not stick_re and not peer_re.get("ok"),
            "unknown_still_denied": not unknown.get("ok"),
        }
        return 0 if report["ok"] else 1
    finally:
        stick_task.cancel()
        try:
            await stick_task
        except (asyncio.CancelledError, Exception):
            pass
        try:
            await stick.ep.close()
        except Exception:
            pass
        out = STATE / "phase4-report.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        log(f"wrote {out}")
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
