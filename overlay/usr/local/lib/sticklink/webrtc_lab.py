"""Lab WebRTC DataChannel framing for Noise IKpsk2 (browser path).

Without aiortc installed, the LoopbackChannel exercises the same byte framing
the browser and stick will use. Optional AiortcBridge loads only when aiortc
is present (Linux VM preferred).

Frame (big-endian):
  u8  type
  u16 length
  bytes payload

Types:
  0x01 noise_msg1   initiator -> stick (96 B Noise msg1)
  0x02 noise_msg2   stick -> initiator (48 B Noise msg2)
  0x10 transport    Noise transport ciphertext (after handshake)
  0x7e abort        UTF-8 reason (lab)
"""
from __future__ import annotations

import asyncio
import os
import struct
from dataclasses import dataclass

from . import noise

T_MSG1 = 0x01
T_MSG2 = 0x02
T_TRANSPORT = 0x10
T_ABORT = 0x7E


def _require_lab():
    if os.environ.get("STICKLINK_TESTING") != "1" or os.environ.get("STICKLINK_LAB") != "1":
        raise PermissionError("webrtc_lab requires STICKLINK_TESTING=1 and STICKLINK_LAB=1")


def pack_frame(ftype: int, payload: bytes) -> bytes:
    if not 0 <= ftype <= 255:
        raise ValueError("bad frame type")
    if len(payload) > 0xFFFF:
        raise ValueError("payload too large")
    return struct.pack(">BH", ftype, len(payload)) + payload


def unpack_frames(buf: bytearray) -> list[tuple[int, bytes]]:
    """Consume complete frames from buf; leave remainder."""
    out = []
    while len(buf) >= 3:
        ftype, length = struct.unpack_from(">BH", buf, 0)
        if len(buf) < 3 + length:
            break
        payload = bytes(buf[3:3 + length])
        del buf[:3 + length]
        out.append((ftype, payload))
    return out


@dataclass
class NoiseOverChannel:
    """Drive IKpsk2 over an abstract bidirectional byte channel."""

    role: str  # "initiator" | "responder"
    static_priv: bytes
    remote_static: bytes
    psk: bytes
    prologue: bytes
    send: object  # async callable(bytes)
    e_priv: bytes | None = None

    def __post_init__(self):
        _require_lab()
        if self.role not in ("initiator", "responder"):
            raise ValueError("role")
        self._buf = bytearray()
        self.session = None
        if self.role == "initiator":
            self._hs = noise.Initiator(
                self.static_priv, self.remote_static, self.psk, self.prologue, e_priv=self.e_priv)
        else:
            self._hs = noise.Responder(self.static_priv, self.prologue, e_priv=self.e_priv)

    async def start_initiator(self):
        if self.role != "initiator":
            raise RuntimeError("not initiator")
        await self.send(pack_frame(T_MSG1, self._hs.write_msg1()))

    async def on_bytes(self, data: bytes):
        self._buf.extend(data)
        for ftype, payload in unpack_frames(self._buf):
            await self._on_frame(ftype, payload)

    async def _on_frame(self, ftype: int, payload: bytes):
        if ftype == T_ABORT:
            raise noise.NoiseError(f"abort: {payload.decode('utf-8', 'replace')}")
        if self.role == "responder" and ftype == T_MSG1 and self.session is None:
            rs, _ = self._hs.read_msg1(payload)
            if rs != self.remote_static:
                raise noise.NoiseError("unexpected initiator static")
            sess, msg2 = self._hs.write_msg2(self.psk)
            self.session = sess
            await self.send(pack_frame(T_MSG2, msg2))
            return
        if self.role == "initiator" and ftype == T_MSG2 and self.session is None:
            self.session, _ = self._hs.read_msg2(payload)
            return
        if ftype == T_TRANSPORT and self.session is not None:
            # nonce is first 8 bytes LE of transport framing for lab
            if len(payload) < 8:
                raise noise.NoiseError("short transport")
            n = int.from_bytes(payload[:8], "little")
            pt = self.session.decrypt(n, payload[8:])
            if self.on_plaintext:
                await self.on_plaintext(pt)
            return
        raise noise.NoiseError(f"unexpected frame type 0x{ftype:02x}")

    on_plaintext = None  # optional async callback

    async def send_plaintext(self, pt: bytes):
        if self.session is None:
            raise RuntimeError("handshake incomplete")
        n, ct = self.session.encrypt(pt)
        await self.send(pack_frame(T_TRANSPORT, n.to_bytes(8, "little") + ct))


class LoopbackChannel:
    """Two NoiseOverChannel peers over asyncio queues (no aiortc)."""

    def __init__(self):
        _require_lab()
        self.a2b: asyncio.Queue[bytes] = asyncio.Queue()
        self.b2a: asyncio.Queue[bytes] = asyncio.Queue()

    def wire(self, left: NoiseOverChannel, right: NoiseOverChannel):
        left.send = self.a2b.put
        right.send = self.b2a.put

        async def pump(q, peer: NoiseOverChannel):
            while True:
                data = await q.get()
                await peer.on_bytes(data)

        return asyncio.create_task(pump(self.a2b, right)), asyncio.create_task(pump(self.b2a, left))


def aiortc_available() -> bool:
    try:
        import aiortc  # noqa: F401
        return True
    except ImportError:
        return False
