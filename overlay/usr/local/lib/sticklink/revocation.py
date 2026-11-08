"""Revoked-peer enforcement (PAIRING-SPEC v0.9 §3/§6; Nink's ruling 2026-10-29).

* Input: a revoked-peer SET for this stick's home, from the server (pull on unlock / `rev` event), a local
  file, or the CLI spool. The real server API is still changing, so the wire shape is parsed in ONE place
  (parse_set) and kept minimal: {"home": b64u?, "set": [{"peer_pub": b64u|hex} | {"slot": b64u|hex}, ...]}.
* Remove-only: the set can only DELETE local registry records. Entries that match no record already in
  this stick's registry are ignored (never added, never remembered). A failed fetch/parse changes nothing.
* Store: the static keys of peers we revoked are kept (sealed aux "revoked") so the responder keeps refusing
  them after a restart even if a stale record reappears (e.g. flash rollback restores a record but not
  this store? - then the next pull deletes it again: documented R6 gap).
* Effect, immediately: registry record deleted; the active Noise session (keys, replay window, paths,
  candidates) is dropped like a bye; any later msg1 for that slot/key is refused. Relay connections may
  persist; the server denies new relay admission.
"""
from __future__ import annotations

import json
import secrets
from pathlib import Path

from . import registry
from .util import b64u, unb64u

AUX = "revoked"


class RevocationError(ValueError):
    pass


def _key(v: str, n: int) -> bytes:
    if isinstance(v, str) and len(v) == 2 * n:
        try:
            return bytes.fromhex(v)
        except ValueError:
            pass
    try:
        return unb64u(v, n)
    except Exception as e:
        raise RevocationError(f"bad {n}-byte value") from e


def parse_set(obj, home: bytes) -> list[tuple[str, bytes]]:
    """-> [("peer_pub", 32 B) | ("slot", 8 B)]. Raises on a malformed set or a set for another home."""
    if not isinstance(obj, dict):
        raise RevocationError("revoked set: not an object")
    h = obj.get("home")
    if h is not None and _key(h, 16) != home:
        raise RevocationError("revoked set is for another home")
    items = obj.get("set", obj.get("revoked"))
    if items is None and isinstance(obj.get("s"), list):  # API.md §5 page body shape (signature checked by the caller, later)
        items = [{"slot": x} for x in obj["s"]]
    if not isinstance(items, list) or len(items) > 4096:
        raise RevocationError("revoked set: no list")
    out = []
    for e in items:
        if isinstance(e, dict) and "peer_pub" in e:
            out.append(("peer_pub", _key(e["peer_pub"], 32)))
        elif isinstance(e, dict) and "slot" in e:
            out.append(("slot", _key(e["slot"], 8)))
        else:
            raise RevocationError("revoked set: bad entry")
    return out


class RevokedStore:
    """Static keys this stick has revoked. Only apply() adds to it (after a matching local record was removed)."""

    def __init__(self, reg: registry.Registry):
        self.reg = reg
        d = registry.load_aux(reg, AUX) or {"keys": []}
        self.keys: set[bytes] = {unb64u(k, 32) for k in d.get("keys", [])}

    def _save(self):
        registry.save_aux(self.reg, AUX, {"keys": sorted(b64u(k) for k in self.keys)})

    def __contains__(self, pub: bytes) -> bool:
        return pub in self.keys

    def apply(self, entries, home: bytes, on_revoke=None) -> dict:
        """Delete every local record matched by an entry; call on_revoke(slot, rec) for each. Remove-only."""
        recs = [r for r in self.reg.list_records() if unb64u(r["home"], 16) == home]
        hit, ignored = [], 0
        for kind, val in entries:
            enc = b64u(val)
            m = [r for r in recs if r[kind] == enc and r not in hit]
            if not m:
                ignored += 1
                continue
            hit.extend(m)
        for r in hit:
            self.keys.add(unb64u(r["peer_pub"], 32))
        if hit:
            self._save()  # remember the key first: a crash after this still refuses the peer
        for r in hit:
            self.reg.delete_record(r["peer_id"])
            if on_revoke:
                on_revoke(unb64u(r["slot"], 8), r)
        return {"revoked": [r["name"] for r in hit], "ignored": ignored}


# -- local inputs (until the server API settles) -------------------------------------------------
def spool_dir(reg: registry.Registry) -> Path:
    return Path(reg.root) / "revoke-spool"


def spool_revoke(reg: registry.Registry, who: str) -> dict:
    """CLI: queue a revocation of one local peer (by name, slot b64u, or key fingerprint) for the daemon,
    or apply it directly when no daemon is running (the daemon applies its spool at start too)."""
    recs = reg.list_records()
    m = [r for r in recs if who in (r["name"], r["slot"], r["peer_pub"])]
    if len(m) != 1:
        raise RevocationError(f"revoke: {len(m)} local peers match")
    d = spool_dir(reg)
    d.mkdir(mode=0o700, exist_ok=True)
    p = d / f"{secrets.token_hex(8)}.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps({"set": [{"peer_pub": m[0]["peer_pub"]}]}))
    tmp.chmod(0o600)
    tmp.rename(p)
    return {"queued": m[0]["name"], "spool": p.name}


def take_spool(reg: registry.Registry) -> list[dict]:
    d = spool_dir(reg)
    out = []
    if d.is_dir():
        for p in sorted(d.glob("*.json")):
            try:
                out.append(json.loads(p.read_text()))
            finally:
                p.unlink(missing_ok=True)
    return out


# -- server-signed revoked pages (API §5, revoked.get; vectors signalling-v2.json "revoked") ---------
DOMAIN_REVOKED = b"sl1/revoked/v1"


def parse_pins(specs) -> dict[str, bytes]:
    """'kid=pub_b64u' or 'kid pub_b64u' (the stack's admit-keys line) -> {kid: 32 B Ed25519 pub}."""
    out = {}
    for s in specs or []:
        kid, _, pub = s.replace("=", " ", 1).partition(" ")
        out[kid.strip()] = unb64u(pub.strip(), 32)
    return out


def verify_page(msg: dict, pins: dict[str, bytes], home: bytes, nonce: bytes | None) -> dict:
    """Verify the bytes in body (never re-serialised), then parse; bind to our home and this session's
    welcome nonce. Raises RevocationError. Returns the parsed body."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    pub = pins.get(msg.get("kid", ""))
    if pub is None:
        raise RevocationError(f"revoked page: kid {msg.get('kid')!r} is not pinned")
    body = unb64u(msg.get("body", ""))
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(unb64u(msg.get("sig", ""), 64), DOMAIN_REVOKED + b"\x00" + body)
    except (InvalidSignature, ValueError) as e:
        raise RevocationError("revoked page: bad signature") from e
    d = json.loads(body)
    if d.get("v") != 1 or unb64u(d.get("home", ""), 16) != home:
        raise RevocationError("revoked page: wrong version or home")
    if nonce is not None and unb64u(d.get("n", ""), 32) != nonce:
        raise RevocationError("revoked page: not bound to this session's nonce")
    if not isinstance(d.get("s"), list) or len(d["s"]) > 64:
        raise RevocationError("revoked page: bad slot list")
    return d
