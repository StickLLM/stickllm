#!/usr/bin/env python3
"""Rendered Agent Zero UI search E2E over StickLink (not mux API shortcuts).

Opens the StickLink browser client, types a web-search prompt into the rendered
A0 chat UI, sends it, waits for search-tool activity and a finished assistant
reply in the chat DOM (not API-only shortcuts, not chrome text).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
PORT = int(__import__("os").environ.get("SL_PORT_HTTP", "8785"))
WS = __import__("os").environ.get("SL_WS", "wss://link.stickllm.com/v1/ws")
LOG = STATE / "logs" / "rendered-ui-search.log"


def log(msg: str):
    line = f"{time.strftime('%H:%M:%S')} ui-search: {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


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
    raise SystemExit("FAIL: no Method C QR — is run_phone_join_lab.py running?")


def join_url(qr: str) -> str:
    return (
        f"http://127.0.0.1:{PORT}/browser/agent_join.html"
        f"?ws={quote(WS, safe='')}&qr={quote(qr, safe='')}"
    )


def chat_snapshot(page) -> dict:
    return page.evaluate(
        """() => {
          const doc = document.getElementById('a0frame')?.contentDocument;
          if (!doc) return { ok: false };
          const input = doc.getElementById('chat-input');
          const stop = doc.querySelector('#stop-button, .stop-button, button.stop, [data-action=\"stop\"]');
          const progress = doc.querySelector('#progress-bar, .progress-bar, .progress');
          const users = [...doc.querySelectorAll('.message-user')]
            .map(el => (el.innerText || '').trim());
          const agents = [...doc.querySelectorAll('.message-agent-response, .message-agent, .message-ai')]
            .map(el => (el.innerText || '').trim());
          const processes = [...doc.querySelectorAll('.process-group')]
            .map(el => (el.innerText || '').trim());
          const hist = doc.querySelector('#chat-history, #messages, .messages, .chat-history, #chat');
          const histText = hist ? (hist.innerText || '') : (doc.body ? doc.body.innerText : '');
          const inputText = String(input && (input.value || input.innerText) || '');
          const thinking = /A0:\\s*Thinking/i.test(histText)
            || /A0:\\s*Thinking/i.test(inputText)
            || /Calling LLM/i.test(inputText);
          const waiting = /Waiting for input/i.test(inputText);
          const stopVisible = !!(stop && stop.offsetParent !== null);
          const srcSearch = /SRC\\s+Searching/i.test(histText);
          return {
            ok: true,
            input: inputText,
            users, agents, processes, histText: histText.slice(0, 40000),
            thinking, waiting, stopVisible, srcSearch,
            progressText: progress ? (progress.innerText || progress.getAttribute('aria-valuenow') || '') : '',
          };
        }"""
    )


def main() -> int:
    LOG.write_text("", encoding="utf-8")
    tag = f"ui-search-{int(time.time())}"
    prompt = (
        f"[{tag}] Use web search. Find restaurants in St. George's Grenada. "
        "Reply with exactly two restaurant names, one per line, nothing else."
    )
    qr = wait_qr()
    log(f"QR ok {qr[:36]}…")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        posts: list[str] = []
        page.on(
            "request",
            lambda r: posts.append(r.url)
            if r.method == "POST" and "/agent-zero/api/" in r.url
            else None,
        )

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
        log("StickLink client paired; A0 iframe live")

        frame = page.frame_locator("#a0frame")
        frame.locator("#chat-input").wait_for(state="visible", timeout=120000)
        asset = page.evaluate(
            """async () => {
              const w = document.getElementById('a0frame').contentWindow;
              const r = await w.fetch('/agent-zero/index.js', { cache: 'no-store' });
              return {
                base: w.document.querySelector('base')?.getAttribute('href') || null,
                indexJs: { status: r.status, n: (await r.arrayBuffer()).byteLength },
              };
            }"""
        )
        log(f"frame assets {asset}")
        if asset.get("indexJs", {}).get("status") != 200:
            raise SystemExit(f"FAIL index.js {asset}")

        boot = page.evaluate(
            """async () => {
              const w = document.getElementById('a0frame').contentWindow;
              const doc = w.document;
              const r = await w.fetch('/agent-zero/api/banners', {
                method: 'POST',
                headers: {'Content-Type':'application/json','X-StickLLM-Client':'ui'},
                body: '{}',
              });
              const j = await r.json().catch(() => ({}));
              const ids = (j.banners || []).map(b => b && b.id).filter(Boolean);
              return {
                hasUx: !!doc.querySelector('[data-stickllm-lab-ux]'),
                hasBridge: !!doc.querySelector('[data-sticklink-ws-bridge]'),
                unsecured: ids.includes('unsecured-connection'),
                hasSend: !!doc.getElementById('send-button'),
              };
            }"""
        )
        log(f"boot {boot}")
        if boot.get("unsecured"):
            raise SystemExit("FAIL: unsecured-connection banner still present")
        if not boot.get("hasSend"):
            raise SystemExit("FAIL: #send-button missing in rendered UI")

        chat = frame.locator("#chat-input")
        send_btn = frame.locator("#send-button")
        chat.click()
        chat.fill("")
        chat.press_sequentially(prompt, delay=4)
        # Requirement 2b: send ONLY via the rendered Send button (no Enter shortcut).
        posts_before = len(posts)
        send_btn.click()
        log("clicked rendered #send-button (no Enter fallback)")

        def user_visible(snap: dict) -> bool:
            return any(tag in u for u in snap.get("users") or []) or (
                tag in (snap.get("histText") or "") and tag not in (snap.get("input") or "")
            )

        t0 = time.time()
        while time.time() - t0 < 45:
            if user_visible(chat_snapshot(page)) and any(
                "message_async" in u for u in posts[posts_before:]
            ):
                break
            time.sleep(0.5)
        else:
            page.screenshot(path=str(STATE / "logs" / "rendered-ui-search-FAIL-send.png"), full_page=True)
            raise SystemExit(
                "FAIL: #send-button click did not deliver prompt "
                f"(message_async after click={any('message_async' in u for u in posts[posts_before:])})"
            )
        log("user message + message_async OK via Send button")

        search_re = re.compile(
            r"SRC\s+Searching|search_engine|searx|duckduckgo|perform a web search|Searching the web|search results",
            re.I,
        )
        line_junk_re = re.compile(
            r"Thinking\.\.\.|Calling LLM|content_copy|volume_up|fork_right|Quick Actions|"
            r"No chats yet|How can I help|Waiting for input|Extracting restaurant|"
            r"Selecting top-rated|Reading /a0/|Current Date and Time|Project File Structure|"
            r"^manage_search\b|^\*\*",
            re.I,
        )
        greeting_re = re.compile(r"Hello!.*Agent Zero|I'm Agent Zero", re.I)

        def clean_agent_text(text: str) -> list[str]:
            out = []
            for ln in (text or "").splitlines():
                s = ln.strip()
                if not s or line_junk_re.search(s) or greeting_re.search(s):
                    continue
                if re.match(r"^(SRC|GEN|TXT|BWK)\b", s) or re.match(r"^A0:", s):
                    continue
                if s.startswith("http"):
                    continue
                out.append(s)
            return out

        saw_search = False
        answer = ""
        t0 = time.time()
        last_log = 0.0
        while time.time() - t0 < 300:
            snap = chat_snapshot(page)
            procs = "\n".join(snap.get("processes") or [])
            hist = snap.get("histText") or ""
            after = hist.split(tag, 1)[-1] if tag in hist else hist
            if not saw_search and (
                snap.get("srcSearch")
                or search_re.search(procs)
                or search_re.search(after)
            ):
                saw_search = True
                log("search tool / web-search activity visible after user message")

            running = bool(snap.get("thinking") or snap.get("stopVisible")) and not snap.get("waiting")
            agents = [a.strip() for a in (snap.get("agents") or []) if a and a.strip()]
            finals: list[str] = []
            for a in agents:
                useful = clean_agent_text(a)
                if useful and len(" ".join(useful)) >= 10:
                    finals.append("\n".join(useful))
            if not finals and snap.get("waiting") and saw_search:
                m = re.split(r"SRC\s+Searching[^\n]*", after, flags=re.I)
                tail = m[-1] if m else after
                useful = clean_agent_text(tail)
                if useful:
                    finals = ["\n".join(useful[-12:])]

            if saw_search and (snap.get("waiting") or not running) and finals:
                # Prefer the last non-greeting agent bubble.
                answer = finals[-1]
                if len(answer) >= 10:
                    break

            if time.time() - last_log > 15:
                last_log = time.time()
                log(
                    f"wait search={saw_search} running={running} waiting={snap.get('waiting')} "
                    f"agents={len(agents)} progress={snap.get('progressText')!r}"
                )
            time.sleep(2)

        shot = STATE / "logs" / "rendered-ui-search.png"
        page.screenshot(path=str(shot), full_page=True)
        log(f"screenshot {shot}")
        log(f"api: {[u.split('/api/')[-1].split('?')[0] for u in posts if '/api/' in u][-20:]}")

        if not saw_search:
            raise SystemExit("FAIL: no search-tool activity in rendered chat after user message")
        if not answer:
            snap = chat_snapshot(page)
            raise SystemExit(
                "FAIL: no finished assistant answer in rendered chat "
                f"(thinking={snap.get('thinking')} stop={snap.get('stopVisible')} "
                f"agents={snap.get('agents')!r})"
            )
        log(f"PASS rendered answer:\n{answer}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
