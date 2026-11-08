#!/usr/bin/env python3
"""Phone Agent Zero flaky-refresh test.

Loads the current kiosk StickLink join URL in an iPhone viewport, then
reloads N times (~1 minute apart) and scores each load:
  pass / black / broken_layout / splash_stuck / error

This matches the user test: refresh screen produces different results.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import paramiko
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "state" / "phone-refresh-flaky"
OUT.mkdir(parents=True, exist_ok=True)
pw = Path.home().joinpath(".grokbot", "s60pw").read_text(encoding="utf-8").strip()

RUNS = 6
GAP_SEC = 60
IPHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
}


def log(msg: str):
    line = f"{time.strftime('%H:%M:%S')} flaky: {msg}"
    print(line, flush=True)
    with (OUT / "log.txt").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def kiosk_join_url() -> str:
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
        doc = json.loads(o.read().decode("utf-8", "replace"))
    finally:
        c.close()
    url = str(doc.get("url") or "").strip()
    if not url:
        raise RuntimeError(f"no join url: {doc}")
    return url


SCORE_JS = """() => {
  const body = document.body;
  const text = (body && body.innerText || '').trim();
  const title = document.title || '';
  const bg = getComputedStyle(document.documentElement).backgroundColor
    || getComputedStyle(body || document.documentElement).backgroundColor;
  const chat = document.querySelector('#chat-input');
  const send = document.querySelector('#send-button');
  const hist = document.querySelector('#chat-history');
  const right = document.querySelector('#right-panel');
  const left = document.querySelector('#left-panel');
  const splash = /starting agent zero/i.test(text) && text.length < 80;
  const rect = (el) => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return {
      w: Math.round(r.width), h: Math.round(r.height),
      x: Math.round(r.x), y: Math.round(r.y),
      display: s.display, visibility: s.visibility, opacity: s.opacity
    };
  };
  const chatR = rect(chat);
  const histR = rect(hist);
  const rightR = rect(right);
  const sendR = rect(send);
  const visibleChat = !!(chatR && chatR.w > 40 && chatR.h > 20 && chatR.opacity !== '0');
  const visibleSend = !!(sendR && sendR.w > 10 && sendR.h > 10);
  const histOk = !!(histR && histR.w > 50 && histR.h > 50);
  const rightOk = !!(rightR && rightR.w > 100 && rightR.h > 100);
  const hasWelcome = /how can i help|ask anything|agent zero/i.test(text);
  const hasNav = /chats|quick actions|hello/i.test(text);
  const nearlyEmpty = text.length < 40;
  let verdict = 'pass';
  if (splash) verdict = 'splash_stuck';
  else if (nearlyEmpty && !visibleChat) verdict = 'black';
  else if (!visibleChat || !visibleSend) verdict = 'broken_layout';
  else if (!histOk && !hasWelcome) verdict = 'broken_layout';
  else if (visibleChat && visibleSend && (hasWelcome || hasNav || histOk || rightOk)) verdict = 'pass';
  else verdict = 'broken_layout';
  return {
    verdict, title, textLen: text.length, textHead: text.slice(0, 160).replace(/\\s+/g,' '),
    bg, visibleChat, visibleSend, histOk, rightOk, splash,
    chatR, histR, rightR, sendR, href: location.href
  };
}"""


def score_page(page, run: int) -> dict:
    page.wait_for_timeout(8000)
    data = page.evaluate(SCORE_JS)
    shot = OUT / f"run-{run:02d}-{data.get('verdict')}.png"
    page.screenshot(path=str(shot), full_page=True)
    data["screenshot"] = str(shot)
    data["run"] = run
    data["at"] = time.strftime("%H:%M:%S")
    return data


def main():
    (OUT / "log.txt").write_text("", encoding="utf-8")
    join = kiosk_join_url()
    log(f"join URL (fixed for series): {join}")
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(**IPHONE)
        page = context.new_page()
        page.set_extra_http_headers({"X-StickLLM-Client": "ui"})

        for i in range(1, RUNS + 1):
            log(f"RUN {i}/{RUNS} — {'initial load' if i == 1 else 'refresh (reload)'}")
            t0 = time.time()
            try:
                if i == 1:
                    page.goto(join, wait_until="domcontentloaded", timeout=90000)
                else:
                    page.reload(wait_until="domcontentloaded", timeout=90000)
                data = score_page(page, i)
            except Exception as e:
                data = {
                    "run": i,
                    "at": time.strftime("%H:%M:%S"),
                    "verdict": "error",
                    "error": str(e),
                    "screenshot": None,
                }
                try:
                    page.screenshot(path=str(OUT / f"run-{i:02d}-error.png"), full_page=True)
                except Exception:
                    pass
            data["elapsed_s"] = round(time.time() - t0, 1)
            results.append(data)
            log(
                f"RUN {i} => {data.get('verdict')} "
                f"chat={data.get('visibleChat')} send={data.get('visibleSend')} "
                f"histOk={data.get('histOk')} textLen={data.get('textLen')} "
                f"head={data.get('textHead', '')[:80]!r}"
            )
            (OUT / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
            if i < RUNS:
                log(f"sleep {GAP_SEC}s before next refresh…")
                time.sleep(GAP_SEC)

        browser.close()

    counts: dict[str, int] = {}
    for r in results:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    summary = {
        "ok": counts.get("pass", 0) == RUNS,
        "join": join,
        "runs": RUNS,
        "gap_sec": GAP_SEC,
        "counts": counts,
        "verdicts": [r["verdict"] for r in results],
        "out": str(OUT),
    }
    (OUT / "SUMMARY.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("SUMMARY", json.dumps(summary))
    if counts.get("pass", 0) < RUNS:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
