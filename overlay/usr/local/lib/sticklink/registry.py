"""Minimal sticklink registry (§3 formats): identity.sealed + records/<peer_id>.rec,
plus signal.sealed for the provisioned signalling credential.

E2E-milestone scope: the registry_key is passed in by the caller. The combined
PIN+key-file unlock that produces it (§0 P1, LUKS slot map) is deferred; until
then the daemon takes a test-only --registry-key-file (refused unless
STICKLINK_TESTING=1).

Plaintext encodings pinned here (the spec leaves them to StickLLM, §3):
  identity : JSON {"v":1,"cur_epoch":int,"cur_priv":b64u32,"pending_epoch":int|null,"pending_priv":b64u32|null}
  record   : JSON {"v":1,"peer_id","name","kind","peer_pub","pair_psk","home","slot","adm","epoch","created"}
  signal   : JSON {"v":2,"dev","home"}  sealed like identity with
             key HKDF(registry_key,"sl1/signal"), AD "sl1/signal"||01 (addition, not in §3 table)
  auth     : auth.sealed (0600), the device's Ed25519 server-auth seed (32 B, API §3.1 / Q-S1), kept
             apart from the Noise identity; key HKDF(registry_key,"sl1/auth"), AD "sl1/auth"||01.
             Only its public key `ak` ever leaves the stick (provision.mjs --ak).
"""
from __future__ import annotations

import json
import os
import secrets
import time
from pathlib import Path

from . import crypto, formats, fsio
from .util import b64u, unb64u

L_SIGNAL = b"sl1/signal"
L_AUTH = b"sl1/auth"


def _signal_key(rk: bytes) -> bytes:
    return crypto.hkdf(rk, L_SIGNAL)


class Registry:
    def __init__(self, root: Path, registry_key: bytes):
        if len(registry_key) != 32:
            raise ValueError("registry_key must be 32 bytes")
        self.root = Path(root)
        self.rk = registry_key
        self.records_dir = self.root / "records"

    # -- layout -------------------------------------------------------------
    def init_dirs(self) -> None:
        fsio.ensure_dir(self.root)
        fsio.ensure_dir(self.records_dir)
        fsio.cleanup_temps(self.root, self.records_dir)

    def lock(self, exclusive=True):
        return fsio.Lock(self.root, exclusive=exclusive)

    # -- identity -----------------------------------------------------------
    def load_identity(self) -> dict | None:
        p = self.root / "identity.sealed"
        if not p.exists():
            return None
        d = json.loads(formats.open_identity(self.rk, fsio.read_exact(p)))
        if d.get("v") != 1:
            raise formats.FormatError("identity: unknown version")
        return d

    def static_priv(self) -> bytes:
        d = self.load_identity()
        if d is None:
            raise FileNotFoundError("no identity; run sticklinkd init")
        return unb64u(d["cur_priv"], 32)

    def create_identity(self, priv: bytes | None = None) -> bytes:
        """priv is for the TEST-ONLY fixture import (e2einterop); normal init generates one."""
        if priv is not None and (os.environ.get("STICKLINK_TESTING") != "1" or len(priv) != 32):
            raise ValueError("a supplied identity key is test-only")
        with self.lock():
            if (self.root / "identity.sealed").exists():
                raise FileExistsError("identity already exists")
            priv = priv or crypto.x25519_generate()
            body = {"v": 1, "cur_epoch": 0, "cur_priv": b64u(priv), "pending_epoch": None, "pending_priv": None}
            fsio.atomic_write(self.root / "identity.sealed",
                              formats.seal_identity(self.rk, json.dumps(body).encode()), "identity")
            return crypto.x25519_public(priv)

    # -- signalling credential ----------------------------------------------
    def save_signal(self, dev: str, home: str) -> None:
        unb64u(dev, 16), unb64u(home, 16)
        body = json.dumps({"v": 2, "dev": dev, "home": home}).encode()
        hdr = bytes([formats.VERSION])
        nonce, ct = crypto.seal(_signal_key(self.rk), body, L_SIGNAL + hdr)
        with self.lock():
            fsio.atomic_write(self.root / "signal.sealed", hdr + nonce + ct, "signal")

    def load_signal(self) -> dict:
        blob = fsio.read_exact(self.root / "signal.sealed")
        if len(blob) < formats.SEALED_MIN or blob[0] != formats.VERSION:
            raise formats.FormatError("signal.sealed: bad version or length")
        d = json.loads(crypto.open_(_signal_key(self.rk), blob[1:13], blob[13:], L_SIGNAL + blob[:1]))
        return d

    # -- device server-auth key (Ed25519 seed; separate from the Noise static key) --
    def save_auth_seed(self, seed: bytes | None = None) -> bytes:
        """Store (or generate from the OS RNG) the auth seed; returns the public key ak."""
        seed = seed if seed is not None else secrets.token_bytes(32)
        if len(seed) != 32:
            raise ValueError("auth seed must be 32 B")
        hdr = bytes([formats.VERSION])
        nonce, ct = crypto.seal(crypto.hkdf(self.rk, L_AUTH), seed, L_AUTH + hdr)
        with self.lock():
            fsio.atomic_write(self.root / "auth.sealed", hdr + nonce + ct, "auth")
        return crypto.ed25519_public(seed)

    def auth_seed(self) -> bytes:
        blob = fsio.read_exact(self.root / "auth.sealed")
        if len(blob) < formats.SEALED_MIN or blob[0] != formats.VERSION:
            raise formats.FormatError("auth.sealed: bad version or length")
        return crypto.open_(crypto.hkdf(self.rk, L_AUTH), blob[1:13], blob[13:], L_AUTH + blob[:1])

    def auth_pub(self) -> bytes:
        return crypto.ed25519_public(self.auth_seed())

    # -- records ------------------------------------------------------------
    def add_record(self, *, name: str, kind: str, peer_pub: bytes, pair_psk: bytes, home: bytes,
                   slot: bytes, adm: int = 0) -> dict:
        if len(peer_pub) != 32 or len(pair_psk) != 32 or len(home) != 16 or len(slot) != 8:
            raise ValueError("bad record field length")
        peer_id = secrets.token_bytes(16)
        rec = {"v": 1, "peer_id": peer_id.hex(), "name": name[:64], "kind": kind[:16],
               "peer_pub": b64u(peer_pub), "pair_psk": b64u(pair_psk), "home": b64u(home),
               "slot": b64u(slot), "adm": int(bool(adm)), "epoch": 0, "created": int(time.time())}
        with self.lock():
            for r in self._list_unlocked():
                if r["slot"] == rec["slot"] or r["peer_pub"] == rec["peer_pub"]:
                    raise FileExistsError("slot or peer key already paired")
            fsio.atomic_write(self.records_dir / f"{peer_id.hex()}.rec",
                              formats.seal_record(self.rk, peer_id, json.dumps(rec).encode()), "record")
        return rec

    def _list_unlocked(self) -> list[dict]:
        out = []
        if not self.records_dir.is_dir():
            return out
        for p in sorted(self.records_dir.glob("*.rec")):
            pid = bytes.fromhex(p.stem)
            rec = json.loads(formats.open_record(self.rk, pid, fsio.read_exact(p)))
            if rec.get("peer_id") != p.stem:
                raise formats.FormatError("record name/peer_id mismatch")
            out.append(rec)
        return out

    def list_records(self) -> list[dict]:
        with self.lock(exclusive=False):
            return self._list_unlocked()

    def by_slot(self, slot: bytes) -> dict | None:
        s = b64u(slot)
        return next((r for r in self.list_records() if r["slot"] == s), None)

    def delete_record(self, peer_id_hex: str) -> bool:
        with self.lock():
            return fsio.atomic_delete(self.records_dir / f"{peer_id_hex}.rec")


# -- test-only pending pairing offers (pairfile.py) ---------------------------
L_PENDING = b"sl1/pending"


def _pending_key(rk: bytes) -> bytes:
    return crypto.hkdf(rk, L_PENDING)


def save_pending(reg: Registry, slot_b64: str, body: dict) -> None:
    d = reg.root / "pending"
    fsio.ensure_dir(d)
    hdr = bytes([formats.VERSION])
    nonce, ct = crypto.seal(_pending_key(reg.rk), json.dumps(body).encode(), L_PENDING + hdr + slot_b64.encode())
    with reg.lock():
        fsio.atomic_write(d / f"{slot_b64}.sealed", hdr + nonce + ct, "pending")


def load_pending(reg: Registry, slot_b64: str) -> dict | None:
    unb64u(slot_b64, 8)
    p = reg.root / "pending" / f"{slot_b64}.sealed"
    if not p.exists():
        return None
    blob = fsio.read_exact(p)
    if len(blob) < formats.SEALED_MIN or blob[0] != formats.VERSION:
        raise formats.FormatError("pending: bad version or length")
    return json.loads(crypto.open_(_pending_key(reg.rk), blob[1:13], blob[13:], L_PENDING + blob[:1] + slot_b64.encode()))


def drop_pending(reg: Registry, slot_b64: str) -> None:
    with reg.lock():
        fsio.atomic_delete(reg.root / "pending" / f"{slot_b64}.sealed")


# -- small sealed aux files (relay node key) ------------------------------------
def save_aux(reg: Registry, name: str, body: dict) -> None:
    label = b"sl1/aux/" + name.encode()
    hdr = bytes([formats.VERSION])
    nonce, ct = crypto.seal(crypto.hkdf(reg.rk, label), json.dumps(body).encode(), label + hdr)
    with reg.lock():
        fsio.atomic_write(reg.root / f"{name}.sealed", hdr + nonce + ct, name)


def load_aux(reg: Registry, name: str) -> dict | None:
    p = reg.root / f"{name}.sealed"
    if not p.exists():
        return None
    label = b"sl1/aux/" + name.encode()
    blob = fsio.read_exact(p)
    if len(blob) < formats.SEALED_MIN or blob[0] != formats.VERSION:
        raise formats.FormatError(f"{name}.sealed: bad version or length")
    return json.loads(crypto.open_(crypto.hkdf(reg.rk, label), blob[1:13], blob[13:], label + blob[:1]))
