"""Primitives. No home-made crypto: HKDF/ChaCha20-Poly1305/X25519/Ed25519 from
python3-cryptography, Argon2id from libsodium (python3-nacl).

Pinned Argon2id parameters (§0 P1): 256 MiB, 4 passes, 1 lane, 16-byte salt,
32-byte output. libsodium's crypto_pwhash argon2id always uses 1 lane, which
matches. Checked against the reference `argon2` CLI (-id -t 4 -m 18 -p 1).
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


@dataclass(frozen=True)
class KdfParams:
    time: int
    memory_kib: int
    lanes: int


PINNED = KdfParams(time=4, memory_kib=262144, lanes=1)
# Test-only: tiny costs so unit tests under emulation finish. Never reachable
# unless STICKLINK_TESTING=1 and STICKLINK_FAST_KDF=1 are both set.
FAST_TEST = KdfParams(time=4, memory_kib=32768, lanes=1)


def params() -> KdfParams:
    if os.environ.get("STICKLINK_TESTING") == "1" and os.environ.get("STICKLINK_FAST_KDF") == "1":
        return FAST_TEST
    return PINNED


SALT_LEN = 16
KEY_LEN = 32
NONCE_LEN = 12
TAG_LEN = 16


def argon2id(secret: bytes, salt: bytes) -> bytes:
    if len(salt) != SALT_LEN:
        raise ValueError("salt must be 16 bytes")
    import nacl.pwhash
    p = params()
    return nacl.pwhash.argon2id.kdf(KEY_LEN, secret, salt, opslimit=p.time, memlimit=p.memory_kib * 1024)


def hkdf(ikm: bytes, info: bytes, length: int = KEY_LEN, *, salt: bytes | None = None) -> bytes:
    # salt = empty/None: RFC 5869 Extract uses HashLen zeros (cryptography salt=None).
    # Non-empty salt (e.g. Method C TH for boot_psk) is passed through unchanged.
    if salt is not None and len(salt) == 0:
        salt = None
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def seal(key: bytes, plaintext: bytes, ad: bytes) -> tuple[bytes, bytes]:
    nonce = secrets.token_bytes(NONCE_LEN)
    return nonce, ChaCha20Poly1305(key).encrypt(nonce, plaintext, ad)


def open_(key: bytes, nonce: bytes, ct: bytes, ad: bytes) -> bytes:
    return ChaCha20Poly1305(key).decrypt(nonce, ct, ad)


def x25519_generate() -> bytes:
    k = X25519PrivateKey.generate()
    return k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())


def x25519_public(priv: bytes) -> bytes:
    return X25519PrivateKey.from_private_bytes(priv).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def ed25519_public(seed: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def ed25519_sign(seed: bytes, msg: bytes) -> bytes:
    return Ed25519PrivateKey.from_private_bytes(seed).sign(msg)


def random_key() -> bytes:
    return secrets.token_bytes(KEY_LEN)
