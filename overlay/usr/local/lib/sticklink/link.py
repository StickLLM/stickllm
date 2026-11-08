"""sticklink data path: one UDP socket + one DERP connection per process,
Noise IKpsk2 sessions per paired peer, direct-first with DERP fallback.

Wire packets (identical over UDP and inside DERP SendPacket):
  0x01 INIT  slot(8) || sidx(4) || msg1(96)
  0x02 RESP  sidx(4) || ridx(4) || msg2(48)      (sidx = responder's index, ridx = initiator's)
  0x04 DATA  ridx(4) || ctr(8 LE) || ChaChaPoly(ct)   (ridx = receiver's index)
  0x05 PUNCH 8 random bytes (NAT opener, ignored)
Data plaintext (PAIRING-SPEC §4 "type(1) || body"): 0x01 PING id(8), 0x02 PONG id(8),
  0x10 ECHO_REQ body, 0x11 ECHO_REP body, 0x20 APP body.

Path policy (SIGNALLING-PLAN §3): try every direct candidate at once; after
1.5 s also try DERP; first authenticated reply wins. While on DERP the
initiator keeps probing direct candidates every second and moves to direct on
the first authenticated PONG over UDP; if direct goes quiet for 5 s it falls
back to DERP. The responder answers on the path a packet arrived on and sends
its own traffic on the freshest authenticated path, direct preferred.
force_relay: no candidates advertised, no STUN, UDP never used.

Only Noise ciphertext crosses DERP or UDP. The relay sees DERP node keys and
packet sizes, nothing else.
"""
from __future__ import annotations

import asyncio
import hmac
import ipaddress
import json
import os
import secrets
import socket
import struct
import subprocess
import time

from . import crypto, derp, noise, stun
from .util import b64u, unb64u

T_INIT, T_RESP, T_DATA, T_PUNCH = 0x01, 0x02, 0x04, 0x05
MAX_PRFLX = 4
DEBUG_PKT = os.environ.get("STICKLINK_DEBUG_PKT") == "1"  # metadata only, never payloads
D_PING, D_PONG, D_ECHO_REQ, D_ECHO_REP, D_APP = 0x01, 0x02, 0x10, 0x11, 0x20
DERP_DELAY = 1.5
DIRECT_STALE = 5.0
HS_TIMEOUT = 15.0


def fp(b: bytes) -> str:
    """Short, non-secret fingerprint for logs."""
    return b.hex()[:8]


def path_str(path) -> str:
    return f"direct {path[1][0]}:{path[1][1]}" if path[0] == "udp" else f"derp {fp(path[1])}"


def parse_addr(a: str) -> tuple[str, int]:
    host, _, port = a.rpartition(":")
    host = host.strip("[]")
    ipaddress.ip_address(host)
    p = int(port)
    if not 0 < p < 65536:
        raise ValueError("bad port")
    return host, p


def fmt_addr(ip: str, port: int) -> str:
    return f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"


# Candidate "p" (type) labels. Informational only: receivers never branch on them
# (canonical per Sticklink server 7f8b564: host, v6, stun4, stun6, cfg); one place to switch.
MAX_DGRAM = 1280  # Q-N11 (API.md): max sl1 datagram, any path
CAND_LAN4, CAND_LAN6, CAND_STUN4, CAND_STUN6 = "host", "v6", "stun4", "stun6"


def local_addresses(probe_host: str | None) -> list[tuple[str, str]]:
    out = []
    try:
        j = json.loads(subprocess.run(["ip", "-j", "addr"], capture_output=True, text=True, timeout=3).stdout or "[]")
        for itf in j:
            for a in itf.get("addr_info", []):
                ip = ipaddress.ip_address(a["local"])
                if ip.is_loopback or ip.is_link_local or (ip.version == 6 and ip in ipaddress.ip_network("fec0::/10")):
                    continue
                out.append((str(ip), CAND_LAN4 if ip.version == 4 else CAND_LAN6))
    except Exception:
        pass
    if probe_host and not out:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((probe_host, 9))
            out.append((s.getsockname()[0], CAND_LAN4))
            s.close()
        except OSError:
            pass
    return out


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, ep):
        self.ep = ep

    def datagram_received(self, data, addr):
        self.ep._on_udp(data, (addr[0], addr[1]))

    def error_received(self, exc):
        pass


class Endpoint:
    def __init__(self, *, udp_port=0, derp_url=None, derp_priv=None, derp_cafile=None, stun_addr=None,
                 force_relay=False, extra_cands=(), log=print, derp_pin=None, derp_sni=None):
        self.derp_pin, self.derp_sni = derp_pin, derp_sni
        self.udp_port, self.derp_url, self.derp_cafile = udp_port, derp_url, derp_cafile
        self.derp_priv = derp_priv or noise.crypto.x25519_generate()
        self.stun_addr, self.force_relay, self.extra_cands, self.log = stun_addr, force_relay, list(extra_cands), log
        self.transport = None
        self.derp: derp.DerpClient | None = None
        self.handler = None  # fn(path, pkt)
        self._stun_waiters: dict[bytes, asyncio.Future] = {}
        self.mapped = None
        self._derp_task = None

    @property
    def derp_pub(self) -> bytes:
        return derp.PrivateKey(self.derp_priv).public_key.encode()

    async def start(self, connect_derp: bool = True):
        loop = asyncio.get_running_loop()
        self.transport, _ = await loop.create_datagram_endpoint(lambda: _Proto(self), local_addr=("0.0.0.0", self.udp_port))
        self.udp_port = self.transport.get_extra_info("sockname")[1]
        if connect_derp:
            self.start_derp()

    def start_derp(self):
        """Connect to DERP (idempotent). sticklinkd calls this only after relay.reg, so the relay's
        fail-closed admission already knows the node key on the first connect."""
        if self.derp_url and self._derp_task is None:
            self._derp_task = asyncio.create_task(self._derp_loop())

    async def close(self):
        if self._derp_task:
            self._derp_task.cancel()
            try:
                await self._derp_task
            except (asyncio.CancelledError, Exception):
                pass
            self._derp_task = None
        if self.transport:
            self.transport.close()
            self.transport = None

    async def _derp_loop(self):
        backoff = 1
        while True:
            c = derp.DerpClient(self.derp_url, self.derp_priv, self.derp_cafile, pin_sha256=self.derp_pin, sni=self.derp_sni,
                                on_packet=lambda src, p: self._dispatch(("derp", src), p), log=self.log)
            try:
                await c.connect()
                self.derp = c
                self.log(f"derp connected {self.derp_url} as {fp(self.derp_pub)}")
                backoff = 1
                await c.run()
                self.log("derp connection closed")
            except Exception as e:
                self.log(f"derp connect failed: {type(e).__name__}: {str(e)[:80]}")
            finally:
                if self.derp is c:
                    self.derp = None
                await c.close()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def wait_derp(self, timeout=10.0) -> bool:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.derp and self.derp.connected.is_set():
                return True
            await asyncio.sleep(0.1)
        return False

    def _on_udp(self, data: bytes, addr):
        if stun.is_stun(data):
            for tid, fut in list(self._stun_waiters.items()):
                m = stun.parse_response(data, tid)
                if m and not fut.done():
                    fut.set_result(m)
            return
        if DEBUG_PKT:
            self.log(f"dbg udp rx type={data[:1].hex()} len={len(data)} from {fmt_addr(*addr)}{' (dropped: force-relay)' if self.force_relay else ''}")
        if self.force_relay:
            return
        self._dispatch(("udp", addr), data)

    def _dispatch(self, path, pkt):
        if self.handler and pkt:
            try:
                self.handler(path, pkt)
            except Exception as e:  # never let a bad packet kill the loop
                self.log(f"drop packet from {path[0]}: {type(e).__name__}")

    async def stun_mapped(self, timeout=2.0):
        if not self.stun_addr or self.force_relay:
            return None
        for _ in range(3):
            req, tid = stun.request()
            fut = asyncio.get_running_loop().create_future()
            self._stun_waiters[tid] = fut
            self.transport.sendto(req, parse_addr(self.stun_addr))
            try:
                self.mapped = await asyncio.wait_for(fut, timeout / 3)
                return self.mapped
            except asyncio.TimeoutError:
                continue
            finally:
                self._stun_waiters.pop(tid, None)
        return None

    async def candidates(self, probe_host=None) -> list[dict]:
        if self.force_relay:
            return []
        c = [{"a": fmt_addr(ip, self.udp_port), "p": kind} for ip, kind in local_addresses(probe_host)]
        m = await self.stun_mapped()
        if m:
            c.append({"a": fmt_addr(*m), "p": CAND_STUN4 if ":" not in m[0] else CAND_STUN6})
        c += [{"a": a, "p": "cfg"} for a in self.extra_cands]
        seen, out = set(), []
        for x in c:
            if x["a"] not in seen:
                seen.add(x["a"])
                out.append(x)
        return out[:8]

    def send(self, path, pkt: bytes):
        if path[0] == "udp":
            if DEBUG_PKT:
                self.log(f"dbg udp tx type={pkt[:1].hex()} to {fmt_addr(*path[1])}{' (suppressed)' if self.force_relay else ''}")
            if not self.force_relay and self.transport:
                self.transport.sendto(pkt, path[1])
        elif self.derp and self.derp.connected.is_set():
            asyncio.ensure_future(self.derp.send(path[1], pkt))


class Peer:
    """One remote peer: its candidates, DERP key, Noise session and path state."""

    def __init__(self, ep: Endpoint, name: str, log=print, follow_peer: bool = False):
        self.ep, self.name, self.log = ep, name, log
        # responder (stick) only: the initiator (KVM/phone) picks the path and we follow it; if both ends
        # followed each other neither would ever probe back to direct after a DERP fallback.
        self.follow_peer = follow_peer
        self.cands: list[tuple[str, int]] = []
        self._signalled: list[tuple[str, int]] = []
        self.prflx: list[tuple[str, int]] = []
        self.derp_key: bytes | None = None
        self.session: noise.Session | None = None
        self.local_idx = secrets.randbits(32)
        self.remote_idx = None
        self.direct_addr = None
        self.last_direct_rx = 0.0
        self.last_rx_path = None
        self.on_data = None  # fn(type, body, path)
        self.events = []
        self.sig_sid = None  # the peer's current signalling sid (from its cand/derp boxes)

    def reset(self):
        """Drop everything about the peer's current session (API.md §4.1 bye): Noise session and its
        replay window, learned paths, signalled and peer-reflexive candidates (so no pending punches)."""
        self.session, self.remote_idx = None, None
        self.local_idx = secrets.randbits(32)
        self.cands, self._signalled, self.prflx = [], [], []
        self.derp_key = None
        self.direct_addr, self.last_direct_rx, self.last_rx_path = None, 0.0, None
        self._tx_path = None
        self.sig_sid = None

    def note(self, ev: str):
        self.events.append((round(time.time(), 3), ev))
        self.log(f"[{self.name}] {ev}")

    def set_cands(self, c: list[dict]):
        out = []
        for x in c[:8]:
            try:
                out.append(parse_addr(x["a"]))
            except (ValueError, KeyError, TypeError):
                continue
        self._signalled = list(out)
        self.cands = out + [a for a in getattr(self, "prflx", []) if a not in out]
        self.note(f"remote candidates: {', '.join(fmt_addr(*a) for a in out) or 'none'}")

    def best_path(self):
        if self.direct_addr and time.monotonic() - self.last_direct_rx < DIRECT_STALE and not self.ep.force_relay:
            return ("udp", self.direct_addr)
        if self.derp_key:
            return ("derp", self.derp_key)
        return self.last_rx_path

    def send_data(self, typ: int, body: bytes = b"", path=None) -> bool:
        if not self.session:
            return False
        explicit = path is not None
        path = path or self.best_path()
        if path is None:
            return False
        if not explicit and path != getattr(self, "_tx_path", None):
            if getattr(self, "_tx_path", None) is not None:
                self.note(f"path -> {path_str(path)}")
            self._tx_path = path
        if 1 + 4 + 8 + 1 + len(body) + 16 > MAX_DGRAM:
            raise ValueError(f"datagram over {MAX_DGRAM} B (Q-N11)")
        n, ct = self.session.encrypt(bytes([typ]) + body)
        self.ep.send(path, struct.pack("!BI", T_DATA, self.remote_idx) + n.to_bytes(8, "little") + ct)
        return True

    def learn_addr(self, addr):
        """Peer-reflexive candidate (ICE-style): the source address of a PUNCH. Needed behind
        address-dependent NATs (QEMU slirp is one) where the STUN-mapped port only answers the
        STUN server. Unauthenticated, so capped; it only ever receives handshake/ping retries."""
        if self.ep.force_relay or addr in self.cands:
            return
        self.prflx = [a for a in getattr(self, "prflx", []) if a != addr][-(MAX_PRFLX - 1):] + [addr]
        self.cands = [a for a in self.cands if a in self._signalled] + self.prflx
        self.note(f"learned peer-reflexive candidate {fmt_addr(*addr)}")

    def punch(self):
        for a in self.cands:
            self.ep.send(("udp", a), bytes([T_PUNCH]) + secrets.token_bytes(8))

    def rx_data(self, path, n: int, ct: bytes):
        pt = self.session.decrypt(n, ct)
        prev = self.best_path()
        self.last_rx_path = path
        if path[0] == "udp":
            if self.direct_addr != path[1] or time.monotonic() - self.last_direct_rx >= DIRECT_STALE:
                self.direct_addr = path[1]
            self.last_direct_rx = time.monotonic()
        else:
            if self.derp_key is None:
                self.derp_key = path[1]
            # Follow the peer (responder): authenticated DATA over DERP means the initiator is not using direct
            # (e.g. its UDP receive is dead while its sends still reach us): stop preferring direct until it
            # sends direct again.
            if self.follow_peer:
                self.last_direct_rx = 0.0
        now = self.best_path()
        if prev != now and now is not None:
            self.note(f"path -> {path_str(now)}")
        if not pt:
            return
        typ, body = pt[0], pt[1:]
        if typ == D_PING:
            self.send_data(D_PONG, body, path=path)
        elif typ == D_ECHO_REQ:
            self.send_data(D_ECHO_REP, body, path=path)  # answer on the arrival path, like PONG
        if self.on_data:
            self.on_data(typ, body, path)


class Responder:
    """Stick side. records: slot(bytes) -> dict(priv, peer_pub, psk, home, name)."""

    def __init__(self, ep: Endpoint, static_priv: bytes, log=print):
        self.ep, self.s, self.log = ep, static_priv, log
        self.s_pub = crypto.x25519_public(static_priv)
        self.slots: dict[bytes, dict] = {}
        self.peers: dict[bytes, Peer] = {}       # slot -> Peer
        self.by_idx: dict[int, Peer] = {}
        self._resp_cache: dict[bytes, bytes] = {}  # slot -> (msg1 digest || resp)
        self.revoked_keys: set[bytes] = set()    # peer static keys: never accept msg1 from these again
        self.revoked_slots: set[bytes] = set()
        ep.handler = self.on_packet

    def add_slot(self, slot: bytes, rec: dict):
        self.slots[slot] = rec
        if slot not in self.peers:
            self.peers[slot] = Peer(self.ep, rec["name"], self.log, follow_peer=True)

    def drop_session(self, slot: bytes):
        peer = self.peers.get(slot)
        if peer is None:
            return
        self.by_idx.pop(peer.local_idx, None)
        self._resp_cache.pop(slot, None)
        peer.reset()

    def apply_revocation(self, slot: bytes) -> bool:
        """Revoked peer: kill its active session now (Noise keys, replay window, paths, candidates, cached
        RESP: same as a bye) and refuse any later msg1 for its slot or static key. Relay connections are left
        alone (the server denies new relay admission). Returns whether the slot was known."""
        rec = self.slots.get(slot)
        if rec is not None:
            self.revoked_keys.add(rec["peer_pub"])
        self.revoked_slots.add(slot)
        self.drop_session(slot)
        self.slots.pop(slot, None)
        peer = self.peers.pop(slot, None)
        if peer is not None:
            peer.note("REVOKED: active session terminated, state dropped")
        return rec is not None

    def on_packet(self, path, pkt: bytes):
        if not pkt or len(pkt) > MAX_DGRAM:
            return  # Q-N11: <= 1280 B per datagram
        t = pkt[0]
        if t == T_INIT and len(pkt) == 1 + 8 + 4 + 96:
            self._on_init(path, pkt)
        elif t == T_DATA and len(pkt) >= 1 + 4 + 8 + 16:
            idx = struct.unpack("!I", pkt[1:5])[0]
            p = self.by_idx.get(idx)
            if p and p.session:
                p.rx_data(path, int.from_bytes(pkt[5:13], "little"), pkt[13:])

    def _on_init(self, path, pkt):
        slot, sidx, msg1 = pkt[1:9], struct.unpack("!I", pkt[9:13])[0], pkt[13:]
        if slot in self.revoked_slots:
            self.log(f"msg1 for revoked slot {fp(slot)} refused")
            return
        rec = self.slots.get(slot)
        if rec is None:
            return
        peer = self.peers[slot]
        cached = self._resp_cache.get(slot)
        if cached and hmac.compare_digest(cached[0], msg1):
            self.ep.send(path, cached[1])  # same handshake seen on another path: same answer
            peer.note(f"handshake retry answered via {path_str(path)}")
            if path[0] == "udp":
                peer.direct_addr, peer.last_direct_rx = path[1], time.monotonic()
            return
        r = noise.Responder(self.s, noise.prologue(rec["home"], slot, rec["peer_pub"], self.s_pub))
        rs, _ = r.read_msg1(msg1)
        if rs in self.revoked_keys:
            self.log(f"[{rec['name']}] msg1 from revoked key {fp(rs)} refused")
            return
        if not hmac.compare_digest(rs, rec["peer_pub"]):
            self.log(f"[{rec['name']}] handshake with an unpinned static key refused")
            return
        sess, msg2 = r.write_msg2(rec["psk"])
        old = peer.local_idx
        self.by_idx.pop(old, None)
        peer.local_idx = secrets.randbits(32)
        peer.remote_idx, peer.session = sidx, sess
        self.by_idx[peer.local_idx] = peer
        # new session: forget the previous session's paths (the peer may have restarted on a new port)
        peer.direct_addr, peer.last_direct_rx, peer._tx_path = None, 0.0, None
        if path[0] == "derp":
            peer.derp_key = path[1]
        resp = struct.pack("!BII", T_RESP, peer.local_idx, sidx) + msg2
        self._resp_cache[slot] = (msg1, resp)
        peer.last_rx_path = path
        if path[0] == "udp":
            peer.direct_addr, peer.last_direct_rx = path[1], time.monotonic()
        self.ep.send(path, resp)
        peer.note(f"handshake ok (Noise IKpsk2, pinned key {fp(rs)}) via {path_str(path)}")


class Initiator:
    """Client side (AI KVM / phone / test peer)."""

    def __init__(self, ep: Endpoint, static_priv: bytes, stick_pub: bytes, psk: bytes, home: bytes, slot: bytes,
                 name="stick", log=print):
        self.ep, self.s, self.rs, self.psk, self.home, self.slot = ep, static_priv, stick_pub, psk, home, slot
        self.peer = Peer(ep, name, log)
        self.log = log
        self._hs = None
        self._msg2 = None
        self._init = None
        self.established = asyncio.Event()
        self.first_path = None
        ep.handler = self.on_packet

    def on_packet(self, path, pkt):
        t = pkt[0]
        p = self.peer
        if t == T_RESP and len(pkt) == 1 + 8 + 48:
            sidx, ridx = struct.unpack("!II", pkt[1:9])
            if ridx != p.local_idx or self._hs is None:
                return
            msg2 = pkt[9:]
            if self._msg2 is not None:
                if hmac.compare_digest(msg2, self._msg2) and path[0] == "udp":
                    p.direct_addr, p.last_direct_rx = path[1], time.monotonic()
                    p.note(f"direct path confirmed by duplicate handshake reply: {path_str(path)}")
                return
            sess, _ = self._hs.read_msg2(msg2)
            self._msg2 = msg2
            p.session, p.remote_idx = sess, sidx
            p.last_rx_path = path
            if path[0] == "udp":
                p.direct_addr, p.last_direct_rx = path[1], time.monotonic()
            self.first_path = path
            p.note(f"handshake ok (Noise IKpsk2) via {path_str(path)}")
            self.established.set()
        elif t == T_PUNCH and len(pkt) == 9 and path[0] == "udp":
            p.learn_addr(path[1])
            if self._hs is not None and not self.established.is_set() and self._init:
                self.ep.send(path, self._init)  # answer the punch with the handshake right away
        elif t == T_DATA and len(pkt) >= 1 + 4 + 8 + 16 and p.session:
            if struct.unpack("!I", pkt[1:5])[0] == p.local_idx:
                p.rx_data(path, int.from_bytes(pkt[5:13], "little"), pkt[13:])

    async def handshake(self, timeout=HS_TIMEOUT) -> bool:
        p = self.peer
        self._hs = noise.Initiator(self.s, self.rs, self.psk,
                                   noise.prologue(self.home, self.slot, crypto.x25519_public(self.s), self.rs))
        p.local_idx = secrets.randbits(32)
        init = struct.pack("!B", T_INIT) + self.slot + struct.pack("!I", p.local_idx) + self._hs.write_msg1()
        self._init = init
        t0 = time.monotonic()
        derp_started = False
        while time.monotonic() - t0 < timeout and not self.established.is_set():
            if not self.ep.force_relay:
                for a in p.cands:
                    self.ep.send(("udp", a), init)
            if time.monotonic() - t0 >= DERP_DELAY and p.derp_key:
                if not derp_started:
                    p.note("no direct reply after 1.5 s; also trying DERP")
                    derp_started = True
                self.ep.send(("derp", p.derp_key), init)
            try:
                await asyncio.wait_for(self.established.wait(), 0.5)
            except asyncio.TimeoutError:
                pass
        return self.established.is_set()

    async def maintain(self):
        """Probe direct while on DERP; keepalive the current path."""
        p = self.peer
        while True:
            await asyncio.sleep(1.0)
            if not p.session:
                continue
            cur = p.best_path()
            if cur and cur[0] == "derp" and not self.ep.force_relay:
                for a in p.cands:
                    p.send_data(D_PING, secrets.token_bytes(8), path=("udp", a))
            p.send_data(D_PING, secrets.token_bytes(8))
