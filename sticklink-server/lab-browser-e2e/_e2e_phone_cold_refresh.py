#!/usr/bin/env python3
"""Phone Agent Zero COLD refresh flake test.

User insight: once a load succeeds, later refreshes stay good (cache).
So each run uses a brand-new browser context with cache disabled — equivalent
to a hard reload / first open after scanning QR.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import paramiko
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "state" / "phone-cold-refresh"
OUT.mkdir(parents=True, exist_ok=True)
pw = Path.home().joinpath(".grokbot", "s60pw").read_text(encoding="utf-8").strip()

RUNS = 6
GAP_SEC = 60

SCORE_JS = """() => {
  const text = (document.body && document.body.innerText || '').trim();
  const chat = document.querySelector('#chat-input');
  const send = document.querySelector('#send-button');
  const hist = document.querySelector('#chat-history');
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return {w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),y:Math.round(r.y),op:s.opacity,vis:s.visibility};
  };
  const chatR = rect(chat), sendR = rect(send), histR = rect(hist);
  const visibleChat = !!(chatR && chatR.w>40 && chatR.h>20 && chatR.op!=='0');
  const visibleSend = !!(sendR && sendR.w>10 && sendR.h>10);
  const histOk = !!(histR && histR.w>50 && histR.h>50);
  const splash = /starting agent zero/i.test(text) && text.length < 80;
  const nearlyEmpty = text.length < 40;
  const hasUi = /how can i help|ask anything|chats|quick actions/i.test(text);
  let verdict = 'pass';
  if (splash) verdict = 'splash_stuck';
  else if (nearlyEmpty && !visibleChat) verdict = 'black';
  else if (!visibleChat || !visibleSend) verdict = 'broken_layout';
  else if (!hasUi && !histOk) verdict = 'broken_layout';
  return {verdict, textLen:text.length, textHead:text.slice(0,140).replace(/\\s+/g,' '),
    visibleChat, visibleSend, histOk, splash, chatR, sendR, histR, title:document.title, href:location.href};
}"""


def log(msg: str):
    line = f"{time.strftime('%H:%M:%S')} cold: {msg}"
    print(line, flush=True)
    with (OUT / "log.txt").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def join_url() -> str:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        "192.168.72.50",
        username="stickllm",
        password=pw,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
    try:
        _i, o, _e = c.exec_command(
            "curl -s -H 'X-StickLLM-Client: ui' http://127.0.0.1/api/pair/sticklink-join",
            timeout=20,
        )
        doc = json.loads(o.read().decode())
    finally:
        c.close()
    url = str(doc.get("url") or "").strip()
    if not url:
        raise RuntimeError(doc)
    return url


def main():
    (OUT / "log.txt").write_text("", encoding="utf-8")
    join = join_url()
    log(f"join={join}")
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for i in range(1, RUNS + 1):
            log(f"RUN {i}/{RUNS} — COLD context (cache disabled)")
            t0 = time.time()
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                device_scale_factor=3,
                is_mobile=True,
                has_touch=True,
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
                    "Mobile/15E148 Safari/604.1"
                ),
            )
            # Disable HTTP cache for this context
            context.route(
                "**/*",
                lambda route: route.continue_(
                    headers={
                        **route.request.headers,
                        "Cache-Control": "no-cache",
                        "Pragma": "no-cache",
                    }
                ),
            )
            page = context.new_page()
            page.set_extra_http_headers({"X-StickLLM-Client": "ui"})
            try:
                # Clear any residual storage
                page.goto("about:blank")
                page.goto(join, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(9000)
                data = page.evaluate(SCORE_JS)
                shot = OUT / f"run-{i:02d}-{data['verdict']}.png"
                page.screenshot(path=str(shot), full_page=True)
                data["screenshot"] = str(shot)
            except Exception as e:
                data = {"verdict": "error", "error": str(e)}
                try:
                    page.screenshot(path=str(OUT / f"run-{i:02d}-error.png"), full_page=True)
                except Exception:
                    pass
            context.close()
            data["run"] = i
            data["at"] = time.strftime("%H:%M:%S")
            data["elapsed_s"] = round(time.time() - t0, 1)
            results.append(data)
            log(
                f"RUN {i} => {data.get('verdict')} chat={data.get('visibleChat')} "
                f"send={data.get('visibleSend')} textLen={data.get('textLen')} "
                f"head={str(data.get('textHead',''))[:70]!r}"
            )
            (OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            if i < RUNS:
                log(f"sleep {GAP_SEC}s…")
                time.sleep(GAP_SEC)
        browser.close()

    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    summary = {
        "mode": "cold_context_each_run",
        "join": join,
        "runs": RUNS,
        "gap_sec": GAP_SEC,
        "counts": counts,
        "verdicts": [r["verdict"] for r in results],
        "ok": counts.get("pass", 0) == RUNS,
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("SUMMARY", json.dumps(summary))
    if not summary["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
