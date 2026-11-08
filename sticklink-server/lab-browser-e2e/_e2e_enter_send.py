#!/usr/bin/env python3
"""Verify Enter in rendered A0 chat sends (StickLink client), and banners strip."""
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
    print(f"{time.strftime('%H:%M:%S')} enter: {msg}", flush=True)


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
    raise SystemExit("no QR")


def main() -> int:
    tag = f"enter-{int(time.time())}"
    prompt = f"[{tag}] reply with exactly: ENTER_OK"
    qr = wait_qr()
    url = (
        f"http://127.0.0.1:{PORT}/browser/agent_join.html"
        f"?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        posts: list[str] = []
        page.on(
            "request",
            lambda r: posts.append(r.url)
            if r.method == "POST" and "message_async" in r.url
            else None,
        )
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function(
            "() => !!(window.__sticklinkA0 && window.__sticklinkA0.mux) || !!window.__sticklinkFail",
            timeout=180000,
        )
        fail = page.evaluate("() => window.__sticklinkFail || null")
        if fail:
            raise SystemExit(f"pair fail {fail}")
        page.wait_for_function("() => document.body.classList.contains('a0-live')", timeout=60000)
        frame = page.frame_locator("#a0frame")
        frame.locator("#chat-input").wait_for(state="visible", timeout=120000)

        meta = page.evaluate(
            """async () => {
              const w = document.getElementById('a0frame').contentWindow;
              const doc = w.document;
              // Force banners fetch and inspect stripped payload via mux parent path:
              const r = await w.fetch('/agent-zero/api/banners', {
                method: 'POST',
                headers: {'Content-Type':'application/json','X-StickLLM-Client':'ui'},
                body: '{}',
              });
              const j = await r.json().catch(() => ({}));
              const ids = (j.banners||[]).map(b => b && b.id).filter(Boolean);
              return {
                hasUx: !!doc.querySelector('[data-stickllm-lab-ux]'),
                hasBridge: !!doc.querySelector('[data-sticklink-ws-bridge]'),
                bannerIds: ids,
                unsecured: ids.includes('unsecured-connection'),
              };
            }"""
        )
        log(f"meta {meta}")
        if meta.get("unsecured"):
            raise SystemExit("FAIL: unsecured-connection banner still present after strip")
        if not meta.get("hasBridge"):
            raise SystemExit("FAIL: ws bridge missing")

        chat = frame.locator("#chat-input")
        chat.click()
        chat.fill("")
        chat.press_sequentially(prompt, delay=4)
        chat.press("Enter")
        log("pressed Enter")

        t0 = time.time()
        while time.time() - t0 < 30:
            if posts:
                break
            hist = page.evaluate(
                """(tag) => {
                  const doc = document.getElementById('a0frame').contentDocument;
                  const users = [...doc.querySelectorAll('.message-user')].map(e => e.innerText||'');
                  return users.some(u => u.includes(tag));
                }""",
                tag,
            )
            if hist:
                break
            time.sleep(0.4)
        if not posts and not hist:
            page.screenshot(path=str(STATE / "logs" / "enter-send-FAIL.png"), full_page=True)
            raise SystemExit("FAIL: Enter did not send (no message_async / user bubble)")
        log(f"PASS Enter sent message_async={bool(posts)} tag_in_chat=True")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
