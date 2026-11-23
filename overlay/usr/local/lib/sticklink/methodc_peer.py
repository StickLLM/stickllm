"""Stick-resident Method C peer (Milestone A).

Phone wire protocol unchanged (methodc-lte-accept-20261108.1 / APP-MUX-V1).
Upstream Agent Zero is **loopback only** — never a lab-PC address.

Development authorization (`stickllm-sticklink-lab-grant`) is used only when
METHODC_DEV_AUTH=1. It is not production trusted-device approval (Milestone B).
"""
from __future__ import annotations

import asyncio
import hashlib
import http.cookiejar
import json
import os
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("STICKLINK_TESTING", "1")
os.environ.setdefault("STICKLINK_LAB", "1")
os.environ.setdefault("STICKLINK_FAST_KDF", "1")

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sticklink import crypto, noise, pair_qr
from sticklink.app_mux_bridge import AppMuxBridge
from sticklink.util import b64u, unb64u

RUN = Path(os.environ.get("STICKLLM_RUN", "/run/stickllm"))
ROOT = Path(os.environ.get("STICKLINK_ROOT", "/var/lib/sticklink"))
WS_URL = os.environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")
# Optional public join host (Worker/Pages). Empty → peer stays up and waits.
JOIN_PUBLIC_BASE = os.environ.get("SL_JOIN_PUBLIC_BASE", "").rstrip("/")
DEV_AUTH = os.environ.get("METHODC_DEV_AUTH", "0") == "1"
SESSION_RETRY_SEC = int(os.environ.get("METHODC_RETRY_SEC", "5"))
# Remint-only: cap sess.revoke / resume.clear waits before minting a new join.
# Idle Always-On keepalive never calls durable_sess_close on this path.
REMINT_SESS_CLOSE_TIMEOUT = float(os.environ.get("METHODC_REMINT_CLOSE_TIMEOUT", "2.5"))
# Mailbox / on-screen QR lifetime request (server clamps to MBX_EXP_S, now 600s).
# Long enough to open the phone and scan; Refresh mints a new one. Live phone
# sessions must NOT die when this TTL hits (server keeps mjoin; peer ignores pair.closed).
PAIR_OPEN_EXP_SEC = int(os.environ.get("METHODC_PAIR_EXP_SEC", "600"))
# Silent reconnect mailbox (server clamps to MBX_RESUME_EXP_S). No QR is on
# screen, so this is purely how long a waking phone has to find the offer; the
# peer re-mints when it lapses (resume opens skip the pair.open rate lock).
RESUME_OPEN_EXP_SEC = int(os.environ.get("METHODC_RESUME_EXP_SEC", "600"))
METHODC_TRANSPORT = os.environ.get("METHODC_TRANSPORT", "wss").strip().lower()
# DERP fallback for slice 2 — opaque sess.frame over relay-tor1 when WSS unavailable.
SESS_VER = 0x01
SESS_REPLY_MAX = int(os.environ.get("METHODC_SESS_QUEUE_MAX", "256"))
STICKLLM_LIB = Path(os.environ.get("STICKLLM_LIB", "/var/lib/stickllm"))
PAIRING_META_PATH = ROOT / "methodc-pairing.json"
# Resume token in /run alone is lost on peer restart → phone reconnects forever
# while the stick shows a fresh kiosk QR. Keep a durable copy beside pairing.
DURABLE_RESUME_TOKEN_PATH = ROOT / "sticklink-resume.token"
# The phone pins this static at pairing, so it must live or die with the pairing
# metadata beside it. Keeping it under /var/lib/stickllm meant the two could get
# out of step: the peer silently minted a new static, every later wake failed
# Noise msg1 as "decrypt failed", and the phone retried forever.
STICK_NOISE_PATH = Path(
    os.environ.get("METHODC_SESS_STATIC_KEY", str(ROOT / "sticklink-sess-static.key"))
)
LEGACY_STICK_NOISE_PATHS = (
    STICKLLM_LIB / "sticklink-sess-static.key",
    ROOT / "methodc-noise-static.json",
)
# ROOT and STICKLLM_LIB both sit on the live image's RAM overlay, so the pinned
# static and the pairing it belongs to only survive while the stick stays up: a
# reboot (or anything that clears the overlay) silently downgraded an Always-On
# pairing into "scan a new QR". Mirror the durable pairing onto the USB data
# partition and read it back when the overlay copy is gone.
PERSIST_ROOT = Path(
    os.environ.get("METHODC_PERSIST_ROOT", "/mnt/stickllm-data/sticklink")
)


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} methodc-peer: {msg}", flush=True)


def token_hint(token: str) -> str:
    """Short token label for logs (never print full resume secrets)."""
    t = (token or "").strip()
    if len(t) <= 8:
        return "…"
    return f"…{t[-6:]}"


async def sleep_interruptible(seconds: float, *, check_remint: bool = True) -> bool:
    """Sleep up to `seconds`. Return True if remint.req appeared (abort early)."""
    deadline = time.time() + max(0.0, float(seconds))
    while time.time() < deadline:
        if check_remint and remint_requested():
            return True
        await asyncio.sleep(min(1.0, max(0.05, deadline - time.time())))
    return bool(check_remint and remint_requested())


def resolve_a0_https() -> str:
    """Force Agent Zero upstream to loopback. Lab-PC / LAN hosts are refused."""
    raw = (os.environ.get("SL_A0_HTTPS") or "https://127.0.0.1").strip().rstrip("/")
    u = urlparse(raw)
    host = (u.hostname or "").lower()
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError(
            f"refusing non-local Agent Zero upstream {raw!r}; "
            "Method C peer may only reach loopback A0"
        )
    if u.scheme not in ("https", "http"):
        raise RuntimeError(f"bad SL_A0_HTTPS scheme: {raw!r}")
    # Normalize to https://127.0.0.1 (gateway TLS on stick).
    return "https://127.0.0.1"


A0_HTTPS = "https://127.0.0.1"  # set in main after resolve


def enc(x: bytes) -> bytes:
    import struct

    return struct.pack(">H", len(x)) + x


def seal_env(env_k: bytes, mbx: bytes, direction: int, pt: bytes) -> bytes:
    ad = enc(mbx) + mbx + bytes([direction])
    nonce, ct = crypto.seal(env_k, pt, ad)
    return nonce + ct


def open_env(env_k: bytes, mbx: bytes, direction: int, blob: bytes) -> bytes:
    ad = enc(mbx) + mbx + bytes([direction])
    return crypto.open_(env_k, blob[:12], blob[12:], ad)


def qr_prologue(home: bytes, mbx: bytes, stick_pub: bytes) -> bytes:
    return b"sl1/qr" + bytes([1]) + home + mbx + stick_pub


def _frame(n: int, ct: bytes) -> bytes:
    return n.to_bytes(8, "little") + ct


def sess_token_id(token: str) -> bytes:
    return hashlib.sha256(token.strip().encode("utf-8")).digest()[:8]


def sess_resume_psk(token: str, pair_psk: bytes) -> bytes:
    """Resume PSK v2: leaked token alone is insufficient without pair_psk."""
    if len(pair_psk) != 32:
        raise ValueError("pair_psk must be 32 bytes")
    ikm = pair_psk + token.strip().encode("utf-8")
    return crypto.hkdf(ikm, b"sl1/sess-psk/v2")


def sess_resume_prologue(home: bytes, token: str, phone_pub: bytes, stick_pub: bytes) -> bytes:
    tid = sess_token_id(token)
    return b"sl1/sess" + bytes([SESS_VER]) + home + tid + phone_pub + stick_pub


def persist_available() -> bool:
    """True when the USB data partition is mounted and writable."""
    try:
        return PERSIST_ROOT.parent.is_dir() and os.access(PERSIST_ROOT.parent, os.W_OK)
    except Exception:
        return False


def persist_mirror(path: Path) -> None:
    """Best-effort copy of a durable pairing file onto the data partition."""
    if not path.is_file() or not persist_available():
        return
    try:
        PERSIST_ROOT.mkdir(parents=True, exist_ok=True)
        PERSIST_ROOT.chmod(0o700)
        dst = PERSIST_ROOT / path.name
        tmp = dst.with_name(dst.name + ".tmp")
        tmp.write_bytes(path.read_bytes())
        tmp.chmod(0o600)
        os.replace(tmp, dst)
    except Exception as e:
        log(f"persist mirror {path.name} failed (keeping overlay copy): {e}")


def persist_restore(path: Path) -> bool:
    """Bring a durable pairing file back after the overlay lost it."""
    if path.is_file() or not persist_available():
        return False
    src = PERSIST_ROOT / path.name
    try:
        if not src.is_file():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(src.read_bytes())
        path.chmod(0o600)
        log(f"restored {path.name} from USB data partition")
        return True
    except Exception as e:
        log(f"persist restore {path.name} failed: {e}")
        return False


def persist_drop(path: Path) -> None:
    """Forget a mirrored file — only on a real unpair, never on a read error."""
    if not persist_available():
        return
    try:
        (PERSIST_ROOT / path.name).unlink(missing_ok=True)
    except Exception:
        pass


def _read_stick_noise_file(path: Path) -> tuple[bytes, bytes] | None:
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        priv = unb64u(str(doc["priv"]), 32)
        pub = crypto.x25519_public(priv)
        if unb64u(str(doc.get("pub", "")), 32) != pub:
            raise ValueError("pub mismatch")
        return priv, pub
    except Exception:
        return None


def _write_stick_noise(priv: bytes, pub: bytes) -> None:
    STICK_NOISE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STICK_NOISE_PATH.write_text(
        json.dumps({"priv": b64u(priv), "pub": b64u(pub)}), encoding="utf-8"
    )
    STICK_NOISE_PATH.chmod(0o600)
    persist_mirror(STICK_NOISE_PATH)


def load_or_create_stick_noise() -> tuple[bytes, bytes]:
    """Durable X25519 static for Method C / always-on sess (pinned across wake resume)."""
    # The overlay copy can be gone while the pairing it belongs to is still
    # valid (reboot, or the legacy path being unlinked under a live session).
    # Restoring beats minting: minting is what forces a new QR.
    persist_restore(STICK_NOISE_PATH)
    persist_restore(PAIRING_META_PATH)
    persist_restore(DURABLE_RESUME_TOKEN_PATH)
    for path in (STICK_NOISE_PATH, *LEGACY_STICK_NOISE_PATHS):
        loaded = _read_stick_noise_file(path)
        if loaded:
            priv, pub = loaded
            # Always re-mirror to the canonical path so a blip that unlinks the
            # live file cannot strand a still-valid Always-On pairing.
            _write_stick_noise(priv, pub)
            if path != STICK_NOISE_PATH:
                log(f"migrating stick sess static from {path}")
            return priv, pub
    # Minting here invalidates any pinned pairing: the phone's Noise msg1 is
    # sealed to the old static and can never be read again. Drop the pairing so
    # the kiosk asks for a new QR instead of offering a resume that cannot work.
    if PAIRING_META_PATH.is_file():
        log("stick sess static lost — pinned pairing is unusable; clearing for re-pair")
        clear_durable_pairing()
        clear_resume_token()
    priv = crypto.x25519_generate()
    pub = crypto.x25519_public(priv)
    _write_stick_noise(priv, pub)
    return priv, pub


def ensure_stick_noise_on_disk(priv: bytes, pub: bytes) -> None:
    """Re-write the live sess static if it vanished mid-session (Never lose Always-On)."""
    loaded = _read_stick_noise_file(STICK_NOISE_PATH)
    if loaded and loaded[1] == pub:
        return
    log("stick sess static missing/mismatched on disk — rewriting from live session")
    _write_stick_noise(priv, pub)


def save_pairing_meta(*, phone_pub: bytes, stick_pub: bytes, pair_psk: bytes) -> None:
    if len(pair_psk) != 32:
        raise ValueError("pair_psk must be 32 bytes")
    ROOT.mkdir(parents=True, exist_ok=True)
    PAIRING_META_PATH.write_text(
        json.dumps(
            {
                "phone_pub": b64u(phone_pub),
                "stick_pub": b64u(stick_pub),
                "pair_psk": b64u(pair_psk),
            }
        ),
        encoding="utf-8",
    )
    PAIRING_META_PATH.chmod(0o600)
    persist_mirror(PAIRING_META_PATH)
    # Noise must already be on disk (ensure_stick_noise_on_disk); mirror USB copy.
    persist_mirror(STICK_NOISE_PATH)


def load_phone_pub() -> bytes:
    try:
        doc = json.loads(PAIRING_META_PATH.read_text(encoding="utf-8"))
        return unb64u(str(doc["phone_pub"]), 32)
    except Exception:
        return b""


def load_pinned_stick_pub() -> bytes:
    """Stick static the phone pinned at pairing — must still match our own."""
    try:
        doc = json.loads(PAIRING_META_PATH.read_text(encoding="utf-8"))
        return unb64u(str(doc["stick_pub"]), 32)
    except Exception:
        return b""


def load_pair_psk() -> bytes:
    try:
        doc = json.loads(PAIRING_META_PATH.read_text(encoding="utf-8"))
        return unb64u(str(doc["pair_psk"]), 32)
    except Exception:
        return b""


def clear_pairing_pins() -> None:
    """Drop phone pairing pins + resume only. Keep stick Noise static on disk.

    Generate/remint must not delete the sess static that the upcoming QR will
    advertise: load_or_create runs *before* wait_for_mint_needed, and wiping the
    key there left Always-On with an in-memory pub and an empty disk/USB — peer
    restart then minted a new static and the phone showed session ended.
    """
    try:
        PAIRING_META_PATH.unlink(missing_ok=True)
    except TypeError:
        if PAIRING_META_PATH.is_file():
            PAIRING_META_PATH.unlink()
    persist_drop(PAIRING_META_PATH)


def clear_durable_pairing() -> None:
    """Full unpair: phone pins + stick sess key (factory / static-lost only)."""
    clear_pairing_pins()
    for p in (STICK_NOISE_PATH, *LEGACY_STICK_NOISE_PATHS):
        try:
            p.unlink(missing_ok=True)
        except TypeError:
            if p.is_file():
                p.unlink()
        persist_drop(p)


class ReplyQueue:
    """Stick→phone outbound frames indexed by stick_seq (Noise encrypt counter n)."""

    def __init__(self, max_items: int = SESS_REPLY_MAX):
        self._max = max(16, max_items)
        self._frames: dict[int, bytes] = {}

    def remember(self, n: int, frame: bytes) -> None:
        self._frames[n] = frame
        while len(self._frames) > self._max:
            self._frames.pop(min(self._frames))

    def resend_after(self, n: int) -> list[tuple[int, bytes]]:
        return sorted((k, v) for k, v in self._frames.items() if k > n)


def sess_resume_join_url() -> str:
    return (
        f"{JOIN_PUBLIC_BASE}/browser/agent_join.html"
        f"?mode=sess&ws={urllib.parse.quote(WS_URL, safe='')}"
    )


async def try_sess_open(
    sw: "StickWS",
    *,
    token: str,
    stick_pub: bytes,
    phone_pub: bytes | None,
    join: str | None = None,
    sid: str | None = None,
    rotate_from: str | None = None,
) -> bool:
    body: dict = {
        "t": "sess.open",
        "id": 14,
        "token": token,
        "stick_pub": b64u(stick_pub),
    }
    if phone_pub and len(phone_pub) == 32:
        body["phone_pub"] = b64u(phone_pub)
    if join:
        body["join"] = join
    if sid:
        body["sid"] = sid
    if rotate_from:
        body["rotate_from"] = rotate_from
    try:
        await sw.req(body, "sess.ok")
        log(f"sess.open ok token={token_hint(token)}")
        return True
    except RuntimeError as e:
        log(f"sess.open unavailable ({e}); slice1 peer ready for Worker deploy")
        return False
    except Exception as e:
        log(f"sess.open failed ({e})")
        return False


async def put_durable_resume(sw: "StickWS", *, token: str, join: str) -> bool:
    try:
        await sw.req(
            {
                "t": "resume.put",
                "id": 16,
                "token": token,
                "join": join,
                "durable": True,
            },
            "ok",
        )
        log(f"resume.put durable ok token={token_hint(token)}")
        return True
    except Exception as e:
        log(f"resume.put durable failed ({e})")
        return False


async def durable_sess_close(
    sw: "StickWS", token: str, *, timeout: float | None = None
) -> None:
    """Best-effort sess.revoke + resume.clear before a remint mint.

    StickWS.req can hang indefinitely when live sess.frame traffic never leaves
    a quiet gap for the matching reply id. Cap the wait (~2–3s) so Generate can
    proceed; do not use this path for Always-On idle stay-alive.
    """
    budget = REMINT_SESS_CLOSE_TIMEOUT if timeout is None else float(timeout)
    budget = max(0.1, budget)
    want_ids = {15, 13}
    for obj in (
        {"t": "sess.revoke", "id": 15, "token": token},
        {"t": "resume.clear", "id": 13, "token": token},
    ):
        try:
            await sw.ws.send(json.dumps(obj))
        except Exception as e:
            log(f"durable_sess_close send {obj.get('t')}: {e}")
    deadline = time.time() + budget
    seen: set[int] = set()
    while time.time() < deadline and len(seen) < len(want_ids):
        try:
            m = await sw.next(timeout=min(0.25, max(0.05, deadline - time.time())))
        except asyncio.TimeoutError:
            continue
        except Exception as e:
            log(f"durable_sess_close wait: {e}")
            break
        mid = m.get("id")
        if isinstance(mid, int) and mid in want_ids:
            seen.add(mid)
    if len(seen) < len(want_ids):
        log(
            f"durable_sess_close: partial/no ack in {budget:.1f}s "
            f"(got {sorted(seen) or 'none'}) — continuing remint"
        )


async def noise_sess_responder_on_wss(
    sw: "StickWS",
    raw,
    *,
    stick_priv: bytes,
    stick_pub: bytes,
    phone_pub: bytes,
    tokens: list[str],
    pair_psk: bytes,
    home: bytes,
    phone_conn: str,
    timeout: float = 120.0,
) -> tuple[noise.Session, bytes, str]:
    """Answer a waking phone's Noise msg1 on sess.frame.

    The token is baked into the prologue, so a stale copy fails as an opaque
    ``decrypt failed``. The phone's presented ``rt`` and our stored token can
    drift apart (rotation races), so try each.
    """
    cands = [t.strip() for t in tokens if t and t.strip()]
    cands = list(dict.fromkeys(cands))
    if not cands:
        raise RuntimeError("sess resume: no candidate token")
    deadline = time.time() + timeout
    noted = False
    while time.time() < deadline:
        if remint_requested():
            raise RuntimeError("kiosk remint requested")
        try:
            m = await sw.next(timeout=min(1.0, max(0.1, deadline - time.time())))
        except asyncio.TimeoutError:
            continue
        if m.get("t") in ("peer", "sess.peer") and m.get("state") == "join":
            # The phone gave up and rejoined under a new conn; frames for the old
            # one are dead. Hand the join back so the next pass uses it at once.
            sw._stash_join(m)
            raise RuntimeError("sess resume: phone rejoined — restarting handshake")
        if m.get("t") != "sess.frame":
            continue
        frm_conn = m.get("from") or m.get("conn")
        if phone_conn and frm_conn and frm_conn != phone_conn:
            continue
        try:
            wire = unb64u(m["body"])
        except Exception:
            continue
        if len(wire) < 96:
            continue
        for tok in cands:
            prologue = sess_resume_prologue(home, tok, phone_pub, stick_pub)
            resp = noise.Responder(stick_priv, prologue)
            try:
                # msg1 is exactly 96 B; the phone may append its first mux frame.
                rs, _ = resp.read_msg1(wire[:96])
            except Exception as e:
                log(f"sess resume: msg1 rejected for token={token_hint(tok)} ({e})")
                continue
            if rs != phone_pub:
                raise RuntimeError("sess resume: phone static mismatch")
            sess, msg2 = resp.write_msg2(sess_resume_psk(tok, pair_psk))
            await raw.send(
                json.dumps({"t": "sess.frame", "to": phone_conn, "body": b64u(msg2)})
            )
            log(f"sess noise resume ok token={token_hint(tok)}")
            return sess, wire[96:], tok
        if not noted:
            # A phone that thinks its old session is still live replays app-mux
            # ciphertext here. Keep waiting for a real msg1 rather than tearing
            # the session down on the first frame we cannot read.
            noted = True
            log(
                f"sess resume: frame len={len(wire)} nonce0={int.from_bytes(wire[:8], 'little')} "
                f"is not msg1 for {len(cands)} candidate token(s) — still waiting"
            )
    raise TimeoutError("sess.frame: no Noise msg1 from phone")


def load_identity() -> tuple[dict, bytes]:
    ids_path = ROOT / "device.ids.json"
    seed_path = ROOT / "device-auth-seed"
    if not ids_path.is_file():
        cand = list(ROOT.glob("*.ids.json"))
        if not cand:
            raise FileNotFoundError(f"no device ids under {ROOT}")
        ids_path = cand[0]
    if not seed_path.is_file():
        raise FileNotFoundError(f"missing {seed_path}")
    ids = json.loads(ids_path.read_text(encoding="utf-8"))
    seed = unb64u(seed_path.read_text(encoding="utf-8").strip(), 32)
    return ids, seed


# Boot-scoped Bearer (tmpfs /run). Survives Method C remints / new QRs; cleared on reboot.
BOOT_BEARER = RUN / "sticklink-methodc-bearer"


def _bearer_alive(token: str) -> bool:
    """True if gateway still accepts this StickLink lab Bearer."""
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        f"{A0_HTTPS}/api/pair/status",
        headers={
            "Authorization": f"Bearer {token}",
            "X-StickLLM-Client": "ui",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            if r.status != 200:
                return False
            doc = json.loads(r.read().decode())
        # Loopback status may set require_pair false; accept any 200 with ok/paired.
        return bool(doc.get("ok", True)) or bool(doc.get("paired")) or "require_pair" in doc
    except Exception:
        return False


def mint_dev_token(*, force: bool = False) -> str:
    """Isolated development grant only — not production authorization.

    Reuse one Bearer for the whole stick boot so a live phone session is not
    invalidated when the kiosk remints a QR or the peer starts another mailbox.
    """
    if not DEV_AUTH:
        raise RuntimeError(
            "METHODC_DEV_AUTH=1 required for temporary lab grant "
            "(Milestone A development testing only; not production auth)"
        )
    RUN.mkdir(parents=True, exist_ok=True)
    if not force and BOOT_BEARER.is_file():
        try:
            existing = BOOT_BEARER.read_text(encoding="utf-8").strip()
        except Exception:
            existing = ""
        if len(existing) >= 32 and _bearer_alive(existing):
            log(f"reusing boot Bearer …{existing[-6:]}")
            return existing

    env = os.environ.copy()
    env["METHODC_DEV_AUTH"] = "1"
    grant_bin = "/usr/local/bin/stickllm-sticklink-lab-grant"
    # Peer unit runs as root; avoid depending on sudoers for the DEV grant helper.
    cmd = [grant_bin] if os.geteuid() == 0 else ["sudo", "-n", grant_bin]
    out = subprocess.check_output(cmd, text=True, timeout=30, env=env)
    grant = ""
    for line in out.splitlines():
        s = line.strip()
        if len(s) >= 32 and " " not in s and not s.startswith("{"):
            grant = s
            break
    if not grant:
        raise RuntimeError("dev grant mint failed: " + out[-400:])
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(
        f"{A0_HTTPS}/api/pair/sticklink-lab",
        data=json.dumps({"grant": grant}).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-StickLLM-Client": "ui",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, context=ctx, timeout=30) as r:
        doc = json.loads(r.read().decode())
    if not doc.get("ok") or not doc.get("token"):
        raise RuntimeError(f"sticklink-lab redeem failed: {doc}")
    token = str(doc["token"])
    try:
        BOOT_BEARER.write_text(token + "\n", encoding="utf-8")
        BOOT_BEARER.chmod(0o600)
    except Exception as e:
        log(f"warn: could not persist boot Bearer: {e}")
    return token


class LocalA0Bridge:
    def __init__(self, token: str, origin: str):
        self.token = token
        self.ctx = ssl._create_unverified_context()
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=self.ctx),
            urllib.request.HTTPCookieProcessor(self.jar),
        )
        self.origin = origin
        self.referer = self.origin + "/agent-zero/"

    def cookie_header(self) -> str:
        return "; ".join(f"{c.name}={c.value}" for c in self.jar)

    def request(self, method: str, path: str, headers: dict | None = None, body: bytes | None = None) -> dict:
        # Defense in depth: never leave loopback.
        if urlparse(self.origin).hostname not in ("127.0.0.1", "localhost", "::1"):
            raise RuntimeError("A0 bridge origin escaped loopback")
        url = self.origin + path
        hdrs = {
            "Authorization": f"Bearer {self.token}",
            "X-StickLLM-Client": "ui",
            # Gateway treats Method C as remote for open_app / screen targeting
            # even though the peer TCP source is loopback.
            "X-StickLLM-Via": "sticklink",
            "Accept": "*/*",
            "User-Agent": "StickLink-methodc-peer",
            "Origin": self.origin,
            "Referer": self.referer,
        }
        if headers:
            for k, v in headers.items():
                lk = k.lower()
                if lk in (
                    "authorization",
                    "host",
                    "connection",
                    "content-length",
                    "cookie",
                    "origin",
                    "referer",
                ) or lk.startswith("sec-"):
                    continue
                hdrs[k] = v
        cookie = self.cookie_header()
        if cookie:
            hdrs["Cookie"] = cookie
        req = urllib.request.Request(url, data=body, method=method.upper(), headers=hdrs)
        try:
            # Downloads (PDF/Doc from A0 work dir) need a longer read timeout.
            timeout = 300 if "download_work_dir_file" in path else 60
            with self.opener.open(req, timeout=timeout) as r:
                raw, status, resp_headers = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            raw, status, resp_headers = e.read(), e.code, e.headers
        out_headers = {k.lower(): v for k, v in resp_headers.items()}
        return {"status": status, "headers": out_headers, "body_b64": b64u(raw), "cookies": self.cookie_header()}


def publish_remint_status(status: str, **extra) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    doc = {"status": status, "at": time.time(), **extra}
    (RUN / "sticklink-join-remint.json").write_text(json.dumps(doc), encoding="utf-8")


def clear_remint_req() -> None:
    remint_req = RUN / "sticklink-join-remint.req"
    try:
        remint_req.unlink(missing_ok=True)
    except TypeError:
        if remint_req.is_file():
            remint_req.unlink()


def publish_join(qr: str, join_url: str, mbx_b: str, home: str, exp_abs: int) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    doc = {
        "qr": qr,
        "url": join_url,
        "mbx": mbx_b,
        "home": home,
        "exp": exp_abs,
        "at": time.time(),
        "via": "methodc-peer",
        "dev_auth": DEV_AUTH,
        "connected": False,
    }
    (RUN / "sticklink-join.json").write_text(json.dumps(doc), encoding="utf-8")
    (RUN / "sticklink-join-url.txt").write_text(join_url + "\n", encoding="utf-8")
    # Ack kiosk Refresh / remint so Devices & Pairing stops spinning.
    publish_remint_status("done", url=join_url, exp=exp_abs)
    clear_remint_req()
    log(f"published join → {RUN / 'sticklink-join.json'}")


def publish_joining(*, conn: str = "") -> None:
    """Hide the kiosk QR after mailbox join without claiming connected.

    Clears the scannable join URL so a second phone cannot reuse the same QR
    while handshake is in progress. UI stays non-connected until DataChannel
    opens (see publish_connected) — avoids stick=connected / phone=Reconnecting.
    """
    RUN.mkdir(parents=True, exist_ok=True)
    doc = {
        "connected": False,
        "joining": True,
        "url": "",
        "qr": "",
        "at": time.time(),
        "via": "methodc-peer",
        "dev_auth": DEV_AUTH,
        "conn": conn or None,
        "reason": "handshake",
    }
    (RUN / "sticklink-join.json").write_text(json.dumps(doc), encoding="utf-8")
    try:
        (RUN / "sticklink-join-url.txt").unlink(missing_ok=True)
    except TypeError:
        p = RUN / "sticklink-join-url.txt"
        if p.is_file():
            p.unlink()
    publish_remint_status(
        "joining",
        message="Phone joining — finishing secure link…",
        conn=conn or None,
    )
    log("published joining — kiosk QR cleared; connected deferred until DC")


def publish_connected(*, conn: str = "") -> None:
    """Mark phone live once DataChannel (or sess) proves the link."""
    RUN.mkdir(parents=True, exist_ok=True)
    doc = {
        "connected": True,
        "url": "",
        "qr": "",
        "at": time.time(),
        "via": "methodc-peer",
        "dev_auth": DEV_AUTH,
        "conn": conn or None,
    }
    (RUN / "sticklink-join.json").write_text(json.dumps(doc), encoding="utf-8")
    try:
        (RUN / "sticklink-join-url.txt").unlink(missing_ok=True)
    except TypeError:
        p = RUN / "sticklink-join-url.txt"
        if p.is_file():
            p.unlink()
    publish_remint_status(
        "connected",
        message="Phone connected — QR hidden. Generate a new code after it disconnects.",
        conn=conn or None,
    )
    clear_remint_req()
    log("published connected — kiosk QR cleared")


def remint_requested() -> bool:
    return (RUN / "sticklink-join-remint.req").is_file()


def read_join_doc() -> dict:
    try:
        doc = json.loads((RUN / "sticklink-join.json").read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def current_join_exp() -> int:
    try:
        return int(read_join_doc().get("exp") or 0)
    except Exception:
        return 0


def publish_idle(*, reason: str = "disconnected") -> None:
    """Clear QR and require Generate before the next pair.open."""
    RUN.mkdir(parents=True, exist_ok=True)
    doc = {
        "connected": False,
        "awaiting_remint": True,
        "url": "",
        "qr": "",
        "at": time.time(),
        "via": "methodc-peer",
        "reason": reason,
    }
    (RUN / "sticklink-join.json").write_text(json.dumps(doc), encoding="utf-8")
    try:
        (RUN / "sticklink-join-url.txt").unlink(missing_ok=True)
    except TypeError:
        p = RUN / "sticklink-join-url.txt"
        if p.is_file():
            p.unlink()
    publish_remint_status(
        "idle",
        message="Tap Generate for a new StickLink QR.",
        reason=reason,
    )
    log(f"published idle reason={reason} — waiting for Generate")


def publish_reconnecting(*, reason: str = "transport-lost") -> None:
    """Phone dropped; stick will silent-mint resume offers (no new QR on kiosk)."""
    RUN.mkdir(parents=True, exist_ok=True)
    doc = {
        "connected": False,
        "reconnecting": True,
        "awaiting_remint": False,
        "url": "",
        "qr": "",
        "at": time.time(),
        "via": "methodc-peer",
        "reason": reason,
    }
    (RUN / "sticklink-join.json").write_text(json.dumps(doc), encoding="utf-8")
    publish_remint_status(
        "reconnecting",
        message="Phone reconnecting — leave the StickLink tab open. Generate only to force a new QR.",
        reason=reason,
    )
    log(f"published reconnecting reason={reason}")


def resume_token_path() -> Path:
    return RUN / "sticklink-resume.token"


def _read_resume_token_file(path: Path) -> str:
    try:
        t = path.read_text(encoding="utf-8").strip()
        return t if len(t) >= 16 else ""
    except Exception:
        return ""


def is_paired() -> bool:
    return len(load_phone_pub()) == 32 and len(load_pair_psk()) == 32


def ensure_resume_token_if_paired() -> bool:
    """After peer restart, reissue resume token when pairing survived overlay."""
    if load_resume_token():
        return True
    if not is_paired():
        return False
    tok = b64u(crypto.random_key()[:16])
    save_resume_token(tok)
    log(f"reissued resume token for persisted pairing token={token_hint(tok)}")
    return True


def load_resume_token() -> str:
    persist_restore(DURABLE_RESUME_TOKEN_PATH)
    for path in (resume_token_path(), DURABLE_RESUME_TOKEN_PATH):
        t = _read_resume_token_file(path)
        if t:
            if path != resume_token_path() and not resume_token_path().is_file():
                RUN.mkdir(parents=True, exist_ok=True)
                resume_token_path().write_text(t + "\n", encoding="utf-8")
            return t
    return ""


def save_resume_token(token: str) -> None:
    tok = token.strip()
    if len(tok) < 16:
        return
    line = tok + "\n"
    RUN.mkdir(parents=True, exist_ok=True)
    resume_token_path().write_text(line, encoding="utf-8")
    ROOT.mkdir(parents=True, exist_ok=True)
    DURABLE_RESUME_TOKEN_PATH.write_text(line, encoding="utf-8")
    DURABLE_RESUME_TOKEN_PATH.chmod(0o600)
    persist_mirror(DURABLE_RESUME_TOKEN_PATH)


def clear_resume_token() -> None:
    for p in (resume_token_path(), DURABLE_RESUME_TOKEN_PATH):
        try:
            p.unlink(missing_ok=True)
        except TypeError:
            if p.is_file():
                p.unlink()
    persist_drop(DURABLE_RESUME_TOKEN_PATH)


def user_disconnect_requested() -> bool:
    return (RUN / "sticklink-user-disconnect.req").is_file()


def clear_user_disconnect() -> None:
    p = RUN / "sticklink-user-disconnect.req"
    try:
        p.unlink(missing_ok=True)
    except TypeError:
        if p.is_file():
            p.unlink()


async def wait_for_mint_needed(sw=None) -> str:
    """Block until a new pair.open is warranted.

    Returns mint mode: \"kiosk\" (show QR) or \"resume\" (silent reconnect offer).

    Cold boot (no join.json) → kiosk mint once.
    Paired resume token + reconnecting/idle transport loss → silent resume.
    Explicit Generate (remint.req) → kiosk mint (clears prior resume).
    Valid unscanned kiosk QR → wait out TTL, then wait for Generate.
    """
    while True:
        # This can idle for hours holding the signalling socket; if that socket
        # died the Worker no longer sees the stick, so re-dial instead of
        # waiting on a corpse.
        if sw is not None and sw.dead():
            raise ConnectionError("signalling WSS closed while waiting to mint")
        if remint_requested():
            # Keep stick Noise static — only forget the previous phone pins.
            clear_pairing_pins()
            clear_resume_token()
            clear_user_disconnect()
            publish_remint_status(
                "minting",
                message="Creating join key…",
            )
            log("mint needed: remint.req (kiosk)")
            return "kiosk"
        if user_disconnect_requested():
            clear_pairing_pins()
            clear_resume_token()
            clear_user_disconnect()
            publish_idle(reason="user-disconnect")
            log("user disconnect — waiting for Generate")
            while not remint_requested():
                await asyncio.sleep(1.0)
            clear_remint_req()
            return "kiosk"
        ensure_resume_token_if_paired()
        path = RUN / "sticklink-join.json"
        if not path.is_file():
            if load_resume_token():
                publish_reconnecting(reason="peer-restart")
                log("mint needed: resume after peer restart (pairing kept)")
                return "resume"
            log("mint needed: no join published (kiosk)")
            return "kiosk"
        doc = read_join_doc()
        # connected:true is only valid inside run_one_session. Seeing it here means
        # peer restarted (or died) while kiosk still showed "phone connected" —
        # clear the lie and Prefer Always-On resume over spinning forever.
        if doc.get("connected"):
            if load_resume_token():
                publish_reconnecting(reason="stale-connected")
                log("stale connected UI after session end — resume mode")
                return "resume"
            publish_idle(reason="stale-connected")
            log("stale connected UI, no resume token — waiting for Generate")
            while not remint_requested():
                await asyncio.sleep(1.0)
            return "kiosk"
        # Transport lost but phone still paired → silent resume (no Generate).
        if load_resume_token() and (doc.get("reconnecting") or doc.get("reason") in (
            "session-ended",
            "transport-lost",
            "user-disconnect",
        )):
            if doc.get("reason") == "user-disconnect":
                await asyncio.sleep(1.0)
                continue
            log("mint needed: resume offer for paired phone")
            return "resume"
        if doc.get("awaiting_remint") and not load_resume_token():
            await asyncio.sleep(1.0)
            continue
        if doc.get("reconnecting") and load_resume_token():
            log("mint needed: resume refresh")
            return "resume"
        url = str(doc.get("url") or doc.get("join") or "").strip()
        exp = 0
        try:
            exp = int(doc.get("exp") or 0)
        except Exception:
            exp = 0
        now = time.time()
        if url and exp > 0 and now < (exp - 1):
            await asyncio.sleep(1.0)
            continue
        if url and exp > 0 and now >= (exp - 1):
            # Expired unscanned kiosk QR — if we have a resume token, keep offering
            # silent reconnect; otherwise wait for Generate.
            if load_resume_token():
                publish_reconnecting(reason="transport-lost")
                log("kiosk QR expired — resume mode")
                return "resume"
            publish_remint_status(
                "expired",
                message="StickLink join expired — tap Refresh StickLink QR to mint a new one.",
                exp=exp,
            )
            log("join expired — waiting for Refresh before pair.open (quota)")
            while not remint_requested():
                await asyncio.sleep(1.0)
            publish_remint_status(
                "minting",
                message="Creating join key…",
            )
            log("mint needed: remint.req after expiry")
            return "kiosk"
        if not url:
            if load_resume_token() and not doc.get("awaiting_remint"):
                publish_reconnecting(reason=str(doc.get("reason") or "transport-lost"))
                return "resume"
            if not doc.get("awaiting_remint"):
                publish_idle(reason="empty-join")
            while not remint_requested():
                if load_resume_token() and not remint_requested():
                    # Should not silent-resume while explicitly awaiting Generate
                    # unless reconnecting was set — stay waiting.
                    pass
                await asyncio.sleep(1.0)
            publish_remint_status(
                "minting",
                message="Creating join key…",
            )
            log("mint needed: remint.req after idle")
            return "kiosk"
        await asyncio.sleep(1.0)


def parse_rate_retry(err: BaseException | dict | str) -> int | None:
    """Extract StickLink pair.open rate-limit retry seconds, if present.

    Accepts exception strings, Worker err dicts, or raw text. Honour
    ``code: rate`` / ``code:rate`` even when ``retry`` is missing (default
    600s) — a parser that only handled HTTP 429 let remint.req during the
    short session backoff hammer ``pair.open`` into a ~10 min home lock.
    """
    import re

    if isinstance(err, dict):
        code = str(err.get("code") or err.get("error") or "").lower()
        t = str(err.get("t") or "").lower()
        blob = json.dumps(err, default=str)
        retry_raw = err.get("retry")
    else:
        blob = str(err)
        code = ""
        t = ""
        retry_raw = None
        m_code = re.search(
            r"['\"]code['\"]\s*:\s*['\"]?(rate)['\"]?", blob, re.I
        )
        if m_code:
            code = "rate"
    if "rate" not in blob.lower() and code != "rate" and t != "rate":
        return None
    if code and code not in ("rate", "rate_limited", "ratelimit") and "rate" not in blob.lower():
        return None
    if retry_raw is not None:
        try:
            return max(1, int(retry_raw))
        except (TypeError, ValueError):
            pass
    m = re.search(r"['\"]retry['\"]\s*:\s*(\d+)", blob)
    if m:
        return max(1, int(m.group(1)))
    # code:rate without retry — still back off hard (do not 5s-hammer).
    if code == "rate" or re.search(r"\bcode\s*[:=]\s*rate\b", blob, re.I):
        return 600
    return None


class RateLimited(RuntimeError):
    def __init__(self, retry: int, detail: str = ""):
        self.retry = retry
        super().__init__(detail or f"pair.open rate-limited retry={retry}s")


def enter_rate_limit_backoff(retry: int, detail: str = "") -> int:
    """Publish rate_limited UI and drop any queued remint.req.

    Scan/join must never look like Generate. A leftover remint.req (kiosk
    Refresh, lab helper, or agent diagnosis) must not fire ``pair.open``
    every few seconds during the lock — that is what extends the home lock.
    After the window, wait for an explicit new Generate.
    """
    retry = max(int(retry), SESSION_RETRY_SEC)
    clear_remint_req()
    publish_remint_status(
        "rate_limited",
        message=(
            detail
            or (
                f"StickLink pairing rate-limited — next try in {retry}s. "
                "Do not spam Refresh."
            )
        ),
        retry=retry,
    )
    return retry


class ResumeOfferExpired(RuntimeError):
    """Silent reconnect mailbox aged out — mint a fresh offer, no Generate."""


async def wait_peer_or_remint(
    sw: "StickWS", exp_abs: int, timeout: float | None = None, resume_mode: bool = False
):
    """Wait for phone join, or abort only on kiosk remint.

    Do **not** auto-remint on mailbox expiry — pair.open is rate-limited
    (5 / 10 min, then 10 min lock per home). Expiry marks the QR stale; the
    Devices & Pairing Refresh button writes remint.req for a deliberate remint.

    No idle/join deadline by default: an unscanned QR stays published until
    Refresh/remint or stick reboot (mailbox may already be server-expired for
    *new* scans — that is separate from this wait loop).
    """
    deadline = (time.time() + timeout) if timeout is not None and timeout > 0 else None
    expired_noted = False
    early = sw.take_join()
    if early is not None:
        log(f"peer joined during mint — using stashed {early.get('t')}")
        return early
    while deadline is None or time.time() < deadline:
        if remint_requested():
            raise RuntimeError("kiosk remint requested")
        if not expired_noted and time.time() >= (exp_abs - 1):
            expired_noted = True
            if resume_mode:
                # Always-On: nothing is on screen to refresh, and resume mints
                # skip the pair.open rate lock. Re-offer so a phone that wakes
                # later still finds a live mailbox behind its resume join URL.
                publish_reconnecting(reason="resume-offer-expired")
                log("resume offer expired — minting a fresh one (rate-limit exempt)")
                raise ResumeOfferExpired("resume offer expired")
            publish_remint_status(
                "expired",
                message="StickLink join expired — tap Refresh StickLink QR to mint a new one.",
                exp=exp_abs,
            )
            log("QR expired — waiting for kiosk remint (not auto-reminting; protects pair.open quota)")
        try:
            m = await sw.next(timeout=1.0)
        except asyncio.TimeoutError:
            if sw.dead():
                raise ConnectionError("signalling WSS closed while awaiting peer join")
            continue
        if m.get("t") in ("peer", "sess.peer") and m.get("state") == "join":
            return m
        if m.get("t") == "err":
            raise RuntimeError(f"err while waiting peer: {m}")
    raise TimeoutError("no peer join before timeout")


def ice_configuration():
    from aiortc import RTCConfiguration, RTCIceServer

    return RTCConfiguration(
        iceServers=[
            RTCIceServer(urls=["stun:stun.l.google.com:19302"]),
            RTCIceServer(urls=["stun:stun.cloudflare.com:3478"]),
            RTCIceServer(urls=["stun:relay-tor1.stickllm.com:3478"]),
        ]
    )


async def ed_hello_sig(seed: bytes, n: bytes, dev: bytes, role: int, home: bytes | None) -> bytes:
    home16 = home if home is not None else b"\x00" * 16
    body = n + dev + bytes([role]) + home16
    msg = b"sl1/dev-hello/v1\x00" + body
    return Ed25519PrivateKey.from_private_bytes(seed).sign(msg)


class StickWS:
    def __init__(self, ws):
        self.ws = ws
        self.q: asyncio.Queue = asyncio.Queue()
        self.closed = asyncio.Event()
        self.close_exc: BaseException | None = None
        self.reader_task: asyncio.Task | None = None
        # A phone that wakes the moment we reconnect joins while we are still in
        # hello / pair.open, whose id-matching loops used to drop the join on the
        # floor — the stick then waited for a peer that had already arrived.
        self.pending_joins: list[dict] = []

    async def reader(self):
        try:
            async for raw in self.ws:
                await self.q.put(json.loads(raw))
        except Exception as e:  # noqa: BLE001 — recorded, surfaced via dead()
            self.close_exc = e
        finally:
            self.closed.set()

    def dead(self) -> bool:
        """True once the signalling socket is gone.

        An Always-On session outlives its DataChannel, so after the phone drops
        nothing else reads this socket: a silent WSS death left the peer waiting
        forever while the Worker had already dropped the stick.
        """
        if self.closed.is_set():
            return True
        if getattr(self.ws, "closed", False):
            return True
        state = getattr(self.ws, "state", None)
        return getattr(state, "name", "") in ("CLOSING", "CLOSED")

    async def next(self, timeout=60.0):
        return await asyncio.wait_for(self.q.get(), timeout)

    def _stash_join(self, m) -> None:
        if isinstance(m, dict) and m.get("state") == "join" and m.get("t") in ("peer", "sess.peer"):
            self.pending_joins.append(m)

    def take_join(self) -> dict | None:
        return self.pending_joins.pop(0) if self.pending_joins else None

    async def expect(self, t: str, timeout=60.0):
        while True:
            m = await self.next(timeout)
            if m.get("t") == t:
                return m
            if m.get("t") == "err":
                raise RuntimeError(f"err while waiting {t}: {m}")
            self._stash_join(m)

    async def req(self, obj, want=None):
        await self.ws.send(json.dumps(obj))
        want_id = obj.get("id")
        while True:
            m = await self.next()
            if want_id is not None and m.get("id") != want_id:
                self._stash_join(m)
                continue
            if isinstance(m, dict) and m.get("t") == "err":
                retry = parse_rate_retry(m)
                if retry is not None:
                    raise RateLimited(retry, f"err {m}")
                raise RuntimeError(f"err while waiting {want or 'response'}: {m}")
            if want and m.get("t") != want:
                retry = parse_rate_retry(m) if isinstance(m, dict) else None
                if retry is not None:
                    raise RateLimited(retry, f"want {want} got {m}")
                raise RuntimeError(f"want {want} got {m}")
            return m


async def run_one_session(a0_https: str) -> None:
    from aiortc import RTCPeerConnection, RTCSessionDescription

    global A0_HTTPS
    A0_HTTPS = a0_https

    if not JOIN_PUBLIC_BASE.startswith("https://"):
        raise RuntimeError(
            "SL_JOIN_PUBLIC_BASE unset — waiting for public https:// join host "
            "(Worker/Pages; not lab PC; CF must not proxy A0)"
        )

    ids, seed = load_identity()
    dev = unb64u(ids["dev"], 16)
    home = unb64u(ids["home"], 16)
    stick_priv, stick_pub = load_or_create_stick_noise()

    # Catch a dead pairing before offering a resume the crypto cannot honour.
    pinned = load_pinned_stick_pub()
    if pinned and pinned != stick_pub:
        log("pinned pairing is for a different stick static — clearing; phone must rescan")
        clear_durable_pairing()
        clear_resume_token()
        publish_idle(reason="stick-static-changed")

    uri = f"{WS_URL}?dev={ids['dev']}"
    # Protocol-level WS pings keep the stick signalling socket alive for the
    # whole live session (no idle expiry on our side).
    async with websockets.connect(
        uri,
        subprotocols=["sticklink.1"],
        open_timeout=30,
        ping_interval=20,
        ping_timeout=60,
        close_timeout=5,
    ) as raw:
        sw = StickWS(raw)
        sw.reader_task = asyncio.create_task(sw.reader())
        welcome = await sw.expect("welcome")
        n = unb64u(welcome["n"], 32)
        sig = await ed_hello_sig(seed, n, dev, 1, home)
        await sw.req(
            {
                "t": "hello",
                "id": 1,
                "dev": ids["dev"],
                "role": "server",
                "home": ids["home"],
                "sig": b64u(sig),
            },
            "ready",
        )
        log("signalling ready")
        mint_mode = await wait_for_mint_needed(sw)
        resume_mint = mint_mode == "resume"
        # Remint used to unlink the sess static after load_or_create; rewrite now
        # so this QR's P= matches disk+USB even if clear_pairing_pins raced.
        ensure_stick_noise_on_disk(stick_priv, stick_pub)

        invite = crypto.random_key()
        jk = pair_qr.jk_qr(invite)
        open_body = {
            "t": "pair.open",
            "id": 11,
            "m": "qr",
            "jk": b64u(jk),
            "exp": max(60, PAIR_OPEN_EXP_SEC if not resume_mint else RESUME_OPEN_EXP_SEC),
        }
        if resume_mint:
            open_body["resume"] = True
        try:
            ok = await sw.req(open_body, "pair.ok")
        except RateLimited:
            raise
        except RuntimeError as e:
            retry = parse_rate_retry(e)
            if retry is not None:
                raise RateLimited(retry, str(e)) from e
            raise
        mbx_b = ok["mbx"]
        mbx = unb64u(mbx_b, 8)
        exp_abs = int(time.time()) + int(ok["exp"])
        qr = pair_qr.encode_qr(
            mailbox_id=mbx, stick_static_pub=stick_pub, invite_secret=invite, exp=exp_abs
        )
        env_k = pair_qr.env_qr(invite, mbx, home)
        th = pair_qr.transcript_hash(mailbox_id=mbx, home_id=home, stick_static_pub=stick_pub)
        boot = pair_qr.boot_psk(invite, th)

        join_url = (
            f"{JOIN_PUBLIC_BASE}/browser/agent_join.html"
            f"?ws={urllib.parse.quote(WS_URL, safe='')}"
            f"&qr={urllib.parse.quote(qr, safe='')}"
        )
        if resume_mint:
            token = load_resume_token()
            if not token:
                token = b64u(crypto.random_key()[:16])
                save_resume_token(token)
            # Short TTL: legacy silent remint before sess.open binds durable always-on.
            try:
                await sw.req(
                    {"t": "resume.put", "id": 12, "token": token, "join": join_url},
                    "ok",
                )
                log(f"resume.put legacy offer token={token_hint(token)}")
            except Exception as e:
                log(f"resume.put failed: {e}")
            publish_reconnecting(reason="resume-offer")
            log(f"resume offer ready exp={exp_abs}")
        else:
            publish_join(qr, join_url, mbx_b, ids["home"], exp_abs)
            log(f"QR ready exp={exp_abs}")

        peer = await wait_peer_or_remint(sw, exp_abs, timeout=None, resume_mode=resume_mint)
        via = str(peer.get("t") or "peer")
        log(
            f"peer join {peer.get('conn')} via={via}"
            + (f" sid={peer.get('sid')}" if peer.get("sid") else "")
            + (" mbx" if peer.get("mbx") else "")
        )
        assert peer.get("state") == "join"
        # A `sess.peer` joiner woke over WSS `?rt=` + sess.resume and will send a
        # Noise msg1 on sess.frame, never a WebRTC `need-offer`. Only the pinned
        # pairing can answer it; without those we have nothing to resume from.
        resume_rt = str(peer.get("rt") or "").strip()
        wss_resume = (
            via == "sess.peer"
            and len(load_phone_pub()) == 32
            and len(load_pair_psk()) == 32
            and bool(resume_rt or load_resume_token())
        )
        if via == "sess.peer" and not wss_resume:
            log("WARNING: durable sess join without pinned pairing — needs a new QR")
        # Kiosk QR: hide immediately on join but do NOT claim connected until DC.
        # Resume offers: stay reconnecting until DataChannel proves the phone is live.
        if resume_mint:
            log("peer join during resume — deferring connected UI")
        else:
            publish_joining(conn=str(peer.get("conn") or ""))

        ice = ice_configuration()
        log(f"ICE servers={len(ice.iceServers or [])}")
        pc = RTCPeerConnection(configuration=ice)
        dc = pc.createDataChannel("sl1", ordered=True)
        dc_q: asyncio.Queue = asyncio.Queue()

        @dc.on("message")
        def _on_dc_msg(message):
            dc_q.put_nowait(bytes(message) if not isinstance(message, bytes) else message)

        _DC_CLOSED = object()
        resume_tail = b""

        if wss_resume:
            # Durable ?rt= wake: the phone is already past pairing, so there is
            # nothing to confirm and no agent_ready to resend. Answer its Noise
            # msg1 on sess.frame and bring the mux straight back up. Negotiating
            # WebRTC here is what deadlocked as "no need-offer from phone".
            phone_pub_pinned = load_phone_pub()
            pair_psk_pinned = load_pair_psk()
            stored_token = load_resume_token()
            sess_sid = str(peer.get("sid") or "")
            durable_join = sess_resume_join_url()
            sess_bound = True
            pinned_stick_pub = load_pinned_stick_pub()
            if pinned_stick_pub and pinned_stick_pub != stick_pub:
                # The phone sealed msg1 to a stick static we no longer hold, so
                # no retry can ever decrypt it. Say so instead of reconnecting
                # forever: drop the dead pairing and ask for a scan.
                log("stick sess static changed since pairing — resume impossible, need new QR")
                clear_durable_pairing()
                clear_resume_token()
                publish_idle(reason="stick-static-changed")
                raise RuntimeError("sess resume: stick static changed — awaiting Generate")
            log(
                f"durable resume: awaiting Noise msg1 rt={token_hint(resume_rt) or 'none'} "
                f"stored={token_hint(stored_token) or 'none'}"
            )
            sess, resume_tail, resume_token = await noise_sess_responder_on_wss(
                sw,
                raw,
                stick_priv=stick_priv,
                stick_pub=stick_pub,
                phone_pub=phone_pub_pinned,
                tokens=[resume_rt, stored_token],
                pair_psk=pair_psk_pinned,
                home=home,
                phone_conn=str(peer.get("conn") or ""),
                timeout=45.0,
            )
            save_resume_token(resume_token)
            token = mint_dev_token()
            bridge = LocalA0Bridge(token, a0_https)

            def _remint_token() -> str:
                t = mint_dev_token(force=True)
                log(f"lab Bearer reminted …{t[-6:]}")
                return t

            def _not_ready(obj: dict) -> None:
                log(f"mux send before transport ready: {obj.get('t')}")

            mux = AppMuxBridge(
                stick_https=a0_https,
                bridge_http=bridge,
                send_pt=_not_ready,
                log=log,
                remint_token=_remint_token,
            )
            publish_connected(conn=str(peer.get("conn") or ""))
            log(f"durable resume live; app-mux → {a0_https} (Bearer …{token[-6:]})")
        else:
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            for _ in range(100):
                if remint_requested():
                    raise RuntimeError("kiosk remint requested")
                if pc.iceGatheringState == "complete":
                    break
                await asyncio.sleep(0.1)

            need_offer_deadline = time.time() + 120
            while True:
                if remint_requested():
                    raise RuntimeError("kiosk remint requested")
                if time.time() >= need_offer_deadline:
                    if load_resume_token():
                        publish_reconnecting(reason="handshake-timeout-need-offer")
                    else:
                        publish_idle(reason="handshake-timeout-need-offer")
                    raise TimeoutError("no need-offer from phone")
                try:
                    m = await sw.next(timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if m.get("t") != "pmsg":
                    continue
                obj = json.loads(open_env(env_k, mbx, 0x01, unb64u(m["body"])))
                if obj.get("k") == "need-offer":
                    body = seal_env(
                        env_k, mbx, 0x02, json.dumps({"k": "offer", "sdp": pc.localDescription.sdp}).encode()
                    )
                    await raw.send(json.dumps({"t": "pmsg", "to": peer["conn"], "body": b64u(body)}))
                    log("sent offer")
                    break

            answer_deadline = time.time() + 120
            while True:
                if remint_requested():
                    raise RuntimeError("kiosk remint requested")
                if time.time() >= answer_deadline:
                    if load_resume_token():
                        publish_reconnecting(reason="handshake-timeout-answer")
                    else:
                        publish_idle(reason="handshake-timeout-answer")
                    raise TimeoutError("no WebRTC answer from phone")
                remaining = max(1.0, answer_deadline - time.time())
                try:
                    m = await sw.next(timeout=min(1.0, remaining))
                except asyncio.TimeoutError:
                    continue
                if m.get("t") != "pmsg":
                    continue
                obj = json.loads(open_env(env_k, mbx, 0x01, unb64u(m["body"])))
                if obj.get("k") == "answer":
                    await pc.setRemoteDescription(RTCSessionDescription(sdp=obj["sdp"], type="answer"))
                    log("set remote answer")
                    break

            dc_deadline = time.time() + 90
            while dc.readyState != "open":
                if time.time() >= dc_deadline:
                    if load_resume_token():
                        publish_reconnecting(reason="handshake-timeout-dc")
                    else:
                        publish_idle(reason="handshake-timeout-dc")
                    raise TimeoutError(f"datachannel not open (state={dc.readyState})")
                await asyncio.sleep(0.05)
            log("datachannel open")
            # Phone proven live — mark connected (also covers deferred resume join).
            publish_connected(conn=str(peer.get("conn") or ""))

            prologue = qr_prologue(home, mbx, stick_pub)
            resp = noise.Responder(stick_priv, prologue)
            msg1 = await asyncio.wait_for(dc_q.get(), timeout=60)
            rs, _ = resp.read_msg1(bytes(msg1))
            sess, msg2 = resp.write_msg2(boot)
            dc.send(bytes(msg2))
            log("noise ok")


            async def dc_recv_pt():
                rawm = await dc_q.get()
                if rawm is _DC_CLOSED:
                    raise ConnectionError("datachannel closed")
                n0 = int.from_bytes(rawm[:8], "little")
                return sess.decrypt(n0, rawm[8:])

            def dc_send_pt(obj):
                n0, ct = sess.encrypt(json.dumps(obj).encode())
                dc.send(_frame(n0, ct))

            ready_obj = json.loads(await dc_recv_pt())
            assert ready_obj.get("t") == "ready"

            r_i_msg = json.loads(await dc_recv_pt())
            assert r_i_msg.get("t") == "r_i"
            r_i = unb64u(r_i_msg["r"], 32)
            r_r = crypto.random_key()
            dc_send_pt({"t": "r_r", "r": b64u(r_r)})
            hh = sess.handshake_hash
            psk = pair_qr.pair_psk(
                r_i=r_i,
                r_r=r_r,
                prior=boot,
                handshake_hash=hh,
                th=th,
                initiator_static=rs,
                responder_static=stick_pub,
                key_epoch=0,
            )
            kc = pair_qr.pair_confirm_kc(psk)
            confirm_i = json.loads(await dc_recv_pt())
            assert confirm_i.get("t") == "confirm_i"
            if not pair_qr.verify_confirm(kc, "i", hh, unb64u(confirm_i["mac"], 32)):
                raise RuntimeError("confirm_i failed")
            dc_send_pt({"t": "confirm_r", "mac": b64u(pair_qr.confirm_mac(kc, "r", hh))})
            log("pair_psk+confirm ok")
            ensure_stick_noise_on_disk(stick_priv, stick_pub)
            save_pairing_meta(phone_pub=rs, stick_pub=stick_pub, pair_psk=psk)
            phone_pub_pinned = rs
            pair_psk_pinned = psk

            token = mint_dev_token()
            bridge = LocalA0Bridge(token, a0_https)
            log(f"agent bridge ready (loopback; Bearer …{token[-6:]})")

            def _remint_token() -> str:
                t = mint_dev_token(force=True)
                log(f"lab Bearer reminted …{t[-6:]}")
                return t

            mux = AppMuxBridge(
                stick_https=a0_https,
                bridge_http=bridge,
                send_pt=dc_send_pt,
                log=log,
                remint_token=_remint_token,
            )
            resume_token = load_resume_token() or b64u(crypto.random_key()[:16])
            save_resume_token(resume_token)
            sess_sid = ""
            dc_send_pt(
                {
                    "t": "agent_ready",
                    "via": "sticklink-lab",
                    "resume": {
                        "token": resume_token,
                        "origin": JOIN_PUBLIC_BASE.rstrip("/"),
                        "ws": WS_URL,
                        "pair_psk": b64u(pair_psk_pinned),
                        "home": b64u(home),
                        "stick_pub": b64u(stick_pub),
                        "phone_pub": b64u(phone_pub_pinned),
                    },
                }
            )
            log("agent_ready; app-mux → https://127.0.0.1 only")

            durable_join = sess_resume_join_url()
            sess_bound = await try_sess_open(
                sw,
                token=resume_token,
                stick_pub=stick_pub,
                phone_pub=phone_pub_pinned,
                join=durable_join,
            )
            if sess_bound:
                await put_durable_resume(sw, token=resume_token, join=durable_join)
        use_wss = wss_resume or (sess_bound and METHODC_TRANSPORT in ("wss", "both"))
        use_webrtc = not wss_resume and (
            METHODC_TRANSPORT in ("webrtc", "both") or not use_wss
        )
        phone_conn = str(peer.get("conn") or "")
        phone_pub = phone_pub_pinned or load_phone_pub()
        pair_psk_live = pair_psk_pinned if len(pair_psk_pinned) == 32 else load_pair_psk()
        noise_trans: noise.Session = sess
        reply_q = ReplyQueue()
        pt_in: asyncio.Queue[bytes] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        phone_live = True
        wss_mux = wss_resume
        resume_presented = resume_token
        last_ping = 0.0
        last_pong = time.time()
        last_rx = time.time()
        last_wss_rx = time.time()
        keepalive_sec = float(os.environ.get("METHODC_DC_KEEPALIVE_SEC", "30"))
        # Hard ceiling: after this with no pong on WSS mux, end session for
        # Always-On resume. Must NOT sess.revoke — pairing + resume token stay.
        keepalive_dead_sec = float(
            os.environ.get(
                "METHODC_KEEPALIVE_DEAD_SEC",
                str(max(180.0, keepalive_sec * 6)),
            )
        )
        bearer_refresh_sec = float(os.environ.get("METHODC_BEARER_REFRESH_SEC", "1800"))
        last_bearer_refresh = time.time()
        force_remint = False
        sess_hs_lock = asyncio.Lock()
        transport_dead = False

        def mark_transport_lost(reason: str) -> None:
            """Clear false-connected kiosk UI; keep Always-On pairing/token."""
            nonlocal phone_live, transport_dead
            if transport_dead:
                return
            transport_dead = True
            phone_live = False
            # Transport blips must never drop the Noise static — phone pins seal to it.
            try:
                ensure_stick_noise_on_disk(stick_priv, stick_pub)
            except Exception as e:
                log(f"ensure stick noise on transport-lost: {e}")
            if load_resume_token():
                publish_reconnecting(reason=reason)
            else:
                publish_idle(reason=reason)
            log(f"transport lost ({reason}) — kiosk cleared; pairing kept for resume")

        def rearm_liveness(why: str) -> None:
            """A phone that just (re)joined gets a fresh liveness window.

            last_pong keeps ageing while the phone is away, so the first
            keepalive tick after a rejoin used to count the whole absence as
            silence, tear the new session down as keepalive-timeout, and send
            the resume path on to clear the pairing.
            """
            nonlocal last_ping, last_pong, last_rx, last_wss_rx, transport_dead
            now = time.time()
            last_ping = now
            last_pong = now
            last_rx = now
            last_wss_rx = now
            if transport_dead:
                log(f"liveness re-armed ({why}) — transport no longer dead")
            transport_dead = False

        async def ingest_transport_wire(wire: bytes) -> None:
            """Decrypt inbound frames. Answer ping/pong immediately so heavy
            http_req/mux work cannot starve the phone's 90s pong watchdog."""
            nonlocal last_rx, last_wss_rx, last_pong
            if len(wire) < 8:
                return
            try:
                n0 = int.from_bytes(wire[:8], "little")
                pt = noise_trans.decrypt(n0, wire[8:])
            except Exception as e:
                log(f"transport decrypt: {e}")
                return
            now = time.time()
            last_rx = now
            last_wss_rx = now
            # Fast path: keepalive must not wait behind Agent Zero page loads.
            try:
                peek = json.loads(pt)
                tpeek = peek.get("t") if isinstance(peek, dict) else None
            except Exception:
                tpeek = None
            if tpeek == "pong":
                last_pong = now
                return
            if tpeek == "ping":
                last_pong = now
                try:
                    send_pt(
                        {"t": "pong", "ts": peek.get("ts"), "id": peek.get("id")}
                    )
                except Exception as e:
                    log(f"ingest keepalive pong failed: {e}")
                return
            await pt_in.put(pt)

        async def send_transport_frame(frame: bytes) -> None:
            n = int.from_bytes(frame[:8], "little")
            reply_q.remember(n, frame)
            # WSS only after wake handshake (wss_mux). First pair stays on DC —
            # do not drop outbound mux when METHODC_TRANSPORT=wss but phone is
            # still on the DataChannel (that froze "Loading Agent Zero…").
            # After sess.peer leave we publish reconnecting and clear phone_live,
            # but Android may keep using the durable WSS mux — still deliver
            # frames so polls/chat do not stall while kiosk says reconnecting.
            try:
                if use_wss and wss_mux and phone_conn and (phone_live or sess_bound):
                    await raw.send(
                        json.dumps(
                            {"t": "sess.frame", "to": phone_conn, "body": b64u(frame)}
                        )
                    )
                elif dc.readyState == "open" and not wss_mux:
                    dc.send(frame)
            except Exception as e:
                # Fire-and-forget keepalive/mux tasks used to die as
                # "Task exception was never retrieved" while kiosk stayed
                # connected:true (zombie WSS after plugin-install load).
                mark_transport_lost("transport-send-failed")
                log(f"transport send failed: {e!r}")
                raise

        def send_pt(obj: dict) -> None:
            n0, ct = noise_trans.encrypt(json.dumps(obj).encode())

            async def _send_and_note() -> None:
                try:
                    await send_transport_frame(_frame(n0, ct))
                except Exception:
                    # mark_transport_lost already ran; main loop exits on flag.
                    pass

            loop.create_task(_send_and_note())

        mux.send_pt = send_pt

        async def rotate_resume_token_after_noise() -> None:
            """Mint fresh token inside Noise; previous accepted ~5 min on Worker."""
            nonlocal resume_token, sess_sid
            if len(pair_psk_live) != 32 or len(phone_pub) != 32:
                return
            old = resume_token
            new = b64u(crypto.random_key()[:16])
            ok = await try_sess_open(
                sw,
                token=new,
                stick_pub=stick_pub,
                phone_pub=phone_pub,
                join=durable_join,
                sid=sess_sid or None,
                rotate_from=old,
            )
            if not ok:
                log("resume token rotate failed; keeping prior")
                return
            resume_token = new
            save_resume_token(new)
            send_pt(
                {
                    "t": "resume_token",
                    "token": new,
                    "exp": int(time.time()) + 24 * 3600,
                }
            )
            log(f"resume token rotated {token_hint(old)}→{token_hint(new)}")

        async def complete_wss_handshake(wire: bytes, conn: str) -> bool:
            nonlocal noise_trans, wss_mux, resume_presented
            if not use_wss or wss_mux or len(phone_pub) != 32:
                return False
            if len(wire) < 96:
                return False
            if len(pair_psk_live) != 32:
                log("sess resume: missing pair_psk")
                return False
            async with sess_hs_lock:
                if wss_mux:
                    return False
                tok = (resume_presented or resume_token or "").strip()
                if not tok:
                    return False
                psk = sess_resume_psk(tok, pair_psk_live)
                prologue = sess_resume_prologue(home, tok, phone_pub, stick_pub)
                resp = noise.Responder(stick_priv, prologue)
                rs, _ = resp.read_msg1(wire[:96])
                if rs != phone_pub:
                    log("sess resume: phone static mismatch")
                    # Hard reject: wrong phone identity for this slot.
                    raise RuntimeError("sess resume: phone static mismatch")
                noise_trans, msg2 = resp.write_msg2(psk)
                await raw.send(
                    json.dumps({"t": "sess.frame", "to": conn, "body": b64u(msg2)})
                )
                wss_mux = True
                mux.send_pt = send_pt
                log("live mux on WSS sess.frame")
                try:
                    await rotate_resume_token_after_noise()
                except Exception as e:
                    log(f"token rotate: {e}")
                return True

        @dc.on("close")
        def _on_dc_close():
            log("datachannel closed by peer/stack")
            try:
                dc_q.put_nowait(_DC_CLOSED)
            except Exception:
                pass

        @pc.on("connectionstatechange")
        def _on_pc_state():
            log(f"webrtc connectionState={pc.connectionState}")

        async def _dc_to_mux() -> None:
            nonlocal phone_live
            while True:
                rawm = await dc_q.get()
                if rawm is _DC_CLOSED:
                    if sess_bound and load_resume_token():
                        phone_live = False
                        publish_reconnecting(reason="transport-lost")
                        log("DC closed — A0 mux kept up; awaiting sess peer")
                        continue
                    raise ConnectionError("datachannel closed")
                if wss_mux:
                    continue
                n0 = int.from_bytes(rawm[:8], "little")
                try:
                    pt = noise_trans.decrypt(n0, rawm[8:])
                except Exception as e:
                    log(f"dc decrypt: {e}")
                    continue
                last_rx = time.time()
                await pt_in.put(pt)

        async def _signalling_mux() -> None:
            nonlocal phone_conn, phone_live, noise_trans, wss_mux, phone_pub, resume_presented
            while True:
                try:
                    m = await sw.next(timeout=1.0)
                except asyncio.TimeoutError:
                    if sw.dead():
                        log("signalling WSS closed — ending session for reconnect")
                        mark_transport_lost("signalling-closed")
                        return
                    continue
                except Exception as e:
                    log(f"signalling ended: {e}")
                    mark_transport_lost("signalling-closed")
                    return
                t = m.get("t")
                if t == "sess.peer":
                    conn = str(m.get("conn") or "")
                    if m.get("state") == "leave":
                        phone_live = False
                        publish_reconnecting(reason="transport-lost")
                        log(f"sess.peer leave conn={conn}")
                        continue
                    if m.get("state") == "join" and conn:
                        phone_conn = conn
                        phone_live = True
                        rearm_liveness(f"sess.peer join {conn}")
                        publish_connected(conn=conn)
                        wss_mux = False
                        presented = str(m.get("rt") or "").strip()
                        if presented:
                            resume_presented = presented
                        log(f"sess.peer join conn={conn} — await Noise msg1")
                    continue
                if t == "sess.have":
                    try:
                        n = int(m.get("n"))
                    except Exception:
                        continue
                    for _, frame in reply_q.resend_after(n):
                        await send_transport_frame(frame)
                    continue
                if t == "sess.frame":
                    try:
                        wire = unb64u(m["body"])
                    except Exception:
                        continue
                    frm = m.get("from") or m.get("conn")
                    if phone_conn and frm and frm != phone_conn:
                        continue
                    conn = phone_conn or str(frm or "")
                    if not wss_mux and use_wss:
                        if await complete_wss_handshake(wire, conn):
                            if len(wire) > 96:
                                await ingest_transport_wire(wire[96:])
                        continue
                    if wss_mux and len(wire) >= 8:
                        if not phone_live:
                            phone_live = True
                            rearm_liveness("inbound sess.frame")
                            publish_connected(conn=phone_conn or conn)
                            log("inbound sess.frame after leave — cleared reconnecting UI")
                        await ingest_transport_wire(wire)
                    continue
                if t == "pair.closed":
                    log(f"signalling pair.closed why={m.get('why')} — keep mux")
                    continue
                if t in ("peer", "sess.peer") and m.get("state") == "leave":
                    if sess_bound and load_resume_token():
                        phone_live = False
                        publish_reconnecting(reason="transport-lost")
                        log(f"peer leave conn={m.get('conn')} — keep A0")
                    continue
                if t == "err":
                    code = str(m.get("code") or "")
                    why = str(m.get("why") or m.get("reason") or "")
                    log(f"signalling err code={code} why={why or 'unspecified'}")
                    # 4001 is the Worker's stick-offline close: transport only,
                    # pairing stays so the phone can resume.
                    if code in ("4001", "stick-offline"):
                        mark_transport_lost("stick-offline")
                        return
                    # A bare 4403 used to be read as "revoked" and wiped the
                    # pairing. The Worker also emits it when the stick↔Worker
                    # socket drops under load, so only an explicit revocation
                    # may destroy a pairing; anything else is transport loss.
                    revoked = code == "revoke" or why in (
                        "revoke",
                        "revoked",
                        "unpaired",
                    )
                    if code == "4403" and not revoked:
                        log("4403 without explicit revoke — treating as transport loss")
                        mark_transport_lost("signalling-4403")
                        return
                    if revoked:
                        await durable_sess_close(sw, resume_token)
                        clear_durable_pairing()
                        clear_resume_token()
                        publish_idle(reason="revoke")
                        raise RuntimeError("session revoked")
        if resume_tail:
            # The phone packed its first mux frame behind Noise msg1.
            await ingest_transport_wire(resume_tail)
        dc_task = asyncio.create_task(_dc_to_mux())
        sig_task = asyncio.create_task(_signalling_mux())
        try:
            while True:
                if remint_requested():
                    force_remint = True
                    publish_remint_status(
                        "closing",
                        message="Ending previous session…",
                    )
                    await durable_sess_close(sw, resume_token)
                    clear_durable_pairing()
                    clear_resume_token()
                    raise RuntimeError("kiosk remint requested")
                if not sess_bound and dc.readyState != "open":
                    log(f"datachannel not open (state={dc.readyState})")
                    break
                if not sess_bound and pc.connectionState in ("failed", "closed"):
                    log(f"webrtc {pc.connectionState}")
                    break
                try:
                    raw_msg = await asyncio.wait_for(pt_in.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    now = time.time()
                    if transport_dead:
                        log("transport dead — ending live session for Always-On resume")
                        break
                    # Signalling WSS already closed: do not keep kiosk "connected".
                    # Unconditional — an Always-On session whose DataChannel has
                    # gone still needs this socket to hear the phone come back.
                    if sw.dead():
                        log("signalling WSS closed — ending session for reconnect")
                        mark_transport_lost("signalling-closed")
                        break
                    if (
                        bearer_refresh_sec > 0
                        and (now - last_bearer_refresh) >= bearer_refresh_sec
                    ):
                        try:
                            bridge.token = mint_dev_token(force=True)
                            last_bearer_refresh = now
                            log(f"proactive lab Bearer refresh …{bridge.token[-6:]}")
                        except Exception as e:
                            log(f"proactive Bearer refresh failed (keeping session): {e}")
                            last_bearer_refresh = now
                    if (
                        phone_live
                        and keepalive_sec > 0
                        and (now - last_ping) >= keepalive_sec
                        and (wss_mux or dc.readyState == "open")
                    ):
                        try:
                            send_pt({"t": "ping", "ts": int(now)})
                            last_ping = now
                            # Liveness is "did we hear the phone at all", not
                            # "did it answer ping". Under heavy Agent Zero load
                            # the phone keeps the mux busy with polls and lets
                            # pongs slip past keepalive_dead_sec; judging on
                            # last_pong alone killed sessions that were plainly
                            # alive, and the teardown then dropped the pairing.
                            heard = max(last_pong, last_rx, last_wss_rx)
                            silent = now - heard
                            if silent > max(90.0, keepalive_sec * 4):
                                log(
                                    f"keepalive: silent for {int(silent)}s "
                                    f"(pong {int(now - last_pong)}s ago)"
                                )
                            if wss_mux and silent > keepalive_dead_sec:
                                mark_transport_lost("keepalive-timeout")
                                break
                        except Exception as e:
                            log(f"keepalive ping failed: {e}")
                            if wss_mux:
                                mark_transport_lost("keepalive-ping-failed")
                                break
                    if (
                        sess_bound
                        and phone_live
                        and wss_mux
                        and (now - last_wss_rx) > max(120.0, keepalive_sec * 5)
                    ):
                        # Phone may be asleep — OK — but not if the stick WSS
                        # is already closed (that was the false-connected bug).
                        if sw.dead():
                            mark_transport_lost("signalling-closed-idle")
                            break
                        log("sess.frame idle — peer may be asleep")
                    continue
                except ConnectionError:
                    if sess_bound and load_resume_token():
                        continue
                    break
                last_rx = time.time()
                msg = json.loads(raw_msg)
                t = msg.get("t")
                if t == "close":
                    why = str(msg.get("why") or "")
                    log(f"client close why={why or 'unspecified'}")
                    if why in ("user", "disconnect", "logout"):
                        await durable_sess_close(sw, resume_token)
                        clear_durable_pairing()
                        clear_resume_token()
                        publish_idle(reason="user-disconnect")
                        raise RuntimeError("user disconnect — awaiting remint")
                    break
                if t == "pong":
                    last_pong = time.time()
                    continue
                if t == "ping":
                    try:
                        send_pt(
                            {"t": "pong", "ts": msg.get("ts"), "id": msg.get("id")}
                        )
                    except Exception as e:
                        log(f"keepalive pong failed: {e}")
                    continue
                try:
                    if not phone_live and sess_bound:
                        phone_live = True
                        publish_connected(conn=phone_conn or "")
                        log("mux traffic after leave — cleared reconnecting UI")
                    await mux.handle(msg)
                except Exception as e:
                    log(f"mux error: {e}")
                    if t == "http_req" and msg.get("id"):
                        send_pt(
                            {
                                "t": "http_res",
                                "id": msg["id"],
                                "status": 502,
                                "headers": {"content-type": "text/plain"},
                                "body_b64": b64u(str(e).encode()),
                            }
                        )
        finally:
            dc_task.cancel()
            sig_task.cancel()
            for task in (dc_task, sig_task):
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

        log(f"live session ended (last_rx_age={int(time.time() - last_rx)}s)")
        try:
            await pc.close()
        except Exception:
            pass

        if force_remint or remint_requested():
            clear_durable_pairing()
            clear_resume_token()
            raise RuntimeError("kiosk remint requested")
        if sess_bound and load_resume_token():
            publish_reconnecting(reason="transport-lost")
            raise RuntimeError("session ended — resume")
        if load_resume_token():
            publish_reconnecting(reason="transport-lost")
            raise RuntimeError("session ended — resume")
        publish_idle(reason="session-ended")
        raise RuntimeError("session ended — awaiting remint")


async def main() -> None:
    a0 = resolve_a0_https()
    build_stamp = os.environ.get("METHODC_BUILD_STAMP", "unknown")
    keepalive_sec = os.environ.get("METHODC_DC_KEEPALIVE_SEC", "30")
    log(
        f"build={build_stamp} transport={METHODC_TRANSPORT} keepalive_dc={keepalive_sec}s "
        f"(foreground; background keepalive is phone-side) "
        f"A0 upstream={a0} DEV_AUTH={int(DEV_AUTH)} pair_exp={PAIR_OPEN_EXP_SEC} "
        f"join_base={JOIN_PUBLIC_BASE or '(unset)'}"
    )
    # Stay running: systemd Restart= + this loop recover from session failures.
    resume_fail_streak = 0
    persist_restore(PAIRING_META_PATH)
    persist_restore(STICK_NOISE_PATH)
    persist_restore(DURABLE_RESUME_TOKEN_PATH)
    ensure_resume_token_if_paired()
    while True:
        try:
            await run_one_session(a0)
            resume_fail_streak = 0
        except ResumeOfferExpired:
            # Not a failure: Always-On keeps a live offer waiting for the phone.
            resume_fail_streak = 0
            continue
        except RateLimited as e:
            # Honour server retry — hammering pair.open extends the lock.
            # Drop remint.req: after the window require a fresh Generate so a
            # queued lab/agent remint cannot instantly burn another pair.open.
            retry = enter_rate_limit_backoff(e.retry)
            log(f"session ended: {e!r}; honouring rate retry {retry}s (remint.req cleared)")
            await sleep_interruptible(retry, check_remint=False)
            # Do not auto-mint when the lock lifts — wait for explicit Generate.
            publish_idle(reason="rate-limit-clear")
            resume_fail_streak = 0
        except Exception as e:
            retry = parse_rate_retry(e)
            if retry is not None:
                retry = enter_rate_limit_backoff(
                    retry,
                    f"StickLink pairing rate-limited — next try in {retry}s.",
                )
                log(f"session ended: {e!r}; honouring rate retry {retry}s (remint.req cleared)")
                await sleep_interruptible(retry, check_remint=False)
                publish_idle(reason="rate-limit-clear")
                resume_fail_streak = 0
                continue
            # Transport loss / failed resume handshake with token → silent retry.
            # Cap pace: 0.5s hammer on resume pair.open still burns Worker quota
            # when resume offers are not exempt (or fail into kiosk mint).
            msg = str(e)
            handshake_fail = (
                "need-offer" in msg
                or "WebRTC answer" in msg
                or "datachannel not open" in msg
                or "handshake" in msg
                or "Noise msg1" in msg
                or "sess resume" in msg
            )
            if (
                ("resume" in msg or handshake_fail)
                and load_resume_token()
                and not remint_requested()
            ):
                if handshake_fail and not read_join_doc().get("reconnecting"):
                    publish_reconnecting(reason="handshake-timeout")
                resume_fail_streak = min(resume_fail_streak + 1, 6)
                delay = min(30.0, 2.0 * (2 ** (resume_fail_streak - 1)))
                log(f"session ended: {e!r}; resume retry in {delay:.0f}s")
                await sleep_interruptible(delay, check_remint=True)
                continue
            resume_fail_streak = 0
            # Idle remint / session errors: short backoff, but wake immediately
            # if Devices & Pairing already asked for a new QR.
            # Never treat remint.req as a reason to skip rate-limit parsing —
            # that path is handled above.
            log(f"session ended: {e!r}; retry in {SESSION_RETRY_SEC}s")
            if await sleep_interruptible(SESSION_RETRY_SEC):
                log("remint.req during backoff — minting now")


if __name__ == "__main__":
    asyncio.run(main())
