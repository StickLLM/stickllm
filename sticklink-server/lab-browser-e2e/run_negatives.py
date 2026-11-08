#!/usr/bin/env python3
"""Negative Method C cases against local wrangler (browser + kiosk + slot join).

Cases:
  wrong_pin   — QR K (Noise pin) mutated in browser; Noise must fail
  wrong_psk   — kiosk uses random boot_psk; browser must reject msg2
  tamper      — after confirm, kiosk sends corrupted AEAD; browser must fail decrypt
  revoked_reconnect — after slot.del, join with old jk must auth-fail

Does not deploy or touch live relay. Keep admit deny-all until separate cutover.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(REPO / "overlay/usr/local/lib"))

from lab_common import (  # noqa: E402
    STATE, browser_url, free, start_http, start_kiosk, start_wrangler,
    stop_proc, wait_port, wait_qr,
)

PORT_W = int(os.environ.get("SL_PORT_WORKER", "8810"))
PORT_HTTP = int(os.environ.get("SL_PORT_HTTP", "8780"))


def run_browser_case(page_factory, url: str, wait_pred, timeout_s=45):
    page = page_factory()
    page.on("console", lambda m: print("BROWSER", m.type, m.text, flush=True))
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    t0 = time.time()
    result = None
    while time.time() - t0 < timeout_s:
        result = page.evaluate("window.__SL_RESULT__ || null")
        if result and wait_pred(result):
            break
        time.sleep(0.25)
    log_txt = page.inner_text("#log")
    page.close()
    return result, log_txt


async def revoked_reconnect(home_b64: str, slot_b64: str, jk_b64: str, ws_base: str) -> dict:
    import websockets
    from sticklink import sigcrypto as sc
    from sticklink.util import b64u, unb64u

    home = unb64u(home_b64, 16)
    slot = unb64u(slot_b64, 8)
    jk = unb64u(jk_b64, 32)
    uri = f"{ws_base}?home={home_b64}"
    async with websockets.connect(uri, subprotocols=["sticklink.1"], open_timeout=20) as ws:
        welcome = json.loads(await ws.recv())
        assert welcome["t"] == "welcome"
        n = unb64u(welcome["n"], 32)
        mac = sc.join_mac(jk, n, home, slot)
        await ws.send(json.dumps({
            "t": "join", "id": 3, "home": home_b64, "slot": slot_b64, "mac": b64u(mac),
        }))
        reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        # Expect auth fail (err) — slot is gone / revoked, never rejoinable.
        return {"reply": reply, "rejected": reply.get("t") == "err" or reply.get("t") != "joined"}


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    (STATE / "results").mkdir(parents=True, exist_ok=True)
    if not free(PORT_W):
        raise SystemExit(f"port {PORT_W} busy; set SL_PORT_WORKER")
    if not free(PORT_HTTP):
        raise SystemExit(f"port {PORT_HTTP} busy")

    env = os.environ.copy()
    env["WRANGLER_SEND_METRICS"] = "false"
    wrangler = start_wrangler(PORT_W, env)
    results = {}
    kiosk = None
    try:
        wait_port(PORT_W)
        start_http(PORT_HTTP)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            def new_page():
                return browser.new_page()

            # --- wrong_pin ---
            kiosk = start_kiosk(PORT_W, env)
            qr = wait_qr(kiosk)
            url = browser_url(PORT_HTTP, PORT_W, qr, expect_fail="wrong_pin")
            br, _ = run_browser_case(
                new_page, url,
                lambda r: r.get("neg") == "wrong_pin" and r.get("noise_failed"),
                timeout_s=40,
            )
            stop_proc(kiosk)
            results["wrong_pin"] = {
                "pass": bool(br and br.get("ok") and br.get("noise_failed")),
                "browser": br,
            }
            print("wrong_pin", results["wrong_pin"]["pass"])

            # --- wrong_psk ---
            kiosk = start_kiosk(PORT_W, env, neg_mode="wrong_psk")
            qr = wait_qr(kiosk)
            url = browser_url(PORT_HTTP, PORT_W, qr, expect_fail="wrong_psk")
            br, _ = run_browser_case(
                new_page, url,
                lambda r: r.get("neg") == "wrong_psk" and r.get("noise_failed"),
                timeout_s=40,
            )
            try:
                kiosk.wait(timeout=15)
            except Exception:
                stop_proc(kiosk)
            kr = {}
            if (STATE / "kiosk-result.json").exists():
                kr = json.loads((STATE / "kiosk-result.json").read_text(encoding="utf-8"))
            results["wrong_psk"] = {
                "pass": bool(br and br.get("ok") and br.get("noise_failed") and kr.get("neg") == "wrong_psk"),
                "browser": br,
                "kiosk": kr,
            }
            print("wrong_psk", results["wrong_psk"]["pass"])

            # --- tamper ---
            kiosk = start_kiosk(PORT_W, env, neg_mode="tamper")
            qr = wait_qr(kiosk)
            url = browser_url(PORT_HTTP, PORT_W, qr, expect_fail="tamper")
            br, _ = run_browser_case(
                new_page, url,
                lambda r: r.get("neg") == "tamper" and r.get("aead_failed"),
                timeout_s=50,
            )
            try:
                kiosk.wait(timeout=20)
            except Exception:
                stop_proc(kiosk)
            kr = {}
            if (STATE / "kiosk-result.json").exists():
                kr = json.loads((STATE / "kiosk-result.json").read_text(encoding="utf-8"))
            results["tamper"] = {
                "pass": bool(br and br.get("ok") and br.get("aead_failed") and kr.get("neg") == "tamper"),
                "browser": br,
                "kiosk": kr,
            }
            print("tamper", results["tamper"]["pass"])

            # --- positive enough to get slot then revoke reconnect ---
            # Re-run a short path: use last positive e2e artifacts if present, else one more kiosk.
            kiosk = start_kiosk(PORT_W, env)
            qr = wait_qr(kiosk)
            url = browser_url(PORT_HTTP, PORT_W, qr)
            br, _ = run_browser_case(
                new_page, url,
                lambda r: r.get("ok") and r.get("revoked") and r.get("pair_psk_confirm"),
                timeout_s=60,
            )
            try:
                kiosk.wait(timeout=30)
            except Exception:
                stop_proc(kiosk)
            kr = {}
            if (STATE / "kiosk-result.json").exists():
                kr = json.loads((STATE / "kiosk-result.json").read_text(encoding="utf-8"))
            browser.close()

        reconnect = {"pass": False}
        if kr.get("slot") and kr.get("jk") and kr.get("home"):
            reconnect = asyncio.run(revoked_reconnect(
                kr["home"], kr["slot"], kr["jk"], f"ws://127.0.0.1:{PORT_W}/v1/ws",
            ))
            reconnect["pass"] = bool(reconnect.get("rejected"))
        else:
            reconnect = {"pass": False, "error": "missing slot/jk/home from kiosk", "kiosk": kr, "browser": br}
        results["revoked_reconnect"] = reconnect
        print("revoked_reconnect", results["revoked_reconnect"]["pass"])

        report = {
            "ok": all(v.get("pass") for v in results.values()),
            "cases": results,
            "lab_bypass_trusted_approval": True,
            "note": "Native VT overlay and LabPairSession.approve_local are bypassed in this harness.",
        }
        out = STATE / "results" / "negatives-report.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
        if not report["ok"]:
            raise SystemExit(1)
    finally:
        stop_proc(kiosk)
        stop_proc(wrangler)


if __name__ == "__main__":
    main()
