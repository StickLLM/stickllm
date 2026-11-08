#!/usr/bin/env python3
"""Method C → full Agent Zero SPA (x2 cycles with search).

1. Kiosk publishes Method C QR
2. Client Method C pairs, redirects to /agent-zero/
3. Full A0 UI loads; send search prompt; assert answer
4. Disconnect, remint, repeat
"""
from __future__ import annotations

import json
import subprocess
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
    print(f"{time.strftime('%H:%M:%S')} e2e-a0: {msg}", flush=True)


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
    raise SystemExit("no Method C QR — is run_phone_join_lab.py running?")


def join_url(qr: str) -> str:
    return (
        f"http://127.0.0.1:{PORT}/browser/agent_join.html"
        f"?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
    )


def remint(old_qr: str) -> str:
    log("remint kiosk peer…")
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
            time.sleep(1)
            log(f"new QR {qr[:40]}…")
            return qr
        time.sleep(0.8)
    raise SystemExit("remint timeout")


def search_via_spa(page, tag: str) -> list[str]:
    """Use A0 APIs in the SPA origin (cookies + CSRF from the loaded app)."""
    prompt = (
        f"[{tag}] Use web search. Find restaurants in St. George's Grenada. "
        "Reply with exactly two restaurant names, one per line, nothing else."
    )
    result = page.evaluate(
        """async ({ prompt, tag }) => {
          const csrfR = await fetch('/agent-zero/api/csrf_token', {
            credentials: 'include',
            headers: { 'X-StickLLM-Client': 'ui' },
          });
          const csrfJ = await csrfR.json();
          const tok = csrfJ.token || csrfJ.csrf_token;
          if (!csrfR.ok || !tok) return { ok: false, err: 'csrf ' + csrfR.status };

          const msgR = await fetch('/agent-zero/api/message_async', {
            method: 'POST',
            credentials: 'include',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRF-Token': tok,
              'X-StickLLM-Client': 'ui',
            },
            body: JSON.stringify({ text: prompt, context_id: '', message_id: tag }),
          });
          const msgJ = await msgR.json().catch(() => ({}));
          if (!msgR.ok) return { ok: false, err: 'message ' + msgR.status + ' ' + JSON.stringify(msgJ).slice(0,200) };
          const ctx = msgJ.context;
          if (!ctx) return { ok: false, err: 'no context' };

          const t0 = Date.now();
          let beforeNo = -1;
          while (Date.now() - t0 < 180000) {
            const pollR = await fetch('/agent-zero/api/poll', {
              method: 'POST',
              credentials: 'include',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRF-Token': tok,
                'X-StickLLM-Client': 'ui',
              },
              body: JSON.stringify({
                context: ctx,
                log_from: 0,
                notifications_from: 0,
                timezone: 'UTC',
              }),
            });
            const poll = await pollR.json();
            const logs = poll.logs || [];
            if (beforeNo < 0) {
              for (const it of logs) {
                if (it.type === 'user' && String(it.content || '').includes(tag)) {
                  beforeNo = Number(it.no || 0);
                }
              }
            }
            const recent = logs.filter((it) => Number(it.no || 0) > beforeNo);
            const blob = JSON.stringify(recent).toLowerCase();
            const saw = ['search','searx','finding restaurants','web search'].some((k) => blob.includes(k));
            const answers = recent.filter((it) => it.type === 'response' && it.content).map((it) => String(it.content));
            const running = (poll.contexts || []).find((c) => c.id === ctx)?.running;
            if (answers.length && saw && running === false) {
              return { ok: true, answers, saw, ctx };
            }
            await new Promise((r) => setTimeout(r, 4000));
          }
          return { ok: false, err: 'timeout' };
        }""",
        {"prompt": prompt, "tag": tag},
    )
    if not result.get("ok"):
        raise SystemExit(f"search failed: {result}")
    useful = []
    for a in result["answers"]:
        for ln in str(a).splitlines():
            ln = ln.strip("` ").strip()
            if len(ln) > 2 and not ln.startswith("[") and "plaintext" not in ln.lower():
                useful.append(ln)
    if not useful:
        raise SystemExit(f"empty answers: {result['answers']}")
    return useful


def one_cycle(browser, label: str) -> dict:
    qr = wait_qr()
    png = STATE / "sticklink-join-qr.png"
    if not png.exists():
        raise SystemExit("missing kiosk QR png")
    log(f"{label}: kiosk QR png ok ({png.stat().st_size}B)")

    page = browser.new_page()
    try:
        page.goto(join_url(qr), wait_until="domcontentloaded", timeout=60000)
        # Method C then redirect into full SPA
        page.wait_for_url("**/agent-zero/**", timeout=180000)
        log(f"{label}: landed {page.url}")
        # SPA chrome
        page.wait_for_selector("#chat-input, #chat-input-container, textarea, [contenteditable]", timeout=120000)
        # Prefer chat input if present
        has_input = page.locator("#chat-input").count() > 0
        log(f"{label}: SPA loaded chat-input={has_input}")
        names = search_via_spa(page, f"{label}-{int(time.time())}")
        log(f"{label}: SEARCH OK {names[:4]}")
        return {"qr": qr, "answers": names, "url": page.url}
    finally:
        page.close()
        log(f"{label}: disconnected")


def main() -> int:
    log(f"full Agent Zero SPA cycles={CYCLES}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        results = []
        for i in range(1, CYCLES + 1):
            if i > 1:
                remint(results[-1]["qr"])
            results.append(one_cycle(browser, f"pass{i}"))
        browser.close()
    log("PASS Method C → full Agent Zero SPA x" + str(CYCLES))
    for i, r in enumerate(results, 1):
        log(f"  pass{i}: {r['answers'][:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
