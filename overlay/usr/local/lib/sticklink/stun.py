"""Minimal RFC 5389 STUN binding request/response (XOR-MAPPED-ADDRESS) on an
existing UDP socket; derper serves STUN on udp/3478."""
from __future__ import annotations

import ipaddress
import secrets
import struct
import zlib

MAGIC = 0x2112A442
BIND_REQ = 0x0001
BIND_OK = 0x0101


SOFTWARE = b"tailnode"  # derper only answers requests carrying SOFTWARE=tailnode + FINGERPRINT


def request() -> tuple[bytes, bytes]:
    tid = secrets.token_bytes(12)
    body_len = 4 + len(SOFTWARE) + 8
    b = struct.pack("!HHI", BIND_REQ, body_len, MAGIC) + tid
    b += struct.pack("!HH", 0x8022, len(SOFTWARE)) + SOFTWARE
    fp = (zlib.crc32(b) ^ 0x5354554E) & 0xFFFFFFFF
    return b + struct.pack("!HHI", 0x8028, 4, fp), tid


def is_stun(pkt: bytes) -> bool:
    return len(pkt) >= 20 and pkt[0] & 0xC0 == 0 and struct.unpack("!I", pkt[4:8])[0] == MAGIC


def parse_response(pkt: bytes, tid: bytes) -> tuple[str, int] | None:
    if not is_stun(pkt):
        return None
    typ, ln = struct.unpack("!HH", pkt[:4])
    if typ != BIND_OK or pkt[8:20] != tid or len(pkt) < 20 + ln:
        return None
    off, end = 20, 20 + ln
    mapped = None
    while off + 4 <= end:
        at, al = struct.unpack("!HH", pkt[off:off + 4])
        v = pkt[off + 4:off + 4 + al]
        if at in (0x0020, 0x0001) and len(v) >= 8:
            fam, port = v[1], struct.unpack("!H", v[2:4])[0]
            raw = v[4:8] if fam == 1 else v[4:20]
            if at == 0x0020:
                port ^= MAGIC >> 16
                key = struct.pack("!I", MAGIC) + tid
                raw = bytes(a ^ b for a, b in zip(raw, key))
            ip = str(ipaddress.ip_address(raw))
            if at == 0x0020 or mapped is None:
                mapped = (ip, port)
        off += 4 + al + (-al % 4)
    return mapped
