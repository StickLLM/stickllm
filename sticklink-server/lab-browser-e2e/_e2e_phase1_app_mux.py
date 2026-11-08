#!/usr/bin/env python3
"""Phase 1 acceptance T2–T6: Agent Zero fully over StickLink DC (no HTTP A0 proxy).

T2: bootstrap /agent-zero returns 404; A0 still loads via DC
T3: chat + search + streamed/poll answers
T4: large asset integrity over DC
T5: burst fetches without deadlock
T6: disconnect / remint / reconnect
"""
from __future__ import annotations

import hashlib
import json
import subprocess
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
LOG = ROOT / "state" / "logs" / "phase1-acceptance.log"


def log(msg: str):
    line = f"{time.strftime('%H:%M:%S')} phase1: {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


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
    raise SystemExit("FAIL T0: no Method C QR")


def join_url(qr: str) -> str:
    return (
        f"http://127.0.0.1:{PORT}/browser/agent_join.html"
        f"?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
    )


def remint(old: str) -> str:
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
        if qr != old:
            time.sleep(1)
            return qr
        time.sleep(0.5)
    raise SystemExit("FAIL T6: remint timeout")


def t2_bootstrap_a0_404():
    log("T2: bootstrap must 404 /agent-zero")
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/agent-zero/", timeout=10)
        raise SystemExit("FAIL T2: /agent-zero/ unexpectedly 200")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        log(f"T2: GET /agent-zero/ -> {e.code} {body[:120]}")
        if e.code != 404:
            raise SystemExit(f"FAIL T2: expected 404 got {e.code}")
        if "sticklink_dc_only" not in body and "a0_via_sticklink" not in body:
            log("T2: warn body missing marker (still 404)")
    log("T2 PASS")


def pair_and_boot(page, qr: str):
    page.goto(join_url(qr), wait_until="domcontentloaded", timeout=60000)
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
    log("paired + A0 iframe live")


def t4_large_asset(page) -> str:
    log("T4: large asset over DC")
    result = page.evaluate(
        """async () => {
          const mux = window.__sticklinkA0.mux;
          const paths = [
            '/agent-zero/vendor/ace-min/ace.js',
            '/agent-zero/vendor/katex/katex.min.js',
            '/agent-zero/index.js',
          ];
          for (const p of paths) {
            const res = await mux.http('GET', p, { 'Accept': '*/*', 'X-StickLLM-Client': 'ui' });
            if (res.status === 200 && res.body.length > 250000) {
              // sha256 in browser
              const hash = await crypto.subtle.digest('SHA-256', res.body);
              const hex = [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2,'0')).join('');
              return { ok: true, path: p, n: res.body.length, sha256: hex,
                       truncated: !!(res.headers['x-sticklink-truncated']) };
            }
            if (res.status === 200 && res.body.length > 100000) {
              const hash = await crypto.subtle.digest('SHA-256', res.body);
              const hex = [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2,'0')).join('');
              return { ok: true, path: p, n: res.body.length, sha256: hex,
                       truncated: !!(res.headers['x-sticklink-truncated']), note: 'lt250k' };
            }
          }
          return { ok: false, err: 'no large 200 asset' };
        }"""
    )
    log(f"T4 result {result}")
    if not result.get("ok"):
        raise SystemExit(f"FAIL T4: {result}")
    if result.get("truncated"):
        raise SystemExit("FAIL T4: truncated flag set")
    if result["n"] < 100000:
        raise SystemExit(f"FAIL T4: asset too small {result['n']}")
    log("T4 PASS")
    return result["sha256"]


def t5_burst(page):
    log("T5: burst 20 GETs")
    result = page.evaluate(
        """async () => {
          const mux = window.__sticklinkA0.mux;
          const paths = [];
          for (let i = 0; i < 20; i++) paths.push('/agent-zero/api/csrf_token');
          const t0 = performance.now();
          const outs = await Promise.all(paths.map(p =>
            mux.http('GET', p, { 'Accept': 'application/json', 'X-StickLLM-Client': 'ui' })
          ));
          const ms = performance.now() - t0;
          const bad = outs.filter(r => r.status !== 200);
          return { ok: bad.length === 0, ms, bad: bad.length, n: outs.length };
        }"""
    )
    log(f"T5 result {result}")
    if not result.get("ok"):
        raise SystemExit(f"FAIL T5: {result}")
    log("T5 PASS")


def t3_search(page, tag: str) -> list[str]:
    log(f"T3: search {tag}")
    result = page.evaluate(
        """async ({ tag }) => {
          const mux = window.__sticklinkA0.mux;
          const csrf = await mux.http('GET', '/agent-zero/api/csrf_token', {
            'Accept': 'application/json', 'X-StickLLM-Client': 'ui'
          });
          if (csrf.status !== 200) return { ok:false, err:'csrf '+csrf.status };
          const tok = JSON.parse(csrf.text).token;
          const prompt = `[${tag}] Use web search. Find restaurants in St. George's Grenada. `
            + 'Reply with exactly two restaurant names, one per line, nothing else.';
          const msg = await mux.http('POST', '/agent-zero/api/message_async', {
            'Content-Type': 'application/json',
            'X-CSRF-Token': tok,
            'X-StickLLM-Client': 'ui',
            'Accept': 'application/json',
          }, JSON.stringify({ text: prompt, context_id: '', message_id: tag }));
          if (msg.status !== 200) return { ok:false, err:'msg '+msg.status+' '+msg.text.slice(0,200) };
          const ctx = JSON.parse(msg.text).context;
          let beforeNo = -1;
          const t0 = Date.now();
          while (Date.now() - t0 < 180000) {
            const poll = await mux.http('POST', '/agent-zero/api/poll', {
              'Content-Type': 'application/json',
              'X-CSRF-Token': tok,
              'X-StickLLM-Client': 'ui',
              'Accept': 'application/json',
            }, JSON.stringify({ context: ctx, log_from: 0, notifications_from: 0, timezone: 'UTC' }));
            if (poll.status !== 200) return { ok:false, err:'poll '+poll.status };
            const doc = JSON.parse(poll.text);
            const logs = doc.logs || [];
            if (beforeNo < 0) {
              for (const it of logs) {
                if (it.type === 'user' && String(it.content||'').includes(tag))
                  beforeNo = Number(it.no||0);
              }
            }
            const recent = logs.filter(it => Number(it.no||0) > beforeNo);
            const blob = JSON.stringify(recent).toLowerCase();
            const saw = ['search','searx','finding restaurants','web search'].some(k => blob.includes(k));
            const answers = recent.filter(it => it.type === 'response' && it.content).map(it => String(it.content));
            const running = (doc.contexts||[]).find(c => c.id === ctx)?.running;
            if (answers.length && saw && running === false)
              return { ok:true, answers, saw, ctx, streamed: recent.some(it => it.type && it.type !== 'user') };
            await new Promise(r => setTimeout(r, 4000));
          }
          return { ok:false, err:'timeout' };
        }""",
        {"tag": tag},
    )
    log(f"T3 result keys ok={result.get('ok')} saw={result.get('saw')} streamed={result.get('streamed')}")
    if not result.get("ok"):
        raise SystemExit(f"FAIL T3: {result}")
    useful = []
    for a in result["answers"]:
        for ln in str(a).splitlines():
            ln = ln.strip("` ").strip()
            if len(ln) > 2 and "plaintext" not in ln.lower() and not ln.startswith("["):
                useful.append(ln)
    if not useful:
        raise SystemExit(f"FAIL T3 empty answers {result['answers']}")
    log(f"T3 PASS {useful[:4]}")
    return useful


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    log("=== Phase 1 acceptance T2–T6 ===")
    t2_bootstrap_a0_404()
    qr = wait_qr()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        pair_and_boot(page, qr)
        t4_large_asset(page)
        t5_burst(page)
        t3_search(page, f"p1a-{int(time.time())}")
        page.close()
        log("T6: disconnect + remint + reconnect")
        qr2 = remint(qr)
        page2 = browser.new_page()
        pair_and_boot(page2, qr2)
        t3_search(page2, f"p1b-{int(time.time())}")
        # quick auth check: csrf again after reconnect
        auth = page2.evaluate(
            """async () => {
              const r = await window.__sticklinkA0.mux.http('GET', '/agent-zero/api/csrf_token',
                {'Accept':'application/json','X-StickLLM-Client':'ui'});
              return { status: r.status, n: r.body.length };
            }"""
        )
        log(f"T6 auth csrf {auth}")
        if auth.get("status") != 200:
            raise SystemExit(f"FAIL T6 auth {auth}")
        page2.close()
        browser.close()
    log("T6 PASS")
    log("=== ALL PHASE 1 T2–T6 PASS ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
