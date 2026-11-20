"""Minimal DERP client (tailscale derp protocol v2, derp/derp.go), asyncio.

HTTP(S) GET /derp with Upgrade: DERP -> 101, then frames of
type(1) || len(4 BE) || payload. Login: server sends ServerKey (magic + 32 B
key), client sends ClientInfo (pub || naclbox(json)), server sends
ServerInfo. Packets: SendPacket(dst32 || pkt) / RecvPacket(src32 || pkt).

The relay only ever sees the sticklink UDP packets, which are Noise messages;
the node key here is a separate, registerable Curve25519 key (relay.reg nk).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import ssl
import struct
from urllib.parse import urlsplit

from nacl.public import Box, PrivateKey, PublicKey

MAGIC = b"DERP\xf0\x9f\x94\x91"
F_SERVER_KEY, F_CLIENT_INFO, F_SERVER_INFO = 0x01, 0x02, 0x03
F_SEND, F_RECV, F_KEEPALIVE, F_NOTE_PREFERRED = 0x04, 0x05, 0x06, 0x07
F_PEER_GONE, F_PEER_PRESENT, F_PING, F_PONG, F_HEALTH, F_RESTARTING = 0x08, 0x09, 0x12, 0x13, 0x14, 0x15
MAX_FRAME = 1 << 20
MAX_PACKET = 64 << 10


class DerpError(Exception):
    pass


def normalise_pin(p: str) -> str:
    """Accepts 'sha256:<hex>', '<hex>' or 'AA:BB:..' (openssl -fingerprint form)."""
    h = p.strip().lower().removeprefix("sha256:").removeprefix("sha256 fingerprint=").replace(":", "")
    if len(h) != 64 or any(c not in "0123456789abcdef" for c in h):
        raise ValueError("pin must be a SHA-256 hex fingerprint")
    return h


def nodekey_str(pub: bytes) -> str:
    return "nodekey:" + pub.hex()


def parse_nodekey(s: str) -> bytes:
    if not isinstance(s, str) or not s.startswith("nodekey:") or len(s) != 8 + 64:
        raise ValueError("bad nodekey")
    return bytes.fromhex(s[8:])


class DerpClient:
    def __init__(self, url: str, priv: bytes, cafile: str | None = None, on_packet=None, log=print,
                 pin_sha256: str | None = None, sni: str | None = None):
        self.sni = sni
        self.url, self.priv = url, PrivateKey(priv)
        self.pin = normalise_pin(pin_sha256) if pin_sha256 else None
        self.pub = bytes(self.priv.public_key)
        self.cafile, self.on_packet, self.log = cafile, on_packet, log
        self.reader = self.writer = None
        self.server_key = None
        self.connected = asyncio.Event()
        self._wlock = asyncio.Lock()

    async def _read_frame(self):
        hdr = await self.reader.readexactly(5)
        t, n = hdr[0], struct.unpack("!I", hdr[1:])[0]
        if n > MAX_FRAME:
            raise DerpError("frame too large")
        return t, await self.reader.readexactly(n)

    async def _write_frame(self, t: int, payload: bytes):
        async with self._wlock:
            self.writer.write(bytes([t]) + struct.pack("!I", len(payload)) + payload)
            await self.writer.drain()

    async def connect(self, timeout: float = 10.0):
        u = urlsplit(self.url)
        tls = u.scheme == "https"
        port = u.port or (443 if tls else 80)
        ctx = None
        if tls:
            ctx = ssl.create_default_context(cafile=self.cafile)
            if self.pin:  # self-signed dev relay: trust exactly this certificate (SHA-256 of the DER leaf)
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(u.hostname, port, ssl=ctx, server_hostname=(self.sni or u.hostname) if tls else None), timeout)
        if tls and self.pin:
            der = self.writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
            if not der or not hmac.compare_digest(hashlib.sha256(der).hexdigest(), self.pin):
                self.writer.close()
                raise DerpError("relay certificate does not match the pinned SHA-256")
        path = u.path or "/derp"
        req = (f"GET {path} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: DERP\r\nConnection: Upgrade\r\n"
               f"User-Agent: sticklinkd\r\n\r\n").encode()
        self.writer.write(req)
        await self.writer.drain()
        head = await asyncio.wait_for(self.reader.readuntil(b"\r\n\r\n"), timeout)
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status + b" ":
            raise DerpError(f"upgrade refused: {status[:60]!r}")
        t, p = await asyncio.wait_for(self._read_frame(), timeout)
        if t != F_SERVER_KEY or p[:8] != MAGIC or len(p) < 40:
            raise DerpError("bad server key frame")
        self.server_key = p[8:40]
        info = json.dumps({"version": 2, "CanAckPings": True}).encode()
        await self._write_frame(F_CLIENT_INFO, self.pub + bytes(Box(self.priv, PublicKey(self.server_key)).encrypt(info)))
        # ServerInfo arrives only if admitted (sticklink-admit allowlist); a refusal closes the socket.
        t, p = await asyncio.wait_for(self._read_frame(), timeout)
        if t != F_SERVER_INFO:
            raise DerpError(f"expected ServerInfo, got 0x{t:02x}")
        Box(self.priv, PublicKey(self.server_key)).decrypt(p[24:], p[:24])
        await self._write_frame(F_NOTE_PREFERRED, b"\x01")
        self.connected.set()

    async def send(self, dst: bytes, pkt: bytes):
        if len(pkt) > MAX_PACKET:
            raise DerpError("packet too big")
        await self._write_frame(F_SEND, dst + pkt)

    async def run(self):
        """Read loop. Returns when the connection closes."""
        try:
            while True:
                t, p = await self._read_frame()
                if t == F_RECV and len(p) >= 32:
                    if self.on_packet:
                        self.on_packet(p[:32], p[32:])
                elif t == F_PING and len(p) == 8:
                    await self._write_frame(F_PONG, p)
                elif t == F_HEALTH and p:
                    self.log(f"derp health: {p[:80].decode(errors='replace')}")
                elif t == F_PEER_GONE:
                    pass
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            self.connected.clear()

    async def close(self):
        if self.writer:
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass
