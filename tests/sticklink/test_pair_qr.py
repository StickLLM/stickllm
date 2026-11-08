"""Method C (QR) schedule vs qr-v1.json; lab approve gate."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from conftest import QR_VECTORS

from sticklink import crypto, pair_qr, pair_qr_lab, registry
from sticklink.util import b64u

V = json.loads(QR_VECTORS.read_text()) if QR_VECTORS.exists() else None
h = bytes.fromhex


def _make_reg(tmp_path: Path) -> registry.Registry:
    root = tmp_path / f"root-{os.urandom(4).hex()}"
    rk = crypto.random_key()
    reg = registry.Registry(root, rk)
    reg.init_dirs()
    reg.create_identity()
    # Round-trip immediately so Windows lab fsio regressions fail here, not later.
    assert reg.load_identity() is not None
    assert len(reg.static_priv()) == 32
    reg.save_signal(b64u(os.urandom(16)), b64u(os.urandom(16)))
    assert "home" in reg.load_signal()
    reg.save_auth_seed()
    return reg


@pytest.mark.skipif(V is None, reason="qr-v1.json missing")
def test_qr_v1_transcript_and_keys():
    mbx, home = h(V["mailbox_id"]), h(V["home_id"])
    invite, stick = h(V["invite_secret"]), h(V["stick_static_pub"])
    th = pair_qr.transcript_hash(mailbox_id=mbx, home_id=home, stick_static_pub=stick)
    assert th == h(V["TH"])
    assert pair_qr.boot_psk(invite, th) == h(V["boot_psk"])
    assert pair_qr.jk_qr(invite) == h(V["jk_qr"])
    assert pair_qr.env_qr(invite, mbx, home) == h(V["env_qr"])
    assert pair_qr.join_mac(pair_qr.jk_qr(invite), h(V["server_nonce"]), mbx) == h(V["join_mac"])
    th_wrong = pair_qr.transcript_hash(
        mailbox_id=mbx, home_id=home, stick_static_pub=stick,
        initiator_static=h(V["phone_static_pub"]))
    assert th_wrong == h(V["TH_if_real_phone_key_were_used_NOT_THE_SPEC"])
    assert th_wrong != th


@pytest.mark.skipif(V is None, reason="qr-v1.json missing")
def test_qr_roundtrip_encode_decode():
    mbx, stick, invite = h(V["mailbox_id"]), h(V["stick_static_pub"]), h(V["invite_secret"])
    exp = 1_800_000_000
    qr = pair_qr.encode_qr(mailbox_id=mbx, stick_static_pub=stick, invite_secret=invite, exp=exp)
    assert qr.startswith("sl1:")
    got = pair_qr.decode_qr(qr)
    assert got["mailbox_id"] == mbx
    assert got["stick_static_pub"] == stick
    assert got["invite_secret"] == invite
    assert got["exp"] == exp


def test_spake2_flag_stays_off():
    assert pair_qr.FEATURE_SPAKE2_CODE == "0"


def test_lab_session_requires_flags(tmp_path):
    os.environ["STICKLINK_TESTING"] = "1"
    os.environ.pop("STICKLINK_LAB", None)
    reg = _make_reg(tmp_path)
    with pytest.raises(PermissionError):
        pair_qr_lab.LabPairSession(reg, tmp_path / "lab")


def test_lab_approve_flow(tmp_path):
    os.environ["STICKLINK_TESTING"] = "1"
    os.environ["STICKLINK_LAB"] = "1"
    reg = _make_reg(tmp_path)
    sess = pair_qr_lab.LabPairSession(reg, tmp_path / "lab")
    inv = sess.open_invite(mailbox_id=bytes.fromhex("d90c13749910a177"))
    pub = sess.status_public()
    assert pub["spake2"] == "disabled"
    assert "invite_secret" not in pub
    assert "approve_token" not in pub
    decoded = pair_qr.decode_qr(inv.qr)
    assert decoded["mailbox_id"] == inv.mailbox_id
    with pytest.raises(ValueError):
        sess.approve_local("wrong-token")
    out = sess.approve_local(inv.approve_token)
    assert out["approved"] is True
    d = sess.derived()
    assert len(d["boot_psk"]) == 64
