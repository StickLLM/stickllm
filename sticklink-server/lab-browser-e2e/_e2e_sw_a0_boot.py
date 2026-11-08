#!/usr/bin/env python3
"""Smoke: Method C pair → SW-tunneled A0 iframe boots (no splash failure)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
PORT = int(__import__("os").environ.get("SL_PORT_HTTP", "8785"))
WS = __import__("os").environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} sw-boot: {msg}", flush=True)


def wait_qr(timeout: float = 90.0) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout:
        kj = STATE / "kiosk.json"
        if kj.exists():
            doc = json.loads(kj.read_text(encoding="utf-8"))
            qr = doc.get("qr") or ""
            if qr.startswith("sl1:"):
                return qr
        time.sleep(0.4)
    raise SystemExit("no Method C QR")


def main() -> int:
    qr = wait_qr()
    url = (
        f"http://127.0.0.1:{PORT}/browser/agent_join.html"
        f"?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
    )
    log(f"join {url[:80]}…")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function(
            "() => !!(window.__sticklinkA0 && window.__sticklinkA0.mux) || !!window.__sticklinkFail",
            timeout=180000,
        )
        fail = page.evaluate("() => window.__sticklinkFail || null")
        if fail:
            raise SystemExit(f"FAIL pair: {fail}")
        page.wait_for_function(
            "() => document.body.classList.contains('a0-live')",
            timeout=60000,
        )
        frame = page.frame_locator("#a0frame")
        # Splash failure text must not stick; A0 chrome or chat should appear.
        page.wait_for_timeout(8000)
        info = page.evaluate(
            """async () => {
              const f = document.getElementById('a0frame');
              const sw = !!(navigator.serviceWorker && navigator.serviceWorker.controller);
              let frameHref = null, splashFail = null, hasChat = false, bodyText = '';
              try {
                const doc = f.contentDocument;
                frameHref = f.contentWindow && f.contentWindow.location.href;
                bodyText = (doc && doc.body && doc.body.innerText || '').slice(0, 400);
                splashFail = /Unable to load Agent Zero/i.test(bodyText);
                hasChat = !!(doc && (
                  doc.querySelector('#chat-input') ||
                  doc.querySelector('textarea') ||
                  doc.querySelector('.chat') ||
                  doc.querySelector('#right-panel')
                ));
              } catch (e) {
                return { sw, err: String(e) };
              }
              // Also probe an asset via SW→mux from the iframe
              let asset = null;
              try {
                const r = await f.contentWindow.fetch('/agent-zero/index.css', { cache: 'no-store' });
                asset = { status: r.status, n: (await r.arrayBuffer()).byteLength };
              } catch (e) {
                asset = { err: String(e) };
              }
              return { sw, frameHref, splashFail, hasChat, bodyText, asset };
            }"""
        )
        log(f"result {info}")
        browser.close()
        if not info.get("sw"):
            raise SystemExit("FAIL: join page not SW-controlled")
        if info.get("splashFail"):
            raise SystemExit("FAIL: splash still shows Unable to load Agent Zero")
        if not info.get("frameHref") or "agent-zero" not in str(info.get("frameHref")):
            raise SystemExit(f"FAIL: bad frame href {info.get('frameHref')}")
        asset = info.get("asset") or {}
        if asset.get("status") != 200 or not asset.get("n"):
            raise SystemExit(f"FAIL: iframe asset via SW {asset}")
        log("PASS: A0 iframe on StickLink SW→DC")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
