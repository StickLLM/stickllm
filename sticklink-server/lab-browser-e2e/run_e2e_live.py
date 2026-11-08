#!/usr/bin/env python3
"""Method C browser ↔ aiortc against live link.stickllm.com (lab stick).

Uses SL_LAB_PROV credentials. Does not start local wrangler. LAB BYPASS still
applies (no native VT) — see LAB-BYPASS.md. Legacy LAN stickllm-pair unchanged.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from lab_common import (
    STATE, browser_url, free, start_http, start_kiosk, stop_proc, wait_qr,
)

PORT_HTTP = int(os.environ.get("SL_PORT_HTTP", "8771"))
WS = os.environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")
PROV = os.environ.get("SL_LAB_PROV", r"C:\Users\peter\sticklink-secrets\lab-stick-prov")


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    if not free(PORT_HTTP):
        raise SystemExit(f"port {PORT_HTTP} busy; set SL_PORT_HTTP")
    if not Path(PROV).is_dir():
        raise SystemExit(f"missing SL_LAB_PROV={PROV}")

    env = os.environ.copy()
    env["SL_LAB_PROV"] = PROV
    env["STICKLINK_TESTING"] = "1"
    env["STICKLINK_LAB"] = "1"
    env["STICKLINK_FAST_KDF"] = "1"

    kiosk = None
    httpd = None
    try:
        httpd = start_http(PORT_HTTP)
        print("http up", PORT_HTTP, "ws", WS, flush=True)
        kiosk = start_kiosk(0, env, ws_url=WS)
        qr = wait_qr(kiosk, timeout=45)
        print("QR ready", qr[:32], "…", flush=True)

        from playwright.sync_api import sync_playwright

        url = browser_url(PORT_HTTP, 0, qr, ws_url=WS)
        browser_result = None
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("console", lambda m: print("BROWSER", m.type, m.text, flush=True))
            page.on("pageerror", lambda e: print("PAGEERR", e, flush=True))
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            for _ in range(240):
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
            kiosk.wait(timeout=45)
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
            "target": WS,
            "lab_bypass_trusted_approval": True,
            "browser": browser_result,
            "kiosk": kiosk_result,
            "browser_log_tail": log_txt[-1500:] if log_txt else "",
            "proven": {
                "method_c_mailbox_live": bool(browser_result and browser_result.get("method_c")),
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
        out = STATE / "results" / "e2e-live-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps({"ok": report["ok"], "proven": report["proven"], "target": WS}, indent=2))
        if not report["ok"]:
            print("--- kiosk log ---")
            print((STATE / "logs" / "kiosk.log").read_text(encoding="utf-8", errors="replace")[-3000:])
            print("--- browser ---")
            print(json.dumps(browser_result, indent=2)[:2000])
            raise SystemExit(1)
    finally:
        stop_proc(kiosk)
        if httpd:
            httpd.shutdown()


if __name__ == "__main__":
    main()
