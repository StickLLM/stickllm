import json

import pytest
from conftest import VECTORS

from sticklink import sigcrypto as sc
from sticklink.util import b64u, unb64u

S = VECTORS / "signalling-v2.json"
I = VECTORS / "ikpsk2-v2.json"
pytestmark = pytest.mark.skipif(not S.exists(), reason="server vectors not present")
h = bytes.fromhex


def test_slot_derivations():
    v = json.loads(S.read_text())["slot_join"]
    psk = h(v["pair_psk"])
    assert sc.p_slot(psk) == h(v["P_slot"])
    assert sc.join_key(psk) == h(v["jk"]) and b64u(sc.join_key(psk)) == v["jk_b64"]
    assert sc.env_key(psk) == h(v["env_k"])
    assert sc.join_mac(h(v["jk"]), h(v["nonce"]), h(v["home"]), h(v["slot"])) == h(v["join_mac"])


def test_hello_sigs_v2():
    from sticklink import crypto
    d = json.loads(S.read_text())["device"]
    seed, n, dev = h(d["auth_seed"]), h(d["nonce"]), h(d["dev"])
    assert crypto.ed25519_public(seed) == h(d["ak"])
    assert sc.hello_input(n, dev, sc.ROLE_SERVER, h(d["home"])) == h(d["hello_input_server"])
    assert sc.hello_input(n, dev, sc.ROLE_CLIENT, None) == h(d["hello_input_client"])
    assert sc.hello_sig(seed, n, dev, sc.ROLE_SERVER, h(d["home"])) == h(d["hello_sig_server"])
    assert sc.hello_sig(seed, n, dev, sc.ROLE_CLIENT, None) == h(d["hello_sig_client"])


def test_revoked_page_vector():
    from sticklink import revocation
    v = json.loads(S.read_text())
    pg, sg = v["revoked"], v["signing"]
    body = json.loads(pg["body_json"])
    pins = {sg["kid"]: h(sg["pub"])}
    d = revocation.verify_page(pg, pins, unb64u(body["home"], 16), unb64u(body["n"], 32))
    assert d["s"] == body["s"]
    with pytest.raises(revocation.RevocationError):
        revocation.verify_page(pg, pins, b"\x00" * 16, None)  # other home
    with pytest.raises(revocation.RevocationError):
        revocation.verify_page(pg, pins, unb64u(body["home"], 16), b"\x01" * 32)  # other session
    with pytest.raises(revocation.RevocationError):
        revocation.verify_page(dict(pg, sig=pg["sig"][:-2] + "AA"), pins, unb64u(body["home"], 16), None)


def test_box_vector_and_dirs():
    b = json.loads(I.read_text())["box"]
    v = json.loads(S.read_text())["slot_join"]
    home, slot, k = h(v["home"]), h(v["slot"]), h(b["env_k"])
    out = sc.seal_box(k, home, slot, sc.DIR_C2S, b["inner"].encode(), nonce=h(b["nonce"]))
    assert out == b["box_b64"] and len(unb64u(out)) == b["box_len"]
    assert sc.open_box(k, home, slot, sc.DIR_C2S, out)["k"] == "derp"
    with pytest.raises(Exception):
        sc.open_box(k, home, slot, sc.DIR_S2C, out)  # direction bound
    with pytest.raises(Exception):
        sc.open_box(k, home, b"\x00" * 8, sc.DIR_C2S, out)  # slot bound


def test_rotate_pop_vector():
    from sticklink import crypto
    d = json.loads(S.read_text())["device"]
    new = h(d["rotate_new_seed"])
    assert crypto.ed25519_public(new) == h(d["rotate_new_ak"])
    assert sc.rotate_pop(new, h(d["nonce"]), h(d["dev"]), h(d["ak"])) == h(d["rotate_pop"])


def test_wire_hello_server_matches():
    from sticklink import crypto  # noqa: F401
    d = json.loads(S.read_text())["device"]
    w = d["wire_hello_server"]
    w = json.loads(w) if isinstance(w, str) else w
    assert w["sig"] == b64u(sc.hello_sig(h(d["auth_seed"]), h(d["nonce"]), h(d["dev"]), sc.ROLE_SERVER, h(d["home"])))
    assert "mac" not in w
