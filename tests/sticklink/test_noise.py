import json

import pytest
from conftest import VECTORS

from sticklink import noise

V = json.loads((VECTORS / "ikpsk2-v2.json").read_text()) if (VECTORS / "ikpsk2-v2.json").exists() else None
pytestmark = pytest.mark.skipif(V is None, reason="server vectors not present")
h = bytes.fromhex


def _pair(psk_r=None):
    pro = h(V["prologue"])
    i = noise.Initiator(h(V["kvm_static"]), h(V["stick_static_pub"]), h(V["psk"]), pro, e_priv=h(V["kvm_eph"]))
    r = noise.Responder(h(V["stick_static"]), pro, e_priv=h(V["stick_eph"]))
    return i, r


def test_prologue_rule():
    p = h(V["prologue"])
    assert len(p) == V["prologue_len"] == 96 and p[:8] == b"sl1/net\x01"
    assert noise.prologue(p[8:24], p[24:32], h(V["kvm_static_pub"]), h(V["stick_static_pub"])) == p


@pytest.mark.parametrize("case", ["swapped_statics", "other_slot", "ver_2", "v1_31_byte"])
def test_prologue_mismatch_responder_rejects_msg1(case):
    assert V["prologue_mismatch_responder_rejects_msg1"][case]
    p = h(V["prologue"])
    bad = {"swapped_statics": p[:32] + p[64:96] + p[32:64],
           "other_slot": p[:24] + b"\x00" * 8 + p[32:],
           "ver_2": p[:7] + b"\x02" + p[8:],
           "v1_31_byte": b"sl1/net" + p[8:32]}[case]
    i = noise.Initiator(h(V["kvm_static"]), h(V["stick_static_pub"]), h(V["psk"]), p, e_priv=h(V["kvm_eph"]))
    r = noise.Responder(h(V["stick_static"]), bad, e_priv=h(V["stick_eph"]))
    with pytest.raises(noise.NoiseError):
        r.read_msg1(i.write_msg1())


def test_vectors_byte_exact():
    i, r = _pair()
    m1 = i.write_msg1()
    assert m1 == h(V["msg1"]) and len(m1) == 96
    rs, pl = r.read_msg1(m1)
    assert rs == h(V["kvm_static_pub"]) and pl == b""
    rsess, m2 = r.write_msg2(h(V["psk"]))
    assert m2 == h(V["msg2"]) and len(m2) == 48
    isess, _ = i.read_msg2(m2)
    assert isess.handshake_hash == rsess.handshake_hash == h(V["handshake_hash"])
    pt = V["transport_plain"].encode()
    n, c = isess.encrypt(pt)
    assert n == 0 and c == h(V["transport_i2r_0"])
    assert rsess.decrypt(0, c) == pt
    n, c = rsess.encrypt(pt)
    assert c == h(V["transport_r2i_0"])
    assert isess.decrypt(0, c) == pt


def test_wrong_psk_rejected():
    i, r = _pair()
    r.read_msg1(i.write_msg1())
    _, m2 = r.write_msg2(b"\x00" * 32)
    assert m2 == h(V["wrong_psk_msg2"])
    with pytest.raises(noise.NoiseError):
        i.read_msg2(m2)


def test_replay_window():
    i, r = _pair()
    r.read_msg1(i.write_msg1())
    rs, m2 = r.write_msg2(h(V["psk"]))
    s, _ = i.read_msg2(m2)
    pk = [s.encrypt(b"x%d" % k) for k in range(100)]
    assert rs.decrypt(*pk[5]) == b"x5"
    assert rs.decrypt(*pk[3]) == b"x3"
    with pytest.raises(noise.NoiseError):
        rs.decrypt(*pk[3])
    assert rs.decrypt(*pk[99]) == b"x99"
    with pytest.raises(noise.NoiseError):
        rs.decrypt(*pk[10])  # outside the window now
    n, c = pk[98]
    with pytest.raises(noise.NoiseError):
        rs.decrypt(n, c[:-1] + bytes([c[-1] ^ 1]))
    assert rs.decrypt(*pk[98]) == b"x98"  # forged copy did not burn the counter
