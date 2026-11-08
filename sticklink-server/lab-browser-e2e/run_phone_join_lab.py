#!/usr/bin/env python3
"""Start StickLink Method C Agent bridge + public join URL + kiosk QR.

Usage (lab PC on same LAN as stick):
  set SL_LAB_PROV=C:\\Users\\peter\\sticklink-secrets\\lab-methodc-prov
  python run_phone_join_lab.py

Then: disable Wi‑Fi on phone, scan the Devices & Pairing QR within ~60s.

Design path: phone → Method C (WSS join) → WebRTC/Noise DC → this PC → stick
Agent Zero. Cloudflare trycloudflare hosts ONLY the join HTML bootstrap; Agent
Zero does not ride the tunnel.

LAB: Method C peer runs on this PC (aiortc); Agent Zero stays on the stick.
SL_ALLOW_DIRECT=1 restores the old tunnel-only bypass (not product).
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

from agent_proxy_server import serve as serve_proxy
from kiosk_agent_session import mint_stick_token

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
PORT_HTTP = int(os.environ.get("SL_PORT_HTTP", "8785"))
WS = os.environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")
PROV = os.environ.get(
    "SL_LAB_PROV",
    r"C:\Users\peter\sticklink-secrets\lab-methodc-prov",
)
# Explicit opt-in only — not the product path.
DIRECT = os.environ.get("SL_ALLOW_DIRECT", os.environ.get("SL_DIRECT", "0")) == "1"


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} phone-join: {msg}", flush=True)


def stop_stick_sticklinkd():
    import paramiko
    pw = Path.home().joinpath(".grokbot", "s60pw").read_text(encoding="utf-8").strip()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("192.168.72.50", username="stickllm", password=pw, timeout=20, allow_agent=False, look_for_keys=False)
    # stop via enable helper's sibling if present; else pkill
    stdin, stdout, stderr = c.exec_command(
        "sudo stickllm-sticklink-stop; sleep 1; pgrep -af sticklinkd || echo stopped",
        timeout=30,
        get_pty=True,
    )
    buff = b""
    end = time.time() + 30
    while time.time() < end:
        if stdout.channel.recv_ready():
            chunk = stdout.channel.recv(16384)
            buff += chunk
            if b"[sudo]" in chunk.lower() or b"password for" in chunk.lower():
                stdin.write(pw + "\n")
                stdin.flush()
        elif stdout.channel.exit_status_ready():
            break
        else:
            time.sleep(0.05)
    log("sticklinkd: " + buff.decode("utf-8", "replace")[-200:].replace(pw, "***"))
    c.close()


def _ssh_stick():
    import paramiko
    pw = Path.home().joinpath(".grokbot", "s60pw").read_text(encoding="utf-8").strip()
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("192.168.72.50", username="stickllm", password=pw, timeout=20, allow_agent=False, look_for_keys=False)
    return c, pw


def _run_sudo(c, pw: str, cmd: str, timeout: int = 40) -> str:
    stdin, stdout, stderr = c.exec_command(cmd, get_pty=True, timeout=timeout)
    buff = b""
    end = time.time() + timeout
    while time.time() < end:
        if stdout.channel.recv_ready():
            chunk = stdout.channel.recv(4096)
            buff += chunk
            if b"[sudo]" in chunk.lower() or b"password for" in chunk.lower():
                stdin.write(pw + "\n")
                stdin.flush()
        elif stdout.channel.exit_status_ready():
            break
        else:
            time.sleep(0.05)
    while stdout.channel.recv_ready():
        buff += stdout.channel.recv(4096)
    stdout.channel.recv_exit_status()
    return buff.decode("utf-8", "replace")


def stick_remint_requested() -> bool:
    """True when kiosk Refresh asked for a new StickLink join."""
    try:
        c, pw = _ssh_stick()
        try:
            # RuntimeDirectory is stickllm-owned — no sudo needed to observe.
            stdin, stdout, stderr = c.exec_command(
                "test -f /run/stickllm/sticklink-join-remint.req && echo YES || echo NO",
                timeout=15,
            )
            out = stdout.read().decode("utf-8", "replace")
        finally:
            c.close()
        return "YES" in out
    except Exception as e:
        log(f"remint poll error: {e}")
        return False


def push_kiosk_qr(join_url: str, png_path: Path):
    """Publish StickLink join URL for Devices & Pairing QR (gateway /api/pair/sticklink-join)."""
    now = int(time.time())
    doc = {
        "url": join_url,
        "via": "sticklink",
        # exp 0 = no wall-clock expiry (gateway/proxy treat 0 as unset).
        # Session ends when this lab PC reboots / the phone-join lab stops.
        "exp": 0,
        "at": now,
        "until": "lab-reboot",
    }
    payload = json.dumps(doc) + "\n"
    remint_status = json.dumps({"status": "done", "at": now, "url": join_url}) + "\n"
    c, pw = _ssh_stick()
    sftp = c.open_sftp()
    try:
        sftp.put(str(png_path), "/home/stickllm/sticklink-join-qr.png")
        with sftp.file("/home/stickllm/sticklink-join-url.txt", "w") as f:
            f.write(join_url + "\n")
        with sftp.file("/home/stickllm/sticklink-join.json", "w") as f:
            f.write(payload)
        with sftp.file("/home/stickllm/sticklink-join-remint.json", "w") as f:
            f.write(remint_status)
    finally:
        sftp.close()

    # Gateway has ProtectHome=true — must publish into /run/stickllm via helper.
    # Helper also clears sticklink-join-remint.req and installs remint status.
    out = _run_sudo(c, pw, "sudo -n stickllm-sticklink-join-publish")
    c.close()
    log("published StickLink join → /run/stickllm/sticklink-join.json (Devices & Pairing QR)")
    if "published" not in out:
        log("publish warn: " + out[-500:])


def make_qr_png(url: str, dest: Path):
    try:
        import qrcode
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "qrcode[pil]", "-q"])
        import qrcode
    img = qrcode.make(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Windows may lock a previously opened PNG; write a new name then replace.
    tmp = dest.with_name(dest.stem + f".{int(time.time())}.png")
    img.save(tmp)
    try:
        if dest.exists():
            dest.unlink()
        tmp.replace(dest)
    except OSError:
        dest = tmp
        log(f"QR locked; using {dest.name}")
    log(f"wrote QR {dest}")
    return dest


def _cloudflared_bin() -> str:
    found = shutil.which("cloudflared")
    if found:
        return found
    for cand in (
        Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe"),
        Path(r"C:\Program Files\cloudflared\cloudflared.exe"),
    ):
        if cand.is_file():
            return str(cand)
    raise FileNotFoundError(
        "cloudflared not on PATH; install Cloudflare.cloudflared or add it to PATH"
    )


def start_cloudflared() -> tuple[subprocess.Popen, str]:
    # Unique log so a remint can bring up a NEW tunnel before killing the old one
    # (kill-first → Cloudflare 502 Bad Gateway on Refresh).
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    log_path = STATE / "logs" / f"cloudflared.{int(time.time())}.log"
    logf = open(log_path, "w", encoding="utf-8")
    try:
        (STATE / "logs" / "cloudflared.log").unlink(missing_ok=True)
    except Exception:
        pass
    try:
        (STATE / "logs" / "cloudflared.log").symlink_to(log_path)
    except Exception:
        # Windows may block symlink without admin — copy path marker instead.
        (STATE / "logs" / "cloudflared.log").write_text(str(log_path), encoding="utf-8")
    p = subprocess.Popen(
        [_cloudflared_bin(), "tunnel", "--url", f"http://127.0.0.1:{PORT_HTTP}"],
        stdout=logf,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = ""
    t0 = time.time()
    while time.time() - t0 < 45:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
        if m:
            url = m.group(0)
            break
        if p.poll() is not None:
            raise RuntimeError("cloudflared exited: " + text[-800:])
        time.sleep(0.4)
    if not url:
        raise RuntimeError("no cloudflared URL yet: " + log_path.read_text(encoding="utf-8", errors="replace")[-800:])
    return p, url


def mint_and_publish_direct(cf: subprocess.Popen | None) -> tuple[subprocess.Popen, str]:
    """New Bearer + new trycloudflare tunnel + publish Devices & Pairing QR.

    Bring the new tunnel up BEFORE tearing down the old one so Refresh never
    publishes a URL that Cloudflare 502s (Bad Gateway) mid-cutover.
    """
    old = cf
    log("DIRECT lab: starting new tunnel (keep old up until publish)…")
    cf, public = start_cloudflared()
    join = f"{public}/agent-zero/"
    log("DIRECT lab: minting sticklink-lab token (no pair.open)…")
    token = mint_stick_token()
    (STATE / "agent-session.json").write_text(
        json.dumps(
            {
                "token": token,
                "via": "direct-lab",
                "exp": 0,
                "at": time.time(),
                "until": "lab-reboot",
            }
        ),
        encoding="utf-8",
    )
    # Smoke local proxy, then the PUBLIC trycloudflare URL (DNS/edge lag is what
    # shows up as Cloudflare Bad Gateway on a freshly minted kiosk QR).
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{PORT_HTTP}/agent-zero/api/csrf_token", timeout=20
        ) as r:
            if r.status != 200:
                raise RuntimeError(f"proxy csrf {r.status}")
    except Exception as e:
        try:
            cf.terminate()
        except Exception:
            pass
        raise RuntimeError(f"new tunnel origin not ready: {e}") from e
    pub_ok = False
    pub_err = ""
    for attempt in range(1, 25):
        try:
            req = urllib.request.Request(
                join.rstrip("/") + "/api/csrf_token",
                headers={"User-Agent": "StickLink-lab-smoke", "X-StickLLM-Client": "ui"},
            )
            with urllib.request.urlopen(req, timeout=20) as r:
                body = r.read()
                if r.status == 200 and body:
                    pub_ok = True
                    log(f"public tunnel ready (attempt {attempt})")
                    break
                pub_err = f"status {r.status}"
        except Exception as e:
            pub_err = str(e)
            log(f"public tunnel not ready yet ({attempt}/24): {pub_err[:120]}")
            time.sleep(1.5)
    if not pub_ok:
        try:
            cf.terminate()
        except Exception:
            pass
        if old is not None:
            # Keep previous tunnel; do not publish a dead QR.
            log(f"ABORT remint — public URL never became ready: {pub_err[:200]}")
            return old, ""
        raise RuntimeError(f"public tunnel not ready: {pub_err}")
    log(f"PUBLIC AGENT URL:\n{join}")
    png = make_qr_png(join, STATE / "sticklink-join-qr.png")
    push_kiosk_qr(join, png)
    if old is not None:
        try:
            old.terminate()
            old.wait(timeout=8)
        except Exception:
            try:
                old.kill()
            except Exception:
                pass
    # Do not os.startfile(png) — that pops the QR on the lab PC every remint.
    # The kiosk Devices & Pairing QR is the one to scan.
    return cf, join


def public_join_healthy(join: str) -> bool:
    """True when the published trycloudflare join still answers (not CF 1033/530)."""
    if not join:
        return False
    try:
        req = urllib.request.Request(
            join.rstrip("/") + "/api/csrf_token",
            headers={"User-Agent": "StickLink-lab-watchdog", "X-StickLLM-Client": "ui"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200 and bool(r.read())
    except Exception as e:
        log(f"watchdog: public join unhealthy: {e}")
        return False


def start_direct_lab() -> None:
    """Mint lab Bearer + tunnel QR straight to /agent-zero (no StickLink mailbox)."""
    httpd = serve_proxy(PORT_HTTP)
    log(f"proxy http://127.0.0.1:{PORT_HTTP}/agent-zero/")
    cf, join = mint_and_publish_direct(None)
    log("Phone: scan QR → Agent Zero (StickLink skipped; signalling rate-locked)")
    log("Refresh StickLink QR on the stick remints a new tunnel+token")
    log("Watchdog: if cloudflared dies or CF returns 1033/530, auto-remint")
    log("Ctrl+C to stop")
    last_health = time.time()
    try:
        while True:
            if stick_remint_requested():
                log("kiosk requested StickLink remint — minting new join…")
                new_cf, new_join = mint_and_publish_direct(cf)
                if new_join:
                    cf, join = new_cf, new_join
                    log(f"reminted PUBLIC AGENT URL:\n{join}")
                else:
                    cf = new_cf
                    log("remint aborted; previous join still published")
                last_health = time.time()
            # cloudflared quick tunnels drop silently → phone hard-refresh shows
            # Cloudflare Error 1033 / black-looking error pages; soft refresh of a
            # cached SPA still "works". Detect and remint.
            elif cf is not None and cf.poll() is not None:
                log(f"watchdog: cloudflared exited (code={cf.returncode}) — reminting…")
                cf, join = mint_and_publish_direct(None)
                last_health = time.time()
            elif join and time.time() - last_health >= 45:
                if public_join_healthy(join):
                    last_health = time.time()
                else:
                    log("watchdog: public join failed health check — reminting…")
                    cf, join = mint_and_publish_direct(cf)
                    last_health = time.time()
            time.sleep(1.5)
    except KeyboardInterrupt:
        log("stopping…")
    finally:
        try:
            cf.terminate()
        except Exception:
            pass
        httpd.shutdown()


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    if not Path(PROV).is_dir():
        raise SystemExit(f"missing SL_LAB_PROV={PROV}")

    os.environ["SL_LAB_PROV"] = PROV
    os.environ["SL_WS"] = WS
    os.environ["STICKLINK_TESTING"] = "1"
    os.environ["STICKLINK_LAB"] = "1"
    os.environ["STICKLINK_FAST_KDF"] = "1"
    # Method C data path is the default (WebRTC + Noise DC).
    os.environ.setdefault("SL_WEBRTC", "1")

    # Never reuse a prior Method C mailbox — stale QR → WSS 404 → phone "Error: ws"
    for stale in (STATE / "kiosk.json", STATE / "kiosk-result.json", STATE / "agent-session.json"):
        if stale.exists():
            stale.unlink()

    if DIRECT:
        log("SL_ALLOW_DIRECT=1 — Cloudflare tunnel bypass (NOT Method C product path)")
        start_direct_lab()
        return

    log("stopping stick sticklinkd (free lab device slot)…")
    stop_stick_sticklinkd()

    httpd = serve_proxy(PORT_HTTP)
    log(f"join host http://127.0.0.1:{PORT_HTTP}/browser/agent_join.html")
    cf, public = start_cloudflared()
    log(f"join HTML bootstrap (static only): {public}")

    def start_kiosk():
        kiosk_log = open(STATE / "logs" / "kiosk-agent.log", "w", encoding="utf-8")
        started = time.time()
        proc = subprocess.Popen(
            [sys.executable, str(ROOT / "kiosk_agent_session.py")],
            cwd=str(ROOT),
            env=os.environ.copy(),
            stdout=kiosk_log,
            stderr=subprocess.STDOUT,
        )
        qr = ""
        t0 = time.time()
        while time.time() - t0 < 60:
            kj = STATE / "kiosk.json"
            if kj.exists() and kj.stat().st_mtime >= started - 1:
                doc = json.loads(kj.read_text(encoding="utf-8"))
                if doc.get("qr") and doc["qr"].startswith("sl1:"):
                    qr = doc["qr"]
                    break
            if proc.poll() is not None:
                klog = (STATE / "logs" / "kiosk-agent.log").read_text(
                    encoding="utf-8", errors="replace"
                )
                raise RuntimeError("kiosk exited: " + klog[-1500:])
            time.sleep(0.3)
        if not qr:
            proc.terminate()
            raise RuntimeError("no Method C QR from kiosk")
        return proc, qr, kiosk_log

    log("starting Method C kiosk (pair.open → sl1: → WebRTC/Noise)…")
    kiosk, qr, kiosk_log = start_kiosk()
    log("Method C QR ready (mailbox ~60s — scan promptly)")
    join = f"{public}/browser/agent_join.html?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
    log(f"PUBLIC JOIN URL (embeds Method C sl1:):\n{join}")
    log(f"raw Method C payload:\n{qr}")

    png = make_qr_png(join, STATE / "sticklink-join-qr.png")
    push_kiosk_qr(join, png)

    log("Phone: Wi‑Fi OFF → scan within ~60s → Method C → Agent Zero over StickLink DC")
    log("Refresh remints a new Method C mailbox (not a Cloudflare Agent tunnel)")
    log("Ctrl+C to stop")
    def remint_mailbox(reason: str):
        nonlocal kiosk, qr, kiosk_log, join
        log(f"remint ({reason}): new Method C mailbox…")
        try:
            if kiosk.poll() is None:
                kiosk.terminate()
                kiosk.wait(timeout=8)
        except Exception:
            try:
                kiosk.kill()
            except Exception:
                pass
        try:
            kiosk_log.close()
        except Exception:
            pass
        for stale in (STATE / "kiosk.json", STATE / "agent-session.json"):
            if stale.exists():
                stale.unlink()
        kiosk, qr, kiosk_log = start_kiosk()
        join = (
            f"{public}/browser/agent_join.html"
            f"?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
        )
        png = make_qr_png(join, STATE / "sticklink-join-qr.png")
        push_kiosk_qr(join, png)
        log("remint published — scan new QR within ~60s")

    try:
        while True:
            if kiosk.poll() is not None:
                # Peer never joined / mailbox timed out — keep lab up with a fresh QR.
                remint_mailbox("kiosk exited")
                continue
            if stick_remint_requested():
                remint_mailbox("kiosk Refresh")
            time.sleep(1)
    except KeyboardInterrupt:
        log("stopping…")
    finally:
        try:
            kiosk.terminate()
        except Exception:
            pass
        try:
            cf.terminate()
        except Exception:
            pass
        httpd.shutdown()
        try:
            kiosk_log.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
