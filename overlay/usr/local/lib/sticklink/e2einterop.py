"""TEST-ONLY interop with the Sticklink e2e fixture files (server/ENDPOINTS.md section 4):
pairing.json ("sl1-e2e-pairing/1"), <role>.id.json ("sl1-e2e-identity/1") and stack.json
("sl1-e2e-stack/1"). These carry raw test secrets (pair_psk, static_priv, auth_seed), so every
entry point requires STICKLINK_TESTING=1. The production stick never reads or writes them.
"""
from __future__ import annotations

import hmac
import json
import os
from pathlib import Path

from .derp import normalise_pin
from . import crypto, noise, sigcrypto
from .util import b64u, unb64u

PAIRING_FMT = "sl1-e2e-pairing/1"
IDENTITY_FMT = "sl1-e2e-identity/2"
STACK_FMT = "sl1-e2e-stack/1"


class InteropError(ValueError):
    pass


def _testing():
    if os.environ.get("STICKLINK_TESTING") != "1":
        raise InteropError("e2e fixture files are test-only (STICKLINK_TESTING=1)")


def _hex(v, n, what):
    try:
        b = bytes.fromhex(v)
    except (TypeError, ValueError):
        raise InteropError(f"{what}: not hex") from None
    if len(b) != n:
        raise InteropError(f"{what}: want {n} bytes")
    return b


def load_pairing(path) -> dict:
    """Parse and check a pairing file. 'derived' (if present) must match our own recomputation."""
    _testing()
    p = json.loads(Path(path).read_text())
    if p.get("format") != PAIRING_FMT:
        raise InteropError(f"pairing: format is not {PAIRING_FMT}")
    out = {"home": unb64u(p["home"], 16), "slot": unb64u(p["slot"], 8),
           "pair_psk": _hex(p["pair_psk"], 32, "pair_psk"),
           "stick_pub": _hex(p["stick"]["static_pub"], 32, "stick.static_pub"),
           "kvm_pub": _hex(p["kvm"]["static_pub"], 32, "kvm.static_pub")}
    ps = sigcrypto.p_slot(out["pair_psk"])
    mine = {"P_slot": ps, "jk": sigcrypto.join_key(out["pair_psk"]), "env_k": sigcrypto.env_key(out["pair_psk"]),
            "prologue": noise.prologue(out["home"], out["slot"], out["kvm_pub"], out["stick_pub"])}
    for k, v in (p.get("derived") or {}).items():
        if k in mine and not hmac.compare_digest(bytes.fromhex(v), mine[k]):
            raise InteropError(f"pairing: derived.{k} does not match the recomputation")
    return out


def load_identity(path, role: str) -> dict:
    _testing()
    d = json.loads(Path(path).read_text())
    if d.get("format") != IDENTITY_FMT or d.get("role") != role:
        raise InteropError(f"identity: want {IDENTITY_FMT} with role {role}")
    return {"dev": d["dev"], "auth_seed": unb64u(d["auth_seed"], 32), "static_priv": _hex(d["static_priv"], 32, "static_priv")}


def load_stack(path) -> dict:
    """stack.json -> sticklinkd config keys (ws, derp, derp_pin, stun, rg)."""
    s = json.loads(Path(path).read_text())
    if s.get("format") != STACK_FMT:
        raise InteropError(f"stack: format is not {STACK_FMT}")
    d = s.get("derp") or {}
    return {k: v for k, v in {"ws": s.get("ws"), "rg": s.get("rg"), "derp": d.get("url"),
                              "derp_pin": d.get("cert_sha256") and normalise_pin(d["cert_sha256"]), "stun": d.get("stun")}.items() if v}


def import_stick(reg, pairing_path, identity_path, name="kvm-e2e", kind="kvm") -> dict:
    """Provision a fresh registry as the fixture stick paired with the fixture KVM."""
    p = load_pairing(pairing_path)
    i = load_identity(identity_path, "stick")
    if not hmac.compare_digest(crypto.x25519_public(i["static_priv"]), p["stick_pub"]):
        raise InteropError("stick static_priv does not match pairing stick.static_pub")
    reg.init_dirs()
    reg.create_identity(priv=i["static_priv"])
    reg.save_signal(i["dev"], b64u(p["home"]))
    reg.save_auth_seed(i["auth_seed"])
    return reg.add_record(name=name, kind=kind, peer_pub=p["kvm_pub"], pair_psk=p["pair_psk"],
                          home=p["home"], slot=p["slot"])


def export_pairing(reg, slot_b64: str) -> dict:
    """A sticklinkd pairing (e.g. from pair-offer/answer) in the fixture format, for a KVM sim."""
    _testing()
    rec = reg.by_slot(unb64u(slot_b64, 8))
    if rec is None:
        raise InteropError("no record for that slot")
    psk, home, slot = unb64u(rec["pair_psk"], 32), unb64u(rec["home"], 16), unb64u(rec["slot"], 8)
    ps = sigcrypto.p_slot(psk)
    return {"format": PAIRING_FMT, "home": rec["home"], "slot": rec["slot"], "pair_psk": psk.hex(),
            "stick": {"static_pub": crypto.x25519_public(reg.static_priv()).hex()},
            "kvm": {"static_pub": unb64u(rec["peer_pub"], 32).hex()},
            "derived": {"P_slot": ps.hex(), "jk": sigcrypto.join_key(psk).hex(), "env_k": sigcrypto.env_key(psk).hex(),
                        "prologue": noise.prologue(home, slot, unb64u(rec["peer_pub"], 32),
                                                   crypto.x25519_public(reg.static_priv())).hex()}}


USB_REC_FIELDS = ("kvm_static_pub", "stick_static_pub", "pair_psk", "home", "slot")


def import_usb_record(reg, path, name=None) -> dict:
    """TEST-ONLY: add the stick-side record written by AI KVM's sl1-host-sim after a USB pairing
    (kvm-<serial>.json: hex fields) as a slot of this already-provisioned stick."""
    _testing()
    d = json.loads(Path(path).read_text())
    missing = [k for k in USB_REC_FIELDS if k not in d]
    if missing:
        raise InteropError(f"usb record: missing {missing}")
    psk = _hex(d["pair_psk"], 32, "pair_psk")
    home, slot = _hex(d["home"], 16, "home"), _hex(d["slot"], 8, "slot")
    kvm_pub, stick_pub = _hex(d["kvm_static_pub"], 32, "kvm_static_pub"), _hex(d["stick_static_pub"], 32, "stick_static_pub")
    if not hmac.compare_digest(crypto.x25519_public(reg.static_priv()), stick_pub):
        raise InteropError("usb record: stick_static_pub is not this stick's static key")
    if unb64u(reg.load_signal()["home"], 16) != home:
        raise InteropError("usb record: home is not this stick's home")
    # informative fields the host-sim derives: must equal our recomputation (key-schedule interop)
    for k, mine in (("slot_jk", sigcrypto.join_key(psk)), ("slot_env_k", sigcrypto.env_key(psk))):
        if k in d and not hmac.compare_digest(bytes.fromhex(d[k]), mine):
            raise InteropError(f"usb record: {k} does not match our recomputation")
    if reg.by_slot(slot) is not None:
        raise InteropError("usb record: slot already present")
    return reg.add_record(name=name or f"kvm-usb-{d.get('serial', 'x')}"[:32], kind="kvm", peer_pub=kvm_pub,
                          pair_psk=psk, home=home, slot=slot)
