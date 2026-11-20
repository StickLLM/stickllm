"""Signalling-side derivations (server/API.md, SIGNALLING-PLAN):

  P_slot = HKDF(pair_psk, "sl1/slot-secret")      jk    = HKDF(P_slot, "sl1/join")
  env_k  = HKDF(P_slot, "sl1/env")
  hello sig = Ed25519(auth_seed, "sl1/dev-hello/v1"||0x00||n32||dev16||role||home16)   (v2, Q-S1; v1 HMAC removed)
  rotate pop = Ed25519(NEW auth_seed, "sl1/dev-rotate/v1"||0x00||n32||dev16||new_ak32||old_ak32)
  join  mac = HMAC-SHA256(jk, "sl1/join"||n32||home16||slot8)
  sig box   = nonce12 || ChaCha20-Poly1305(env_k, nonce, inner_json,
              AAD "sl1/box"||home16||slot8||dir)   dir 0x01 client->stick, 0x02 stick->client

The box AAD and the Noise prologue are server-side PROPOSALS (Q-N1/Q-N2);
checked against server/vectors.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets

from . import crypto
from .util import b64u, unb64u

ROLE_SERVER = 0x01
ROLE_CLIENT = 0x02
DIR_C2S = 0x01
DIR_S2C = 0x02
MAX_BOX_CHARS = 3072


def p_slot(pair_psk: bytes) -> bytes:
    return crypto.hkdf(pair_psk, b"sl1/slot-secret")


def join_key(pair_psk: bytes) -> bytes:
    return crypto.hkdf(p_slot(pair_psk), b"sl1/join")


def env_key(pair_psk: bytes) -> bytes:
    return crypto.hkdf(p_slot(pair_psk), b"sl1/env")


def hello_input(n: bytes, dev: bytes, role: int, home: bytes | None) -> bytes:
    home = home if role == ROLE_SERVER else b"\x00" * 16
    if len(n) != 32 or len(dev) != 16 or len(home) != 16:
        raise ValueError("hello: n 32 B, dev 16 B, home 16 B")
    return b"sl1/dev-hello/v1\x00" + n + dev + bytes([role]) + home


def hello_sig(auth_seed: bytes, n: bytes, dev: bytes, role: int, home: bytes | None) -> bytes:
    return crypto.ed25519_sign(auth_seed, hello_input(n, dev, role, home))


def rotate_pop(new_seed: bytes, n: bytes, dev: bytes, old_ak: bytes) -> bytes:
    new_ak = crypto.ed25519_public(new_seed)
    return crypto.ed25519_sign(new_seed, b"sl1/dev-rotate/v1\x00" + n + dev + new_ak + old_ak)


def join_mac(jk: bytes, n: bytes, home: bytes, slot: bytes) -> bytes:
    assert len(n) == 32 and len(home) == 16 and len(slot) == 8
    return hmac.new(jk, b"sl1/join" + n + home + slot, hashlib.sha256).digest()


def _aad(home: bytes, slot: bytes, direction: int) -> bytes:
    return b"sl1/box" + home + slot + bytes([direction])


def seal_box(env_k: bytes, home: bytes, slot: bytes, direction: int, inner: dict | bytes,
             nonce: bytes | None = None) -> str:
    pt = inner if isinstance(inner, bytes) else json.dumps(inner, separators=(",", ":")).encode()
    nonce = nonce or secrets.token_bytes(12)
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    out = b64u(nonce + ChaCha20Poly1305(env_k).encrypt(nonce, pt, _aad(home, slot, direction)))
    if len(out) > MAX_BOX_CHARS:
        raise ValueError("sig box too large")
    return out


def open_box(env_k: bytes, home: bytes, slot: bytes, direction: int, box: str) -> dict:
    raw = unb64u(box)
    if len(raw) < 12 + 16 or len(box) > MAX_BOX_CHARS:
        raise ValueError("bad box")
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    pt = ChaCha20Poly1305(env_k).decrypt(raw[:12], raw[12:], _aad(home, slot, direction))
    m = json.loads(pt)
    if not isinstance(m, dict) or not isinstance(m.get("k"), str):
        raise ValueError("bad inner message")
    return m
