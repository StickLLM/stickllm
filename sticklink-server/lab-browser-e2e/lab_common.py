"""Shared helpers for local wrangler Method C browser/kiosk lab runs."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from threading import Thread
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent
WORKER = ROOT.parent / "worker"
STATE = ROOT / "state"


def free(port: int) -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def wait_port(port: int, secs=90):
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            s = socket.create_connection(("127.0.0.1", port), 1)
            s.close()
            return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError(f"port {port} not open")


def ensure_dev_vars(env: dict) -> str:
    envf = str(STATE / "dev.vars")
    if not Path(envf).exists():
        subprocess.check_call(
            ["node", str(WORKER / "scripts" / "dev-vars.mjs")],
            cwd=str(WORKER),
            env={**env, "SL_DEV_VARS_OUT": envf},
        )
    return envf


def start_wrangler(port_w: int, env: dict) -> subprocess.Popen:
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    persist = str(STATE / "d1")
    envf = ensure_dev_vars(env)
    wrangler_bin = WORKER / "node_modules" / ".bin" / "wrangler.cmd"
    if wrangler_bin.exists():
        cmd = [str(wrangler_bin), "dev", "--local",
               "--ip", "127.0.0.1", "--port", str(port_w),
               "--persist-to", persist, "--env-file", envf,
               "--inspector-port", str(port_w + 1500)]
    else:
        cmd = ["node", str(WORKER / "node_modules" / "wrangler" / "bin" / "wrangler.js"),
               "dev", "--local", "--ip", "127.0.0.1", "--port", str(port_w),
               "--persist-to", persist, "--env-file", envf,
               "--inspector-port", str(port_w + 1500)]
    return subprocess.Popen(
        cmd, cwd=str(WORKER), env=env,
        stdout=open(STATE / "logs" / "wrangler.log", "w"),
        stderr=subprocess.STDOUT,
    )


def start_http(port_http: int) -> ThreadingHTTPServer:
    os.chdir(ROOT)

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", port_http), H)
    Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def clear_kiosk_state():
    for stale in (STATE / "kiosk.json", STATE / "kiosk-result.json"):
        if stale.exists():
            stale.unlink()


def start_kiosk(port_w: int, env: dict, neg_mode: str = "", ws_url: str | None = None) -> subprocess.Popen:
    clear_kiosk_state()
    kiosk_env = {
        **env,
        "SL_WS": ws_url or f"ws://127.0.0.1:{port_w}/v1/ws",
        "SL_KIOSK_OUT": str(STATE / "kiosk.json"),
        "STICKLINK_TESTING": "1",
        "STICKLINK_LAB": "1",
        "STICKLINK_FAST_KDF": "1",
    }
    if neg_mode:
        kiosk_env["SL_NEG_MODE"] = neg_mode
    return subprocess.Popen(
        [sys.executable, str(ROOT / "kiosk_stick.py")],
        cwd=str(ROOT),
        env=kiosk_env,
        stdout=open(STATE / "logs" / f"kiosk{('-' + neg_mode) if neg_mode else ''}.log", "w"),
        stderr=subprocess.STDOUT,
    )



def wait_qr(kiosk: subprocess.Popen, timeout=20.0) -> str:
    qr_path = STATE / "kiosk.json"
    t0 = time.time()
    while time.time() - t0 < timeout:
        if qr_path.exists() and "qr" in qr_path.read_text(encoding="utf-8"):
            return json.loads(qr_path.read_text(encoding="utf-8"))["qr"]
        if kiosk.poll() is not None:
            raise RuntimeError("kiosk exited early: " + (STATE / "logs" / "kiosk.log").read_text(encoding="utf-8", errors="replace")[-1500:])
        time.sleep(0.2)
    raise RuntimeError("no QR from kiosk")


def browser_url(port_http: int, port_w: int, qr: str, expect_fail: str = "", ws_url: str | None = None) -> str:
    ws = quote(ws_url or f"ws://127.0.0.1:{port_w}/v1/ws", safe="")
    q = quote(qr, safe="")
    u = f"http://127.0.0.1:{port_http}/browser/index.html?ws={ws}&qr={q}"
    if expect_fail:
        u += f"&expectFail={quote(expect_fail)}"
    return u



def stop_proc(p: subprocess.Popen | None, timeout=10):
    if p is None:
        return
    if p.poll() is not None:
        return
    p.terminate()
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        p.kill()
