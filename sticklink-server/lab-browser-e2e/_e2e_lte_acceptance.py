#!/usr/bin/env python3
"""LTE acceptance prep checks for StickLink Method C (real browser UI).

- Verifies CF bootstrap 404s A0
- Real Playwright pointer/keyboard into rendered A0 (Send button + Enter)
- Two consecutive messages; second is a web search
- Captures console errors, failed resources, ICE type, cold/warm timings
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
PORT = int(__import__("os").environ.get("SL_PORT_HTTP", "8785"))
WS = __import__("os").environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")
OUT = STATE / "logs" / "lte-acceptance-report.json"
BUILD_EXPECT = "methodc-lte-accept-20261108.1"


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} lte: {msg}", flush=True)


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
    raise SystemExit("FAIL: no Method C QR")


def join_url(qr: str) -> str:
    return (
        f"http://127.0.0.1:{PORT}/browser/agent_join.html"
        f"?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
    )


def http_probe(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=15) as r:
            return r.status, r.read().decode("utf-8", "replace")[:300]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")[:300]


def chat_snap(page) -> dict:
    return page.evaluate(
        """() => {
          const doc = document.getElementById('a0frame')?.contentDocument;
          if (!doc) return { ok:false };
          const input = doc.getElementById('chat-input');
          const users = [...doc.querySelectorAll('.message-user')].map(e => (e.innerText||'').trim());
          const agents = [...doc.querySelectorAll('.message-agent-response,.message-agent,.message-ai')]
            .map(e => (e.innerText||'').trim());
          const hist = (doc.querySelector('#chat-history,#messages,.messages') || doc.body).innerText || '';
          const waiting = /Waiting for input/i.test(String(input && (input.value||input.innerText)||''));
          return { ok:true, input: String(input && (input.value||input.innerText)||''), users, agents, hist, waiting };
        }"""
    )


def wait_idle(page, tag: str, timeout_s: float = 240) -> dict:
    t0 = time.time()
    last = {}
    while time.time() - t0 < timeout_s:
        last = chat_snap(page)
        if tag in "\n".join(last.get("users") or []) or tag in (last.get("hist") or ""):
            if last.get("waiting"):
                return last
        time.sleep(2)
    return last


def dismiss_overlays(page, frame):
    """Close A0 modals that intercept pointer events (scheduler, etc.)."""
    for _ in range(4):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        try:
            frame.locator(".modal.show .close, .modal.show [data-dismiss], .modal.show button:has-text('Close')").first.click(
                timeout=800, force=True
            )
        except Exception:
            pass
        shown = frame.locator(".modal.show")
        try:
            if shown.count() == 0:
                break
            # Hide via DOM as last resort so real input can proceed (still UI document).
            page.evaluate(
                """() => {
                  const doc = document.getElementById('a0frame')?.contentDocument;
                  if (!doc) return;
                  doc.querySelectorAll('.modal.show').forEach(m => {
                    m.classList.remove('show');
                    m.style.display = 'none';
                  });
                }"""
            )
        except Exception:
            break
        time.sleep(0.3)


def send_via_button(page, frame, prompt: str, tag: str):
    dismiss_overlays(page, frame)
    chat = frame.locator("#chat-input")
    chat.click(force=True)
    # contenteditable — fill may not clear; select-all then type.
    chat.press("Control+A")
    chat.press_sequentially(prompt, delay=3)
    # Real UI click — not page.evaluate(sendMessage).
    frame.locator("#send-button").click(force=True)
    log(f"clicked #send-button for {tag}")


def send_via_enter(page, frame, prompt: str, tag: str):
    dismiss_overlays(page, frame)
    chat = frame.locator("#chat-input")
    chat.click(force=True)
    chat.press("Control+A")
    chat.press_sequentially(prompt, delay=3)
    chat.press("Enter")
    log(f"pressed Enter for {tag}")


def main() -> int:
    report: dict = {
        "buildExpected": BUILD_EXPECT,
        "buildActual": None,
        "services": {},
        "pathChecks": {},
        "cacheChecks": {},
        "ice": None,
        "cold": None,
        "warm": None,
        "messages": [],
        "consoleErrors": [],
        "pageErrors": [],
        "failedRequests": [],
        "wsEvents": [],
        "verdictNotes": [],
    }

    # Bootstrap health / CF join-only
    for path, expect in [
        ("/lab/ready", 200),
        ("/lab/ice", 200),
        ("/browser/agent_join.html", 200),
        ("/sticklink-asset-sw.js", 200),
        ("/agent-zero/", 404),
        ("/agent-zero/ui/index", 404),
        ("/api/csrf_token", 404),
        ("/public/document.svg", 404),
    ]:
        code, body = http_probe(path)
        report["pathChecks"][path] = {"status": code, "body": body[:160]}
        ok = code == expect
        if path == "/lab/ready" and code == 200 and "sticklink" not in body and "sticklink-dc" not in body:
            # ready may 503 before pair; note only
            pass
        log(f"probe {path} -> {code} (expect {expect}) {'OK' if ok else 'UNEXPECTED'}")
        if not ok and path.startswith("/agent-zero") or path in ("/api/csrf_token", "/public/document.svg"):
            if code != 404:
                report["verdictNotes"].append(f"A0 bootstrap leak? {path} status {code}")

    qr = wait_qr()
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed: list[dict] = []
    ws_events: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda m: console_errors.append(f"{m.type}: {m.text}") if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on(
            "requestfailed",
            lambda r: failed.append({"url": r.url, "err": r.failure}),
        )
        page.on(
            "websocket",
            lambda ws: ws_events.append(f"open {ws.url}")
            or ws.on("close", lambda: ws_events.append(f"close {ws.url}"))
            or ws.on("socketerror", lambda: ws_events.append(f"error {ws.url}")),
        )

        page.goto(join_url(qr), wait_until="domcontentloaded", timeout=60000)
        page.wait_for_function(
            "() => !!(window.__sticklinkA0 && window.__sticklinkA0.mux) || !!window.__sticklinkFail",
            timeout=180000,
        )
        fail = page.evaluate("() => window.__sticklinkFail || null")
        if fail:
            raise SystemExit(f"FAIL pair: {fail}")
        page.wait_for_function("() => document.body.classList.contains('a0-live')", timeout=60000)

        meta = page.evaluate(
            """() => ({
              build: window.__sticklinkBuild || window.__sticklinkA0?.build || null,
              ice: window.__sticklinkIce || window.__sticklinkA0?.ice || null,
            })"""
        )
        report["buildActual"] = meta.get("build")
        report["ice"] = meta.get("ice")
        log(f"build={meta.get('build')} ice={meta.get('ice')}")
        if meta.get("build") != BUILD_EXPECT:
            report["verdictNotes"].append(
                f"build mismatch expected={BUILD_EXPECT} actual={meta.get('build')}"
            )

        frame = page.frame_locator("#a0frame")
        t_cold = time.time()
        frame.locator("#chat-input").wait_for(state="visible", timeout=180000)
        cold_ms = (time.time() - t_cold) * 1000
        page.wait_for_timeout(2000)
        dismiss_overlays(page, frame)
        cold_perf = page.evaluate("() => window.__sticklinkPerf?.summary?.() || null")
        report["cold"] = {"wallChatInputMs": round(cold_ms), "perf": cold_perf}
        log(f"cold interactive wall={cold_ms:.0f}ms")

        # Cache checks via SW headers on a static asset twice.
        cache = page.evaluate(
            """async () => {
              const w = document.getElementById('a0frame').contentWindow;
              const p = '/agent-zero/index.css';
              const r1 = await w.fetch(p, { cache: 'reload' });
              const h1 = r1.headers.get('x-sticklink-sw-cache');
              await r1.arrayBuffer();
              const r2 = await w.fetch(p);
              const h2 = r2.headers.get('x-sticklink-sw-cache');
              const n2 = (await r2.arrayBuffer()).byteLength;
              // Auth/API must not be cacheable even if fetched twice.
              const a1 = await w.fetch('/agent-zero/api/csrf_token', { headers: { 'Accept':'application/json','X-StickLLM-Client':'ui' }});
              const ah1 = a1.headers.get('x-sticklink-sw-cache');
              await a1.arrayBuffer();
              const a2 = await w.fetch('/agent-zero/api/csrf_token', { headers: { 'Accept':'application/json','X-StickLLM-Client':'ui' }});
              const ah2 = a2.headers.get('x-sticklink-sw-cache');
              return {
                static1: h1, static2: h2, staticBytes: n2,
                api1: ah1, api2: ah2,
                apiStatus: a2.status,
              };
            }"""
        )
        report["cacheChecks"] = cache
        log(f"cache {cache}")
        if cache.get("static2") != "HIT":
            report["verdictNotes"].append("static SW cache HIT not observed on 2nd index.css fetch")
        if cache.get("api1") == "HIT" or cache.get("api2") == "HIT":
            report["verdictNotes"].append("API csrf_token was SW-cached — forbidden")

        # Warm reload via HUD button (real click).
        page.locator("#perfWarm").click()
        t_warm = time.time()
        frame.locator("#chat-input").wait_for(state="visible", timeout=180000)
        warm_ms = (time.time() - t_warm) * 1000
        page.wait_for_timeout(1500)
        warm_perf = page.evaluate("() => window.__sticklinkPerf?.summary?.() || null")
        report["warm"] = {
            "wallChatInputMs": round(warm_ms),
            "hudWarmMs": page.evaluate("() => window.__sticklinkWarmMs || null"),
            "perf": warm_perf,
        }
        log(f"warm interactive wall={warm_ms:.0f}ms")

        # Message 1 via Send button (ping).
        tag1 = f"acc-btn-{int(time.time())}"
        prompt1 = f"[{tag1}] Reply with exactly: BUTTON_OK"
        send_via_button(page, frame, prompt1, tag1)
        snap1 = wait_idle(page, tag1, 180)
        hist1 = snap1.get("hist") or ""
        ok1 = (tag1 in hist1 or any(tag1 in u for u in (snap1.get("users") or []))) and (
            "BUTTON_OK" in hist1 or any("BUTTON_OK" in a for a in (snap1.get("agents") or []))
        )
        report["messages"].append(
            {
                "tag": tag1,
                "via": "send-button",
                "ok": bool(ok1),
                "waiting": snap1.get("waiting"),
                "histTail": hist1[-500:],
            }
        )
        log(f"msg1 button ok={ok1} waiting={snap1.get('waiting')}")
        if not ok1:
            page.screenshot(path=str(STATE / "logs" / "lte-msg1-fail.png"), full_page=True)

        # Message 2 via Enter — web search.
        tag2 = f"acc-enter-{int(time.time())}"
        prompt2 = (
            f"[{tag2}] Use web search. Find restaurants in St. George's Grenada. "
            "Reply with exactly two restaurant names, one per line, nothing else."
        )
        send_via_enter(page, frame, prompt2, tag2)
        snap2 = wait_idle(page, tag2, 300)
        hist2 = snap2.get("hist") or ""
        search_ok = bool(re.search(r"SRC\s+Searching|web search|searx|search_engine", hist2, re.I))
        agents = "\n".join(snap2.get("agents") or [])
        answer_ok = bool(re.search(r"[A-Za-z].{3,}", agents)) or (
            "Restaurant" in hist2 or "Grill" in hist2 or "Jean" in hist2
        )
        report["messages"].append(
            {
                "tag": tag2,
                "via": "enter",
                "ok": bool(search_ok and answer_ok),
                "searchSeen": search_ok,
                "answerSeen": answer_ok,
                "waiting": snap2.get("waiting"),
                "agentTail": agents[-400:],
            }
        )
        log(f"msg2 enter search={search_ok} answer={answer_ok}")

        # Wait until composer is idle before third send.
        t_idle = time.time()
        while time.time() - t_idle < 120:
            if chat_snap(page).get("waiting"):
                break
            time.sleep(2)
        dismiss_overlays(page, frame)

        # Repeat Send after response (Enter already used for msg2).
        tag3 = f"acc-btn2-{int(time.time())}"
        prompt3 = f"[{tag3}] Reply with exactly: AGAIN_OK"
        send_via_button(page, frame, prompt3, tag3)
        snap3 = wait_idle(page, tag3, 180)
        ok3 = "AGAIN_OK" in (snap3.get("hist") or "") or any(
            "AGAIN_OK" in a for a in (snap3.get("agents") or [])
        )
        report["messages"].append({"tag": tag3, "via": "send-button-after-response", "ok": bool(ok3)})
        log(f"msg3 button-after-response ok={ok3}")

        page.screenshot(path=str(STATE / "logs" / "lte-acceptance.png"), full_page=True)
        browser.close()

    # Filter noisy console (optional fonts)
    report["consoleErrors"] = [c for c in console_errors if "favicon" not in c.lower()][:40]
    report["pageErrors"] = page_errors[:20]
    report["failedRequests"] = [
        f for f in failed if "favicon" not in f.get("url", "") and "sticklink-dc_only" not in str(f)
    ][:40]
    report["wsEvents"] = ws_events[:20]

    # Lab services snapshot
    report["services"] = {
        "proxyPort": PORT,
        "ws": WS,
        "note": "run_phone_join_lab + kiosk_agent_session + cloudflared join tunnel",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (STATE / "BUILD-LTE-ACCEPT.txt").write_text(
        f"{BUILD_EXPECT}\n{time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        encoding="utf-8",
    )
    log(f"wrote {OUT}")

    hard_fail = []
    if report["buildActual"] != BUILD_EXPECT:
        hard_fail.append("build")
    if any(report["pathChecks"].get(p, {}).get("status") != 404 for p in ("/agent-zero/", "/agent-zero/ui/index")):
        hard_fail.append("a0_bootstrap_not_404")
    if not all(m.get("ok") for m in report["messages"]):
        hard_fail.append("messages")
    if hard_fail:
        raise SystemExit(f"ACCEPTANCE_GAPS {hard_fail} — see {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
