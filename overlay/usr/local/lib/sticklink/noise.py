"""Noise_IKpsk2_25519_ChaChaPoly_SHA256 (Noise rev 34), built only from
python3-cryptography primitives (X25519, ChaCha20-Poly1305, HMAC-SHA256).

Roles (SIGNALLING-PLAN / server/vectors/ikpsk2-v1.json): initiator = AI KVM or
other client, responder = the stick. rs = the stick static key pinned at
pairing, psk = pair_psk, prologue = "sl1/net" || home(16) || slot(8).

   <- s
   ...
   -> e, es, s, ss        (msg1, 96 B with empty payload)
   <- e, ee, se, psk      (msg2, 48 B with empty payload)

Checked byte-for-byte against ikpsk2-v1.json (tests/sticklink/test_noise.py).
"""
from __future__ import annotations

import hashlib
import hmac

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from . import crypto

PROTOCOL = b"Noise_IKpsk2_25519_ChaChaPoly_SHA256"
DHLEN = 32
HASHLEN = 32
TAGLEN = 16
MAX_NONCE = (1 << 64) - 1


class NoiseError(Exception):
    pass


NET_VER = 0x01


def prologue(home: bytes, slot: bytes, initiator_pub: bytes, responder_pub: bytes) -> bytes:
    """The ONLY place the IKpsk2 prologue is built (Responder and Initiator both call this).
    v2 (ikpsk2-v2.json, Q-N1): 'sl1/net' || ver 0x01 || home(16) || slot(8) || initiator static pub(32)
    || responder static pub(32) = 96 B. Initiator = AI KVM / phone / desktop, responder = the stick.
    The responder takes the initiator key from the slot's pinned record."""
    if len(home) != 16 or len(slot) != 8 or len(initiator_pub) != 32 or len(responder_pub) != 32:
        raise ValueError("home 16 B, slot 8 B, static pubs 32 B")
    return b"sl1/net" + bytes([NET_VER]) + home + slot + initiator_pub + responder_pub


def _hmac(k: bytes, d: bytes) -> bytes:
    return hmac.new(k, d, hashlib.sha256).digest()


def _hkdf(ck: bytes, ikm: bytes, n: int):
    t = _hmac(ck, ikm)
    o1 = _hmac(t, b"\x01")
    o2 = _hmac(t, o1 + b"\x02")
    if n == 2:
        return o1, o2
    return o1, o2, _hmac(t, o2 + b"\x03")


def _nonce(n: int) -> bytes:
    return b"\x00" * 4 + n.to_bytes(8, "little")


def _dh(priv: bytes, pub: bytes) -> bytes:
    out = X25519PrivateKey.from_private_bytes(priv).exchange(X25519PublicKey.from_public_bytes(pub))
    if out == b"\x00" * 32:
        raise NoiseError("low-order point")
    return out


def aead_encrypt(k: bytes, n: int, ad: bytes, pt: bytes) -> bytes:
    if n >= MAX_NONCE:
        raise NoiseError("nonce exhausted")
    return ChaCha20Poly1305(k).encrypt(_nonce(n), pt, ad)


def aead_decrypt(k: bytes, n: int, ad: bytes, ct: bytes) -> bytes:
    try:
        return ChaCha20Poly1305(k).decrypt(_nonce(n), ct, ad)
    except InvalidTag as e:
        raise NoiseError("decrypt failed") from e


class _Sym:
    def __init__(self, prologue_: bytes):
        self.h = hashlib.sha256(PROTOCOL).digest() if len(PROTOCOL) > HASHLEN else PROTOCOL.ljust(HASHLEN, b"\x00")
        self.ck = self.h
        self.k = None
        self.n = 0
        self.mix_hash(prologue_)

    def mix_hash(self, d: bytes):
        self.h = hashlib.sha256(self.h + d).digest()

    def mix_key(self, ikm: bytes):
        self.ck, k = _hkdf(self.ck, ikm, 2)
        self.k, self.n = k, 0

    def mix_key_and_hash(self, ikm: bytes):
        self.ck, th, k = _hkdf(self.ck, ikm, 3)
        self.mix_hash(th)
        self.k, self.n = k, 0

    def enc_hash(self, pt: bytes) -> bytes:
        if self.k is None:
            ct = pt
        else:
            ct = aead_encrypt(self.k, self.n, self.h, pt)
            self.n += 1
        self.mix_hash(ct)
        return ct

    def dec_hash(self, ct: bytes) -> bytes:
        if self.k is None:
            pt = ct
        else:
            pt = aead_decrypt(self.k, self.n, self.h, ct)
            self.n += 1
        self.mix_hash(ct)
        return pt

    def split(self):
        return _hkdf(self.ck, b"", 2)


class Session:
    """Transport keys after the handshake. Over UDP/DERP packets can be lost or
    reordered, so the counter travels explicitly with each packet (as in
    WireGuard) and a 64-entry sliding window rejects replays. The AEAD nonce
    and AD are exactly Noise's (n as 64-bit LE, empty AD), so counter 0 matches
    the transport vectors."""

    WINDOW = 64

    def __init__(self, send_k: bytes, recv_k: bytes, hh: bytes, remote_static: bytes):
        self.send_k, self.recv_k, self.handshake_hash = send_k, recv_k, hh
        self.remote_static = remote_static
        self.send_n = 0
        self.max_recv = -1
        self.bitmap = 0

    def encrypt(self, pt: bytes) -> tuple[int, bytes]:
        n = self.send_n
        self.send_n += 1
        return n, aead_encrypt(self.send_k, n, b"", pt)

    def decrypt(self, n: int, ct: bytes) -> bytes:
        if n < 0 or n >= MAX_NONCE:
            raise NoiseError("bad counter")
        if n <= self.max_recv - self.WINDOW:
            raise NoiseError("replay (old)")
        if n <= self.max_recv and (self.bitmap >> (self.max_recv - n)) & 1:
            raise NoiseError("replay")
        pt = aead_decrypt(self.recv_k, n, b"", ct)  # authenticate before updating the window
        if n > self.max_recv:
            shift = n - self.max_recv
            self.bitmap = ((self.bitmap << shift) | 1) & ((1 << self.WINDOW) - 1) if self.max_recv >= 0 else 1
            self.max_recv = n
        else:
            self.bitmap |= 1 << (self.max_recv - n)
        return pt


class Initiator:
    def __init__(self, s_priv: bytes, rs_pub: bytes, psk: bytes, prologue_: bytes, e_priv: bytes | None = None):
        if len(psk) != 32:
            raise ValueError("psk 32 B")
        self.s, self.rs, self.psk = s_priv, rs_pub, psk
        self.e = e_priv or crypto.x25519_generate()
        self.sym = _Sym(prologue_)
        self.sym.mix_hash(rs_pub)

    def write_msg1(self, payload: bytes = b"") -> bytes:
        y = self.sym
        e_pub = crypto.x25519_public(self.e)
        y.mix_hash(e_pub)
        y.mix_key(e_pub)                       # psk modifier: e also mixes the key
        y.mix_key(_dh(self.e, self.rs))        # es
        c_s = y.enc_hash(crypto.x25519_public(self.s))
        y.mix_key(_dh(self.s, self.rs))        # ss
        return e_pub + c_s + y.enc_hash(payload)

    def read_msg2(self, msg: bytes) -> tuple[Session, bytes]:
        if len(msg) < 32 + TAGLEN:
            raise NoiseError("msg2 too short")
        y = self.sym
        re_ = msg[:32]
        y.mix_hash(re_)
        y.mix_key(re_)
        y.mix_key(_dh(self.e, re_))            # ee
        y.mix_key(_dh(self.s, re_))            # se
        y.mix_key_and_hash(self.psk)           # psk
        payload = y.dec_hash(msg[32:])
        k1, k2 = y.split()
        return Session(k1, k2, y.h, self.rs), payload


class Responder:
    def __init__(self, s_priv: bytes, prologue_: bytes, e_priv: bytes | None = None):
        self.s = s_priv
        self.e = e_priv or crypto.x25519_generate()
        self.sym = _Sym(prologue_)
        self.sym.mix_hash(crypto.x25519_public(s_priv))
        self.re = self.rs = None

    def read_msg1(self, msg: bytes) -> tuple[bytes, bytes]:
        """Returns (initiator static pub, payload). The caller must compare the
        static key with the pinned one before calling write_msg2."""
        if len(msg) < 32 + 48 + TAGLEN:
            raise NoiseError("msg1 too short")
        y = self.sym
        self.re = msg[:32]
        y.mix_hash(self.re)
        y.mix_key(self.re)
        y.mix_key(_dh(self.s, self.re))        # es
        self.rs = y.dec_hash(msg[32:80])
        y.mix_key(_dh(self.s, self.rs))        # ss
        return self.rs, y.dec_hash(msg[80:])

    def write_msg2(self, psk: bytes, payload: bytes = b"") -> tuple[Session, bytes]:
        if len(psk) != 32:
            raise ValueError("psk 32 B")
        y = self.sym
        e_pub = crypto.x25519_public(self.e)
        y.mix_hash(e_pub)
        y.mix_key(e_pub)
        y.mix_key(_dh(self.e, self.re))        # ee
        y.mix_key(_dh(self.e, self.rs))        # se
        y.mix_key_and_hash(psk)
        msg = e_pub + y.enc_hash(payload)
        k1, k2 = y.split()
        return Session(k2, k1, y.h, self.rs), msg
