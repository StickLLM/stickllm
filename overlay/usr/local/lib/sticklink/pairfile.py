"""TEST-ONLY pairing by exchanging two files (stands in for the QR flow, §4.6,
which needs the pair.open mailbox; deferred). Refused unless STICKLINK_TESTING=1.

  stick : offer  -> {"t":"sl1-testpair-offer","v":1,"home","slot","stick_pub","pair_psk","exp"}
  peer  : answer -> {"t":"sl1-testpair-answer","v":1,"slot","peer_pub","name","kind",
                     "mac": HMAC-SHA256(pair_psk, "sl1/testpair"||slot||peer_pub||stick_pub)}

The stick keeps the offer sealed under sticklink/pending/ and pins peer_pub only
when the answer's MAC verifies under that offer's pair_psk. The offer file holds
pair_psk in clear, exactly as the QR would; delete it after use.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time

from . import crypto, registry
from .util import b64u, unb64u

OFFER_TTL = 600


def _require_testing():
    if os.environ.get("STICKLINK_TESTING") != "1":
        raise PermissionError("file pairing is test-only (set STICKLINK_TESTING=1 in a VM)")


def _mac(psk: bytes, slot: bytes, peer_pub: bytes, stick_pub: bytes) -> bytes:
    return hmac.new(psk, b"sl1/testpair" + slot + peer_pub + stick_pub, hashlib.sha256).digest()


def make_offer(reg: registry.Registry) -> dict:
    _require_testing()
    sig = reg.load_signal()
    slot = secrets.token_bytes(8)
    psk = crypto.random_key()
    stick_pub = crypto.x25519_public(reg.static_priv())
    offer = {"t": "sl1-testpair-offer", "v": 1, "home": sig["home"], "slot": b64u(slot),
             "stick_pub": b64u(stick_pub), "pair_psk": b64u(psk), "exp": int(time.time()) + OFFER_TTL}
    registry.save_pending(reg, offer["slot"], offer)
    return offer


def make_answer(offer: dict, peer_priv: bytes, name: str, kind: str) -> dict:
    _require_testing()
    if offer.get("t") != "sl1-testpair-offer" or offer.get("v") != 1:
        raise ValueError("not a test pairing offer")
    if offer["exp"] < time.time():
        raise ValueError("offer expired")
    slot, psk, spub = unb64u(offer["slot"], 8), unb64u(offer["pair_psk"], 32), unb64u(offer["stick_pub"], 32)
    ppub = crypto.x25519_public(peer_priv)
    return {"t": "sl1-testpair-answer", "v": 1, "slot": offer["slot"], "peer_pub": b64u(ppub),
            "name": name, "kind": kind, "mac": b64u(_mac(psk, slot, ppub, spub))}


def accept_answer(reg: registry.Registry, answer: dict) -> dict:
    _require_testing()
    if answer.get("t") != "sl1-testpair-answer" or answer.get("v") != 1:
        raise ValueError("not a test pairing answer")
    pend = registry.load_pending(reg, answer["slot"])
    if pend is None:
        raise ValueError("no pending offer for that slot")
    try:
        if pend["exp"] < time.time():
            raise ValueError("offer expired")
        slot, psk = unb64u(pend["slot"], 8), unb64u(pend["pair_psk"], 32)
        spub, ppub = unb64u(pend["stick_pub"], 32), unb64u(answer["peer_pub"], 32)
        if not hmac.compare_digest(_mac(psk, slot, ppub, spub), unb64u(answer["mac"], 32)):
            raise ValueError("answer MAC mismatch")
        if spub != crypto.x25519_public(reg.static_priv()):
            raise ValueError("offer was made for a different stick key")
        rec = reg.add_record(name=str(answer.get("name", "peer")), kind=str(answer.get("kind", "client")),
                             peer_pub=ppub, pair_psk=psk, home=unb64u(pend["home"], 16), slot=slot)
    finally:
        registry.drop_pending(reg, answer["slot"])
    return rec


def dump(obj: dict, path: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
