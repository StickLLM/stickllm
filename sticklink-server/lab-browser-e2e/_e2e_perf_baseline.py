#!/usr/bin/env python3
"""Cold + warm StickLink Method C A0 load timings (real browser UI, not API-only)."""
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
OUT = STATE / "logs" / "perf-baseline.json"
LABEL = __import__("os").environ.get("SL_PERF_LABEL", "baseline")


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} perf: {msg}", flush=True)


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


def join_url(qr: str) -> str:
    return (
        f"http://127.0.0.1:{PORT}/browser/agent_join.html"
        f"?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
    )


def wait_chat(page, timeout_ms: int = 180000):
    page.frame_locator("#a0frame").locator("#chat-input").wait_for(
        state="visible", timeout=timeout_ms
    )


def grab(page) -> dict:
    return page.evaluate(
        """() => {
          const P = window.__sticklinkPerf;
          if (!P) return { error: 'no perf' };
          try {
            const doc = document.getElementById('a0frame')?.contentDocument;
            if (doc && doc.getElementById('chat-input') && !P.state.render.chatInputVisibleMs) {
              P.state.render.chatInputVisibleMs = P.now() - P.state.t0;
              P.mark('chat_input_visible');
            }
          } catch (_) {}
          return P.summary();
        }"""
    )


def main() -> int:
    qr = wait_qr()
    report = {"label": LABEL, "ts": time.time(), "cold": None, "warm": None}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(join_url(qr), wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function(
            "() => !!(window.__sticklinkA0 && window.__sticklinkA0.mux) || !!window.__sticklinkFail",
            timeout=180000,
        )
        fail = page.evaluate("() => window.__sticklinkFail || null")
        if fail:
            raise SystemExit(f"pair fail {fail}")
        page.wait_for_function(
            "() => document.body.classList.contains('a0-live')", timeout=60000
        )
        log("paired; waiting cold chat-input…")
        t_cold = time.time()
        wait_chat(page)
        cold_wall = (time.time() - t_cold) * 1000
        # Settle briefly so late assets finish.
        page.wait_for_timeout(2500)
        cold = grab(page)
        cold["wallChatInputMs"] = round(cold_wall)
        report["cold"] = cold
        log(
            f"COLD chat={cold_wall:.0f}ms http={cold.get('http',{}).get('count')} "
            f"bytes={cold.get('http',{}).get('bytes')} maxInflight={cold.get('http',{}).get('maxInflight')} "
            f"overlap={cold.get('http',{}).get('overlapRatio')} maxBuf={cold.get('dc',{}).get('maxBuffered')}"
        )
        top = (cold.get("http") or {}).get("topSlow") or []
        for row in top[:8]:
            log(f"  slow {row.get('ms')}ms {row.get('bytes')}B wait={row.get('waitedMs')} {row.get('path')}")

        # Warm: re-navigate iframe (same DC session, SW may cache nothing yet).
        log("warm reload iframe…")
        page.evaluate(
            """() => {
              window.__sticklinkPerf.resetBase();
              window.__sticklinkPerf.mark('warm_start');
              const f = document.getElementById('a0frame');
              f.src = '/agent-zero/ui/index';
            }"""
        )
        t_warm = time.time()
        wait_chat(page)
        warm_wall = (time.time() - t_warm) * 1000
        page.wait_for_timeout(2500)
        warm = grab(page)
        warm["wallChatInputMs"] = round(warm_wall)
        report["warm"] = warm
        log(
            f"WARM chat={warm_wall:.0f}ms http={warm.get('http',{}).get('count')} "
            f"bytes={warm.get('http',{}).get('bytes')} maxInflight={warm.get('http',{}).get('maxInflight')} "
            f"overlap={warm.get('http',{}).get('overlapRatio')}"
        )

        page.screenshot(path=str(STATE / "logs" / f"perf-{LABEL}.png"), full_page=True)
        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Merge into history file
    hist_path = STATE / "logs" / "perf-history.json"
    hist = []
    if hist_path.exists():
        try:
            hist = json.loads(hist_path.read_text(encoding="utf-8"))
        except Exception:
            hist = []
    hist.append(report)
    hist_path.write_text(json.dumps(hist, indent=2), encoding="utf-8")
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
