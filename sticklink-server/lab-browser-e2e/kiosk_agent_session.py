#!/usr/bin/env python3
"""Lab Method C session that stays up and proxies Agent Zero over the Noise DC.

LAB BYPASS: skips native VT approval. After pair-confirm, mints a StickLink-lab
gateway grant on the stick (SSH) and answers http_req frames by fetching the
stick Agent Zero / StickLLM UI with that token.

Phone path: cellular → join page (cloudflared) → Method C (WSS+WebRTC) → this
process → HTTPS to stick LAN. Not yet Noise/DERP end-to-end on-stick.
"""
from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("STICKLINK_TESTING", "1")
os.environ.setdefault("STICKLINK_LAB", "1")
os.environ.setdefault("STICKLINK_FAST_KDF", "1")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "overlay/usr/local/lib"))

import websockets
from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sticklink import crypto, noise, pair_qr
from sticklink.util import b64u, unb64u

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
STICK_HTTPS = os.environ.get("SL_STICK_HTTPS", "https://192.168.72.50")
STICK_SSH = os.environ.get("SL_STICK_HOST", "192.168.72.50")
ICE = RTCConfiguration(
    iceServers=[
        RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
        RTCIceServer(urls=["stun:relay-tor1.stickllm.com:3478"]),
        # Lab TURN so cellular phones can reach this PC behind NAT.
        RTCIceServer(
            urls=[
                "turn:openrelay.metered.ca:80",
                "turn:openrelay.metered.ca:443",
                "turn:openrelay.metered.ca:443?transport=tcp",
            ],
            username="openrelayproject",
            credential="openrelayproject",
        ),
    ]
)


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} kiosk-agent: {msg}", flush=True)


def enc(x: bytes) -> bytes:
    import struct
    return struct.pack(">H", len(x)) + x


def seal_env(env_k: bytes, mbx: bytes, direction: int, pt: bytes) -> bytes:
    ad = enc(mbx) + mbx + bytes([direction])
    nonce, ct = crypto.seal(env_k, pt, ad)
    return nonce + ct


def open_env(env_k: bytes, mbx: bytes, direction: int, blob: bytes) -> bytes:
    ad = enc(mbx) + mbx + bytes([direction])
    return crypto.open_(env_k, blob[:12], blob[12:], ad)


def qr_prologue(home: bytes, mbx: bytes, stick_pub: bytes) -> bytes:
    return b"sl1/qr" + bytes([1]) + home + mbx + stick_pub


def _frame(n: int, ct: bytes) -> bytes:
    return n.to_bytes(8, "little") + ct


def load_stick():
    prov = Path(os.environ.get("SL_LAB_PROV", r"C:\Users\peter\sticklink-secrets\lab-stick-prov"))
    ids = json.loads(next(prov.glob("*.ids.json")).read_text(encoding="utf-8"))
    seed = (prov / "device-auth-seed").read_text(encoding="utf-8").strip()
    return ids, seed


def mint_stick_token() -> str:
    """SSH: remint unpaired? No — mint sticklink-lab grant and redeem via HTTPS."""
    import paramiko

    pw = Path.home().joinpath(".grokbot", "s60pw").read_text(encoding="utf-8").strip()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(STICK_SSH, username="stickllm", password=pw, timeout=20, allow_agent=False, look_for_keys=False)
    try:
        stdin, stdout, stderr = c.exec_command("sudo stickllm-sticklink-lab-grant", timeout=30, get_pty=True)
        buff = b""
        end = time.time() + 30
        while time.time() < end:
            if stdout.channel.recv_ready():
                chunk = stdout.channel.recv(16384)
                buff += chunk
                if b"[sudo]" in chunk.lower() or b"password for" in chunk.lower():
                    stdin.write(pw + "\n")
                    stdin.flush()
            elif stdout.channel.exit_status_ready():
                break
            else:
                time.sleep(0.05)
        while stdout.channel.recv_ready():
            buff += stdout.channel.recv(16384)
        text = buff.decode("utf-8", "replace")
        grant = ""
        for line in text.splitlines():
            s = line.strip()
            if len(s) >= 32 and " " not in s and not s.startswith("{"):
                grant = s
                break
        if not grant:
            raise RuntimeError("grant mint failed: " + text[-400:])
    finally:
        c.close()

    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        f"{STICK_HTTPS}/api/pair/sticklink-lab",
        data=json.dumps({"grant": grant}).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-StickLLM-Client": "ui",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        doc = json.loads(r.read().decode())
    if not doc.get("ok") or not doc.get("token"):
        raise RuntimeError(f"sticklink-lab redeem failed: {doc}")
    return doc["token"]


def stick_http(token: str, method: str, path: str, headers: dict | None = None, body: bytes | None = None) -> dict:
    ctx = ssl._create_unverified_context()
    url = STICK_HTTPS.rstrip("/") + path
    hdrs = {
        "Authorization": f"Bearer {token}",
        "X-StickLLM-Client": "ui",
        "Accept": headers.get("accept", "*/*") if headers else "*/*",
        "User-Agent": "StickLink-lab-tunnel",
    }
    if headers:
        for k, v in headers.items():
            if k.lower() in ("authorization", "host", "connection", "content-length"):
                continue
            hdrs[k] = v
    req = urllib.request.Request(url, data=body, method=method.upper(), headers=hdrs)
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
            raw = r.read()
            return {
                "status": r.status,
                "headers": {k.lower(): v for k, v in r.headers.items()},
                "body_b64": b64u(raw),
            }
    except urllib.error.HTTPError as e:
        raw = e.read()
        return {
            "status": e.code,
            "headers": {k.lower(): v for k, v in e.headers.items()},
            "body_b64": b64u(raw),
        }


class StickWS:
    def __init__(self, ws):
        self.ws = ws
        self.q: asyncio.Queue = asyncio.Queue()

    async def reader(self):
        async for raw in self.ws:
            await self.q.put(json.loads(raw))

    async def next(self, timeout=60.0):
        return await asyncio.wait_for(self.q.get(), timeout)

    async def expect(self, t: str, timeout=60.0):
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
                continue
            if want and m.get("t") != want:
                raise RuntimeError(f"want {want} got {m}")
            return m


async def ed_hello_sig(seed: bytes, n: bytes, dev: bytes, role: int, home: bytes | None) -> bytes:
    home16 = home if home is not None else b"\x00" * 16
    body = n + dev + bytes([role]) + home16
    msg = b"sl1/dev-hello/v1\x00" + body
    return Ed25519PrivateKey.from_private_bytes(seed).sign(msg)


async def main():
    ws_url = os.environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")
    ids, seed_b64 = load_stick()
    seed = unb64u(seed_b64, 32)
    dev = unb64u(ids["dev"], 16)
    home = unb64u(ids["home"], 16)
    stick_priv = crypto.x25519_generate()
    stick_pub = crypto.x25519_public(stick_priv)

    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "logs").mkdir(parents=True, exist_ok=True)

    uri = f"{ws_url}?dev={ids['dev']}"
    async with websockets.connect(uri, subprotocols=["sticklink.1"], open_timeout=30) as raw:
        sw = StickWS(raw)
        asyncio.create_task(sw.reader())
        welcome = await sw.expect("welcome")
        n = unb64u(welcome["n"], 32)
        sig = await ed_hello_sig(seed, n, dev, 1, home)
        await sw.req(
            {"t": "hello", "id": 1, "dev": ids["dev"], "role": "server", "home": ids["home"], "sig": b64u(sig)},
            "ready",
        )
        log("signalling ready")

        invite = crypto.random_key()
        jk = pair_qr.jk_qr(invite)
        # Server clamps mailbox TTL to MBX_EXP_S (60s). Scan promptly.
        ok = await sw.req({"t": "pair.open", "id": 11, "m": "qr", "jk": b64u(jk), "exp": 60}, "pair.ok")
        mbx_b = ok["mbx"]
        mbx = unb64u(mbx_b, 8)
        exp_abs = int(time.time()) + int(ok["exp"])
        qr = pair_qr.encode_qr(mailbox_id=mbx, stick_static_pub=stick_pub, invite_secret=invite, exp=exp_abs)
        env_k = pair_qr.env_qr(invite, mbx, home)
        th = pair_qr.transcript_hash(mailbox_id=mbx, home_id=home, stick_static_pub=stick_pub)
        boot = pair_qr.boot_psk(invite, th)
        (STATE / "kiosk.json").write_text(json.dumps({"qr": qr, "mbx": mbx_b, "home": ids["home"]}), encoding="utf-8")
        log(f"QR ready exp={exp_abs}")

        peer = await sw.expect("peer", timeout=600)
        log(f"peer join {peer.get('conn')}")
        assert peer.get("state") == "join"

        # Cellular phones often fail WebRTC/TURN. Mint Agent session as soon as
        # Method C mailbox join succeeds so /agent-zero can ride the Cloudflare
        # reverse proxy without a datachannel.
        try:
            token = await asyncio.to_thread(mint_stick_token)
            (STATE / "agent-session.json").write_text(
                json.dumps({"token": token, "via": "sticklink-lab", "exp": time.time() + 3600, "at": time.time()}),
                encoding="utf-8",
            )
            log("agent-session ready (proxy /agent-zero without WebRTC)")
        except Exception as e:
            log(f"agent-session mint failed: {e}")
            raise

        # Default lab path: hold the process so the reverse proxy keeps working.
        # WebRTC/DC tunnel is optional (SL_WEBRTC=1) and usually fails on cellular.
        if os.environ.get("SL_WEBRTC", "0") != "1":
            log("holding for reverse-proxy Agent Zero (set SL_WEBRTC=1 for DC tunnel)")
            while True:
                await asyncio.sleep(3600)

        pc = RTCPeerConnection(configuration=ICE)
        dc = pc.createDataChannel("sl1", ordered=True)
        dc_q: asyncio.Queue = asyncio.Queue()

        @dc.on("message")
        def _on_dc_msg(message):
            dc_q.put_nowait(bytes(message) if not isinstance(message, bytes) else message)

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)
        for _ in range(100):
            if pc.iceGatheringState == "complete":
                break
            await asyncio.sleep(0.1)

        while True:
            m = await sw.next()
            if m.get("t") != "pmsg":
                continue
            obj = json.loads(open_env(env_k, mbx, 0x01, unb64u(m["body"])))
            if obj.get("k") == "need-offer":
                body = seal_env(env_k, mbx, 0x02, json.dumps({"k": "offer", "sdp": pc.localDescription.sdp}).encode())
                await raw.send(json.dumps({"t": "pmsg", "to": peer["conn"], "body": b64u(body)}))
                log("sent offer")
                break

        answer_deadline = time.time() + 120
        while True:
            remaining = max(1.0, answer_deadline - time.time())
            if remaining <= 1 and time.time() >= answer_deadline:
                raise TimeoutError("no WebRTC answer from phone (ICE/SDP); rescan fresh QR")
            try:
                m = await sw.next(timeout=min(30.0, remaining))
            except asyncio.TimeoutError:
                if time.time() >= answer_deadline:
                    raise TimeoutError("no WebRTC answer from phone (ICE/SDP); rescan fresh QR")
                log("still waiting for phone WebRTC answer…")
                continue
            if m.get("t") != "pmsg":
                continue
            obj = json.loads(open_env(env_k, mbx, 0x01, unb64u(m["body"])))
            if obj.get("k") == "answer":
                await pc.setRemoteDescription(RTCSessionDescription(sdp=obj["sdp"], type="answer"))
                log("set remote answer")
                break

        dc_deadline = time.time() + 90
        while dc.readyState != "open":
            if time.time() >= dc_deadline:
                raise TimeoutError(f"datachannel not open (state={dc.readyState}); TURN/ICE failed from phone")
            await asyncio.sleep(0.05)
        log("datachannel open")

        prologue = qr_prologue(home, mbx, stick_pub)
        resp = noise.Responder(stick_priv, prologue)
        msg1 = await asyncio.wait_for(dc_q.get(), timeout=60)
        rs, _ = resp.read_msg1(bytes(msg1))
        sess, msg2 = resp.write_msg2(boot)
        dc.send(bytes(msg2))
        log("noise ok")

        async def dc_recv_pt():
            rawm = await dc_q.get()
            n0 = int.from_bytes(rawm[:8], "little")
            return sess.decrypt(n0, rawm[8:])

        def dc_send_pt(obj):
            n0, ct = sess.encrypt(json.dumps(obj).encode())
            dc.send(_frame(n0, ct))

        ready_obj = json.loads(await dc_recv_pt())
        assert ready_obj.get("t") == "ready"

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
        log("pair_psk+confirm ok")
        # Token may already exist from peer-join mint; refresh if needed
        if not (STATE / "agent-session.json").exists():
            token = await asyncio.to_thread(mint_stick_token)
            (STATE / "agent-session.json").write_text(
                json.dumps({"token": token, "via": "sticklink-lab", "exp": time.time() + 3600, "at": time.time()}),
                encoding="utf-8",
            )
        dc_send_pt({"t": "agent_ready", "via": "sticklink-lab"})
        log("agent_ready sent; serving http_req tunnel (optional path)")

        # Serve until phone disconnects
        while True:
            msg = json.loads(await dc_recv_pt())
            t = msg.get("t")
            if t == "http_req":
                rid = msg.get("id")
                method = str(msg.get("method") or "GET").upper()
                path = str(msg.get("path") or "/")
                if not path.startswith("/"):
                    path = "/" + path
                # Only allow StickLLM/Agent paths
                allowed = (
                    path.startswith("/agent-zero")
                    or path.startswith("/api/agent")
                    or path.startswith("/api/pair/status")
                    or path == "/"
                    or path.startswith("/assets")
                    or path.startswith("/app.js")
                    or path.startswith("/style")
                )
                if not allowed:
                    dc_send_pt({"t": "http_res", "id": rid, "status": 403, "headers": {"content-type": "text/plain"}, "body_b64": b64u(b"forbidden path")})
                    continue
                hdrs = msg.get("headers") if isinstance(msg.get("headers"), dict) else {}
                body = unb64u(msg["body_b64"]) if msg.get("body_b64") else None
                try:
                    res = await asyncio.to_thread(stick_http, token, method, path, hdrs, body)
                    res["t"] = "http_res"
                    res["id"] = rid
                    # Cap body for DC (~256KB lab)
                    raw = unb64u(res["body_b64"])
                    if len(raw) > 250_000:
                        res["body_b64"] = b64u(raw[:250_000])
                        res["headers"]["x-sticklink-truncated"] = "1"
                    dc_send_pt(res)
                    log(f"http {method} {path} -> {res['status']}")
                except Exception as e:
                    dc_send_pt({"t": "http_res", "id": rid, "status": 502, "headers": {"content-type": "text/plain"}, "body_b64": b64u(str(e).encode())})
            elif t == "ping":
                dc_send_pt({"t": "pong"})
            elif t == "close":
                log("client close")
                break


if __name__ == "__main__":
    asyncio.run(main())
