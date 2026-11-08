"""import-usb: accepts a matching sl1-host-sim record, refuses a foreign stick/home or bad derived keys."""
import json, os, tempfile, unittest
from pathlib import Path
os.environ["STICKLINK_TESTING"] = "1"
from sticklink import crypto, e2einterop, registry, sigcrypto
from sticklink.util import b64u


class ImportUsb(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())
        self.reg = registry.Registry(self.d / "reg", os.urandom(32))
        self.reg.init_dirs(); self.priv = os.urandom(32); self.reg.create_identity(priv=self.priv)
        self.home = os.urandom(16)
        self.reg.save_signal(b64u(os.urandom(16)), b64u(self.home))
        psk = os.urandom(32)
        self.rec = {"peer_class": "kvm", "serial": "T1", "kvm_static_pub": os.urandom(32).hex(),
                    "stick_static_pub": crypto.x25519_public(self.priv).hex(), "pair_psk": psk.hex(),
                    "home": self.home.hex(), "slot": os.urandom(8).hex(), "key_epoch": 1,
                    "slot_jk": sigcrypto.join_key(psk).hex(), "slot_env_k": sigcrypto.env_key(psk).hex()}

    def imp(self, **over):
        p = self.d / "r.json"; p.write_text(json.dumps({**self.rec, **over}))
        return e2einterop.import_usb_record(self.reg, p)

    def test_ok(self):
        r = self.imp()
        self.assertEqual(r["kind"], "kvm")
        self.assertIsNotNone(self.reg.by_slot(bytes.fromhex(self.rec["slot"])))

    def test_refusals(self):
        for over in ({"stick_static_pub": os.urandom(32).hex()}, {"home": os.urandom(16).hex()},
                     {"slot_jk": "00" * 32}, {"slot_env_k": "00" * 32}, {"pair_psk": "00"}):
            with self.subTest(over=list(over)), self.assertRaises(e2einterop.InteropError):
                self.imp(**over)


if __name__ == "__main__":
    unittest.main()
