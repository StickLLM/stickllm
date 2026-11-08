"""pair_psk + pair-confirm (PAIRING-SPEC §4.5) for Method C prior=boot_psk."""
from __future__ import annotations

import os

import pytest

from sticklink import crypto, pair_qr


def test_pair_psk_and_confirm_roundtrip():
    r_i, r_r = os.urandom(32), os.urandom(32)
    prior = os.urandom(32)
    hh, th = os.urandom(32), os.urandom(32)
    i_pub, r_pub = crypto.x25519_public(crypto.x25519_generate()), crypto.x25519_public(crypto.x25519_generate())
    psk = pair_qr.pair_psk(
        r_i=r_i, r_r=r_r, prior=prior, handshake_hash=hh, th=th,
        initiator_static=i_pub, responder_static=r_pub, key_epoch=0,
    )
    assert len(psk) == 32
    kc = pair_qr.pair_confirm_kc(psk)
    ci = pair_qr.confirm_mac(kc, "i", hh)
    cr = pair_qr.confirm_mac(kc, "r", hh)
    assert ci != cr
    assert pair_qr.verify_confirm(kc, "i", hh, ci)
    assert pair_qr.verify_confirm(kc, "r", hh, cr)
    assert not pair_qr.verify_confirm(kc, "i", hh, cr)
    assert not pair_qr.verify_confirm(kc, "r", hh, ci)


def test_pair_psk_binds_identities_and_contributions():
    base = dict(
        r_i=os.urandom(32), r_r=os.urandom(32), prior=os.urandom(32),
        handshake_hash=os.urandom(32), th=os.urandom(32),
        initiator_static=os.urandom(32), responder_static=os.urandom(32),
        key_epoch=0,
    )
    a = pair_qr.pair_psk(**base)
    b = pair_qr.pair_psk(**{**base, "r_i": os.urandom(32)})
    c = pair_qr.pair_psk(**{**base, "initiator_static": os.urandom(32)})
    d = pair_qr.pair_psk(**{**base, "key_epoch": 1})
    assert len({a, b, c, d}) == 4


def test_wrong_confirm_rejected():
    hh = os.urandom(32)
    psk = os.urandom(32)
    kc = pair_qr.pair_confirm_kc(psk)
    assert not pair_qr.verify_confirm(kc, "i", hh, os.urandom(32))
