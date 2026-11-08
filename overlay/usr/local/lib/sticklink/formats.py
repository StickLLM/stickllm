"""Pinned sealed-file formats (§3 table, v0.9).

Every sealed file: version(0x01) || [luks_slot] || [salt] || nonce(12) || ct.
AD = label || every header byte before the nonce. Readers refuse any other
version or length and never try other keys or formats.
"""
from __future__ import annotations

from . import crypto

VERSION = 0x01
L_WRAP = b"sl1/registry-wrap"
L_WRAP_REC = b"sl1/registry-wrap-recovery"
L_IDENTITY = b"sl1/identity"
L_REC = b"sl1/rec"
I_REGISTRY = b"sl1/registry"
I_IDENTITY = b"sl1/identity"

PIN_WRAP_LEN = 1 + 1 + 12 + 48      # 62
REC_WRAP_LEN = 1 + 1 + 16 + 12 + 48  # 78
SEALED_MIN = 1 + 12 + 16


class FormatError(ValueError):
    pass


def _slot(slot: int) -> bytes:
    if not 0 <= slot <= 31:
        raise ValueError("bad luks slot")
    return bytes([slot])


# --- regkey-pin.wrap -------------------------------------------------------
def wrap_pin(wrap_key: bytes, registry_key: bytes, slot: int) -> bytes:
    if len(registry_key) != 32:
        raise ValueError("registry_key must be 32 bytes")
    hdr = bytes([VERSION]) + _slot(slot)
    nonce, ct = crypto.seal(wrap_key, registry_key, L_WRAP + hdr)
    out = hdr + nonce + ct
    assert len(out) == PIN_WRAP_LEN
    return out


def pin_wrap_slot(blob: bytes) -> int:
    if len(blob) != PIN_WRAP_LEN or blob[0] != VERSION:
        raise FormatError("regkey-pin.wrap: bad version or length")
    return blob[1]


def unwrap_pin(wrap_key: bytes, blob: bytes) -> bytes:
    pin_wrap_slot(blob)
    hdr, nonce, ct = blob[:2], blob[2:14], blob[14:]
    return crypto.open_(wrap_key, nonce, ct, L_WRAP + hdr)


# --- regkey-rec.wrap -------------------------------------------------------
def wrap_rec(wrap_key: bytes, registry_key: bytes, slot: int, salt_rec: bytes) -> bytes:
    if len(registry_key) != 32 or len(salt_rec) != 16:
        raise ValueError("bad registry_key or salt_rec")
    hdr = bytes([VERSION]) + _slot(slot) + salt_rec
    nonce, ct = crypto.seal(wrap_key, registry_key, L_WRAP_REC + hdr)
    out = hdr + nonce + ct
    assert len(out) == REC_WRAP_LEN
    return out


def rec_wrap_header(blob: bytes) -> tuple[int, bytes]:
    if len(blob) != REC_WRAP_LEN or blob[0] != VERSION:
        raise FormatError("regkey-rec.wrap: bad version or length")
    return blob[1], blob[2:18]


def unwrap_rec(wrap_key: bytes, blob: bytes) -> bytes:
    rec_wrap_header(blob)
    hdr, nonce, ct = blob[:18], blob[18:30], blob[30:]
    return crypto.open_(wrap_key, nonce, ct, L_WRAP_REC + hdr)


# --- identity.sealed / records/<peer>.rec ------------------------------------
def _seal_plain(key: bytes, label_ad: bytes, plaintext: bytes) -> bytes:
    hdr = bytes([VERSION])
    nonce, ct = crypto.seal(key, plaintext, label_ad + hdr)
    return hdr + nonce + ct


def _open_plain(key: bytes, label_ad: bytes, blob: bytes, what: str) -> bytes:
    if len(blob) < SEALED_MIN or blob[0] != VERSION:
        raise FormatError(f"{what}: bad version or length")
    return crypto.open_(key, blob[1:13], blob[13:], label_ad + blob[:1])


def identity_key(registry_key: bytes) -> bytes:
    return crypto.hkdf(registry_key, I_IDENTITY)


def record_key(registry_key: bytes) -> bytes:
    return crypto.hkdf(registry_key, I_REGISTRY)


def seal_identity(registry_key: bytes, plaintext: bytes) -> bytes:
    return _seal_plain(identity_key(registry_key), L_IDENTITY, plaintext)


def open_identity(registry_key: bytes, blob: bytes) -> bytes:
    return _open_plain(identity_key(registry_key), L_IDENTITY, blob, "identity.sealed")


def _rec_ad(peer_id: bytes) -> bytes:
    if len(peer_id) != 16:
        raise ValueError("peer_id must be 16 bytes")
    return L_REC


def seal_record(registry_key: bytes, peer_id: bytes, plaintext: bytes) -> bytes:
    _rec_ad(peer_id)
    hdr = bytes([VERSION])
    nonce, ct = crypto.seal(record_key(registry_key), plaintext, L_REC + hdr + peer_id)
    return hdr + nonce + ct


def open_record(registry_key: bytes, peer_id: bytes, blob: bytes) -> bytes:
    _rec_ad(peer_id)
    if len(blob) < SEALED_MIN or blob[0] != VERSION:
        raise FormatError("record: bad version or length")
    return crypto.open_(record_key(registry_key), blob[1:13], blob[13:], L_REC + blob[:1] + peer_id)
