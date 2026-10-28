"""Pair code is kiosk-only, and one pairing covers the main UI and Agent (:5443)."""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
PIN = ROOT / "overlay" / "usr" / "local" / "share" / "stickllm" / "agent-zero.pin"
APP_JS = ROOT / "ui" / "app.js"
TOKEN = "paired-browser-token"
CODE = "482913"


def _load(env: dict, name: str):
    os.environ.update(env)
    loader = importlib.machinery.SourceFileLoader(name, str(GATEWAY))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _setup(tmp_path, paired=True):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html></html>", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    auth = {
        "version": 2,
        "require_pair": True,
        "paired": paired,
        "code_hash": hashlib.sha256(CODE.encode()).hexdigest(),
        "token_hash": hashlib.sha256(TOKEN.encode()).hexdigest() if paired else "",
    }
    (run / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    (run / "pair-code.txt").write_text(CODE + "\n", encoding="utf-8")
    (run / "pair-remint.json").write_text(json.dumps({"id": "r1", "code": CODE}), encoding="utf-8")
    (tmp_path / "vault").mkdir()
    (tmp_path / "empty-mounts").write_text("", encoding="utf-8")
    env = {
        "STICKLLM_UI": str(ui),
        "STICKLLM_RUN": str(run),
        "STICKLLM_VAULT_MNT": str(tmp_path / "vault"),
        "STICKLLM_SETTINGS_MNT": str(tmp_path / "settings"),
        "STICKLLM_AGENT_STATUS": str(run / "agent-status.json"),
        "STICKLLM_AGENT_PIN": str(PIN),
        "STICKLLM_MOUNTS_FILE": str(tmp_path / "empty-mounts"),
        "STICKLLM_AGENT_TLS_PORT": "5443",
        "STICKLLM_LLAMA": "http://127.0.0.1:9",
        "STICKLLM_FILES_PORT": "9",
    }
    return run, env


class _Servers:
    def __init__(self, gateway, loopback: bool):
        class H(gateway.Handler):
            def _is_loopback(self) -> bool:
                return loopback

        self.main = gateway.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.agent = gateway.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.agent.stickllm_agent_gateway = True
        for srv in (self.main, self.agent):
            threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.main_port = self.main.server_address[1]
        self.agent_port = self.agent.server_address[1]

    def close(self):
        self.main.shutdown()
        self.agent.shutdown()


def _call(port, path, method="GET", headers=None, body=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
        headers=headers or {},
        data=body,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers), resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read().decode()


UI = {"X-StickLLM-Client": "ui"}
PAIRED_UI = {**UI, "Authorization": "Bearer " + TOKEN}


def test_lan_browser_never_gets_pair_code_or_ssh_password(tmp_path):
    run, env = _setup(tmp_path)
    gateway = _load(env, "stickllm_gateway_pair_lan")
    srv = _Servers(gateway, loopback=False)
    try:
        for headers in ({}, UI, PAIRED_UI, {"Cookie": "stickllm_pair=" + TOKEN, **UI}):
            code, _h, body = _call(srv.main_port, "/api/health", headers=headers)
            doc = json.loads(body)
            connect = doc.get("connect") or {}
            assert CODE not in body
            assert "pair_code" not in connect and "remint_code" not in connect
            assert not connect.get("ssh_password")
        # A LAN browser, paired or not, cannot make a new code (or unpair anyone).
        for headers in (UI, PAIRED_UI):
            code, _h, body = _call(
                srv.main_port, "/api/pair/remint", "POST",
                {**headers, "Content-Type": "application/json"}, b"{}",
            )
            assert code == 403, body
            assert json.loads(body)["error"] == "kiosk_only"
            assert CODE not in body
        auth = json.loads((run / "auth.json").read_text(encoding="utf-8"))
        assert auth["paired"] is True
        assert auth["token_hash"] == hashlib.sha256(TOKEN.encode()).hexdigest()
        assert (run / "pair-code.txt").read_text(encoding="utf-8").strip() == CODE
        assert not (run / "remint-rate.json").exists()
    finally:
        srv.close()


def test_kiosk_loopback_still_sees_and_remints_code(tmp_path):
    run, env = _setup(tmp_path, paired=False)
    gateway = _load(env, "stickllm_gateway_pair_kiosk")
    gateway.remint_pair_code = lambda: ("135790", "r2")
    srv = _Servers(gateway, loopback=True)
    try:
        code, _h, body = _call(srv.main_port, "/api/health", headers=UI)
        assert json.loads(body)["connect"]["pair_code"] == CODE
        code, _h, body = _call(
            srv.main_port, "/api/pair/remint", "POST",
            {**UI, "Content-Type": "application/json"}, b"{}",
        )
        assert code == 200, body
        doc = json.loads(body)
        assert doc["pair_code"] == "135790" and doc["remint_id"] == "r2"
    finally:
        srv.close()


def test_one_pairing_signs_in_to_agent_port_by_handoff(tmp_path):
    run, env = _setup(tmp_path)
    gateway = _load(env, "stickllm_gateway_pair_handoff")
    srv = _Servers(gateway, loopback=False)
    try:
        # Same browser, no cookie on :5443 yet: refused, with a helpful page.
        code, _h, body = _call(srv.agent_port, "/", headers={"Accept": "text/html"})
        assert code == 401 and "pair_required" in body and "click Agent" in body
        code, _h, body = _call(srv.agent_port, "/")
        assert code == 401 and json.loads(body)["error"] == "pair_required"

        # Unpaired LAN tabs cannot mint a handoff.
        for headers in (UI, {**UI, "Authorization": "Bearer nope"}, {"Authorization": "Bearer " + TOKEN}):
            code, _h, body = _call(srv.main_port, "/api/agent/handoff", "POST", headers, b"{}")
            assert code in (401, 403), body

        code, _h, body = _call(
            srv.main_port, "/api/agent/handoff", "POST",
            {**PAIRED_UI, "Host": "192.168.72.70"}, b"{}",
        )
        assert code == 200, body
        url = json.loads(body)["url"]
        assert url.startswith("https://192.168.72.70:5443/__stickllm/handoff?t=")
        assert TOKEN not in url
        path = url.split(":5443", 1)[1]

        code, headers, body = _call(srv.agent_port, path)
        assert code == 200, body
        set_cookie = headers.get("Set-Cookie") or ""
        assert set_cookie.startswith("stickllm_agent=")
        for attr in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
            assert attr in set_cookie
        value = set_cookie.split(";", 1)[0].split("=", 1)[1]
        assert value and TOKEN not in value
        assert 'http-equiv="refresh"' in body

        # One-time: the same link cannot be replayed.
        code, headers, body = _call(srv.agent_port, path)
        assert code == 401 and "Set-Cookie" not in headers

        # The new cookie opens the Agent port (status page: vault is locked here).
        code, _h, body = _call(srv.agent_port, "/", headers={"Cookie": "stickllm_agent=" + value})
        assert code == 200, body
        assert "Unlock vault" in body
        # It is not accepted as a pair token on the main UI.
        code, _h, body = _call(srv.main_port, "/api/storage", headers={**UI, "Cookie": "stickllm_agent=" + value})
        assert code == 401
        code, _h, body = _call(srv.agent_port, "/", headers={"Cookie": "stickllm_agent=" + "0" * 64})
        assert code == 401
    finally:
        srv.close()


def test_handoff_tickets_expire_and_die_with_the_pairing(tmp_path):
    _run, env = _setup(tmp_path)
    gateway = _load(env, "stickllm_gateway_pair_ticket")
    auth = {"paired": True, "token_hash": hashlib.sha256(TOKEN.encode()).hexdigest()}
    old = gateway.mint_agent_handoff(auth, now=time.time() - 120)
    assert gateway.agent_handoff_redeem(old, auth) is False
    assert gateway.agent_handoff_redeem(TOKEN, auth) is False
    ticket = gateway.mint_agent_handoff(auth)
    reminted = {"paired": True, "token_hash": hashlib.sha256(b"other").hexdigest()}
    assert gateway.agent_handoff_redeem(ticket, reminted) is False
    assert gateway.agent_handoff_redeem(ticket, auth) is True
    assert gateway.agent_handoff_redeem(ticket, auth) is False
    cookie = gateway.agent_session_value(auth)
    assert gateway.agent_session_ok(cookie, auth) is True
    assert gateway.agent_session_ok(cookie, reminted) is False
    assert gateway.agent_session_ok(cookie, {"paired": False, "token_hash": ""}) is False
    assert gateway.mint_agent_handoff({"paired": False}) == ""


def _raw(port, path, method="GET", headers=None, body=None, stream=False):
    """No redirect following; for streams, return after the status line."""
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    if stream:
        status, hdrs = resp.status, dict(resp.getheaders())
        conn.close()
        return status, hdrs, ""
    data = resp.read().decode()
    conn.close()
    return resp.status, dict(resp.getheaders()), data


def test_app_pages_open_with_an_httponly_apps_cookie_not_the_shared_cookie(tmp_path):
    run, env = _setup(tmp_path)
    page = tmp_path / "ui" / "apps" / "solitaire"
    page.mkdir(parents=True)
    (page / "index.html").write_text("<!DOCTYPE html><title>Solitaire</title>", encoding="utf-8")
    (page / "game.js").write_text("1;", encoding="utf-8")
    gateway = _load(env, "stickllm_gateway_pair_apps")
    srv = _Servers(gateway, loopback=False)
    try:
        port = srv.main_port
        # Unpaired: no app page (a ?t= in the URL means nothing).
        for path in ("/apps/solitaire/", "/apps/solitaire/?t=" + TOKEN):
            code, _h, body = _raw(port, path)
            assert code == 401 and json.loads(body)["error"] == "pair_required", path
        # Only a paired StickLLM tab gets the apps cookie.
        code, _h, _b = _raw(port, "/api/ui/apps-session", "POST", {"Authorization": "Bearer " + TOKEN}, b"{}")
        assert code == 403
        for headers in (UI, {**UI, "Authorization": "Bearer nope"}, {**UI, "Cookie": "stickllm_pair=nope"}):
            code, h, _b = _raw(port, "/api/ui/apps-session", "POST", headers, b"{}")
            assert code == 401 and "Set-Cookie" not in h
        code, headers, body = _raw(port, "/api/ui/apps-session", "POST", PAIRED_UI, b"{}")
        assert code == 200 and json.loads(body) == {"ok": True, "cookie": True}
        set_cookie = headers.get("Set-Cookie") or ""
        assert set_cookie.startswith("stickllm_apps=")
        for attr in ("HttpOnly", "SameSite=Strict", "Path=/"):
            assert attr in set_cookie
        value = set_cookie.split(";", 1)[0].split("=", 1)[1]
        assert len(value) == 64 and TOKEN not in value and TOKEN not in body

        # Same URL as the desktop icon, even with a stale stickllm_pair cookie.
        apps = {"Cookie": "stickllm_pair=stale; stickllm_apps=" + value}
        code, _h, body = _raw(port, "/apps/solitaire/", headers=apps)
        assert code == 200 and "Solitaire" in body
        code, _h, _b = _raw(port, "/apps/solitaire/game.js", headers=apps)
        assert code == 200
        # The app page's own stream works; it is not a pair token anywhere else.
        code, _h, _b = _raw(port, "/api/ui/events?app=solitaire", headers=apps, stream=True)
        assert code == 200
        code, _h, _b = _raw(port, "/api/ui/events", headers=apps, stream=True)
        assert code == 401
        for p, m in (("/api/storage", "GET"), ("/api/ui/events-ticket", "POST"), ("/api/ui/apps-session", "POST"),
                     ("/api/agent/handoff", "POST")):
            code, _h, _b = _raw(port, p, m, {**UI, **apps, "Content-Type": "application/json"}, b"{}" if m == "POST" else None)
            assert code == 401, p
        code, _h, _b = _raw(port, "/apps/solitaire/", headers={"Cookie": "stickllm_apps=" + "0" * 64})
        assert code == 401

        # A paired tab's own cookie still opens app pages directly.
        code, _h, _b = _raw(port, "/apps/solitaire/", headers={"Cookie": "stickllm_pair=" + TOKEN})
        assert code == 200

        # Remint: the apps cookie dies with the pairing.
        auth = json.loads((run / "auth.json").read_text(encoding="utf-8"))
        auth["token_hash"] = hashlib.sha256(b"new-token").hexdigest()
        (run / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
        code, _h, _b = _raw(port, "/apps/solitaire/", headers=apps)
        assert code == 401

        log = (run / "kiosk.log").read_text(encoding="utf-8")
        assert "STICKLLM_APPS_AUTH session=set ip=127.0.0.1 pair_cookie=absent" in log
        assert "STICKLLM_APPS_AUTH session=refused ip=127.0.0.1" in log
        assert "STICKLLM_APPS_AUTH denied ip=127.0.0.1 pair_cookie=stale apps_cookie=present" in log
        assert TOKEN not in log and value not in log
    finally:
        srv.close()


def test_apps_cookie_dies_with_the_pairing_and_is_not_an_agent_session(tmp_path):
    _run, env = _setup(tmp_path)
    gateway = _load(env, "stickllm_gateway_pair_app_cookie")
    auth = {"paired": True, "token_hash": hashlib.sha256(TOKEN.encode()).hexdigest()}
    reminted = {"paired": True, "token_hash": hashlib.sha256(b"other").hexdigest()}
    value = gateway.apps_session_value(auth)
    assert value != gateway.agent_session_value(auth)
    assert gateway.apps_session_ok(value, auth) and not gateway.apps_session_ok(value, reminted)
    assert gateway.agent_session_ok(value, auth) is False
    assert gateway.apps_session_value({"paired": False}) == ""
    assert not hasattr(gateway, "mint_app_ticket") and not hasattr(gateway, "app_ticket_redeem")


def test_ui_keeps_pair_code_and_new_code_on_the_kiosk():
    js = APP_JS.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert "(isLocalMode || detectLocalHost())" not in js
    assert "if (!detectLocalHost() || !/^\\d{4,8}$/.test(c)) return;" in js
    assert "function applyPairKioskUi()" in js and "applyPairKioskUi();" in js
    hot = js.split("async function issuePairHotkey()", 1)[1].split("async function issueSshHotkey", 1)[0]
    assert hot.index("if (!detectLocalHost())") < hot.index("remintPairCode()")
    assert '"/api/agent/handoff"' in js
