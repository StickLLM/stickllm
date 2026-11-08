"""TEST-ONLY interop with Sticklink's e2e fixtures (sl1-e2e-pairing/1, sl1-e2e-identity/2, sl1-e2e-stack/1)."""
import json, os, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "overlay/usr/local/lib"))
os.environ["STICKLINK_TESTING"] = "1"; os.environ["STICKLINK_FAST_KDF"] = "1"
from sticklink import crypto, e2einterop, registry, sigcrypto  # noqa: E402
from sticklink.util import b64u  # noqa: E402


def make_fixture(d):
    psk, home, slot = os.urandom(32), os.urandom(16), os.urandom(8)
    sp, kp = crypto.x25519_generate(), crypto.x25519_generate()
    ps = sigcrypto.p_slot(psk)
    pairing = {"format": "sl1-e2e-pairing/1", "home": b64u(home), "slot": b64u(slot), "pair_psk": psk.hex(),
               "stick": {"static_pub": crypto.x25519_public(sp).hex()}, "kvm": {"static_pub": crypto.x25519_public(kp).hex()},
               "derived": {"P_slot": ps.hex(), "jk": sigcrypto.join_key(psk).hex(), "env_k": sigcrypto.env_key(psk).hex(),
                           "prologue": (b"sl1/net\x01" + home + slot + crypto.x25519_public(kp) + crypto.x25519_public(sp)).hex()}}
    ident = {"format": "sl1-e2e-identity/2", "role": "stick", "dev": b64u(os.urandom(16)), "auth_seed": b64u(os.urandom(32)),
             "static_priv": sp.hex()}
    (d / "pairing.json").write_text(json.dumps(pairing)); (d / "stick.id.json").write_text(json.dumps(ident))
    return pairing


class T(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory(); self.d = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def test_roundtrip(self):
        fx = make_fixture(self.d)
        reg = registry.Registry(str(self.d / "root"), os.urandom(32))
        e2einterop.import_stick(reg, str(self.d / "pairing.json"), str(self.d / "stick.id.json"))
        out = e2einterop.export_pairing(reg, fx["slot"])
        for k in ("home", "slot", "pair_psk", "stick", "kvm", "derived"):
            self.assertEqual(out[k], fx[k], k)

    def test_tampered_derived_rejected(self):
        fx = make_fixture(self.d)
        fx["derived"]["jk"] = "00" * 32
        (self.d / "pairing.json").write_text(json.dumps(fx))
        with self.assertRaises(e2einterop.InteropError):
            e2einterop.load_pairing(str(self.d / "pairing.json"))

    def test_wrong_role_rejected(self):
        make_fixture(self.d)
        with self.assertRaises(e2einterop.InteropError):
            e2einterop.load_identity(str(self.d / "stick.id.json"), "kvm")

    def test_stack(self):
        st = {"format": "sl1-e2e-stack/1", "ws": "ws://h:1/v1/ws", "rg": "box",
              "derp": {"url": "https://h:2/derp", "host": "h", "port": 2, "cert_sha256": "AB:" * 31 + "AB", "stun": "h:3"}}
        (self.d / "s.json").write_text(json.dumps(st))
        c = e2einterop.load_stack(str(self.d / "s.json"))
        self.assertEqual((c["ws"], c["derp"], c["stun"], c["rg"]), ("ws://h:1/v1/ws", "https://h:2/derp", "h:3", "box"))
        self.assertEqual(c["derp_pin"], "ab" * 32)

    def test_supplied_priv_needs_testing(self):
        os.environ.pop("STICKLINK_TESTING")
        try:
            with self.assertRaises(Exception):
                registry.Registry(str(self.d / "r"), os.urandom(32)).create_identity(priv=os.urandom(32))
        finally:
            os.environ["STICKLINK_TESTING"] = "1"


if __name__ == "__main__":
    unittest.main()


class AuthSeed(unittest.TestCase):
    def test_seed_separate_0600_and_only_pub_exported(self):
        with tempfile.TemporaryDirectory() as td:
            reg = registry.Registry(str(Path(td) / "root"), os.urandom(32)); reg.init_dirs(); reg.create_identity()
            ak = reg.save_auth_seed()
            f = Path(td) / "root" / "auth.sealed"
            self.assertEqual(f.stat().st_mode & 0o777, 0o600)
            seed = reg.auth_seed()
            self.assertNotIn(seed, f.read_bytes())  # sealed, not plaintext
            self.assertNotEqual(seed, reg.static_priv())
            self.assertEqual(ak, crypto.ed25519_public(seed)); self.assertEqual(reg.auth_pub(), ak)
            wrong = registry.Registry(str(Path(td) / "root"), os.urandom(32))
            with self.assertRaises(Exception):
                wrong.auth_seed()
