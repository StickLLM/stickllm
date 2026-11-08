#!/usr/bin/env python3
"""Test the EXACT kiosk Refresh path: POST sticklink-join-refresh → read URL
from /api/pair/sticklink-join (what the kiosk QR encodes) → open that URL →
search → assert a real answer.
"""
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

CTX = ssl._create_unverified_context()
pw = Path.home().joinpath(".grokbot", "s60pw").read_text(encoding="utf-8").strip()


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} kiosk-e2e: {msg}", flush=True)


def ssh():
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
    return c


def sh(c, cmd: str, timeout: int = 40) -> str:
    _i, o, _e = c.exec_command(cmd, timeout=timeout)
    return o.read().decode("utf-8", "replace")


def kiosk_join_url(c) -> tuple[str, dict]:
    """Same source the kiosk QR uses: gateway /api/pair/sticklink-join."""
    raw = sh(
        c,
        "curl -s -H 'X-StickLLM-Client: ui' http://127.0.0.1/api/pair/sticklink-join",
    )
    doc = json.loads(raw)
    return str(doc.get("url") or ""), doc


def call(op, base: str, method: str, path: str, data=None, headers=None):
    body = None if data is None else json.dumps(data).encode()
    h = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "StickLink-kiosk-qr-e2e",
        "X-StickLLM-Client": "ui",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(base + path, data=body, method=method, headers=h)
    try:
        with op.open(req, timeout=120) as r:
            raw = r.read()
            ct = (r.headers.get("Content-Type") or "").lower()
            if "json" in ct or path.startswith("/api/"):
                return r.status, json.loads(raw.decode("utf-8", "replace")), raw
            return r.status, {"n": len(raw)}, raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            doc = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            doc = {"raw": raw[:400].decode("utf-8", "replace")}
        return e.code, doc, raw


def main():
    c = ssh()
    before, before_doc = kiosk_join_url(c)
    log(f"kiosk QR URL before: {before}")
    if before_doc.get("ok") is False:
        log(f"before doc: {before_doc}")

    # Exact Refresh button call
    refresh = sh(
        c,
        "curl -s -X POST -H 'Content-Type: application/json' "
        "-H 'X-StickLLM-Client: ui' -d '{}' "
        "http://127.0.0.1/api/pair/sticklink-join-refresh",
    )
    log(f"Refresh POST: {refresh.strip()}")
    refresh_doc = json.loads(refresh)
    assert refresh_doc.get("ok") is True, refresh

    deadline = time.time() + 90
    after = before
    after_doc = before_doc
    while time.time() < deadline:
        time.sleep(2)
        after, after_doc = kiosk_join_url(c)
        if after and after != before and after_doc.get("ok") is not False:
            break
        log(f"waiting new kiosk URL… remint={after_doc.get('remint')}")
    c.close()

    if not after or after == before:
        raise SystemExit(f"FAIL: kiosk URL did not change ({after!r})")
    log(f"kiosk QR URL after Refresh: {after}")

    # Hit the URL the QR encodes (public trycloudflare), not localhost.
    m = re.match(r"(https://[^/]+)", after)
    assert m, after
    base = m.group(1) + "/agent-zero"
    op = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        urllib.request.HTTPSHandler(context=CTX),
    )

    # Bad-gateway / DNS lag detection — retry briefly like a phone would refresh.
    st, raw = 0, b""
    for attempt in range(1, 16):
        try:
            st, home, raw = call(op, base, "GET", "/")
            log(f"GET join home → {st} ({len(raw)} B) attempt={attempt}")
            if st in (502, 503, 504) or b"bad gateway" in raw.lower()[:800]:
                time.sleep(2)
                continue
            if st == 200:
                break
        except Exception as e:
            log(f"GET join home error attempt={attempt}: {e}")
            time.sleep(2)
    else:
        raise SystemExit(f"FAIL: kiosk QR URL never became reachable ({st})")
    if st in (502, 503, 504) or b"bad gateway" in raw.lower()[:800]:
        raise SystemExit(f"FAIL: Bad Gateway on kiosk QR URL ({st})")
    assert st == 200, (st, raw[:200])

    st, csrf, _ = call(op, base, "GET", "/api/csrf_token")
    log(f"csrf → {st} {csrf}")
    if st in (502, 503, 504):
        raise SystemExit(f"FAIL: Bad Gateway on csrf ({st})")
    assert st == 200 and csrf.get("token"), csrf
    tok = csrf["token"]
    hdr = {"X-CSRF-Token": tok, "X-CSRFToken": tok}

    prompt = (
        "Use web search. Find restaurants in St. George's Grenada. "
        "Reply with exactly two restaurant names, one per line, nothing else."
    )
    st, msg, _ = call(
        op,
        base,
        "POST",
        "/api/message_async",
        {"text": prompt, "message_id": f"kiosk-qr-{int(time.time())}"},
        hdr,
    )
    log(f"message_async → {st} {msg}")
    assert st == 200, msg
    ctx = msg["context"]

    st0, poll0, _ = call(op, base, "POST", "/api/poll", {"context": ctx, "log_from": 0}, hdr)
    before_no = -1
    for item in poll0.get("logs") or []:
        if item.get("type") == "user" and "exactly two restaurant names" in str(
            item.get("content") or ""
        ):
            before_no = int(item.get("no") or before_no)
    log(f"baseline log no={before_no}")

    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(4)
        st, poll, raw = call(op, base, "POST", "/api/poll", {"context": ctx, "log_from": 0}, hdr)
        if st in (502, 503, 504):
            raise SystemExit(f"FAIL: Bad Gateway during poll ({st})")
        running = next(
            (x.get("running") for x in (poll.get("contexts") or []) if x.get("id") == ctx),
            None,
        )
        answers = []
        for item in poll.get("logs") or []:
            if int(item.get("no") or 0) <= before_no:
                continue
            if item.get("type") == "response" and item.get("content"):
                answers.append(str(item["content"]))
        recent = [
            it
            for it in (poll.get("logs") or [])
            if int(it.get("no") or 0) > before_no
        ]
        saw = any(
            k in json.dumps(recent).lower()
            for k in ("search", "finding restaurants", "searx")
        )
        log(f"running={running} answers={len(answers)} search={saw}")
        if answers and running is False and saw:
            useful = []
            for a in answers:
                for ln in a.splitlines():
                    ln = ln.strip("` ").strip()
                    if (
                        len(ln) > 2
                        and "plaintext" not in ln.lower()
                        and not ln.startswith("```")
                        and "st. george" not in ln.lower()
                    ):
                        useful.append(ln)
            assert useful, answers
            log("PASS kiosk QR Remint → connect → search")
            print("KIOSK_QR_URL", after)
            print("NAMES", useful[:6])
            return
    raise SystemExit("FAIL: timeout waiting for search answer via kiosk QR URL")


if __name__ == "__main__":
    main()
