"""Revocation: remove-only set store, apply_revocation kills the active session, later msg1 refused."""
import os, struct, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "overlay/usr/local/lib"))
os.environ["STICKLINK_TESTING"] = "1"
from sticklink import crypto, link, noise, registry, revocation  # noqa: E402
from sticklink.util import b64u  # noqa: E402


class FakeEp:
    force_relay = True
    def __init__(self): self.sent, self.handler = [], None
    def send(self, path, pkt): self.sent.append((path, pkt))


class Store(unittest.TestCase):
    def setUp(self):
        self.reg = registry.Registry(Path(tempfile.mkdtemp()) / "r", os.urandom(32))
        self.reg.init_dirs(); self.reg.create_identity()
        self.home = os.urandom(16)
        self.a = self.reg.add_record(name="a", kind="kvm", peer_pub=os.urandom(32), pair_psk=os.urandom(32), home=self.home, slot=os.urandom(8))
        self.b = self.reg.add_record(name="b", kind="kvm", peer_pub=os.urandom(32), pair_psk=os.urandom(32), home=self.home, slot=os.urandom(8))

    def test_parse(self):
        pub = os.urandom(32)
        self.assertEqual(revocation.parse_set({"set": [{"peer_pub": pub.hex()}, {"peer_pub": b64u(pub)}]}, self.home),
                         [("peer_pub", pub), ("peer_pub", pub)])
        for bad in ({"home": b64u(os.urandom(16)), "set": []}, {"set": [{"x": 1}]}, {"set": "no"}, [], {"set": [{"slot": "zz"}]}):
            with self.subTest(bad=bad), self.assertRaises(revocation.RevocationError):
                revocation.parse_set(bad, self.home)

    def test_apply_remove_only(self):
        st, got = revocation.RevokedStore(self.reg), []
        stranger = os.urandom(32)
        res = st.apply([("slot", __import__("sticklink.util", fromlist=["x"]).unb64u(self.a["slot"], 8)),
                        ("peer_pub", stranger)], self.home, on_revoke=lambda s, r: got.append(r["name"]))
        self.assertEqual(res, {"revoked": ["a"], "ignored": 1}); self.assertEqual(got, ["a"])
        self.assertEqual([r["name"] for r in self.reg.list_records()], ["b"])
        st2 = revocation.RevokedStore(self.reg)  # persisted; the stranger's key was NOT added
        self.assertEqual(len(st2.keys), 1); self.assertNotIn(stranger, st2)

    def test_cli_spool(self):
        revocation.spool_revoke(self.reg, "b")
        sets = revocation.take_spool(self.reg)
        self.assertEqual(len(sets), 1); self.assertEqual(revocation.take_spool(self.reg), [])
        self.assertEqual(revocation.parse_set(sets[0], self.home)[0][0], "peer_pub")
        with self.assertRaises(revocation.RevocationError):
            revocation.spool_revoke(self.reg, "nobody")


class Responder(unittest.TestCase):
    def setUp(self):
        self.s, self.c = crypto.x25519_generate(), crypto.x25519_generate()
        self.home, self.slot, self.psk = os.urandom(16), os.urandom(8), os.urandom(32)
        self.ep = FakeEp()
        self.r = link.Responder(self.ep, self.s, log=lambda m: None)
        self.r.add_slot(self.slot, {"name": "kvm", "peer_pub": crypto.x25519_public(self.c), "psk": self.psk, "home": self.home})

    def init(self, sidx=1):
        i = noise.Initiator(self.c, crypto.x25519_public(self.s), self.psk, noise.prologue(self.home, self.slot, crypto.x25519_public(self.c), crypto.x25519_public(self.s)))
        n = len(self.ep.sent)
        self.r.on_packet(("udp", ("192.0.2.1", 4000)), struct.pack("!B", link.T_INIT) + self.slot + struct.pack("!I", sidx) + i.write_msg1())
        return len(self.ep.sent) > n

    def test_revoke_kills_session_and_refuses_msg1(self):
        self.assertTrue(self.init())
        p = self.r.peers[self.slot]; idx = p.local_idx
        self.assertIsNotNone(p.session); self.assertIn(idx, self.r.by_idx)
        self.assertTrue(self.r.apply_revocation(self.slot))
        self.assertIsNone(p.session); self.assertIsNone(p.direct_addr); self.assertEqual(p.cands, [])
        self.assertNotIn(idx, self.r.by_idx); self.assertNotIn(self.slot, self.r._resp_cache)
        self.assertNotIn(self.slot, self.r.slots)
        self.assertFalse(self.init(2))  # new handshake: no RESP
        # same key re-added under a new slot (e.g. a stale record): still refused by key
        slot2 = os.urandom(8); self.slot = slot2
        self.r.add_slot(slot2, {"name": "kvm2", "peer_pub": crypto.x25519_public(self.c), "psk": self.psk, "home": self.home})
        self.assertFalse(self.init(3))


if __name__ == "__main__":
    unittest.main()
