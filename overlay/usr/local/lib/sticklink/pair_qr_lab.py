"""Lab-only Method C session with trusted local kiosk approval.

Enabled only when STICKLINK_TESTING=1 and STICKLINK_LAB=1.
SPAKE2 stays disabled. Not for shipping or real sticks.

Approval is intentionally a local kiosk gate for lab VMs (CURSOR lab
approval). Production must use the native sticklink-approve overlay
(PAIRING-SPEC §4.7); this module must not be enabled on shipping images.
"""
from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import crypto, pair_qr, registry
from .util import b64u, unb64u

INVITE_TTL_S = 60
LAB_MARKER = "sticklink-lab-method-c"


def _require_lab():
    if os.environ.get("STICKLINK_TESTING") != "1" or os.environ.get("STICKLINK_LAB") != "1":
        raise PermissionError("Method C lab pairing requires STICKLINK_TESTING=1 and STICKLINK_LAB=1")
    if pair_qr.FEATURE_SPAKE2_CODE != "0":
        raise RuntimeError("SPAKE2 must stay disabled in lab (FEATURE_SPAKE2_CODE!=0)")


@dataclass
class LabInvite:
    mailbox_id: bytes
    home_id: bytes
    stick_static_pub: bytes
    invite_secret: bytes
    exp: int
    approve_token: str
    approved: bool = False
    rejected: bool = False
    peer_pub: bytes | None = None
    qr: str = ""
    meta: dict = field(default_factory=dict)

    def to_public(self) -> dict:
        """Safe for kiosk display: no invite_secret, no approve_token."""
        return {
            "t": LAB_MARKER,
            "mailbox_id": self.mailbox_id.hex(),
            "home_id": b64u(self.home_id),
            "stick_static_pub": b64u(self.stick_static_pub),
            "exp": self.exp,
            "approved": self.approved,
            "rejected": self.rejected,
            "qr": self.qr,
            "spake2": "disabled",
        }


class LabPairSession:
    """In-memory / file-backed lab invite. One live invite at a time."""

    def __init__(self, reg: registry.Registry, state_dir: Path):
        _require_lab()
        self.reg = reg
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.path = self.state_dir / "lab-method-c.json"
        self.invite: LabInvite | None = None
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if raw.get("t") != LAB_MARKER:
            return
        self.invite = LabInvite(
            mailbox_id=bytes.fromhex(raw["mailbox_id"]),
            home_id=unb64u(raw["home_id"], 16),
            stick_static_pub=unb64u(raw["stick_static_pub"], 32),
            invite_secret=unb64u(raw["invite_secret"], 32),
            exp=int(raw["exp"]),
            approve_token=raw["approve_token"],
            approved=bool(raw.get("approved")),
            rejected=bool(raw.get("rejected")),
            peer_pub=unb64u(raw["peer_pub"], 32) if raw.get("peer_pub") else None,
            qr=raw.get("qr", ""),
        )

    def _save(self):
        inv = self.invite
        if inv is None:
            if self.path.exists():
                self.path.unlink()
            return
        doc = {
            "t": LAB_MARKER,
            "mailbox_id": inv.mailbox_id.hex(),
            "home_id": b64u(inv.home_id),
            "stick_static_pub": b64u(inv.stick_static_pub),
            "invite_secret": b64u(inv.invite_secret),
            "exp": inv.exp,
            "approve_token": inv.approve_token,
            "approved": inv.approved,
            "rejected": inv.rejected,
            "peer_pub": b64u(inv.peer_pub) if inv.peer_pub else None,
            "qr": inv.qr,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def open_invite(self, *, mailbox_id: bytes | None = None) -> LabInvite:
        _require_lab()
        sig = self.reg.load_signal()
        home = unb64u(sig["home"], 16)
        stick_pub = crypto.x25519_public(self.reg.static_priv())
        mbx = mailbox_id if mailbox_id is not None else secrets.token_bytes(8)
        if len(mbx) != 8:
            raise ValueError("mailbox_id must be 8 bytes")
        invite = secrets.token_bytes(32)
        exp = int(time.time()) + INVITE_TTL_S
        token = secrets.token_urlsafe(24)
        qr = pair_qr.encode_qr(mailbox_id=mbx, stick_static_pub=stick_pub,
                               invite_secret=invite, exp=exp)
        self.invite = LabInvite(
            mailbox_id=mbx, home_id=home, stick_static_pub=stick_pub,
            invite_secret=invite, exp=exp, approve_token=token, qr=qr,
        )
        self._save()
        return self.invite

    def status_public(self) -> dict | None:
        if self.invite is None:
            return None
        return self.invite.to_public()

    def approve_local(self, token: str) -> dict:
        """Trusted local kiosk approval (lab only)."""
        _require_lab()
        inv = self.invite
        if inv is None:
            raise ValueError("no live invite")
        if inv.rejected:
            raise ValueError("invite rejected")
        if inv.exp < int(time.time()):
            raise ValueError("invite expired")
        if not secrets.compare_digest(token, inv.approve_token):
            raise ValueError("bad approve token")
        inv.approved = True
        self._save()
        return inv.to_public()

    def reject_local(self, token: str) -> dict:
        _require_lab()
        inv = self.invite
        if inv is None:
            raise ValueError("no live invite")
        if not secrets.compare_digest(token, inv.approve_token):
            raise ValueError("bad approve token")
        inv.rejected = True
        inv.approved = False
        self._save()
        return inv.to_public()

    def cancel(self):
        self.invite = None
        self._save()

    def derived(self) -> dict:
        """Return Method C derived keys for the live invite (test/VM)."""
        _require_lab()
        inv = self.invite
        if inv is None:
            raise ValueError("no live invite")
        th = pair_qr.transcript_hash(
            mailbox_id=inv.mailbox_id, home_id=inv.home_id,
            stick_static_pub=inv.stick_static_pub)
        return {
            "TH": th.hex(),
            "boot_psk": pair_qr.boot_psk(inv.invite_secret, th).hex(),
            "jk_qr": pair_qr.jk_qr(inv.invite_secret).hex(),
            "env_qr": pair_qr.env_qr(inv.invite_secret, inv.mailbox_id, inv.home_id).hex(),
            "approved": inv.approved,
            "rejected": inv.rejected,
            "exp": inv.exp,
        }
