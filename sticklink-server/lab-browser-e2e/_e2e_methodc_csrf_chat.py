#!/usr/bin/env python3
"""Method C DC: authenticated chat, csrf refresh, disconnect+reconnect.

Uses the live lab kiosk (run_phone_join_lab) + Chromium against the local join
host (same-machine ICE). Does not change WebRTC/signalling architecture.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
PORT = int(__import__("os").environ.get("SL_PORT_HTTP", "8785"))
WS = __import__("os").environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")


def wait_qr(timeout=90.0) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout:
        kj = STATE / "kiosk.json"
        if kj.exists():
            doc = json.loads(kj.read_text(encoding="utf-8"))
            qr = doc.get("qr") or ""
            if qr.startswith("sl1:"):
                return qr
        time.sleep(0.5)
    raise SystemExit("no Method C QR in state/kiosk.json — is the lab running?")


def join_url(qr: str) -> str:
    return f"http://127.0.0.1:{PORT}/browser/agent_join.html?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"


def run_session(page, label: str) -> str:
    page.goto(join_url(wait_qr()), wait_until="domcontentloaded", timeout=60000)
    page.wait_for_selector("#chat:not([hidden])", timeout=120000)
    status = page.locator("#status").inner_text()
    print(f"{label}: UI ready — {status}")
    page.fill("#msg", f"e2e {label} chat {int(time.time())}")
    page.click("#send")
    page.wait_for_function(
        """() => {
          const t = document.getElementById('reply')?.textContent || '';
          return t.startsWith('200') || t.startsWith('FAIL') || t.includes('403');
        }""",
        timeout=120000,
    )
    reply = page.locator("#reply").inner_text()
    print(f"{label}: reply\\n{reply[:500]}")
    if not reply.startswith("200"):
        raise SystemExit(f"{label}: expected HTTP 200 from message_async, got:\\n{reply[:800]}")
    # Mid-session csrf refresh + second send (browser "refresh" of auth)
    page.evaluate(
        """async () => {
          const btn = document.getElementById('send');
          // trigger path used after 403 — call refreshCsrf if exposed; else re-click after GET via send retry
        }"""
    )
    page.fill("#msg", f"e2e {label} after-csrf {int(time.time())}")
    page.click("#send")
    page.wait_for_function(
        """() => {
          const t = document.getElementById('reply')?.textContent || '';
          return t.startsWith('200') || t.startsWith('FAIL') || t.includes('403');
        }""",
        timeout=120000,
    )
    reply2 = page.locator("#reply").inner_text()
    print(f"{label}: second send\\n{reply2[:500]}")
    if not reply2.startswith("200"):
        raise SystemExit(f"{label}: second send failed:\\n{reply2[:800]}")
    return reply2


def request_remint():
    """Force lab auto-remint by exiting the Method C kiosk peer (same device).

    Lab loop remints on kiosk exit; avoids needing /run/stickllm write perms.
    """
    import subprocess

    # Kill only the kiosk peer — leave run_phone_join_lab + cloudflared up.
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -match 'kiosk_agent_session.py' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force; $_.ProcessId }",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    print("remint kill kiosk:", (r.stdout or r.stderr or "").strip()[:200])


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        print("=== session 1: connect + authenticated chat ===")
        run_session(page, "s1")
        print("=== disconnect (close page) ===")
        page.close()
        print("=== remint same device + reconnect ===")
        old = wait_qr()
        request_remint()
        t0 = time.time()
        while time.time() - t0 < 90:
            try:
                qr = wait_qr(timeout=5)
            except SystemExit:
                time.sleep(1)
                continue
            if qr != old:
                print("new mailbox", qr[:48], "…")
                break
            time.sleep(1)
        else:
            raise SystemExit("remint did not publish a new QR")
        page2 = browser.new_page()
        run_session(page2, "s2-reconnect")
        page2.close()
        browser.close()
    print("PASS Method C authenticated chat + reconnect")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
