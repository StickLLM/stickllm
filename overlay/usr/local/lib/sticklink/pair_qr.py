"""Method C (QR) key schedule — PAIRING-SPEC §4.5 / §4.6.

Lab and unit-test only until signalling mailboxes and the native approval
overlay ship. SPAKE2 (Method D) is intentionally absent.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import struct
from urllib.parse import parse_qs, urlencode

from . import crypto

METHOD = b"qr"
QR_PREFIX = "sl1:"
# Shipping overlay is native VT; lab may approve on trusted local kiosk only.
FEATURE_SPAKE2_CODE = "0"


def enc(x: bytes) -> bytes:
    if len(x) > 0xFFFF:
        raise ValueError("enc length overflow")
    return struct.pack(">H", len(x)) + x


def transcript_hash(*, mailbox_id: bytes, home_id: bytes, stick_static_pub: bytes,
                    initiator_static: bytes | None = None, extra: bytes = b"") -> bytes:
    """TH for Method C. initiator_static defaults to 32 zero bytes (spec X1)."""
    if len(mailbox_id) != 8 or len(home_id) != 16 or len(stick_static_pub) != 32:
        raise ValueError("bad TH field length")
    i_static = b"\x00" * 32 if initiator_static is None else initiator_static
    if len(i_static) != 32:
        raise ValueError("initiator_static must be 32 bytes")
    return hashlib.sha256(
        enc(b"sl1/th/v1") + enc(METHOD) + enc(mailbox_id) + enc(home_id)
        + enc(extra) + i_static + stick_static_pub
    ).digest()


def boot_psk(invite_secret: bytes, th: bytes) -> bytes:
    if len(invite_secret) != 32 or len(th) != 32:
        raise ValueError("boot_psk inputs must be 32 bytes")
    return crypto.hkdf(invite_secret, b"sl1/qr-boot", salt=th)


def jk_qr(invite_secret: bytes) -> bytes:
    if len(invite_secret) != 32:
        raise ValueError("invite_secret must be 32 bytes")
    return crypto.hkdf(invite_secret, b"sl1/qr-join")


def join_mac(jk: bytes, server_nonce: bytes, mailbox_id: bytes) -> bytes:
    if len(jk) != 32 or len(server_nonce) != 32 or len(mailbox_id) != 8:
        raise ValueError("bad join_mac field length")
    return hmac.new(jk, b"sl1/qr-join-mac" + server_nonce + mailbox_id, hashlib.sha256).digest()


def env_qr(invite_secret: bytes, mailbox_id: bytes, home_id: bytes) -> bytes:
    if len(invite_secret) != 32 or len(mailbox_id) != 8 or len(home_id) != 16:
        raise ValueError("bad env_qr field length")
    return crypto.hkdf(invite_secret, b"sl1/qr-env" + enc(mailbox_id) + home_id)


def pair_psk(
    *,
    r_i: bytes,
    r_r: bytes,
    prior: bytes,
    handshake_hash: bytes,
    th: bytes,
    initiator_static: bytes,
    responder_static: bytes,
    key_epoch: int = 0,
) -> bytes:
    """Long-term pair PSK (PAIRING-SPEC §4.5). prior = boot_psk for Method C."""
    for name, v, n in (
        ("r_i", r_i, 32),
        ("r_r", r_r, 32),
        ("prior", prior, 32),
        ("handshake_hash", handshake_hash, 32),
        ("th", th, 32),
        ("initiator_static", initiator_static, 32),
        ("responder_static", responder_static, 32),
    ):
        if len(v) != n:
            raise ValueError(f"{name} must be {n} bytes")
    if key_epoch < 0 or key_epoch > 0xFFFFFFFF:
        raise ValueError("key_epoch out of u32 range")
    info = b"sl1/pair-psk/v1" + initiator_static + responder_static + struct.pack(">I", key_epoch)
    return crypto.hkdf(r_i + r_r + prior, info, salt=handshake_hash + th)


def pair_confirm_kc(psk: bytes) -> bytes:
    if len(psk) != 32:
        raise ValueError("pair_psk must be 32 bytes")
    return crypto.hkdf(psk, b"sl1/pair-confirm")


def confirm_mac(kc: bytes, role: str, handshake_hash: bytes) -> bytes:
    if role not in ("i", "r"):
        raise ValueError("role must be i or r")
    if len(kc) != 32 or len(handshake_hash) != 32:
        raise ValueError("bad confirm_mac field length")
    label = b"sl1/pair-confirm/" + role.encode("ascii")
    return hmac.new(kc, label + handshake_hash, hashlib.sha256).digest()


def verify_confirm(kc: bytes, role: str, handshake_hash: bytes, mac: bytes) -> bool:
    if len(mac) != 32:
        return False
    return hmac.compare_digest(confirm_mac(kc, role, handshake_hash), mac)


_B64U = re.compile(r"^[A-Za-z0-9_-]+$")


def encode_qr(*, mailbox_id: bytes, stick_static_pub: bytes, invite_secret: bytes, exp: int) -> str:
    """QR payload: sl1:M=<16 hex>&K=<b64u pub>&P=<b64u invite>&E=<unix>."""
    if len(mailbox_id) != 8 or len(stick_static_pub) != 32 or len(invite_secret) != 32:
        raise ValueError("bad QR field length")
    from .util import b64u
    q = urlencode({
        "M": mailbox_id.hex(),
        "K": b64u(stick_static_pub),
        "P": b64u(invite_secret),
        "E": str(int(exp)),
    }, safe="-_")
    return QR_PREFIX + q


def decode_qr(payload: str) -> dict:
    """Parse and validate a Method C QR string. Returns raw bytes fields."""
    from .util import unb64u
    s = payload.strip()
    if not s.startswith(QR_PREFIX):
        raise ValueError("not an sl1 QR")
    qs = parse_qs(s[len(QR_PREFIX):], keep_blank_values=False, strict_parsing=True)
    for key in ("M", "K", "P", "E"):
        if key not in qs or len(qs[key]) != 1:
            raise ValueError(f"missing QR field {key}")
    m_hex, k_b64, p_b64, e_s = qs["M"][0], qs["K"][0], qs["P"][0], qs["E"][0]
    if len(m_hex) != 16 or any(c not in "0123456789abcdefABCDEF" for c in m_hex):
        raise ValueError("M must be 16 hex digits")
    if not _B64U.match(k_b64) or not _B64U.match(p_b64):
        raise ValueError("K/P must be base64url")
    exp = int(e_s)
    return {
        "mailbox_id": bytes.fromhex(m_hex),
        "stick_static_pub": unb64u(k_b64, 32),
        "invite_secret": unb64u(p_b64, 32),
        "exp": exp,
    }
