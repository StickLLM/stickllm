#!/usr/bin/env python3
"""Full cycle the user asked for:
1) Connect via current kiosk QR URL
2) Send prompt + search, get result
3) Disconnect
4) Kiosk Refresh → new QR
5) Connect via new QR, search again, get result
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
    print(f"{time.strftime('%H:%M:%S')} cycle: {msg}", flush=True)


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


def kiosk_url(c) -> str:
    doc = json.loads(
        sh(
            c,
            "curl -s -H 'X-StickLLM-Client: ui' http://127.0.0.1/api/pair/sticklink-join",
        )
    )
    if not doc.get("ok", True) and not doc.get("url"):
        raise RuntimeError(f"kiosk join unavailable: {doc}")
    url = str(doc.get("url") or "")
    if not url:
        raise RuntimeError(f"no kiosk url: {doc}")
    return url


def opener():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        urllib.request.HTTPSHandler(context=CTX),
    )


def call(op, base: str, method: str, path: str, data=None, headers=None):
    body = None if data is None else json.dumps(data).encode()
    h = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "StickLink-full-cycle-e2e",
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


def base_from_join(join: str) -> str:
    m = re.match(r"(https://[^/]+)", join)
    if not m:
        raise RuntimeError(f"bad join {join}")
    return m.group(1) + "/agent-zero"


def wait_home(op, base: str) -> None:
    last = None
    for attempt in range(1, 20):
        try:
            st, _, raw = call(op, base, "GET", "/")
            last = (st, raw[:120])
            if st == 200 and b"bad gateway" not in raw.lower()[:500]:
                log(f"connected home 200 attempt={attempt}")
                return
            if st in (502, 503, 504) or b"bad gateway" in raw.lower()[:500]:
                log(f"bad gateway attempt={attempt}")
        except Exception as e:
            last = e
            log(f"connect error attempt={attempt}: {e}")
        time.sleep(2)
    raise RuntimeError(f"could not connect: {last}")


def search_once(op, base: str, tag: str) -> list[str]:
    st, csrf, _ = call(op, base, "GET", "/api/csrf_token")
    if st != 200 or not csrf.get("token"):
        raise RuntimeError(f"csrf fail {st} {csrf}")
    tok = csrf["token"]
    hdr = {"X-CSRF-Token": tok, "X-CSRFToken": tok}
    prompt = (
        f"[{tag}] Use web search. Find restaurants in St. George's Grenada. "
        "Reply with exactly two restaurant names, one per line, nothing else."
    )
    st, msg, _ = call(
        op,
        base,
        "POST",
        "/api/message_async",
        {"text": prompt, "message_id": f"cycle-{tag}-{int(time.time())}"},
        hdr,
    )
    log(f"[{tag}] message_async {st} {msg}")
    if st != 200:
        raise RuntimeError(f"message_async {st} {msg}")
    ctx = msg["context"]

    st0, poll0, _ = call(op, base, "POST", "/api/poll", {"context": ctx, "log_from": 0}, hdr)
    before_no = -1
    for item in poll0.get("logs") or []:
        if item.get("type") == "user" and f"[{tag}]" in str(item.get("content") or ""):
            before_no = int(item.get("no") or before_no)
    log(f"[{tag}] baseline no={before_no}")

    deadline = time.time() + 180
    while time.time() < deadline:
        time.sleep(4)
        st, poll, raw = call(op, base, "POST", "/api/poll", {"context": ctx, "log_from": 0}, hdr)
        if st in (502, 503, 504) or b"bad gateway" in raw.lower()[:400]:
            raise RuntimeError(f"[{tag}] Bad Gateway during poll ({st})")
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
        log(f"[{tag}] running={running} answers={len(answers)} search={saw}")
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
                        and not ln.startswith("[")
                    ):
                        useful.append(ln)
            if not useful:
                raise RuntimeError(f"[{tag}] empty useful answers: {answers}")
            log(f"[{tag}] SEARCH RESULT: {useful[:4]}")
            return useful[:6]
    raise RuntimeError(f"[{tag}] timeout waiting for search result")


def disconnect(op, base: str) -> None:
    """Drop session cookies / stop using this join (phone close equivalent)."""
    try:
        call(op, base, "POST", "/api/poll", {"context": "", "log_from": 0}, None)
    except Exception:
        pass
    # New opener = new cookie jar = disconnected browser
    log("disconnected (dropped cookies / closed client)")


def remint_kiosk(c, before: str) -> str:
    refresh = json.loads(
        sh(
            c,
            "curl -s -X POST -H 'Content-Type: application/json' "
            "-H 'X-StickLLM-Client: ui' -d '{}' "
            "http://127.0.0.1/api/pair/sticklink-join-refresh",
        )
    )
    log(f"kiosk Refresh: {refresh}")
    if refresh.get("ok") is not True:
        raise RuntimeError(f"refresh failed: {refresh}")
    deadline = time.time() + 120
    while time.time() < deadline:
        time.sleep(2)
        after = kiosk_url(c)
        if after and after != before:
            log(f"new kiosk QR URL: {after}")
            return after
        log("waiting for new kiosk QR…")
    raise RuntimeError("kiosk QR did not change after Refresh")


def main():
    c = ssh()
    join1 = kiosk_url(c)
    log(f"STEP1 kiosk QR: {join1}")
    c.close()

    base1 = base_from_join(join1)
    op1 = opener()
    wait_home(op1, base1)
    names1 = search_once(op1, base1, "pass1")
    disconnect(op1, base1)
    del op1

    c = ssh()
    join2 = remint_kiosk(c, join1)
    c.close()
    if join2 == join1:
        raise SystemExit("FAIL: QR URL unchanged after Refresh")

    base2 = base_from_join(join2)
    op2 = opener()
    wait_home(op2, base2)
    names2 = search_once(op2, base2, "pass2")
    disconnect(op2, base2)

    print(
        "CYCLE_PASS",
        json.dumps(
            {
                "ok": True,
                "join1": join1,
                "names1": names1,
                "join2": join2,
                "names2": names2,
                "qr_changed": join1 != join2,
            }
        ),
    )


if __name__ == "__main__":
    main()
