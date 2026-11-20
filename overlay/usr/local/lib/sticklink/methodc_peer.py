"""Stick-resident Method C peer (Milestone A).

Phone wire protocol unchanged (methodc-lte-accept-20261108.1 / APP-MUX-V1).
Upstream Agent Zero is **loopback only** — never a lab-PC address.

Development authorization (`stickllm-sticklink-lab-grant`) is used only when
METHODC_DEV_AUTH=1. It is not production trusted-device approval (Milestone B).
"""
from __future__ import annotations

import asyncio
import http.cookiejar
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("STICKLINK_TESTING", "1")
os.environ.setdefault("STICKLINK_LAB", "1")
os.environ.setdefault("STICKLINK_FAST_KDF", "1")

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sticklink import crypto, noise, pair_qr
from sticklink.app_mux_bridge import AppMuxBridge
from sticklink.util import b64u, unb64u

RUN = Path(os.environ.get("STICKLLM_RUN", "/run/stickllm"))
ROOT = Path(os.environ.get("STICKLINK_ROOT", "/var/lib/sticklink"))
WS_URL = os.environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")
# Optional public join host (Worker/Pages). Empty → peer stays up and waits.
JOIN_PUBLIC_BASE = os.environ.get("SL_JOIN_PUBLIC_BASE", "").rstrip("/")
DEV_AUTH = os.environ.get("METHODC_DEV_AUTH", "0") == "1"
SESSION_RETRY_SEC = int(os.environ.get("METHODC_RETRY_SEC", "5"))
# Mailbox / on-screen QR lifetime request (server clamps to MBX_EXP_S, usually 60s).
# Short so the kiosk QR expires on display; Refresh mints a new one. Live phone
# sessions must NOT die when this TTL hits (server keeps mjoin; peer ignores pair.closed).
PAIR_OPEN_EXP_SEC = int(os.environ.get("METHODC_PAIR_EXP_SEC", "60"))


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} methodc-peer: {msg}", flush=True)


async def sleep_interruptible(seconds: float, *, check_remint: bool = True) -> bool:
    """Sleep up to `seconds`. Return True if remint.req appeared (abort early)."""
    deadline = time.time() + max(0.0, float(seconds))
    while time.time() < deadline:
        if check_remint and remint_requested():
            return True
        await asyncio.sleep(min(1.0, max(0.05, deadline - time.time())))
    return bool(check_remint and remint_requested())


def resolve_a0_https() -> str:
    """Force Agent Zero upstream to loopback. Lab-PC / LAN hosts are refused."""
    raw = (os.environ.get("SL_A0_HTTPS") or "https://127.0.0.1").strip().rstrip("/")
    u = urlparse(raw)
    host = (u.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(
            f"refusing non-local Agent Zero upstream {raw!r}; "
            "Method C peer may only reach loopback A0"
        )
    if u.scheme not in ("https", "http"):
        raise RuntimeError(f"bad SL_A0_HTTPS scheme: {raw!r}")
    # Normalize to https://127.0.0.1 (gateway TLS on stick).
    return "https://127.0.0.1"


A0_HTTPS = "https://127.0.0.1"  # set in main after resolve


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


def load_identity() -> tuple[dict, bytes]:
    ids_path = ROOT / "device.ids.json"
    seed_path = ROOT / "device-auth-seed"
    if not ids_path.is_file():
        cand = list(ROOT.glob("*.ids.json"))
        if not cand:
            raise FileNotFoundError(f"no device ids under {ROOT}")
        ids_path = cand[0]
    if not seed_path.is_file():
        raise FileNotFoundError(f"missing {seed_path}")
    ids = json.loads(ids_path.read_text(encoding="utf-8"))
    seed = unb64u(seed_path.read_text(encoding="utf-8").strip(), 32)
    return ids, seed


# Boot-scoped Bearer (tmpfs /run). Survives Method C remints / new QRs; cleared on reboot.
BOOT_BEARER = RUN / "sticklink-methodc-bearer"


def _bearer_alive(token: str) -> bool:
    """True if gateway still accepts this StickLink lab Bearer."""
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        f"{A0_HTTPS}/api/pair/status",
        headers={
            "Authorization": f"Bearer {token}",
            "X-StickLLM-Client": "ui",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            if r.status != 200:
                return False
            doc = json.loads(r.read().decode())
        # Loopback status may set require_pair false; accept any 200 with ok/paired.
        return bool(doc.get("ok", True)) or bool(doc.get("paired")) or "require_pair" in doc
    except Exception:
        return False


def mint_dev_token(*, force: bool = False) -> str:
    """Isolated development grant only — not production authorization.

    Reuse one Bearer for the whole stick boot so a live phone session is not
    invalidated when the kiosk remints a QR or the peer starts another mailbox.
    """
    if not DEV_AUTH:
        raise RuntimeError(
            "METHODC_DEV_AUTH=1 required for temporary lab grant "
            "(Milestone A development testing only; not production auth)"
        )
    RUN.mkdir(parents=True, exist_ok=True)
    if not force and BOOT_BEARER.is_file():
        try:
            existing = BOOT_BEARER.read_text(encoding="utf-8").strip()
        except Exception:
            existing = ""
        if len(existing) >= 32 and _bearer_alive(existing):
            log(f"reusing boot Bearer …{existing[-6:]}")
            return existing

    env = os.environ.copy()
    env["METHODC_DEV_AUTH"] = "1"
    grant_bin = "/usr/local/bin/stickllm-sticklink-lab-grant"
    # Peer unit runs as root; avoid depending on sudoers for the DEV grant helper.
    cmd = [grant_bin] if os.geteuid() == 0 else ["sudo", "-n", grant_bin]
    out = subprocess.check_output(cmd, text=True, timeout=30, env=env)
    grant = ""
    for line in out.splitlines():
        s = line.strip()
        if len(s) >= 32 and " " not in s and not s.startswith("{"):
            grant = s
            break
    if not grant:
        raise RuntimeError("dev grant mint failed: " + out[-400:])
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        f"{A0_HTTPS}/api/pair/sticklink-lab",
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
    token = str(doc["token"])
    try:
        BOOT_BEARER.write_text(token + "\n", encoding="utf-8")
        BOOT_BEARER.chmod(0o600)
    except Exception as e:
        log(f"warn: could not persist boot Bearer: {e}")
    return token


class LocalA0Bridge:
    def __init__(self, token: str, origin: str):
        self.token = token
        self.ctx = ssl._create_unverified_context()
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.ctx),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        self.origin = origin
        self.referer = self.origin + "/agent-zero/"

    def cookie_header(self) -> str:
        return "; ".join(f"{c.name}={c.value}" for c in self.jar)

    def request(self, method: str, path: str, headers: dict | None = None, body: bytes | None = None) -> dict:
        # Defense in depth: never leave loopback.
        if urlparse(self.origin).hostname not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError("A0 bridge origin escaped loopback")
        url = self.origin + path
        hdrs = {
            "Authorization": f"Bearer {self.token}",
            "X-StickLLM-Client": "ui",
            "Accept": "*/*",
            "User-Agent": "StickLink-methodc-peer",
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
                    "cookie",
                    "origin",
                    "referer",
                ) or lk.startswith("sec-"):
                    continue
                hdrs[k] = v
        cookie = self.cookie_header()
        if cookie:
            hdrs["Cookie"] = cookie
        req = urllib.request.Request(url, data=body, method=method.upper(), headers=hdrs)
        try:
            with self.opener.open(req, timeout=60) as r:
                raw, status, resp_headers = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            raw, status, resp_headers = e.read(), e.code, e.headers
        out_headers = {k.lower(): v for k, v in resp_headers.items()}
        return {"status": status, "headers": out_headers, "body_b64": b64u(raw), "cookies": self.cookie_header()}


def publish_remint_status(status: str, **extra) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    doc = {"status": status, "at": time.time(), **extra}
    (RUN / "sticklink-join-remint.json").write_text(json.dumps(doc), encoding="utf-8")


def clear_remint_req() -> None:
    remint_req = RUN / "sticklink-join-remint.req"
    try:
        remint_req.unlink(missing_ok=True)
    except TypeError:
        if remint_req.is_file():
            remint_req.unlink()


def publish_join(qr: str, join_url: str, mbx_b: str, home: str, exp_abs: int) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    doc = {
        "qr": qr,
        "url": join_url,
        "mbx": mbx_b,
        "home": home,
        "exp": exp_abs,
        "at": time.time(),
        "via": "methodc-peer",
        "dev_auth": DEV_AUTH,
        "connected": False,
    }
    (RUN / "sticklink-join.json").write_text(json.dumps(doc), encoding="utf-8")
    (RUN / "sticklink-join-url.txt").write_text(join_url + "\n", encoding="utf-8")
    # Ack kiosk Refresh / remint so Devices & Pairing stops spinning.
    publish_remint_status("done", url=join_url, exp=exp_abs)
    clear_remint_req()
    log(f"published join → {RUN / 'sticklink-join.json'}")


def publish_connected(*, conn: str = "") -> None:
    """Hide the kiosk QR as soon as a phone joins this mailbox.

    Clears the scannable join URL so a second phone cannot reuse the same QR
    while the first session is live. Explicit Generate (remint.req) ends the
    session immediately and mints a new QR — it is not deferred.
    """
    RUN.mkdir(parents=True, exist_ok=True)
    doc = {
        "connected": True,
        "url": "",
        "qr": "",
        "at": time.time(),
        "via": "methodc-peer",
        "dev_auth": DEV_AUTH,
        "conn": conn or None,
    }
    (RUN / "sticklink-join.json").write_text(json.dumps(doc), encoding="utf-8")
    try:
        (RUN / "sticklink-join-url.txt").unlink(missing_ok=True)
    except TypeError:
        p = RUN / "sticklink-join-url.txt"
        if p.is_file():
            p.unlink()
    publish_remint_status(
        "connected",
        message="Phone connected — QR hidden. Generate a new code after it disconnects.",
        conn=conn or None,
    )
    clear_remint_req()
    log("published connected — kiosk QR cleared")


def remint_requested() -> bool:
    return (RUN / "sticklink-join-remint.req").is_file()


def read_join_doc() -> dict:
    try:
        doc = json.loads((RUN / "sticklink-join.json").read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def current_join_exp() -> int:
    try:
        return int(read_join_doc().get("exp") or 0)
    except Exception:
        return 0


def publish_idle(*, reason: str = "disconnected") -> None:
    """Clear QR and require Generate before the next pair.open."""
    RUN.mkdir(parents=True, exist_ok=True)
    doc = {
        "connected": False,
        "awaiting_remint": True,
        "url": "",
        "qr": "",
        "at": time.time(),
        "via": "methodc-peer",
        "reason": reason,
    }
    (RUN / "sticklink-join.json").write_text(json.dumps(doc), encoding="utf-8")
    try:
        (RUN / "sticklink-join-url.txt").unlink(missing_ok=True)
    except TypeError:
        p = RUN / "sticklink-join-url.txt"
        if p.is_file():
            p.unlink()
    publish_remint_status(
        "idle",
        message="Tap Generate for a new StickLink QR.",
        reason=reason,
    )
    log(f"published idle reason={reason} — waiting for Generate")


async def wait_for_mint_needed() -> None:
    """Block until a new pair.open is warranted.

    Cold boot (no join.json) → mint once.
    Valid unscanned QR → wait out TTL, then wait for Generate (no auto-remint).
    connected / awaiting_remint / empty URL after session → wait for remint.req.
    Never treat connected:true (no exp) as "no join → mint" — that auto-showed
    a new QR ~1 min after scan.
    """
    while True:
        if remint_requested():
            log("mint needed: remint.req")
            return
        path = RUN / "sticklink-join.json"
        if not path.is_file():
            log("mint needed: no join published")
            return
        doc = read_join_doc()
        if doc.get("connected") or doc.get("awaiting_remint"):
            await asyncio.sleep(1.0)
            continue
        url = str(doc.get("url") or doc.get("join") or "").strip()
        exp = 0
        try:
            exp = int(doc.get("exp") or 0)
        except Exception:
            exp = 0
        now = time.time()
        if url and exp > 0 and now < (exp - 1):
            await asyncio.sleep(1.0)
            continue
        if url and exp > 0 and now >= (exp - 1):
            publish_remint_status(
                "expired",
                message="StickLink join expired — tap Refresh StickLink QR to mint a new one.",
                exp=exp,
            )
            log("join expired — waiting for Refresh before pair.open (quota)")
            while not remint_requested():
                await asyncio.sleep(1.0)
            log("mint needed: remint.req after expiry")
            return
        # No scannable URL (idle/disconnected) — do not auto-mint.
        if not url:
            if not doc.get("awaiting_remint"):
                publish_idle(reason="empty-join")
            while not remint_requested():
                await asyncio.sleep(1.0)
            log("mint needed: remint.req after idle")
            return
        await asyncio.sleep(1.0)


def parse_rate_retry(err: BaseException) -> int | None:
    """Extract StickLink pair.open rate-limit retry seconds, if present."""
    import re

    s = str(err)
    if "rate" not in s:
        return None
    m = re.search(r"['\"]retry['\"]\s*:\s*(\d+)", s)
    if not m:
        return None
    return max(1, int(m.group(1)))


class RateLimited(RuntimeError):
    def __init__(self, retry: int, detail: str = ""):
        self.retry = retry
        super().__init__(detail or f"pair.open rate-limited retry={retry}s")


async def wait_peer_or_remint(sw: "StickWS", exp_abs: int, timeout: float | None = None):
    """Wait for phone join, or abort only on kiosk remint.

    Do **not** auto-remint on mailbox expiry — pair.open is rate-limited
    (5 / 10 min, then 10 min lock per home). Expiry marks the QR stale; the
    Devices & Pairing Refresh button writes remint.req for a deliberate remint.

    No idle/join deadline by default: an unscanned QR stays published until
    Refresh/remint or stick reboot (mailbox may already be server-expired for
    *new* scans — that is separate from this wait loop).
    """
    deadline = (time.time() + timeout) if timeout is not None and timeout > 0 else None
    expired_noted = False
    while deadline is None or time.time() < deadline:
        if remint_requested():
            raise RuntimeError("kiosk remint requested")
        if not expired_noted and time.time() >= (exp_abs - 1):
            expired_noted = True
            publish_remint_status(
                "expired",
                message="StickLink join expired — tap Refresh StickLink QR to mint a new one.",
                exp=exp_abs,
            )
            log("QR expired — waiting for kiosk remint (not auto-reminting; protects pair.open quota)")
        try:
            m = await sw.next(timeout=1.0)
        except asyncio.TimeoutError:
            continue
        if m.get("t") == "peer" and m.get("state") == "join":
            return m
        if m.get("t") == "err":
            raise RuntimeError(f"err while waiting peer: {m}")
    raise TimeoutError("no peer join before timeout")


def ice_configuration():
    from aiortc import RTCConfiguration, RTCIceServer

    return RTCConfiguration(
        iceServers=[
            RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
            RTCIceServer(urls=["stun:stun.cloudflare.com:3478"]),
            RTCIceServer(urls=["stun:relay-tor1.stickllm.com:3478"]),
        ]
    )


async def ed_hello_sig(seed: bytes, n: bytes, dev: bytes, role: int, home: bytes | None) -> bytes:
    home16 = home if home is not None else b"\x00" * 16
    body = n + dev + bytes([role]) + home16
    msg = b"sl1/dev-hello/v1\x00" + body
    return Ed25519PrivateKey.from_private_bytes(seed).sign(msg)


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


async def run_one_session(a0_https: str) -> None:
    from aiortc import RTCPeerConnection, RTCSessionDescription

    global A0_HTTPS
    A0_HTTPS = a0_https

    if not JOIN_PUBLIC_BASE.startswith("https://"):
        raise RuntimeError(
            "SL_JOIN_PUBLIC_BASE unset — waiting for public https:// join host "
            "(Worker/Pages; not lab PC; CF must not proxy A0)"
        )

    ids, seed = load_identity()
    dev = unb64u(ids["dev"], 16)
    home = unb64u(ids["home"], 16)
    stick_priv = crypto.x25519_generate()
    stick_pub = crypto.x25519_public(stick_priv)

    uri = f"{WS_URL}?dev={ids['dev']}"
    # Protocol-level WS pings keep the stick signalling socket alive for the
    # whole live session (no idle expiry on our side).
    async with websockets.connect(
        uri,
        subprotocols=["sticklink.1"],
        open_timeout=30,
        ping_interval=20,
        ping_timeout=60,
        close_timeout=5,
    ) as raw:
        sw = StickWS(raw)
        asyncio.create_task(sw.reader())
        welcome = await sw.expect("welcome")
        n = unb64u(welcome["n"], 32)
        sig = await ed_hello_sig(seed, n, dev, 1, home)
        await sw.req(
            {
                "t": "hello",
                "id": 1,
                "dev": ids["dev"],
                "role": "server",
                "home": ids["home"],
                "sig": b64u(sig),
            },
            "ready",
        )
        log("signalling ready")
        await wait_for_mint_needed()

        invite = crypto.random_key()
        jk = pair_qr.jk_qr(invite)
        try:
            ok = await sw.req(
                {
                    "t": "pair.open",
                    "id": 11,
                    "m": "qr",
                    "jk": b64u(jk),
                    "exp": max(60, PAIR_OPEN_EXP_SEC),
                },
                "pair.ok",
            )
        except RuntimeError as e:
            retry = parse_rate_retry(e)
            if retry is not None:
                raise RateLimited(retry, str(e)) from e
            raise
        mbx_b = ok["mbx"]
        mbx = unb64u(mbx_b, 8)
        exp_abs = int(time.time()) + int(ok["exp"])
        qr = pair_qr.encode_qr(
            mailbox_id=mbx, stick_static_pub=stick_pub, invite_secret=invite, exp=exp_abs
        )
        env_k = pair_qr.env_qr(invite, mbx, home)
        th = pair_qr.transcript_hash(mailbox_id=mbx, home_id=home, stick_static_pub=stick_pub)
        boot = pair_qr.boot_psk(invite, th)

        join_url = (
            f"{JOIN_PUBLIC_BASE}/browser/agent_join.html"
            f"?ws={urllib.parse.quote(WS_URL, safe='')}"
            f"&qr={urllib.parse.quote(qr, safe='')}"
        )
        publish_join(qr, join_url, mbx_b, ids["home"], exp_abs)
        log(f"QR ready exp={exp_abs}")

        peer = await wait_peer_or_remint(sw, exp_abs, timeout=None)
        log(f"peer join {peer.get('conn')}")
        assert peer.get("state") == "join"
        # Stop displaying the QR immediately on join (before WebRTC finishes).
        publish_connected(conn=str(peer.get("conn") or ""))

        ice = ice_configuration()
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
            if remint_requested():
                raise RuntimeError("kiosk remint requested")
            if pc.iceGatheringState == "complete":
                break
            await asyncio.sleep(0.1)

        need_offer_deadline = time.time() + 120
        while True:
            if remint_requested():
                raise RuntimeError("kiosk remint requested")
            if time.time() >= need_offer_deadline:
                raise TimeoutError("no need-offer from phone")
            try:
                m = await sw.next(timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if m.get("t") != "pmsg":
                continue
            obj = json.loads(open_env(env_k, mbx, 0x01, unb64u(m["body"])))
            if obj.get("k") == "need-offer":
                body = seal_env(
                    env_k, mbx, 0x02, json.dumps({"k": "offer", "sdp": pc.localDescription.sdp}).encode()
                )
                await raw.send(json.dumps({"t": "pmsg", "to": peer["conn"], "body": b64u(body)}))
                log("sent offer")
                break

        answer_deadline = time.time() + 120
        while True:
            if remint_requested():
                raise RuntimeError("kiosk remint requested")
            if time.time() >= answer_deadline:
                raise TimeoutError("no WebRTC answer from phone")
            remaining = max(1.0, answer_deadline - time.time())
            try:
                m = await sw.next(timeout=min(1.0, remaining))
            except asyncio.TimeoutError:
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
                raise TimeoutError(f"datachannel not open (state={dc.readyState})")
            await asyncio.sleep(0.05)
        log("datachannel open")

        prologue = qr_prologue(home, mbx, stick_pub)
        resp = noise.Responder(stick_priv, prologue)
        msg1 = await asyncio.wait_for(dc_q.get(), timeout=60)
        rs, _ = resp.read_msg1(bytes(msg1))
        sess, msg2 = resp.write_msg2(boot)
        dc.send(bytes(msg2))
        log("noise ok")

        _DC_CLOSED = object()

        async def dc_recv_pt():
            rawm = await dc_q.get()
            if rawm is _DC_CLOSED:
                raise ConnectionError("datachannel closed")
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
            r_i=r_i,
            r_r=r_r,
            prior=boot,
            handshake_hash=hh,
            th=th,
            initiator_static=rs,
            responder_static=stick_pub,
            key_epoch=0,
        )
        kc = pair_qr.pair_confirm_kc(psk)
        confirm_i = json.loads(await dc_recv_pt())
        assert confirm_i.get("t") == "confirm_i"
        if not pair_qr.verify_confirm(kc, "i", hh, unb64u(confirm_i["mac"], 32)):
            raise RuntimeError("confirm_i failed")
        dc_send_pt({"t": "confirm_r", "mac": b64u(pair_qr.confirm_mac(kc, "r", hh))})
        log("pair_psk+confirm ok")

        token = mint_dev_token()
        bridge = LocalA0Bridge(token, a0_https)
        log(f"agent bridge ready (loopback; Bearer …{token[-6:]})")

        def _remint_token() -> str:
            t = mint_dev_token(force=True)
            log(f"lab Bearer reminted …{t[-6:]}")
            return t

        mux = AppMuxBridge(
            stick_https=a0_https,
            bridge_http=bridge,
            send_pt=dc_send_pt,
            log=log,
            remint_token=_remint_token,
        )
        dc_send_pt({"t": "agent_ready", "via": "sticklink-lab"})
        log("agent_ready; app-mux → https://127.0.0.1 only")

        # Live session survives idle / mailbox TTL. Explicit kiosk Generate
        # (remint.req) ends the session immediately so the first click mints.
        keepalive_sec = float(os.environ.get("METHODC_DC_KEEPALIVE_SEC", "5"))
        last_ping = 0.0
        last_rx = time.time()
        last_pong = time.time()
        bearer_refresh_sec = float(os.environ.get("METHODC_BEARER_REFRESH_SEC", "1800"))
        last_bearer_refresh = time.time()
        force_remint = False

        @dc.on("close")
        def _on_dc_close():
            log("datachannel closed by peer/stack")
            try:
                dc_q.put_nowait(_DC_CLOSED)
            except Exception:
                pass

        @pc.on("connectionstatechange")
        def _on_pc_state():
            log(f"webrtc connectionState={pc.connectionState}")

        # Drain signalling (pair.closed / peer leave) without ending the DC session.
        # Mailbox QR TTL must not kill an already-live Agent Zero bridge.
        async def _drain_signalling():
            while True:
                try:
                    m = await sw.next(timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    log(f"signalling drain ended: {e}")
                    return
                t = m.get("t")
                if t == "pair.closed":
                    log(f"signalling pair.closed why={m.get('why')} — keeping live DC")
                    continue
                if t == "peer" and m.get("state") == "leave":
                    log(f"signalling peer leave conn={m.get('conn')} — keeping live DC")
                    continue
                if t == "err":
                    log(f"signalling err (ignored during live): {m}")

        drain_task = asyncio.create_task(_drain_signalling())
        try:
            while True:
                if remint_requested():
                    force_remint = True
                    log("kiosk remint — ending live session for new QR")
                    raise RuntimeError("kiosk remint requested")
                if dc.readyState != "open":
                    log(f"datachannel not open (state={dc.readyState}) — ending live session")
                    break
                if pc.connectionState in ("failed", "closed"):
                    log(f"webrtc {pc.connectionState} — ending live session")
                    break
                try:
                    raw_msg = await asyncio.wait_for(dc_recv_pt(), timeout=1.0)
                except asyncio.TimeoutError:
                    now = time.time()
                    if (
                        bearer_refresh_sec > 0
                        and (now - last_bearer_refresh) >= bearer_refresh_sec
                    ):
                        # Renew lab Bearer in place — never tears down the DataChannel.
                        try:
                            bridge.token = mint_dev_token(force=True)
                            last_bearer_refresh = now
                            log(f"proactive lab Bearer refresh …{bridge.token[-6:]}")
                        except Exception as e:
                            log(f"proactive Bearer refresh failed (keeping session): {e}")
                            last_bearer_refresh = now  # avoid tight retry loop
                    if keepalive_sec > 0 and (now - last_ping) >= keepalive_sec:
                        # Application ping keeps NAT / ICE consent fresh while the
                        # phone tab is alive; JS may be suspended when backgrounded.
                        try:
                            dc_send_pt({"t": "ping", "ts": int(now)})
                            last_ping = now
                            if (now - last_pong) > max(45.0, keepalive_sec * 6):
                                log(
                                    f"keepalive: no pong for {int(now - last_pong)}s "
                                    "(phone may be backgrounded; sticking with DC)"
                                )
                        except Exception as e:
                            log(f"keepalive ping failed: {e}")
                            break
                    continue
                except ConnectionError as e:
                    log(f"dc_recv ended: {e}")
                    break
                except Exception as e:
                    log(f"dc_recv ended: {e}")
                    break
                last_rx = time.time()
                msg = json.loads(raw_msg)
                t = msg.get("t")
                if t == "close":
                    log("client close")
                    break
                if t == "pong":
                    last_pong = time.time()
                    continue
                if t == "ping":
                    # Phone keepalive — answer so both sides confirm DC liveness.
                    try:
                        dc_send_pt(
                            {"t": "pong", "ts": msg.get("ts"), "id": msg.get("id")}
                        )
                    except Exception as e:
                        log(f"keepalive pong failed: {e}")
                        break
                    continue
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
        finally:
            drain_task.cancel()
            try:
                await drain_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        log(f"live session ended (idle_ok last_rx_age={int(time.time() - last_rx)}s)")
        try:
            await pc.close()
        except Exception:
            pass

        if force_remint or remint_requested():
            raise RuntimeError("kiosk remint requested")
        # Natural disconnect — do not auto-mint; wait for Generate.
        publish_idle(reason="session-ended")
        raise RuntimeError("session ended — awaiting remint")


async def main() -> None:
    a0 = resolve_a0_https()
    build_stamp = os.environ.get("METHODC_BUILD_STAMP", "unknown")
    keepalive_sec = os.environ.get("METHODC_DC_KEEPALIVE_SEC", "5")
    log(
        f"build={build_stamp} keepalive_dc={keepalive_sec}s "
        f"A0 upstream={a0} DEV_AUTH={int(DEV_AUTH)} pair_exp={PAIR_OPEN_EXP_SEC} "
        f"join_base={JOIN_PUBLIC_BASE or '(unset)'}"
    )
    # Stay running: systemd Restart= + this loop recover from session failures.
    while True:
        try:
            await run_one_session(a0)
        except RateLimited as e:
            # Honour server retry — hammering pair.open extends the lock.
            # Keep remint.req so after the window the next session still mints.
            retry = max(int(e.retry), SESSION_RETRY_SEC)
            publish_remint_status(
                "rate_limited",
                message=f"StickLink pairing rate-limited — next try in {retry}s. "
                "Do not spam Refresh.",
                retry=retry,
            )
            log(f"session ended: {e!r}; honouring rate retry {retry}s")
            await sleep_interruptible(retry, check_remint=False)
        except Exception as e:
            retry = parse_rate_retry(e)
            if retry is not None:
                publish_remint_status(
                    "rate_limited",
                    message=f"StickLink pairing rate-limited — next try in {retry}s.",
                    retry=retry,
                )
                log(f"session ended: {e!r}; honouring rate retry {retry}s")
                await sleep_interruptible(
                    max(retry, SESSION_RETRY_SEC), check_remint=False
                )
                continue
            # Idle remint / session errors: short backoff, but wake immediately
            # if Devices & Pairing already asked for a new QR.
            log(f"session ended: {e!r}; retry in {SESSION_RETRY_SEC}s")
            if await sleep_interruptible(SESSION_RETRY_SEC):
                log("remint.req during backoff — minting now")


if __name__ == "__main__":
    asyncio.run(main())
