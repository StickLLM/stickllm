#!/usr/bin/env python3
"""Milestone A standalone Method C UI e2e against a live StickLLM USB.

Uses public https://link.stickllm.com join assets + USB-hosted peer.
Does NOT start or modify the frozen lab-browser-e2e phone-join process.
Real Playwright UI only (Send button + Enter); no mocked A0 responses.

Two cycles: mint kiosk QR → join → prompt + search → remint → repeat.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "out" / "methodc-standalone-e2e"
REPORT = OUT_DIR / "report.json"
BUILD_EXPECT = "methodc-lte-accept-20261108.1"
STICK = os.environ.get("SL_STICK_HOST", "192.168.72.50")
SSH_KEY = os.environ.get("SL_STICK_SSH_KEY", r"C:\StickLLM-VM\vm_ed25519")
JOIN_BASE = "https://link.stickllm.com"
CYCLES = int(os.environ.get("SL_E2E_CYCLES", "2"))


def log(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} usb-e2e: {msg}", flush=True)


def ssh(cmd: str, timeout: int = 120) -> str:
    o = [
        "ssh",
        "-i",
        SSH_KEY,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=NUL",
        "-o",
        "LogLevel=ERROR",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=15",
        f"stickllm@{STICK}",
        cmd,
    ]
    r = subprocess.run(o, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ssh failed rc={r.returncode}: {r.stderr or r.stdout}")
    return r.stdout


def http_get(url: str, timeout: float = 20) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) StickLLM-USB-E2E/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _hotfix_root(body: str, vout: str, desc: str) -> str:
    """Run a root bash body on the stick via stickllm-hotfix oneshot."""
    tmp = Path(tempfile.mkdtemp(prefix="usb-e2e-"))
    try:
        bin_d = tmp / "usr" / "local" / "bin"
        sys_d = tmp / "etc" / "systemd" / "system"
        bin_d.mkdir(parents=True)
        sys_d.mkdir(parents=True)
        (bin_d / "stickllm-vmtest").write_text(
            "#!/bin/bash\nexec >%s 2>&1\n%s\n" % (vout, textwrap.dedent(body)),
            encoding="utf-8",
            newline="\n",
        )
        (sys_d / "stickllm-vmtest.service").write_text(
            f"[Unit]\nDescription={desc}\n[Service]\nType=oneshot\n"
            "ExecStart=/bin/bash /usr/local/bin/stickllm-vmtest\n",
            encoding="utf-8",
            newline="\n",
        )
        ssh("rm -rf /tmp/stickllm-hotfix; mkdir -p /tmp/stickllm-hotfix")
        subprocess.run(
            [
                "scp",
                "-i",
                SSH_KEY,
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=NUL",
                "-o",
                "LogLevel=ERROR",
                "-P",
                "22",
                "-r",
                str(tmp / "usr"),
                str(tmp / "etc"),
                f"stickllm@{STICK}:/tmp/stickllm-hotfix/",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        out = ssh(
            "sudo -n stickllm-hotfix stickllm-vmtest.service >/dev/null 2>/tmp/e.err; "
            f"rc=$?; cat {vout} 2>/dev/null; cat /tmp/e.err 2>/dev/null; "
            "rm -rf /tmp/stickllm-hotfix; exit $rc",
            timeout=180,
        )
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _parse_join_json(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        raise RuntimeError(f"no join json in output: {text[-500:]}")
    # Prefer last JSON object (status lines may precede).
    last = text.rfind("\n{")
    if last >= 0:
        start = last + 1
    doc = json.loads(text[start:])
    if not str(doc.get("url", "")).startswith("https://link.stickllm.com/"):
        raise RuntimeError(f"unexpected join url host: {doc.get('url')}")
    if not str(doc.get("qr", "")).startswith("sl1:"):
        raise RuntimeError("missing sl1 qr")
    return doc


def mint_fresh_join(*, old_qr: str | None = None) -> dict:
    """Ask USB peer for a new kiosk QR (no lab PC).

    Prefer remint.req when peer is already up; fall back to service restart.
    """
    old = (old_qr or "").replace("'", "")
    body = f"""
set -euo pipefail
export OLD_QR='{old}'
ACTIVE=$(systemctl is-active stickllm-methodc-peer || true)
if [ "$ACTIVE" = "active" ]; then
  printf '%s\\n' "{{\\"status\\":\\"requested\\",\\"at\\":$(date +%s)}}" >/run/stickllm/sticklink-join-remint.json
  date +%s >/run/stickllm/sticklink-join-remint.req
  echo MODE=remint
else
  systemctl restart stickllm-methodc-peer.service
  echo MODE=restart
fi
for i in $(seq 1 60); do
  if [ -f /run/stickllm/sticklink-join.json ]; then
    set +e
    python3 - <<'PY'
import json, time, os, sys
old = os.environ.get("OLD_QR", "")
doc = json.load(open("/run/stickllm/sticklink-join.json"))
qr = doc.get("qr") or ""
exp = int(doc.get("exp") or 0)
left = exp - int(time.time()) if exp else 99
rem = {{}}
try:
    rem = json.load(open("/run/stickllm/sticklink-join-remint.json"))
except Exception:
    pass
st = rem.get("status")
if st == "rate_limited":
    print("RATE_LIMITED", json.dumps(rem))
    sys.exit(2)
if not qr.startswith("sl1:"):
    sys.exit(1)
if old and qr == old:
    sys.exit(1)
if left < 20:
    sys.exit(1)
if os.path.exists("/run/stickllm/sticklink-join-remint.req") and st == "requested":
    sys.exit(1)
print(json.dumps(doc))
sys.exit(0)
PY
    rc=$?
    set -e
    if [ "$rc" -eq 0 ]; then exit 0; fi
    if [ "$rc" -eq 2 ]; then exit 2; fi
  fi
  sleep 1
done
echo 'TIMEOUT waiting for sticklink-join.json' >&2
journalctl -u stickllm-methodc-peer -n 40 --no-pager >&2 || true
cat /run/stickllm/sticklink-join-remint.json >&2 || true
exit 1
"""
    log("minting kiosk QR on USB peer (no lab)…")
    try:
        out = _hotfix_root(body, "/tmp/stickllm-vmtest-joine2e.out", "mint sticklink join")
    except RuntimeError as e:
        # Peer may still be in an active mux session; force restart then remint.
        log(f"remint timed out ({e}); forcing peer restart…")
        restart_body = f"""
set -euo pipefail
export OLD_QR='{old}'
rm -f /run/stickllm/sticklink-join.json /run/stickllm/sticklink-join-url.txt /run/stickllm/sticklink-join-remint.req
systemctl restart stickllm-methodc-peer.service
for i in $(seq 1 45); do
  if [ -f /run/stickllm/sticklink-join.json ]; then
    python3 - <<'PY'
import json, time, os, sys
old = os.environ.get("OLD_QR", "")
doc = json.load(open("/run/stickllm/sticklink-join.json"))
qr = doc.get("qr") or ""
exp = int(doc.get("exp") or 0)
left = exp - int(time.time()) if exp else 99
if not qr.startswith("sl1:") or (old and qr == old) or left < 20:
    sys.exit(1)
print(json.dumps(doc))
PY
    rc=$?
    if [ "$rc" -eq 0 ]; then exit 0; fi
  fi
  sleep 1
done
journalctl -u stickllm-methodc-peer -n 30 --no-pager >&2 || true
cat /run/stickllm/sticklink-join-remint.json >&2 || true
exit 1
"""
        out = _hotfix_root(restart_body, "/tmp/stickllm-vmtest-joine2e2.out", "restart mint join")
    if "RATE_LIMITED" in out:
        raise RuntimeError(f"pair.open rate-limited: {out[-400:]}")
    doc = _parse_join_json(out)
    left = int(doc.get("exp") or 0) - int(time.time())
    log(f"join ready mbx={doc.get('mbx')} left~{left}s")
    return doc


def assert_no_lab_runtime() -> None:
    """Refuse to run if the frozen lab phone-join process is accidentally up."""
    r = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            # Match the lab scripts as argv only (avoid false positives from editors/agents).
            "Get-CimInstance Win32_Process | "
            "Where-Object { "
            "  $_.Name -match 'python' -and "
            "  $_.CommandLine -match '(^|[\\\\/\\s])run_phone_join_lab\\.py|(^|[\\\\/\\s])kiosk_agent_session\\.py' "
            "} | Select-Object -ExpandProperty ProcessId",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    pids = [p.strip() for p in (r.stdout or "").splitlines() if p.strip()]
    if pids:
        # Best-effort stop — lab must stay frozen/off for USB-only path.
        for pid in pids:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        time.sleep(1)
        r2 = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | "
                "Where-Object { "
                "  $_.Name -match 'python' -and "
                "  $_.CommandLine -match '(^|[\\\\/\\s])run_phone_join_lab\\.py|(^|[\\\\/\\s])kiosk_agent_session\\.py' "
                "} | Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        left = [p.strip() for p in (r2.stdout or "").splitlines() if p.strip()]
        if left:
            raise RuntimeError(
                f"lab phone-join still running (pids {left}) — stop it; this e2e is USB-only"
            )
        log(f"stopped leftover lab phone-join pids {pids}")


def chat_snap(page) -> dict:
    return page.evaluate(
        """() => {
          const doc = document.getElementById('a0frame')?.contentDocument;
          if (!doc) return { ok:false };
          const input = doc.getElementById('chat-input');
          const users = [...doc.querySelectorAll('.message-user')].map(e => (e.innerText||'').trim());
          const agents = [...doc.querySelectorAll(
            '.message-agent-response,.message-agent,.message-ai,.message.agent,.chat-message-agent'
          )].map(e => (e.innerText||'').trim()).filter(Boolean);
          const hist = (doc.querySelector('#chat-history,#messages,.messages') || doc.body).innerText || '';
          const waiting = /Waiting for input/i.test(String(input && (input.value||input.innerText)||''));
          const typing = !!(
            doc.querySelector('.typing-indicator,.message-typing,.loader,.progress') ||
            [...doc.querySelectorAll('.message')].some(m => /^(…|\\.\\.\\.|•••)$/.test((m.innerText||'').trim()))
          );
          return {
            ok:true,
            input: String(input && (input.value||input.innerText)||''),
            users, agents, hist, waiting, typing,
            agentCount: agents.length,
          };
        }"""
    )


def wait_idle(page, tag: str, timeout_s: float = 240, *, need_substr: str | None = None) -> dict:
    t0 = time.time()
    last: dict = {}
    while time.time() - t0 < timeout_s:
        last = chat_snap(page)
        hist = last.get("hist") or ""
        users = "\n".join(last.get("users") or [])
        agents = "\n".join(last.get("agents") or [])
        if tag in hist or tag in users:
            if need_substr and need_substr in agents:
                if not last.get("typing"):
                    return last
            elif agents.strip() and not last.get("typing") and not last.get("waiting"):
                if need_substr is None:
                    return last
        time.sleep(1.5)
    return last


def dismiss_overlays(page, frame) -> None:
    for _ in range(4):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        try:
            frame.locator(
                ".modal.show .close, .modal.show [data-dismiss], .modal.show button:has-text('Close')"
            ).first.click(timeout=800, force=True)
        except Exception:
            pass
        try:
            if frame.locator(".modal.show").count() == 0:
                break
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


def send_via_button(page, frame, prompt: str, tag: str) -> None:
    dismiss_overlays(page, frame)
    chat = frame.locator("#chat-input")
    chat.click(force=True)
    chat.press("Control+A")
    chat.press_sequentially(prompt, delay=3)
    frame.locator("#send-button").click(force=True)
    log(f"clicked #send-button for {tag}")


def send_via_enter(page, frame, prompt: str, tag: str) -> None:
    dismiss_overlays(page, frame)
    chat = frame.locator("#chat-input")
    chat.click(force=True)
    chat.press("Control+A")
    chat.press_sequentially(prompt, delay=3)
    chat.press("Enter")
    log(f"pressed Enter for {tag}")


def run_a0_cycle(page, label: str) -> dict:
    """One joined session: exact reply + web-search prompt."""
    out: dict = {"label": label, "messages": []}
    frame = page.frame_locator("#a0frame")
    frame.locator("#chat-input").wait_for(state="visible", timeout=240000)
    page.wait_for_timeout(1500)
    dismiss_overlays(page, frame)

    tag1 = f"{label}-btn-{int(time.time())}"
    send_via_button(page, frame, f"[{tag1}] Reply with exactly: BUTTON_OK", tag1)
    snap1 = wait_idle(page, tag1, 300, need_substr="BUTTON_OK")
    agents1 = "\n".join(snap1.get("agents") or [])
    ok1 = "BUTTON_OK" in agents1
    out["messages"].append(
        {
            "tag": tag1,
            "via": "send-button",
            "ok": bool(ok1),
            "agentTail": agents1[-400:],
        }
    )
    log(f"{label} msg1 ok={ok1}")
    if not ok1:
        page.screenshot(path=str(OUT_DIR / f"{label}-msg1-fail.png"), full_page=True)

    tag2 = f"{label}-search-{int(time.time())}"
    # Avoid the phrase "web search" in the user prompt — that used to false-pass hist matching.
    prompt2 = (
        f"[{tag2}] Call the search_engine tool. Find restaurants in St. George's Grenada. "
        "After tools finish, reply with exactly two restaurant names, one per line, nothing else."
    )
    agents_before = "\n".join(chat_snap(page).get("agents") or [])
    send_via_enter(page, frame, prompt2, tag2)
    t_search = time.time()
    search_ok = False
    answer_ok = False
    agents2 = ""
    hist2 = ""
    while time.time() - t_search < 300:
        snap2 = chat_snap(page)
        hist2 = snap2.get("hist") or ""
        agents2 = "\n".join(snap2.get("agents") or [])
        # Tool/search markers in history (not the user prompt wording).
        search_ok = bool(
            re.search(
                r"SRC\s+Searching|search_engine|Using tool|Tool:\s*search|Searx|searxng",
                hist2,
                re.I,
            )
        )
        # New agent text beyond the previous BUTTON_OK reply.
        new_agent = agents2[len(agents_before) :] if agents2.startswith(agents_before) else agents2
        # Require restaurant-like answer lines (not just BUTTON_OK / greeting).
        answer_ok = bool(
            re.search(r"[A-Za-z][A-Za-z0-9'&.,\- ]{3,}", new_agent)
            and ("BUTTON_OK" not in new_agent or len(new_agent) > 40)
            and not snap2.get("typing")
            and tag2 in (hist2 + "\n" + "\n".join(snap2.get("users") or []))
        )
        if search_ok and answer_ok:
            break
        time.sleep(2)
    ok2 = bool(search_ok and answer_ok)
    out["messages"].append(
        {
            "tag": tag2,
            "via": "enter-search",
            "ok": ok2,
            "searchSeen": search_ok,
            "answerSeen": answer_ok,
            "agentTail": agents2[-500:],
            "histTail": hist2[-500:],
        }
    )
    log(f"{label} msg2 search={search_ok} answer={answer_ok}")
    if not ok2:
        page.screenshot(path=str(OUT_DIR / f"{label}-search-fail.png"), full_page=True)

    out["ok"] = all(m.get("ok") for m in out["messages"])
    page.screenshot(path=str(OUT_DIR / f"{label}-final.png"), full_page=True)
    return out


def pair_join(page, join_url: str) -> dict:
    page.goto(join_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_function(
        "() => !!(window.__sticklinkA0 && window.__sticklinkA0.mux) || !!window.__sticklinkFail",
        timeout=240000,
    )
    fail = page.evaluate("() => window.__sticklinkFail || null")
    if fail:
        raise RuntimeError(f"FAIL pair: {fail}")
    page.wait_for_function("() => document.body.classList.contains('a0-live')", timeout=90000)
    meta = page.evaluate(
        """() => ({
          build: window.__sticklinkBuild || window.__sticklinkA0?.build || null,
          ice: window.__sticklinkIce || window.__sticklinkA0?.ice || null,
        })"""
    )
    log(f"paired build={meta.get('build')} ice={meta.get('ice')}")
    return meta


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "joinBase": JOIN_BASE,
        "stick": STICK,
        "buildExpected": BUILD_EXPECT,
        "noLabPc": True,
        "cycles": CYCLES,
        "pathChecks": {},
        "cycleResults": [],
        "messages": [],
        "ice": None,
        "buildActual": None,
        "verdictNotes": [],
    }

    assert_no_lab_runtime()
    report["labPhoneJoinRunning"] = False

    for path, expect, body_need in [
        ("/browser/agent_join.html", 200, "StickLink"),
        ("/lab/ice", 200, "iceServers"),
        ("/agent-zero/", 404, "a0_via_sticklink_dc_only"),
        ("/api/csrf", 404, "a0_via_sticklink_dc_only"),
    ]:
        code, body = http_get(JOIN_BASE + path)
        report["pathChecks"][path] = {"status": code, "body": body[:120]}
        ok = code == expect and (not body_need or body_need in body)
        log(f"probe {path} -> {code} ok={ok}")
        if not ok:
            report["verdictNotes"].append(f"probe_fail {path} status={code}")

    console_errors: list[str] = []
    page_errors: list[str] = []
    old_qr: str | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for i in range(1, CYCLES + 1):
            label = f"c{i}"
            log(f"===== cycle {i}/{CYCLES} =====")
            doc = mint_fresh_join(old_qr=old_qr)
            old_qr = doc["qr"]
            join_url = doc["url"]
            report.setdefault("qrs", []).append(doc["qr"][:48])
            report["joinUrlHost"] = JOIN_BASE

            page = browser.new_page()
            page.on(
                "console",
                lambda m: console_errors.append(f"{m.type}: {m.text}")
                if m.type in ("error", "warning")
                else None,
            )
            page.on("pageerror", lambda e: page_errors.append(str(e)))
            try:
                meta = pair_join(page, join_url)
                report["buildActual"] = meta.get("build")
                report["ice"] = meta.get("ice")
                cycle = run_a0_cycle(page, label)
                cycle["qrPrefix"] = doc["qr"][:32]
                cycle["mbx"] = doc.get("mbx")
                report["cycleResults"].append(cycle)
                report["messages"].extend(cycle["messages"])
                if not cycle["ok"]:
                    report["verdictNotes"].append(f"{label}_failed")
            finally:
                page.close()

            # Brief pause before remint so peer finishes teardown cleanly.
            if i < CYCLES:
                time.sleep(3)

        browser.close()

    report["consoleErrors"] = [c for c in console_errors if "favicon" not in c.lower()][:40]
    report["pageErrors"] = page_errors[:20]
    REPORT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log(f"wrote {REPORT}")

    hard = []
    if report.get("buildActual") != BUILD_EXPECT:
        hard.append("build")
    if report["pathChecks"].get("/agent-zero/", {}).get("status") != 404:
        hard.append("a0_bootstrap")
    if len(report.get("cycleResults") or []) != CYCLES:
        hard.append("cycle_count")
    if not all(c.get("ok") for c in report.get("cycleResults") or []):
        hard.append("cycles")
    if len(set(report.get("qrs") or [])) < CYCLES:
        hard.append("qr_unique")
    if hard:
        raise SystemExit(f"STANDALONE_GAPS {hard} — see {REPORT}")
    log("STANDALONE_UI_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
