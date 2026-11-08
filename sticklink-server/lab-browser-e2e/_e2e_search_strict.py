#!/usr/bin/env python3
"""Strict remint + tunnel search: require THIS context to finish with a real answer."""
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
    print(f"{time.strftime('%H:%M:%S')} e2e: {msg}", flush=True)


def ssh_sh(cmd: str, timeout: int = 40) -> str:
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
        _i, out, _e = c.exec_command(cmd, timeout=timeout)
        return out.read().decode("utf-8", "replace")
    finally:
        c.close()


def remint() -> str:
    before = json.loads(ssh_sh("cat /run/stickllm/sticklink-join.json")).get("url") or ""
    log(f"before {before}")
    log(
        "refresh "
        + ssh_sh(
            "curl -s -X POST -H 'Content-Type: application/json' "
            "-H 'X-StickLLM-Client: ui' -d '{}' "
            "http://127.0.0.1/api/pair/sticklink-join-refresh"
        ).strip()
    )
    deadline = time.time() + 90
    while time.time() < deadline:
        time.sleep(2)
        url = json.loads(ssh_sh("cat /run/stickllm/sticklink-join.json")).get("url") or ""
        if url and url != before:
            log(f"reminted {url}")
            return url
    raise RuntimeError("remint timeout")


def opener():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=CTX),
    )


def call(op, base: str, method: str, path: str, data=None, headers=None):
    body = None if data is None else json.dumps(data).encode()
    h = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "StickLink-e2e-strict",
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
            return r.status, {"html": True, "n": len(raw)}, raw
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            doc = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            doc = {"raw": raw[:500].decode("utf-8", "replace")}
        return e.code, doc, raw


def extract_answers(poll: dict, after_no: int = -1) -> list[str]:
    out = []
    log_items = poll.get("logs") or poll.get("log")
    if not isinstance(log_items, list):
        return out
    for item in log_items:
        if not isinstance(item, dict):
            continue
        if int(item.get("no") or 0) <= after_no:
            continue
        typ = str(item.get("type") or "").lower()
        content = item.get("content") or item.get("text") or ""
        if isinstance(content, dict):
            content = json.dumps(content)
        content = str(content)
        if typ == "response" and content.strip():
            out.append(content)
        if typ in ("tool", "code_exe") and "search" in content.lower():
            out.append(content)
    return out


def main():
    join = remint()
    time.sleep(2)
    m = re.match(r"(https://[^/]+)", join)
    assert m
    base = m.group(1) + "/agent-zero"
    op = opener()

    st, home, _ = call(op, base, "GET", "/")
    log(f"home {st}")
    assert st == 200

    st, csrf, _ = call(op, base, "GET", "/api/csrf_token")
    assert st == 200 and csrf.get("token")
    tok = csrf["token"]
    hdr = {"X-CSRF-Token": tok, "X-CSRFToken": tok}

    prompt = (
        "Use the search tool / web search. "
        "Search for restaurants in St. George's Grenada. "
        "Then reply with exactly two restaurant names, one per line, nothing else."
    )
    # Snapshot log cursor so we only accept answers to THIS prompt.
    st0, poll0, _ = call(op, base, "POST", "/api/poll", {"context": "", "log_from": 0}, hdr)
    # Prefer a fresh chat if API supports it; else reuse and track log_no.
    before_no = -1
    if st0 == 200 and isinstance(poll0.get("logs"), list) and poll0["logs"]:
        before_no = int(poll0["logs"][-1].get("no") or -1)

    st, msg, _ = call(
        op,
        base,
        "POST",
        "/api/message_async",
        {"text": prompt, "message_id": f"e2e-{int(time.time())}"},
        hdr,
    )
    log(f"message_async {st} {msg}")
    assert st == 200, msg
    ctx = msg.get("context")
    assert ctx

    # Re-baseline after message lands on the returned context.
    st0, poll0, _ = call(op, base, "POST", "/api/poll", {"context": ctx, "log_from": 0}, hdr)
    if st0 == 200 and isinstance(poll0.get("logs"), list):
        for item in poll0["logs"]:
            if item.get("type") == "user" and "exactly two restaurant names" in str(
                item.get("content") or ""
            ):
                before_no = int(item.get("no") or before_no)
        if before_no < 0 and poll0["logs"]:
            before_no = int(poll0["logs"][-1].get("no") or before_no)
    log(f"baseline after user log no={before_no}")

    deadline = time.time() + 240
    last_answers: list[str] = []
    saw_search = False
    while time.time() < deadline:
        time.sleep(4)
        st, poll, raw = call(op, base, "POST", "/api/poll", {"context": ctx, "log_from": 0}, hdr)
        if st != 200:
            log(f"poll fail {st}")
            continue
        ctx_meta = None
        for c in poll.get("contexts") or []:
            if c.get("id") == ctx:
                ctx_meta = c
                break
        running = bool(ctx_meta and ctx_meta.get("running"))
        answers = extract_answers(poll, after_no=before_no)
        if answers:
            last_answers = answers
        # Only credit search markers after our prompt.
        recent = [
            it
            for it in (poll.get("logs") or [])
            if isinstance(it, dict) and int(it.get("no") or 0) > before_no
        ]
        recent_blob = json.dumps(recent).lower()
        if any(
            k in recent_blob
            for k in (
                "search_engine",
                "response_search",
                "searx",
                '"tool_name": "search',
                "web_search",
                "finding restaurants",
                "search for restaurants",
            )
        ):
            saw_search = True
        log(
            f"ctx running={running} log_len={(ctx_meta or {}).get('log_length')} "
            f"answers={len(answers)} search={saw_search} after_no={before_no}"
        )
        if answers:
            for a in answers[-3:]:
                log(f"ANSWER_SNIP {a[:240].replace(chr(10), ' | ')}")
        if not running and answers:
            joined = "\n".join(answers)
            lines = [ln.strip("` ").strip() for ln in joined.splitlines() if ln.strip()]
            useful = [
                ln
                for ln in lines
                if len(ln) > 2
                and not ln.lower().startswith("```")
                and "search tool" not in ln.lower()
                and "st. george" not in ln.lower()
                and "plaintext" not in ln.lower()
            ]
            if useful and saw_search:
                log("PASS")
                print("FINAL_ANSWERS")
                print("\n".join(useful[:12]))
                print(
                    "META",
                    json.dumps(
                        {
                            "ok": True,
                            "context": ctx,
                            "join": join,
                            "saw_search": saw_search,
                            "names": useful[:8],
                        }
                    ),
                )
                return
    raise SystemExit(
        "FAIL timeout; last answers=" + json.dumps(last_answers)[:1500]
    )


if __name__ == "__main__":
    main()
