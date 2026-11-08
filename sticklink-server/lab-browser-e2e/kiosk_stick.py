#!/usr/bin/env python3
"""Lab kiosk/stick: Method C + aiortc DataChannel + Noise + chat stream/cancel + revoke.

Requires STICKLINK_TESTING=1 STICKLINK_LAB=1. Talks to local wrangler only.
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import time
from pathlib import Path

os.environ.setdefault("STICKLINK_TESTING", "1")
os.environ.setdefault("STICKLINK_LAB", "1")
os.environ.setdefault("STICKLINK_FAST_KDF", "1")

REPO = Path(__file__).resolve().parents[2]  # stickllm-sticklink-wt
sys.path.insert(0, str(REPO / "overlay/usr/local/lib"))

import websockets
from aiortc import RTCPeerConnection, RTCSessionDescription
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sticklink import crypto, noise, pair_qr
from sticklink.util import b64u, unb64u

ROOT = Path(__file__).resolve().parent
FIX = ROOT.parent / "worker" / "fixtures"


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} kiosk: {msg}", flush=True)


def enc(x: bytes) -> bytes:
    return struct.pack(">H", len(x)) + x


def hkdf0(ikm: bytes, info: bytes) -> bytes:
    return crypto.hkdf(ikm, info)


def seal_env(env_k: bytes, mbx: bytes, direction: int, pt: bytes) -> bytes:
    ad = enc(mbx) + mbx + bytes([direction])
    nonce, ct = crypto.seal(env_k, pt, ad)
    return nonce + ct


def open_env(env_k: bytes, mbx: bytes, direction: int, blob: bytes) -> bytes:
    ad = enc(mbx) + mbx + bytes([direction])
    return crypto.open_(env_k, blob[:12], blob[12:], ad)


def qr_prologue(home: bytes, mbx: bytes, stick_pub: bytes) -> bytes:
    return b"sl1/qr" + bytes([1]) + home + mbx + stick_pub


def load_stick_fixture():
    """Local wrangler fixture, or live lab stick when SL_LAB_PROV points at provision dir."""
    prov = os.environ.get("SL_LAB_PROV", "").strip()
    if prov:
        p = Path(prov)
        ids = json.loads(next(p.glob("*.ids.json")).read_text(encoding="utf-8"))
        seed = (p / "device-auth-seed").read_text(encoding="utf-8").strip()
        return {
            "dev": ids["dev"],
            "home": ids["home"],
            "ak": ids["ak"],
            "auth_seed": seed,
            "kind": "stick",
            "name": "lab-stick-live",
        }
    fx = json.loads((FIX / "dev-fixtures.json").read_text(encoding="utf-8"))
    stick = fx["devices"]["stick1"]
    return stick



class StickWS:
    def __init__(self, ws):
        self.ws = ws
        self.q: asyncio.Queue = asyncio.Queue()

    async def reader(self):
        async for raw in self.ws:
            await self.q.put(json.loads(raw))

    async def next(self, timeout=20.0):
        return await asyncio.wait_for(self.q.get(), timeout)

    async def expect(self, t: str, timeout=20.0):
        while True:
            m = await self.next(timeout)
            if m.get("t") == t:
                return m
            if m.get("t") == "err":
                raise RuntimeError(f"err while waiting {t}: {m}")

    async def req(self, obj, want=None):
        await self.ws.send(json.dumps(obj))
        want_id = obj.get("id")
        while True:
            m = await self.next()
            if want_id is not None and m.get("id") != want_id:
                # Unsolicited events (peer/pmsg/rev) — ignore for request/response.
                continue
            if want and m.get("t") != want:
                raise RuntimeError(f"want {want} got {m}")
            return m


async def ed_hello_sig(seed: bytes, n: bytes, dev: bytes, role: int, home: bytes | None) -> bytes:
    # helloBody = n(32)||dev(16)||role(1)||home(16; zeros for client)
    home16 = home if home is not None else b"\x00" * 16
    body = n + dev + bytes([role]) + home16
    msg = b"sl1/dev-hello/v1\x00" + body
    return Ed25519PrivateKey.from_private_bytes(seed).sign(msg)


async def main():
    ws_url = os.environ.get("SL_WS", "ws://127.0.0.1:8797/v1/ws")
    out_path = Path(os.environ.get("SL_KIOSK_OUT", ROOT / "state" / "kiosk.json"))
    stick = load_stick_fixture()
    seed = unb64u(stick["auth_seed"], 32)
    dev = unb64u(stick["dev"], 16)
    home = unb64u(stick["home"], 16)
    stick_priv = crypto.x25519_generate()
    stick_pub = crypto.x25519_public(stick_priv)

    uri = f"{ws_url}?dev={stick['dev']}"
    async with websockets.connect(uri, subprotocols=["sticklink.1"], open_timeout=30) as raw:
        sw = StickWS(raw)
        asyncio.create_task(sw.reader())
        welcome = await sw.expect("welcome")
        n = unb64u(welcome["n"], 32)
        sig = await ed_hello_sig(seed, n, dev, 1, home)  # ROLE_SERVER=1
        ready = await sw.req(
            {"t": "hello", "id": 1, "dev": stick["dev"], "role": "server", "home": stick["home"], "sig": b64u(sig)},
            "ready",
        )
        log(f"ready home={ready.get('home')}")

        invite = crypto.random_key()
        jk = pair_qr.jk_qr(invite)
        ok = await sw.req({"t": "pair.open", "id": 11, "m": "qr", "jk": b64u(jk), "exp": 60}, "pair.ok")
        mbx_b = ok["mbx"]
        mbx = unb64u(mbx_b, 8)
        exp = int(ok["exp"]) + int(time.time()) if ok["exp"] < 10_000 else int(ok["exp"])
        # pair.ok exp is duration seconds
        exp_abs = int(time.time()) + int(ok["exp"])
        qr = pair_qr.encode_qr(mailbox_id=mbx, stick_static_pub=stick_pub, invite_secret=invite, exp=exp_abs)
        env_k = pair_qr.env_qr(invite, mbx, home)
        th = pair_qr.transcript_hash(mailbox_id=mbx, home_id=home, stick_static_pub=stick_pub)
        boot = pair_qr.boot_psk(invite, th)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"qr": qr, "mbx": mbx_b, "home": stick["home"]}), encoding="utf-8")
        log(f"wrote QR to {out_path}")

        peer = await sw.expect("peer")
        log(f"peer {peer}")
        assert peer.get("state") == "join"

        pc = RTCPeerConnection()
        dc = pc.createDataChannel("sl1", ordered=True)
        dc_q: asyncio.Queue = asyncio.Queue()

        @dc.on("message")
        def _on_dc_msg(message):
            dc_q.put_nowait(bytes(message) if not isinstance(message, bytes) else message)

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        for _ in range(50):
            if pc.iceGatheringState == "complete":
                break
            await asyncio.sleep(0.1)

        while True:
            m = await sw.next()
            if m.get("t") != "pmsg":
                continue
            rawb = unb64u(m["body"])
            pt = open_env(env_k, mbx, 0x01, rawb)
            obj = json.loads(pt)
            if obj.get("k") == "need-offer":
                body = seal_env(env_k, mbx, 0x02, json.dumps({"k": "offer", "sdp": pc.localDescription.sdp}).encode())
                await raw.send(json.dumps({"t": "pmsg", "to": peer["conn"], "body": b64u(body)}))
                log("sent offer")
                break

        while True:
            m = await sw.next()
            if m.get("t") != "pmsg":
                continue
            obj = json.loads(open_env(env_k, mbx, 0x01, unb64u(m["body"])))
            if obj.get("k") == "answer":
                await pc.setRemoteDescription(RTCSessionDescription(sdp=obj["sdp"], type="answer"))
                log("set remote answer")
                break

        while dc.readyState != "open":
            await asyncio.sleep(0.05)
        log("datachannel open")

        # LAB BYPASS (documented): this harness skips LabPairSession.approve_local
        # and the native VT overlay (PAIRING-SPEC §4.7). It proceeds as if the
        # operator already approved on a trusted local kiosk.
        mode = os.environ.get("SL_NEG_MODE", "")  # "", wrong_psk, tamper
        prologue = qr_prologue(home, mbx, stick_pub)
        resp = noise.Responder(stick_priv, prologue)
        msg1 = await asyncio.wait_for(dc_q.get(), timeout=20)
        rs, _ = resp.read_msg1(bytes(msg1))
        log(f"pinned initiator static fp={rs[:4].hex()}")
        boot_use = os.urandom(32) if mode == "wrong_psk" else boot
        if mode == "wrong_psk":
            log("NEG wrong_psk: using random boot_psk")
        sess, msg2 = resp.write_msg2(boot_use)
        dc.send(bytes(msg2))
        log(f"noise msg2 sent hh={sess.handshake_hash[:8].hex()}")

        async def dc_recv_pt():
            raw = await dc_q.get()
            n = int.from_bytes(raw[:8], "little")
            return sess.decrypt(n, raw[8:])

        def dc_send_pt(obj):
            n, ct = sess.encrypt(json.dumps(obj).encode())
            dc.send(_frame(n, ct))

        if mode == "wrong_psk":
            # Browser must reject msg2; do not continue the positive path.
            await asyncio.sleep(3)
            result = {"ok": True, "neg": "wrong_psk", "msg2_with_wrong_boot": True}
            (ROOT / "state" / "kiosk-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            await pc.close()
            return

        ready_obj = json.loads(await dc_recv_pt())
        assert ready_obj.get("t") == "ready"
        log("browser ready")

        # pair_psk contributions + pair-confirm (PAIRING-SPEC §4.5)
        r_i_msg = json.loads(await dc_recv_pt())
        assert r_i_msg.get("t") == "r_i"
        r_i = unb64u(r_i_msg["r"], 32)
        r_r = crypto.random_key()
        dc_send_pt({"t": "r_r", "r": b64u(r_r)})
        hh = sess.handshake_hash
        psk = pair_qr.pair_psk(
            r_i=r_i, r_r=r_r, prior=boot, handshake_hash=hh, th=th,
            initiator_static=rs, responder_static=stick_pub, key_epoch=0,
        )
        kc = pair_qr.pair_confirm_kc(psk)
        confirm_i = json.loads(await dc_recv_pt())
        assert confirm_i.get("t") == "confirm_i"
        if not pair_qr.verify_confirm(kc, "i", hh, unb64u(confirm_i["mac"], 32)):
            raise RuntimeError("confirm_i failed")
        dc_send_pt({"t": "confirm_r", "mac": b64u(pair_qr.confirm_mac(kc, "r", hh))})
        log(f"pair_psk+confirm ok fp={psk[:4].hex()}")

        if mode == "tamper":
            # Corrupt ciphertext: flip a byte after a valid frame header.
            n, ct = sess.encrypt(json.dumps({"t": "chat", "id": "tamper", "seq": 0, "body": "x", "fin": True}).encode())
            bad = bytearray(_frame(n, ct))
            bad[-1] ^= 0xFF
            dc.send(bytes(bad))
            log("NEG tamper: sent corrupted AEAD frame")
            await asyncio.sleep(2)
            result = {"ok": True, "neg": "tamper", "tamper_sent": True}
            (ROOT / "state" / "kiosk-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            await pc.close()
            return

        chat_id = "c1"
        cancelled = asyncio.Event()

        async def on_browser():
            while True:
                msg = json.loads(await dc_recv_pt())
                if msg.get("t") == "chat_cancel" and msg.get("id") == chat_id:
                    cancelled.set()
                    dc_send_pt({"t": "chat_cancelled", "id": chat_id})
                    log("ack cancel")
                    return

        reader = asyncio.create_task(on_browser())
        for seq in range(0, 8):
            if cancelled.is_set():
                break
            body = f"chunk-{seq}-" + ("*" * 40)
            dc_send_pt({"t": "chat", "id": chat_id, "seq": seq, "body": body, "fin": False})
            await asyncio.sleep(0.05)
        await asyncio.wait_for(cancelled.wait(), timeout=10)
        await reader

        # Slot from real pair_psk; revoke; browser observes; reconnect must fail.
        from sticklink import sigcrypto as sc
        slot = os.urandom(8)
        jk_slot = sc.join_key(psk)
        await sw.req({"t": "slot.add", "id": 20, "slot": b64u(slot), "jk": b64u(jk_slot), "adm": 0}, "ok")
        log("slot.add ok")
        await sw.req({"t": "slot.del", "id": 21, "slot": b64u(slot)}, "ok")
        log("slot.del ok (revoked)")
        dc_send_pt({"t": "revoked_ok", "slot": b64u(slot)})

        await sw.req({"t": "pair.close", "id": 12, "mbx": mbx_b, "why": "done"}, "ok")
        log("pair.close done")
        result = {
            "ok": True,
            "method_c": True,
            "pair_psk_confirm": True,
            "noise_hh": sess.handshake_hash.hex(),
            "initiator_static_fp": rs[:8].hex(),
            "pair_psk_fp": psk[:8].hex(),
            "chat_cancelled": True,
            "revoked": True,
            "slot": b64u(slot),
            "jk": b64u(jk_slot),
            "home": stick["home"],
            "lab_bypass_trusted_approval": True,
        }
        (ROOT / "state" / "kiosk-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        await asyncio.sleep(1)
        await pc.close()


def _frame(n: int, ct: bytes) -> bytes:
    return n.to_bytes(8, "little") + ct


async def _dc_recv(dc):
    fut = asyncio.get_event_loop().create_future()

    @dc.on("message")
    def on_msg(msg):
        if not fut.done():
            fut.set_result(msg)

    return await fut


async def _dc_recv_pt(dc, sess, role: str):
    raw = await _dc_recv(dc)
    raw = bytes(raw)
    n = int.from_bytes(raw[:8], "little")
    return sess.decrypt(n, raw[8:])


if __name__ == "__main__":
    asyncio.run(main())
