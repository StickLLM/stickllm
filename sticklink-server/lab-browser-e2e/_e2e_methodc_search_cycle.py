#!/usr/bin/env python3
"""End-to-end Method C cycle (x2):

1. Lab publishes Method C QR to Devices & Pairing (kiosk)
2. Client joins via Method C (WSS → WebRTC → Noise DC)
3. Load Agent Zero over StickLink http_req
4. Send a search-forcing prompt; wait for search + answer
5. Disconnect; remint; repeat

Requires run_phone_join_lab.py already running (Method C, not DIRECT).
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
PORT = int(__import__("os").environ.get("SL_PORT_HTTP", "8785"))
WS = __import__("os").environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")
CYCLES = int(__import__("os").environ.get("SL_E2E_CYCLES", "2"))


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} e2e: {msg}", flush=True)


def wait_qr(min_mtime: float = 0.0, timeout: float = 90.0) -> str:
    t0 = time.time()
    while time.time() - t0 < timeout:
        kj = STATE / "kiosk.json"
        if kj.exists() and kj.stat().st_mtime >= min_mtime:
            doc = json.loads(kj.read_text(encoding="utf-8"))
            qr = doc.get("qr") or ""
            if qr.startswith("sl1:"):
                return qr
        time.sleep(0.4)
    raise SystemExit("no Method C QR — start run_phone_join_lab.py first")


def join_url(qr: str) -> str:
    return (
        f"http://127.0.0.1:{PORT}/browser/agent_join.html"
        f"?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
    )


def remint_new_mailbox(old_qr: str) -> str:
    log("remint: kill kiosk peer (lab auto-remints)")
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -match 'kiosk_agent_session.py' } | "
            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    t0 = time.time()
    while time.time() - t0 < 90:
        try:
            qr = wait_qr(min_mtime=t0 - 1, timeout=5)
        except SystemExit:
            time.sleep(1)
            continue
        if qr != old_qr:
            log(f"new QR ready {qr[:40]}…")
            # give publish a beat
            time.sleep(1)
            return qr
        time.sleep(0.8)
    raise SystemExit("remint did not publish a new QR")


def one_cycle(browser, label: str) -> dict:
    qr = wait_qr()
    # Confirm kiosk publish artifact exists (Devices & Pairing QR png)
    png = STATE / "sticklink-join-qr.png"
    if not png.exists():
        raise SystemExit("missing sticklink-join-qr.png (kiosk QR not written)")
    log(f"{label}: kiosk QR png={png.stat().st_size}B")
    log(f"{label}: join {join_url(qr)[:100]}…")

    page = browser.new_page()
    try:
        page.goto(join_url(qr), wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function(
            """() => !!(window.__sticklinkSession && window.__sticklinkSession.runSearchPrompt)
                 || !!window.__sticklinkFail""",
            timeout=120000,
        )
        fail = page.evaluate("() => window.__sticklinkFail || null")
        if fail:
            raise SystemExit(f"{label}: pair failed: {fail}")
        log(f"{label}: Agent Zero session ready over StickLink DC")

        result = page.evaluate(
            """async () => {
              const s = window.__sticklinkSession;
              return await s.runSearchPrompt(null, 180000);
            }"""
        )
        log(f"{label}: SEARCH OK answers={result.get('answers')}")
        if not result.get("ok") or not result.get("sawSearch") or not result.get("answers"):
            raise SystemExit(f"{label}: bad search result: {result}")
        useful = []
        for a in result["answers"]:
            for ln in str(a).splitlines():
                ln = ln.strip("` ").strip()
                if len(ln) > 2 and not ln.startswith("[") and "plaintext" not in ln.lower():
                    useful.append(ln)
        if not useful:
            raise SystemExit(f"{label}: no useful answer lines: {result['answers']}")
        log(f"{label}: RESULT lines={useful[:4]}")
        return {"qr": qr, "answers": useful, "context": result.get("context")}
    finally:
        page.close()
        log(f"{label}: disconnected")


def main() -> int:
    log(f"starting {CYCLES} Method C search cycles")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        results = []
        for i in range(1, CYCLES + 1):
            label = f"pass{i}"
            if i > 1:
                prev = results[-1]["qr"]
                remint_new_mailbox(prev)
            results.append(one_cycle(browser, label))
        browser.close()
    log("PASS Method C search cycle x" + str(CYCLES))
    for i, r in enumerate(results, 1):
        log(f"  pass{i}: {r['answers'][:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
