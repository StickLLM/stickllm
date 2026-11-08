"""API.md §4.1 bye semantics in sticklinkd: current sid drops the peer's session state; old sid is ignored."""
import asyncio, os, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "overlay/usr/local/lib"))
from sticklink import daemon, link, sigcrypto as sc  # noqa: E402
from sticklink.util import b64u  # noqa: E402


class FakeEp:
    force_relay = True  # no punches/sends in the unit test
    def send(self, *a): pass


class T(unittest.TestCase):
    def setUp(self):
        self.home, self.slot, psk = os.urandom(16), os.urandom(8), os.urandom(32)
        self.envk = sc.env_key(psk)
        resp = link.Responder.__new__(link.Responder)
        resp.ep, resp.log = FakeEp(), (lambda m: None)
        resp.slots, resp.peers, resp.by_idx, resp._resp_cache = {self.slot: {"name": "kvm"}}, {}, {}, {}
        resp.peers[self.slot] = link.Peer(resp.ep, "kvm", log=lambda m: None)
        d = daemon.Stick.__new__(daemon.Stick)
        d.resp, d.home, d.conns, d.envk, d.cfg = resp, self.home, {"c1": self.slot}, {self.slot: self.envk}, {"force_relay": True}
        self.d, self.resp, self.peer = d, resp, resp.peers[self.slot]

    def sig(self, inner):
        box = sc.seal_box(self.envk, self.home, self.slot, sc.DIR_C2S, inner)
        asyncio.run(self.d.on_sig({"t": "sig", "from": "c1", "box": box}))

    def established(self):
        self.sig({"k": "cand", "sid": "S1", "seq": 1, "c": [{"a": "192.0.2.1:4000", "p": "host"}]})
        p = self.peer
        p.session, p.remote_idx, p.direct_addr, p.prflx = object(), 7, ("192.0.2.1", 4000), [("192.0.2.9", 1)]
        self.resp.by_idx[p.local_idx] = p
        self.resp._resp_cache[self.slot] = (b"m1", b"r")

    def test_current_sid_bye_drops_state(self):
        self.established()
        old_idx = self.peer.local_idx
        self.sig({"k": "bye", "sid": "S1"})
        p = self.peer
        self.assertIsNone(p.session); self.assertIsNone(p.remote_idx); self.assertIsNone(p.direct_addr)
        self.assertEqual((p.cands, p.prflx), ([], [])); self.assertNotIn(old_idx, self.resp.by_idx)
        self.assertNotIn(self.slot, self.resp._resp_cache)

    def test_old_sid_bye_ignored(self):
        self.established()
        self.sig({"k": "bye", "sid": "S0"})
        self.assertIsNotNone(self.peer.session); self.assertIn(self.peer.local_idx, self.resp.by_idx)

    def test_leave_drops_nothing(self):
        self.established()
        asyncio.run(self.d.on_peer({"conn": "c1", "slot": b64u(self.slot), "state": "leave"}))
        self.assertIsNotNone(self.peer.session)


if __name__ == "__main__":
    unittest.main()


def test_path_follows_peer_to_derp_after_direct_rx():
    """UDP-blocked fallback (one-way UDP): direct DATA seen during the peer's probe window must not keep
    the stick sending on direct once the peer has moved to DERP."""
    import time as _t
    from sticklink import link

    class P:  # minimal stand-in exercising Peer.rx_data/best_path only
        best_path = link.Peer.best_path
        rx_data = link.Peer.rx_data

        def __init__(s):
            s.ep = type("E", (), {"force_relay": False})()
            s.direct_addr, s.last_direct_rx, s.last_rx_path, s.derp_key = None, 0.0, None, None
            s.session = type("S", (), {"decrypt": staticmethod(lambda n, ct: b"")})()
            s.on_data = None
            s.notes = []
            s.follow_peer = True

        def note(s, ev): s.notes.append(ev)

    p = P()
    p.rx_data(("udp", ("10.0.0.2", 4000)), 0, b"")
    assert p.best_path() == ("udp", ("10.0.0.2", 4000))
    p.rx_data(("derp", b"k" * 32), 1, b"")
    assert p.best_path() == ("derp", b"k" * 32)
    p.rx_data(("udp", ("10.0.0.2", 4000)), 2, b"")  # peer back on direct -> direct again
    assert p.best_path()[0] == "udp"

    q = P(); q.follow_peer = False  # initiator side keeps its own (direct-preferring) choice
    q.rx_data(("udp", ("10.0.0.2", 4000)), 0, b""); q.rx_data(("derp", b"k" * 32), 1, b"")
    assert q.best_path()[0] == "udp"
