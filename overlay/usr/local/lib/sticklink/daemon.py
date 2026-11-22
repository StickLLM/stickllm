"""sticklinkd: the stick-side connector (E2E connectivity milestone).

  sticklinkd init        --root R --registry-key-file K --dev D --home H [--auth-seed-file S]  (TEST ONLY)
                         generates the Ed25519 server-auth seed (OS RNG) unless --auth-seed-file
                         imports a TEST seed; prints only the public key `ak` for provision.mjs --ak
  sticklinkd auth-pub    --root R --registry-key-file K      print ak (b64u) for provisioning
  sticklinkd pair-offer  --root R --registry-key-file K --out offer.json                      (TEST ONLY)
  sticklinkd pair-accept --root R --registry-key-file K --in answer.json                      (TEST ONLY)
  sticklinkd list        --root R --registry-key-file K
  sticklinkd run         --root R --registry-key-file K [--config sticklinkd.json] [--ws URL]
                         [--derp URL] [--derp-ca FILE] [--rg tor1] [--stun HOST:PORT] [--udp-port N]
                         [--extra-cand IP:PORT] [--force-relay]

run: hello as `server` on ?dev=, reconcile slots (slot.list -> slot.add), relay.reg
the DERP node key, then for each peer `join` send sealed cand+derp boxes, take
the peer's, punch, and answer Noise IKpsk2 handshakes from pinned keys only.
Logs carry no keys, PSKs, MACs or credentials (8-hex fingerprints only).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import signal
import sys
import time
from pathlib import Path

from . import crypto, e2einterop, link, pairfile, registry, revocation, sigcrypto as sc
from .derp import nodekey_str, parse_nodekey
from .sigclient import SigClient, SigError
from .util import b64u, unb64u

DEFAULT_ROOT = "/mnt/stickllm-settings/sticklink"
# Lab/QEMU DEFAULTS (explicit --ws/--derp/--stack still override). Shipping sticks
# load /etc/sticklink/sticklinkd.json when present (prod link + relay-tor1 + pinned kid).
DEFAULTS = {"ws": "ws://10.0.2.2:8787/v1/ws", "derp": "http://10.0.2.2:3340/derp", "rg": "tor1",
            "stun": "10.0.2.2:3478", "derp_ca": None, "derp_pin": None, "derp_sni": None, "udp_port": 0,
            "revoked_file": None, "sign_keys": None}
DEFAULT_CONFIG_PATH = "/etc/sticklink/sticklinkd.json"
RELAY_TTL_REFRESH = 43200 // 3


def _default_config_path() -> str | None:
    p = Path(DEFAULT_CONFIG_PATH)
    return str(p) if p.is_file() else None



def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} sticklinkd: {msg}", flush=True)


def _registry_key(path: str) -> bytes:
    if os.environ.get("STICKLINK_TESTING") != "1":
        raise SystemExit("--registry-key-file is a test shim until combined unlock lands; set STICKLINK_TESTING=1 (VM only)")
    st = os.stat(path)
    if st.st_mode & 0o077:
        raise SystemExit("registry key file must be 0600")
    k = Path(path).read_bytes()
    if len(k) != 32:
        raise SystemExit("registry key file must hold 32 raw bytes")
    return k


def _read_seed(path: str) -> bytes:
    raw = Path(path).read_bytes()
    if len(raw) == 32:
        return raw
    t = raw.decode().strip()
    if len(t) == 64:
        return bytes.fromhex(t)
    return unb64u(t, 32)


def open_registry(a) -> registry.Registry:
    return registry.Registry(Path(a.root), _registry_key(a.registry_key_file))


class Stick:
    def __init__(self, reg: registry.Registry, cfg: dict):
        self.reg, self.cfg = reg, cfg
        self.sig = reg.load_signal()
        self.home = unb64u(self.sig["home"], 16)
        self.dev = unb64u(self.sig["dev"], 16)
        relay = registry.load_aux(reg, "relay")
        if relay is None:
            relay = {"priv": b64u(crypto.x25519_generate()), "exp": 0}
            registry.save_aux(reg, "relay", relay)
        self.relay = relay
        self.ep = link.Endpoint(udp_port=cfg["udp_port"], derp_url=cfg["derp"], derp_priv=unb64u(relay["priv"], 32),
                                derp_cafile=cfg["derp_ca"], derp_pin=cfg["derp_pin"], derp_sni=cfg["derp_sni"], stun_addr=cfg["stun"], force_relay=cfg["force_relay"],
                                extra_cands=cfg.get("extra_cand") or [], log=log)
        self.resp = link.Responder(self.ep, reg.static_priv(), log=log)
        self.revoked = revocation.RevokedStore(reg)
        self.resp.revoked_keys |= self.revoked.keys
        self._rev_mtime = None
        self.conns: dict[str, bytes] = {}  # conn -> slot
        self.envk: dict[bytes, bytes] = {}
        self.cl: SigClient | None = None
        self._sign_pins = None

    def load_records(self):
        for r in self.reg.list_records():
            slot = unb64u(r["slot"], 8)
            psk = unb64u(r["pair_psk"], 32)
            if unb64u(r["home"], 16) != self.home:
                continue
            if unb64u(r["peer_pub"], 32) in self.revoked:
                log(f"[{r['name']}] key is revoked: record not loaded")
                continue
            self.resp.add_slot(slot, {"name": r["name"], "peer_pub": unb64u(r["peer_pub"], 32), "psk": psk,
                                      "home": self.home, "jk": sc.join_key(psk), "adm": r["adm"]})
            self.envk[slot] = sc.env_key(psk)
            self.resp.peers[slot].on_data = self._on_data(slot)

    # -- revocation -----------------------------------------------------------------------------
    def revoke(self, set_obj, source: str, tell_server: bool = True):
        self._tell_server = tell_server
        try:
            entries = revocation.parse_set(set_obj, self.home)
        except (revocation.RevocationError, ValueError) as e:
            log(f"revoked set from {source} ignored: {e}")
            return
        res = self.revoked.apply(entries, self.home, on_revoke=self._on_revoked)
        log(f"revoked set from {source}: revoked {res['revoked'] or 'none'}, {res['ignored']} entries match no local peer")

    def _on_revoked(self, slot: bytes, rec: dict):
        self.resp.apply_revocation(slot)  # active session killed now; later msg1 refused
        self.envk.pop(slot, None)
        for c in [c for c, s in self.conns.items() if s == slot]:
            self.conns.pop(c, None)
        log(f"[{rec['name']}] REVOKED: record deleted, session terminated (key {link.fp(unb64u(rec['peer_pub'], 32))})")
        if self.cl is not None and getattr(self, "_tell_server", True):
            asyncio.get_running_loop().create_task(self._slot_del(slot, rec["name"]))

    async def on_rev(self, m):
        """API §5 push {"t":"rev","rc","slot","why"}: act at once (kill the session, refuse msg1 for the
        slot and its key, drop the record), then pull revoked.get so the signed page is the durable record."""
        if "set" in m:  # older mock shape
            self.revoke(m, f"server event rc={m.get('rc')}", tell_server=False)
        elif m.get("slot"):
            self.revoke({"set": [{"slot": m["slot"]}]}, f"server rev rc={m.get('rc')} why={m.get('why')}", tell_server=False)
        await self.pull_revoked()

    def _pins(self) -> dict:
        if self._sign_pins is None:
            pins = revocation.parse_pins(self.cfg.get("sign_keys") or [])
            if not pins and os.environ.get("STICKLINK_TESTING") == "1":
                pins = self._fetch_keys_testonly()
            self._sign_pins = pins
        return self._sign_pins

    def _fetch_keys_testonly(self) -> dict:
        # TEST ONLY: firmware pins the key (API §2). Dev stacks: trust GET /v1/keys on first use.
        import urllib.request
        u = self.cfg["ws"].replace("wss://", "https://", 1).replace("ws://", "http://", 1).split("/v1/")[0] + "/v1/keys"
        try:
            with urllib.request.urlopen(u, timeout=5) as r:
                ks = json.loads(r.read())["keys"]
            log(f"TEST: signing keys fetched from {u} (not pinned): {[k['kid'] for k in ks]}")
            return {k["kid"]: unb64u(k["pub"], 32) for k in ks if k.get("alg") == "Ed25519"}
        except Exception as e:
            log(f"TEST: /v1/keys fetch failed: {type(e).__name__}")
            return {}

    async def pull_revoked(self):
        """revoked.get paging from the persisted cursor. A verified page advances the cursor; an unverified
        one is still applied (remove-only, can only take access away) but does not advance it."""
        cur = registry.load_aux(self.reg, "revcursor") or {"after": 0, "rc": 0}
        after = cur["after"]
        for _ in range(64):
            try:
                m = await self.cl.request({"t": "revoked.get", "after": after})
            except SigError as e:
                log(f"revoked.get failed: {e.code}")
                return
            try:
                body = revocation.verify_page(m, self._pins(), self.home, self.cl.nonce)
                ok = True
            except (revocation.RevocationError, ValueError) as e:
                log(f"revoked page not verified ({e}); applying remove-only, cursor kept")
                try:
                    body = json.loads(unb64u(m.get("body", "")))
                except ValueError:
                    return
                ok = False
            if body.get("s"):
                self.revoke({"s": body["s"]}, f"revoked.get rc={body.get('rc')}", tell_server=False)
            if not ok:
                return
            after = int(body.get("next", after))
            registry.save_aux(self.reg, "revcursor", {"after": after, "rc": body.get("rc", cur["rc"])})
            if not body.get("more"):
                log(f"revoked set in sync (rc {body.get('rc')}, cursor {after})")
                return

    async def rotate_auth(self):
        """API §3.1 auth.rotate: new seed, PoP by the new key; on ok, persist the new seed."""
        old_seed = self.reg.auth_seed()
        new_seed = os.urandom(32)
        old_ak = crypto.ed25519_public(old_seed)
        pop = sc.rotate_pop(new_seed, self.cl.nonce, self.dev, old_ak)
        r = await self.cl.request({"t": "auth.rotate", "ak": b64u(crypto.ed25519_public(new_seed)), "pop": b64u(pop)})
        self.reg.save_auth_seed(new_seed)
        log(f"auth key rotated (gen {r.get('gen')})")
        return r

    async def _slot_del(self, slot: bytes, name: str):
        try:
            await self.cl.request({"t": "slot.del", "slot": b64u(slot)})
            log(f"[{name}] slot.del ok")
        except (SigError, OSError, ConnectionError, asyncio.TimeoutError, AttributeError) as e:
            log(f"[{name}] slot.del failed: {getattr(e, 'code', type(e).__name__)} (server side stays authoritative)")

    def poll_revocations(self):
        for obj in revocation.take_spool(self.reg):
            self.revoke(obj, "local CLI")
        f = self.cfg.get("revoked_file")
        if f:
            try:
                mt = os.stat(f).st_mtime_ns
            except FileNotFoundError:
                return
            if mt != self._rev_mtime:
                self._rev_mtime = mt
                try:
                    obj = json.loads(Path(f).read_text())
                except (OSError, ValueError) as e:
                    log(f"revoked-set file unreadable: {type(e).__name__}")
                    return
                self.revoke(obj, "local file")

    async def _watch_revocations(self):
        while True:
            await asyncio.sleep(0.5)
            try:
                self.poll_revocations()
            except Exception as e:
                log(f"revocation poll failed: {type(e).__name__}: {str(e)[:80]}")

    def _on_data(self, slot):
        def f(typ, body, path):
            if typ == link.D_APP:
                log(f"[{self.resp.slots[slot]['name']}] app data {len(body)} B via {link.path_str(path)}")
        return f

    async def session(self):
        cl = self.cl = SigClient(self.cfg["ws"], log=log)
        await cl.connect({"dev": self.sig["dev"]})
        sig = sc.hello_sig(self.reg.auth_seed(), cl.nonce, self.dev, sc.ROLE_SERVER, self.home)
        ready = await cl.request({"t": "hello", "dev": self.sig["dev"], "role": "server", "home": self.sig["home"],
                                  "sig": b64u(sig)})
        log(f"signalling ready (home {self.sig['home'][:6]}…, relays {[r.get('rg') for r in ready.get('relays', [])]})")
        await self.pull_revoked()  # before slot.add, so a slot revoked while we were away is not re-added
        await self.reconcile_slots()
        await self.relay_reg()
        self.ep.start_derp()  # only after relay.reg: the relay's admission is fail-closed
        while True:
            m = await cl.events.get()
            t = m.get("t")
            if t == "_closed":
                raise ConnectionError(f"signalling closed ({m.get('code')})")
            try:
                if t == "peer":
                    await self.on_peer(m)
                elif t == "sig":
                    await self.on_sig(m)
                elif t == "rev":
                    await self.on_rev(m)
                elif t == "err":
                    log(f"signalling err {m.get('code')}")
            except Exception as e:
                log(f"event {t} failed: {type(e).__name__}: {str(e)[:80]}")

    async def reconcile_slots(self):
        try:
            have = {s["slot"] for s in (await self.cl.request({"t": "slot.list"})).get("s", [])}
        except SigError as e:
            log(f"slot.list failed: {e.code}")
            have = set()
        for slot, rec in list(self.resp.slots.items()):
            if b64u(slot) in have:
                continue
            try:
                await self.cl.request({"t": "slot.add", "slot": b64u(slot), "jk": b64u(rec["jk"]), "adm": rec["adm"]})
                log(f"slot.add ok for {rec['name']}")
            except SigError as e:
                if e.code == "auth":  # API §5: a slot id in the revoked set -> treat as revoked, drop, no retry
                    self.revoke({"set": [{"slot": b64u(slot)}]}, "slot.add err{auth}", tell_server=False)
                else:
                    log(f"slot.add for {rec['name']} failed: {e.code}")

    async def relay_reg(self):
        if not self.cfg["derp"]:
            return
        if self.relay.get("exp", 0) - time.time() > 2 * RELAY_TTL_REFRESH:
            log("relay permit still fresh; not re-registering")
            return
        try:
            r = await self.cl.request({"t": "relay.reg", "nk": nodekey_str(self.ep.derp_pub), "rg": self.cfg["rg"]})
            self.relay["exp"] = int(r.get("exp", 0))
            registry.save_aux(self.reg, "relay", self.relay)
            log(f"relay.reg ok, node key {link.fp(self.ep.derp_pub)}")
        except SigError as e:
            log(f"relay.reg failed: {e.code} (DERP fallback may be refused by the relay)")

    async def on_peer(self, m):
        conn, slot = m.get("conn"), unb64u(m.get("slot", ""), 8)
        if slot not in self.resp.slots:
            return
        name = self.resp.slots[slot]["name"]
        if m.get("state") == "leave":
            self.conns.pop(conn, None)
            log(f"[{name}] left signalling ({conn})")
            return
        self.conns[conn] = slot
        log(f"[{name}] joined signalling ({conn}); sending candidates")
        await self.send_offer(conn, slot)

    async def send_offer(self, conn, slot):
        sid = b64u(secrets.token_bytes(8))
        cands = await self.ep.candidates(probe_host=self.cfg["stun"].rsplit(":", 1)[0] if self.cfg["stun"] else None)
        for inner in ({"k": "cand", "sid": sid, "seq": 1, "c": cands},
                      {"k": "derp", "sid": sid, "nk": nodekey_str(self.ep.derp_pub), "rg": self.cfg["rg"]}):
            if inner["k"] == "derp" and not self.cfg["derp"]:
                continue
            box = sc.seal_box(self.envk[slot], self.home, slot, sc.DIR_S2C, inner)
            await self.cl.send({"t": "sig", "to": conn, "box": box})
        log(f"[{self.resp.slots[slot]['name']}] sent {len(cands)} candidates"
            f"{' (force-relay: none)' if self.cfg['force_relay'] else ''} + derp key")

    async def on_sig(self, m):
        conn = m.get("from")
        slot = self.conns.get(conn)
        if slot is None:
            return
        inner = sc.open_box(self.envk[slot], self.home, slot, sc.DIR_C2S, m.get("box", ""))
        peer = self.resp.peers[slot]
        sid = inner.get("sid")
        if inner["k"] == "bye":
            # API.md §4.1: a bye for the peer's CURRENT sid ends that session; an old sid is ignored.
            # (peer leave drops nothing; moving to DERP does not end a session.)
            if sid is not None and sid == peer.sig_sid:
                self.resp.drop_session(slot)
                peer.note("peer said bye: session state dropped")
            else:
                peer.note("bye for an old sid ignored")
            return
        if sid is not None and sid != peer.sig_sid:
            peer.sig_sid = sid
        if inner["k"] == "cand":
            peer.set_cands(inner.get("c") or [])
            if not self.cfg["force_relay"]:
                for _ in range(3):
                    if peer.sig_sid != sid:
                        break  # a bye (or a newer session) cancelled these punches
                    peer.punch()
                    await asyncio.sleep(0.2)
        elif inner["k"] == "derp":
            peer.derp_key = parse_nodekey(inner["nk"])
            peer.note(f"peer derp key {link.fp(peer.derp_key)}")

    async def run(self):
        self.poll_revocations()  # before serving: apply any queued/local revocations first
        asyncio.get_running_loop().create_task(self._watch_revocations())
        await self.ep.start(connect_derp=False)
        log(f"udp :{self.ep.udp_port}{' FORCE-RELAY (direct UDP disabled)' if self.cfg['force_relay'] else ''}")
        backoff = 1
        while True:
            try:
                await self.session()
            except (OSError, ConnectionError, SigError, asyncio.TimeoutError, Exception) as e:
                log(f"signalling session ended: {type(e).__name__}: {str(e)[:80]}")
            finally:
                if self.cl:
                    await self.cl.close()
            await asyncio.sleep(backoff + secrets.randbelow(1000) / 1000)
            backoff = min(backoff * 2, 60)


def _cfg(a) -> dict:
    cfg = dict(DEFAULTS)
    if getattr(a, "stack", None):
        cfg.update(e2einterop.load_stack(a.stack))
    if a.config:
        cfg.update({k: v for k, v in json.loads(Path(a.config).read_text()).items() if k in DEFAULTS})
    for k in DEFAULTS:
        v = getattr(a, k, None)
        if v is not None:
            cfg[k] = v
    cfg["force_relay"] = bool(a.force_relay)
    cfg["extra_cand"] = a.extra_cand
    if cfg["derp"] in ("", "none"):
        cfg["derp"] = None
    return cfg


def main(argv=None):
    ap = argparse.ArgumentParser(prog="sticklinkd")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--root", default=DEFAULT_ROOT)
        p.add_argument("--registry-key-file", required=True)
        return p
    p = common(sub.add_parser("init"))
    p.add_argument("--dev", required=True)
    p.add_argument("--home", required=True)
    p.add_argument("--auth-seed-file", help="TEST ONLY: import this Ed25519 seed (b64u, hex or 32 raw B) instead of generating one")
    common(sub.add_parser("auth-pub", help="print the device auth public key (ak) for provision.mjs --ak"))
    common(sub.add_parser("pair-offer")).add_argument("--out", required=True)
    common(sub.add_parser("pair-accept")).add_argument("--in", dest="inp", required=True)
    common(sub.add_parser("list"))
    p = common(sub.add_parser("import-e2e", help="TEST-ONLY: become the Sticklink e2e fixture stick"))
    p.add_argument("--pairing", required=True)
    p.add_argument("--identity", required=True)
    p = common(sub.add_parser("import-usb", help="TEST-ONLY: add an AI KVM sl1-host-sim USB pairing record"))
    p.add_argument("--record", required=True)
    p.add_argument("--name")
    p = common(sub.add_parser("export-e2e", help="TEST-ONLY: write a pairing as sl1-e2e-pairing/1"))
    p.add_argument("--slot", required=True)
    p.add_argument("--out", required=True)
    p = common(sub.add_parser("run"))
    p.add_argument("--config", default=_default_config_path(),
                   help=f"JSON config (default: {DEFAULT_CONFIG_PATH} if present; lab/QEMU omit and pass --ws/--derp)")
    p.add_argument("--stack", help="Sticklink e2e stack.json (ws, derp url + pin, stun, rg); flags still override")
    p.add_argument("--ws")
    p.add_argument("--derp")
    p.add_argument("--derp-ca", dest="derp_ca")
    p.add_argument("--derp-sni", dest="derp_sni", help="TLS server name when the relay URL is an IP")
    p.add_argument("--derp-pin", dest="derp_pin", help="SHA-256 of the relay's self-signed cert (dev relay)")
    p.add_argument("--rg")
    p.add_argument("--stun")
    p.add_argument("--udp-port", dest="udp_port", type=int)
    p.add_argument("--extra-cand", action="append", default=[])
    p.add_argument("--force-relay", action="store_true", help="test mode: never use direct UDP; DERP only")
    p.add_argument("--revoked-file", dest="revoked_file", help="revoked-peer set file, re-applied whenever it changes")
    p.add_argument("--sign-key", dest="sign_keys", action="append", help="pinned server signing key kid=pub_b64u (repeatable)")
    p = common(sub.add_parser("revoke", help="revoke one local peer (name, slot or peer key); the daemon applies it at once"))
    p.add_argument("--peer", required=True)
    a = ap.parse_args(argv)
    os.umask(0o077)

    if a.cmd == "import-e2e":
        reg = open_registry(a)
        rec = e2einterop.import_stick(reg, a.pairing, a.identity)
        print(json.dumps({"imported": rec["name"], "slot": rec["slot"], "peer_key_fp": link.fp(unb64u(rec["peer_pub"]))}))
        return
    if a.cmd == "revoke":
        print(json.dumps(revocation.spool_revoke(open_registry(a), a.peer)))
        return
    if a.cmd == "import-usb":
        reg = open_registry(a)
        rec = e2einterop.import_usb_record(reg, a.record, a.name)
        print(json.dumps({"imported": rec["name"], "slot": rec["slot"], "peer_key_fp": link.fp(unb64u(rec["peer_pub"]))}))
        return
    if a.cmd == "export-e2e":
        reg = open_registry(a)
        pairfile.dump(e2einterop.export_pairing(reg, a.slot), a.out)
        print(json.dumps({"pairing": a.out}))
        return
    if a.cmd == "init":
        reg = open_registry(a)
        seed = None
        if a.auth_seed_file:
            if os.environ.get("STICKLINK_TESTING") != "1":
                raise SystemExit("--auth-seed-file imports a fixture seed: test-only")
            seed = _read_seed(a.auth_seed_file)
        reg.init_dirs()
        pub = reg.create_identity()
        reg.save_signal(a.dev, a.home)
        ak = reg.save_auth_seed(seed)
        print(json.dumps({"stick_pub_fp": link.fp(pub), "ak": b64u(ak)}))
    elif a.cmd == "auth-pub":
        print(json.dumps({"ak": b64u(open_registry(a).auth_pub())}))
    elif a.cmd == "pair-offer":
        reg = open_registry(a)
        off = pairfile.make_offer(reg)
        pairfile.dump(off, a.out)
        print(json.dumps({"offer": a.out, "slot": off["slot"]}))
    elif a.cmd == "pair-accept":
        reg = open_registry(a)
        rec = pairfile.accept_answer(reg, json.loads(Path(a.inp).read_text()))
        print(json.dumps({"paired": rec["name"], "slot": rec["slot"], "peer_key_fp": link.fp(unb64u(rec["peer_pub"]))}))
    elif a.cmd == "list":
        reg = open_registry(a)
        for r in reg.list_records():
            print(json.dumps({"name": r["name"], "kind": r["kind"], "slot": r["slot"],
                              "peer_key_fp": link.fp(unb64u(r["peer_pub"]))}))
    elif a.cmd == "run":
        reg = open_registry(a)
        reg.init_dirs()
        st = Stick(reg, _cfg(a))
        st.load_records()
        log(f"{len(st.resp.slots)} paired peer(s) loaded")
        loop = asyncio.new_event_loop()
        task = loop.create_task(st.run())
        for s in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(s, task.cancel)
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            log("stopped")
        finally:
            rest = [t for t in asyncio.all_tasks(loop) if not t.done()]
            for t in rest:  # e.g. _watch_revocations, pending slot.del: cancel cleanly on shutdown
                t.cancel()
            if rest:
                loop.run_until_complete(asyncio.gather(*rest, return_exceptions=True))
            loop.run_until_complete(st.ep.close())
            loop.close()


if __name__ == "__main__":
    main()
