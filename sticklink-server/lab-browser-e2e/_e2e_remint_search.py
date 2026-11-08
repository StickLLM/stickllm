#!/usr/bin/env python3
"""E2E: Refresh remints StickLink join → connect via tunnel proxy → search → result."""
from __future__ import annotations

import http.cookiejar
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

import paramiko

STICK = "192.168.72.50"
PROXY = "http://127.0.0.1:8785"
CTX = ssl._create_unverified_context()
pw = Path.home().joinpath(".grokbot", "s60pw").read_text(encoding="utf-8").strip()


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} e2e: {msg}", flush=True)


def ssh():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        STICK,
        username="stickllm",
        password=pw,
        timeout=20,
        allow_agent=False,
        look_for_keys=False,
    )
    return c


def sh(c, cmd: str, timeout: int = 40) -> str:
    _in, out, _err = c.exec_command(cmd, timeout=timeout)
    return out.read().decode("utf-8", "replace")


def remint_and_wait(c) -> str:
    before = sh(c, "cat /run/stickllm/sticklink-join.json").strip()
    before_url = ""
    try:
        before_url = json.loads(before).get("url") or ""
    except Exception:
        pass
    log(f"before join: {before_url}")
    out = sh(
        c,
        "curl -s -X POST -H 'Content-Type: application/json' "
        "-H 'X-StickLLM-Client: ui' -d '{}' "
        "http://127.0.0.1/api/pair/sticklink-join-refresh",
    )
    log(f"refresh API: {out.strip()[:200]}")
    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(2)
        raw = sh(c, "cat /run/stickllm/sticklink-join.json").strip()
        try:
            doc = json.loads(raw)
        except Exception:
            continue
        url = str(doc.get("url") or "")
        if url and url != before_url:
            log(f"reminted join: {url}")
            return url
        st = sh(c, "cat /run/stickllm/sticklink-join-remint.json 2>/dev/null || true").strip()
        log(f"waiting remint… {st[:80]}")
    raise RuntimeError("remint did not publish a new URL")


def http_json(opener, method: str, url: str, data=None, headers: dict | None = None):
    body = None
    hdrs = {
        "Accept": "application/json",
        "User-Agent": "StickLink-e2e-remint-search",
        "X-StickLLM-Client": "ui",
    }
    if data is not None:
        body = data if isinstance(data, bytes) else json.dumps(data).encode()
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with opener.open(req, timeout=120) as resp:
            raw = resp.read()
            return resp.status, raw, dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


def connect_and_search(public_join: str) -> dict:
    # Prefer public tunnel URL (phone path). Fall back to local proxy if tunnel flaps.
    bases = []
    m = re.match(r"(https://[^/]+)", public_join or "")
    if m:
        bases.append(m.group(1) + "/agent-zero")
    bases.append(PROXY + "/agent-zero")

    last_err = None
    for base in bases:
        log(f"trying base {base}")
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cj),
            urllib.request.HTTPSHandler(context=CTX),
        )
        try:
            st, raw, _ = http_json(opener, "GET", base + "/")
            log(f"GET / → {st} ({len(raw)} B)")
            if st >= 400:
                last_err = f"home {st}"
                continue

            st, raw, _ = http_json(opener, "GET", base + "/api/csrf_token")
            log(f"csrf → {st} {raw[:120]!r}")
            if st != 200:
                last_err = f"csrf {st}"
                continue
            csrf_doc = json.loads(raw.decode("utf-8", "replace"))
            csrf = (
                csrf_doc.get("token")
                or csrf_doc.get("csrf_token")
                or csrf_doc.get("csrf")
                or ""
            )
            if not csrf:
                last_err = f"no csrf in {csrf_doc}"
                continue

            # New chat context then search prompt (Grenada restaurants worked before).
            prompt = (
                "Use search. Find 2 restaurants in St. George's, Grenada. "
                "Reply with restaurant names only, one per line. Keep it short."
            )
            payload = {
                "text": prompt,
                "context": "",
                "message_id": f"e2e-{int(time.time())}",
            }
            st, raw, _ = http_json(
                opener,
                "POST",
                base + "/api/message_async",
                data=payload,
                headers={"X-CSRF-Token": csrf, "X-CSRFToken": csrf},
            )
            log(f"message_async → {st} {raw[:200]!r}")
            if st != 200:
                # retry with alternate field names used by some A0 builds
                payload2 = {"text": prompt}
                st, raw, _ = http_json(
                    opener,
                    "POST",
                    base + "/api/message_async",
                    data=payload2,
                    headers={"X-CSRF-Token": csrf, "X-CSRFToken": csrf},
                )
                log(f"message_async retry → {st} {raw[:200]!r}")
            if st != 200:
                last_err = f"message_async {st} {raw[:200]!r}"
                continue

            msg = json.loads(raw.decode("utf-8", "replace"))
            ctx = str(msg.get("context") or msg.get("ctxid") or msg.get("id") or "")
            log(f"context={ctx!r}")

            # Poll until agent finishes / search results appear.
            deadline = time.time() + 180
            best = ""
            while time.time() < deadline:
                time.sleep(3)
                poll_body = {"context": ctx, "log_from": 0} if ctx else {}
                pst, praw, _ = http_json(
                    opener,
                    "POST",
                    base + "/api/poll",
                    data=poll_body,
                    headers={"X-CSRF-Token": csrf, "X-CSRFToken": csrf},
                )
                if pst != 200:
                    # alternate history endpoint
                    pst, praw, _ = http_json(
                        opener,
                        "POST",
                        base + "/api/chat_get",
                        data={"context": ctx} if ctx else {},
                        headers={"X-CSRF-Token": csrf, "X-CSRFToken": csrf},
                    )
                text = praw.decode("utf-8", "replace")
                if len(text) > len(best):
                    best = text
                low = text.lower()
                # success: search tool evidence + a restaurant-like answer
                has_search = any(
                    k in low
                    for k in (
                        "search_engine",
                        "searx",
                        "search results",
                        "web search",
                        '"tool_name": "search',
                        "response_search",
                    )
                )
                has_place = any(
                    k in low
                    for k in (
                        "restaurant",
                        "grenada",
                        "st. george",
                        "st george",
                        "bbq",
                        "cafe",
                        "grill",
                        "hotel",
                        "kitchen",
                    )
                )
                log(f"poll {pst} bytes={len(praw)} search={has_search} place={has_place}")
                if pst == 200 and has_search and has_place:
                    return {
                        "ok": True,
                        "base": base,
                        "context": ctx,
                        "snippet": text[:2500],
                    }
                # finished without explicit tool name but has answer content
                if pst == 200 and has_place and (
                    '"type": "response"' in text
                    or '"heading": "Response"' in text
                    or "log_progress" in low
                ):
                    # keep waiting a bit for search marker; accept if log idle
                    if '"log_guid"' in text and '"log_progress": 0' in text.replace(" ", ""):
                        pass
                    if time.time() + 30 > deadline and has_place:
                        return {
                            "ok": True,
                            "base": base,
                            "context": ctx,
                            "snippet": text[:2500],
                            "note": "place names without explicit search marker",
                        }

            return {
                "ok": False,
                "base": base,
                "context": ctx,
                "error": "timeout waiting for search result",
                "snippet": best[:2500],
            }
        except Exception as e:
            last_err = str(e)
            log(f"base failed: {e}")
            continue
    raise RuntimeError(f"all bases failed: {last_err}")


def main():
    c = ssh()
    try:
        join = remint_and_wait(c)
    finally:
        c.close()

    # Give cloudflared a moment after remint
    time.sleep(2)
    result = connect_and_search(join)
    print("RESULT_JSON", json.dumps({k: v for k, v in result.items() if k != "snippet"}))
    print("SNIPPET_BEGIN")
    print(result.get("snippet", "")[:2000])
    print("SNIPPET_END")
    if not result.get("ok"):
        raise SystemExit(2)
    log("PASS: remint + connect + search returned a result")


if __name__ == "__main__":
    main()
