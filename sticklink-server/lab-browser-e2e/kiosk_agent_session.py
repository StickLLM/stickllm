#!/usr/bin/env python3
"""Lab Method C session: rendezvous → WebRTC → Noise DC → Agent Zero http_req.

LAB BYPASS: skips native VT approval. After pair-confirm, mints a StickLink-lab
gateway grant on the stick (SSH) and answers http_req frames by fetching the
stick Agent Zero / StickLLM UI with that token.

Design path (no Cloudflare for Agent Zero):
  phone join client → wss://link.stickllm.com → WebRTC DataChannel → this
  process (Noise responder) → HTTPS to stick LAN Agent Zero.

Join HTML may be hosted anywhere (lab tunnel is only a static host). Stick traffic
rides StickLink after pair.joined.
"""
from __future__ import annotations

import asyncio
import http.cookiejar
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
from aiortc import RTCPeerConnection, RTCSessionDescription
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sticklink import crypto, noise, pair_qr
from sticklink.util import b64u, unb64u

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
STICK_HTTPS = os.environ.get("SL_STICK_HTTPS", "https://192.168.72.50")
STICK_SSH = os.environ.get("SL_STICK_HOST", "192.168.72.50")

# Lazy ICE: openrelay.metered.ca is sinkholed (192.0.2.1). lab_ice fetches a
# living short-lived TURN from elixir-webrtc Rel (+ STUN fallbacks).
def _ice_config():
    from lab_ice import aiortc_ice

    return aiortc_ice()


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


class StickHttpBridge:
    """Authenticated Agent Zero client for http_req frames.

    A0 CSRF requires the Flask session cookie issued by GET /api/csrf_token to
    accompany later POSTs that carry X-CSRF-Token. The phone cannot hold that
    cookie (requests never hit a browser jar for stick HTTPS), so the bridge
    must persist Set-Cookie across http_req calls for this paired session.
    """

    def __init__(self, token: str):
        self.token = token
        self.ctx = ssl._create_unverified_context()
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.ctx),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        self.origin = STICK_HTTPS.rstrip("/")
        self.referer = self.origin + "/agent-zero/"

    def cookie_header(self) -> str:
        parts = []
        for c in self.jar:
            parts.append(f"{c.name}={c.value}")
        return "; ".join(parts)

    def request(self, method: str, path: str, headers: dict | None = None, body: bytes | None = None) -> dict:
        url = self.origin + path
        hdrs = {
            "Authorization": f"Bearer {self.token}",
            "X-StickLLM-Client": "ui",
            "Accept": "*/*",
            "User-Agent": "StickLink-lab-tunnel",
            # A0 CSRF / session binding expects stick origin (see stickllm_a0client).
            "Origin": self.origin,
            "Referer": self.referer,
        }
        if headers:
            for k, v in headers.items():
                lk = k.lower()
                if lk in (
                    "authorization",
                    "host",
                    "connection",
                    "content-length",
                    "cookie",  # bridge jar is authoritative
                    "origin",
                    "referer",
                ):
                    continue
                if lk.startswith("sec-"):
                    continue
                hdrs[k] = v
        # Explicit Cookie from jar (HTTPCookieProcessor also sets it; keep visible for logs).
        cookie = self.cookie_header()
        if cookie:
            hdrs["Cookie"] = cookie
        req = urllib.request.Request(url, data=body, method=method.upper(), headers=hdrs)
        try:
            with self.opener.open(req, timeout=60) as r:
                raw = r.read()
                status = r.status
                resp_headers = r.headers
        except urllib.error.HTTPError as e:
            raw = e.read()
            status = e.code
            resp_headers = e.headers
        out_headers: dict[str, str] = {}
        for k, v in resp_headers.items():
            lk = k.lower()
            if lk == "set-cookie":
                # Surface to phone for debugging; bridge jar already stored it.
                prev = out_headers.get("set-cookie")
                out_headers["set-cookie"] = f"{prev}, {v}" if prev else v
            else:
                out_headers[lk] = v
        return {
            "status": status,
            "headers": out_headers,
            "body_b64": b64u(raw),
            "cookies": self.cookie_header(),
        }


def stick_http(token: str, method: str, path: str, headers: dict | None = None, body: bytes | None = None) -> dict:
    """One-shot helper (tests). Prefer StickHttpBridge for a live DC session."""
    return StickHttpBridge(token).request(method, path, headers, body)


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

        # Method C design: WebRTC + Noise DC carries Agent Zero (http_req).
        # SL_WEBRTC=0 is the old Cloudflare-proxy bypass — refuse unless explicit.
        if os.environ.get("SL_WEBRTC", "1") == "0":
            raise RuntimeError(
                "SL_WEBRTC=0 disables StickLink data path; unset it to use Method C "
                "(rendezvous → WebRTC → Noise DC). Cloudflare DIRECT is SL_ALLOW_DIRECT=1 only."
            )

        ice = _ice_config()
        log(f"ICE servers={len(ice.iceServers or [])}")
        pc = RTCPeerConnection(configuration=ice)
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
        sess_path = STATE / "agent-session.json"
        token = ""
        if sess_path.exists():
            try:
                token = str(json.loads(sess_path.read_text(encoding="utf-8")).get("token") or "")
            except Exception:
                token = ""
        if not token:
            token = await asyncio.to_thread(mint_stick_token)
            sess_path.write_text(
                json.dumps(
                    {
                        "token": token,
                        "via": "sticklink-lab",
                        "exp": time.time() + 3600,
                        "at": time.time(),
                    }
                ),
                encoding="utf-8",
            )
        bridge = StickHttpBridge(token)
        log(f"agent bridge ready (cookie jar; Bearer …{token[-6:]})")
        from app_mux_bridge import AppMuxBridge

        mux = AppMuxBridge(
            stick_https=STICK_HTTPS,
            bridge_http=bridge,
            send_pt=dc_send_pt,
            log=log,
        )
        dc_send_pt({"t": "agent_ready", "via": "sticklink-lab"})
        log("agent_ready sent; app-mux v1 on StickLink DC (no HTTP proxy for A0)")

        # Serve until phone disconnects
        while True:
            msg = json.loads(await dc_recv_pt())
            t = msg.get("t")
            if t == "close":
                log("client close")
                break
            try:
                await mux.handle(msg)
            except Exception as e:
                log(f"mux error: {e}")
                if t == "http_req" and msg.get("id"):
                    dc_send_pt(
                        {
                            "t": "http_res",
                            "id": msg["id"],
                            "status": 502,
                            "headers": {"content-type": "text/plain"},
                            "body_b64": b64u(str(e).encode()),
                        }
                    )


if __name__ == "__main__":
    asyncio.run(main())
