#!/usr/bin/env python3
"""Start StickLink Method C Agent bridge + public join URL + kiosk QR.

Usage (lab PC on same LAN as stick):
  python run_phone_join_lab.py

Then: disable Wi‑Fi on phone, scan the QR shown (and pushed to the stick),
open Agent Zero in the join page.

LAB: Method C peer runs on this PC (aiortc); Agent Zero stays on the stick.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import quote

from agent_proxy_server import serve as serve_proxy
from kiosk_agent_session import mint_stick_token

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
PORT_HTTP = int(os.environ.get("SL_PORT_HTTP", "8785"))
WS = os.environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")
PROV = os.environ.get("SL_LAB_PROV", r"C:\Users\peter\sticklink-secrets\lab-stick-prov")
# SL_DIRECT=1 → skip StickLink pair (tunnel QR → /agent-zero). Used when
# signalling rate-locks the lab home (5 pair.open / 10 min → 1 h lock).
DIRECT = os.environ.get("SL_DIRECT", "0") == "1"


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


def push_kiosk_qr(join_url: str, png_path: Path):
    """Publish StickLink join URL for Devices & Pairing QR (gateway /api/pair/sticklink-join)."""
    import json
    import paramiko
    pw = Path.home().joinpath(".grokbot", "s60pw").read_text(encoding="utf-8").strip()
    doc = {
        "url": join_url,
        "via": "sticklink",
        "exp": int(time.time()) + 3600,
        "at": int(time.time()),
    }
    payload = json.dumps(doc) + "\n"
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect("192.168.72.50", username="stickllm", password=pw, timeout=20, allow_agent=False, look_for_keys=False)
    sftp = c.open_sftp()
    try:
        sftp.put(str(png_path), "/home/stickllm/sticklink-join-qr.png")
        with sftp.file("/home/stickllm/sticklink-join-url.txt", "w") as f:
            f.write(join_url + "\n")
        with sftp.file("/home/stickllm/sticklink-join.json", "w") as f:
            f.write(payload)
    finally:
        sftp.close()

    def run_sudo(cmd: str, timeout: int = 40) -> str:
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

    # Gateway has ProtectHome=true — must publish into /run/stickllm via helper.
    out = run_sudo("sudo -n stickllm-sticklink-join-publish")
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


def start_cloudflared() -> tuple[subprocess.Popen, str]:
    # cloudflared quick tunnel → trycloudflare.com URL
    logf = open(STATE / "logs" / "cloudflared.log", "w", encoding="utf-8")
    p = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{PORT_HTTP}"],
        stdout=logf,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = ""
    t0 = time.time()
    while time.time() - t0 < 45:
        text = (STATE / "logs" / "cloudflared.log").read_text(encoding="utf-8", errors="replace")
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
        if m:
            url = m.group(0)
            break
        if p.poll() is not None:
            raise RuntimeError("cloudflared exited: " + text[-800:])
        time.sleep(0.4)
    if not url:
        raise RuntimeError("no cloudflared URL yet: " + (STATE / "logs" / "cloudflared.log").read_text(encoding="utf-8", errors="replace")[-800:])
    return p, url


def start_direct_lab() -> None:
    """Mint lab Bearer + tunnel QR straight to /agent-zero (no StickLink mailbox)."""
    log("DIRECT lab: minting sticklink-lab token (no pair.open)…")
    token = mint_stick_token()
    (STATE / "agent-session.json").write_text(
        json.dumps({"token": token, "via": "direct-lab", "exp": time.time() + 3600, "at": time.time()}),
        encoding="utf-8",
    )
    httpd = serve_proxy(PORT_HTTP)
    log(f"proxy http://127.0.0.1:{PORT_HTTP}/agent-zero/")
    cf, public = start_cloudflared()
    join = f"{public}/agent-zero/"
    log(f"PUBLIC AGENT URL:\n{join}")
    png = make_qr_png(join, STATE / "sticklink-join-qr.png")
    push_kiosk_qr(join, png)
    try:
        os.startfile(str(png))  # noqa: PTH123
    except Exception:
        pass
    log("Phone: scan QR → Agent Zero (StickLink skipped; signalling rate-locked)")
    log("Ctrl+C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log("stopping…")
    finally:
        cf.terminate()
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

    # Never reuse a prior Method C mailbox — stale QR → WSS 404 → phone "Error: ws"
    for stale in (STATE / "kiosk.json", STATE / "kiosk-result.json", STATE / "agent-session.json"):
        if stale.exists():
            stale.unlink()

    if DIRECT:
        start_direct_lab()
        return

    log("stopping stick sticklinkd (free lab device slot)…")
    stop_stick_sticklinkd()

    log("starting Method C + Agent tunnel kiosk…")
    kiosk_log = open(STATE / "logs" / "kiosk-agent.log", "w", encoding="utf-8")
    started = time.time()
    kiosk = subprocess.Popen(
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
        if kiosk.poll() is not None:
            klog = (STATE / "logs" / "kiosk-agent.log").read_text(encoding="utf-8", errors="replace")
            if "'code': 'rate'" in klog or '"code": "rate"' in klog or "code': 'rate'" in klog:
                log("StickLink pair.open rate-locked — falling back to DIRECT tunnel")
                kiosk.terminate()
                start_direct_lab()
                return
            raise RuntimeError("kiosk exited: " + klog[-1500:])
        time.sleep(0.3)
    if not qr:
        raise RuntimeError("no Method C QR from kiosk")
    log("Method C QR ready (mailbox ~60s — scan promptly)")

    # Same-origin reverse proxy: join page + /agent-zero → stick with lab token
    httpd = serve_proxy(PORT_HTTP)
    log(f"proxy http://127.0.0.1:{PORT_HTTP}/browser/agent_join.html (+ /agent-zero)")
    cf, public = start_cloudflared()
    join = f"{public}/browser/agent_join.html?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
    log(f"PUBLIC JOIN URL:\n{join}")

    png = STATE / "sticklink-join-qr.png"
    png = make_qr_png(join, png)
    push_kiosk_qr(join, png)

    # Also open QR on this PC for convenience
    try:
        os.startfile(str(png))  # noqa: PTH123
    except Exception:
        pass

    log("Phone: Wi‑Fi OFF → scan QR within ~60s → Agent Zero auto-opens")
    log("Ctrl+C to stop")
    try:
        while True:
            if kiosk.poll() is not None:
                log("kiosk exited")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        log("stopping…")
    finally:
        kiosk.terminate()
        cf.terminate()
        httpd.shutdown()


if __name__ == "__main__":
    main()
