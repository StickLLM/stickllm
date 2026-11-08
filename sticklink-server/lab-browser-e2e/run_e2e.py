#!/usr/bin/env python3
"""Orchestrate local wrangler + kiosk aiortc + Playwright browser Method C E2E.

Includes pair_psk / pair-confirm after Noise. LAB BYPASS: skips native VT
approval and LabPairSession.approve_local (see LAB-BYPASS.md).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from lab_common import (
    ROOT, STATE, browser_url, free, start_http, start_kiosk, start_wrangler,
    stop_proc, wait_port, wait_qr,
)

PORT_W = int(os.environ.get("SL_PORT_WORKER", "8797"))
PORT_HTTP = int(os.environ.get("SL_PORT_HTTP", "8765"))


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    if not free(PORT_W):
        raise SystemExit(f"port {PORT_W} busy; set SL_PORT_WORKER")
    if not free(PORT_HTTP):
        raise SystemExit(f"port {PORT_HTTP} busy")

    env = os.environ.copy()
    env["WRANGLER_SEND_METRICS"] = "false"
    wrangler = start_wrangler(PORT_W, env)
    kiosk = None
    try:
        wait_port(PORT_W)
        print("wrangler up", PORT_W)
        start_http(PORT_HTTP)
        print("http up", PORT_HTTP)

        kiosk = start_kiosk(PORT_W, env)
        qr = wait_qr(kiosk)
        print("QR ready", qr[:40], "…")

        from playwright.sync_api import sync_playwright

        url = browser_url(PORT_HTTP, PORT_W, qr)
        browser_result = None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("console", lambda m: print("BROWSER", m.type, m.text, flush=True))
            page.on("pageerror", lambda e: print("PAGEERR", e, flush=True))
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            for _ in range(200):
                browser_result = page.evaluate("window.__SL_RESULT__ || null")
                if browser_result and browser_result.get("error"):
                    break
                if (
                    browser_result
                    and browser_result.get("ok")
                    and browser_result.get("cancelled")
                    and browser_result.get("pair_psk_confirm")
                    and (browser_result.get("revoked") or kiosk.poll() is not None)
                ):
                    break
                time.sleep(0.25)
            log_txt = page.inner_text("#log")
            browser.close()

        try:
            kiosk.wait(timeout=30)
        except Exception:
            stop_proc(kiosk)
            print((STATE / "logs" / "kiosk.log").read_text(encoding="utf-8", errors="replace")[-2000:])
        kiosk_result = {}
        kr = STATE / "kiosk-result.json"
        if kr.exists():
            kiosk_result = json.loads(kr.read_text(encoding="utf-8"))

        report = {
            "ok": bool(
                browser_result and browser_result.get("ok")
                and kiosk_result.get("ok")
                and browser_result.get("pair_psk_confirm")
                and kiosk_result.get("pair_psk_confirm")
            ),
            "browser": browser_result,
            "kiosk": kiosk_result,
            "browser_log_tail": log_txt[-1500:] if log_txt else "",
            "wrangler": f"ws://127.0.0.1:{PORT_W}/v1/ws",
            "lab_bypass_trusted_approval": True,
            "proven": {
                "method_c_mailbox": bool(browser_result and browser_result.get("method_c")),
                "noise_pinned_dc": bool(browser_result and browser_result.get("noise_pinned")),
                "pair_psk_confirm": bool(
                    browser_result and browser_result.get("pair_psk_confirm")
                    and kiosk_result.get("pair_psk_confirm")
                ),
                "chat_stream_cancel": bool(
                    browser_result and browser_result.get("cancelled")
                    and kiosk_result.get("chat_cancelled")
                ),
                "revocation_slot_del": bool(
                    kiosk_result.get("revoked") and browser_result and browser_result.get("revoked")
                ),
            },
        }
        out = STATE / "results" / "e2e-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        if not report["ok"]:
            print("--- kiosk log ---")
            print((STATE / "logs" / "kiosk.log").read_text(encoding="utf-8", errors="replace")[-3000:])
            raise SystemExit(1)
    finally:
        stop_proc(kiosk)
        stop_proc(wrangler)


if __name__ == "__main__":
    main()
