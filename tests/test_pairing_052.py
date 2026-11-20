"""0.5.2 pairing robustness: server-set HttpOnly cookies, TLS names, re-pair request."""
from __future__ import annotations

import hashlib
import http.client
import json
from pathlib import Path

from test_pairing import CODE, TOKEN, UI, PAIRED_UI, _Servers, _load, _setup

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "ui" / "app.js").read_text(encoding="utf-8").replace("\r\n", "\n")
INDEX = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")


def _req(port, path, method="GET", headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(method, path, body=body, headers=headers or {})
    resp = conn.getresponse()
    cookies = [v for k, v in resp.getheaders() if k.lower() == "set-cookie"]
    data = resp.read().decode()
    conn.close()
    return resp.status, cookies, data


def _servers(gateway, loopback=False, tls=False):
    base = gateway.Handler

    class G(base):
        def _is_tls(self) -> bool:  # noqa: D401
            return tls

    gateway.Handler = G
    try:
        return _Servers(gateway, loopback=loopback)
    finally:
        gateway.Handler = base


JSON = {"Content-Type": "application/json"}


def test_pair_sets_httponly_cookies_http_and_tls_names(tmp_path):
    for tls, pair_name, apps_name in ((False, "stickllm_pair", "stickllm_apps"),
                                      (True, "__Secure-stickllm_pair", "__Secure-stickllm_apps")):
        sub = tmp_path / ("tls" if tls else "http")
        sub.mkdir()
        run, env = _setup(sub, paired=False)
        gateway = _load(env, "stickllm_gateway_052_pair_" + str(tls))
        srv = _servers(gateway, tls=tls)
        try:
            code, cookies, body = _req(srv.main_port, "/api/pair", "POST", {**UI, **JSON},
                                       json.dumps({"code": CODE}).encode())
            assert code == 200, body
            token = json.loads(body)["token"]
            byname = {c.split("=", 1)[0]: c for c in cookies}
            assert pair_name in byname and apps_name in byname, cookies
            for c in (byname[pair_name], byname[apps_name]):
                assert "HttpOnly" in c and "SameSite=Strict" in c and "Path=/" in c
                assert ("Secure" in c) is tls
            # The pair cookie alone authorizes the UI (no localStorage needed).
            pv = byname[pair_name].split(";", 1)[0].split("=", 1)[1]
            assert pv == token
            code, _c, body = _req(srv.main_port, "/api/pair/status", headers={**UI, "Cookie": f"{pair_name}={pv}"})
            assert code == 200 and json.loads(body).get("this_paired") is True
            # Either apps-cookie name opens a game page.
            av = byname[apps_name].split(";", 1)[0].split("=", 1)[1]
            page = sub / "ui" / "apps" / "minesweeper"
            page.mkdir(parents=True)
            (page / "index.html").write_text("<title>Minesweeper</title>", encoding="utf-8")
            for name in ("stickllm_apps", "__Secure-stickllm_apps") if tls else ("stickllm_apps",):
                code, _c, body = _req(srv.main_port, "/apps/minesweeper/", headers={"Cookie": f"{name}={av}"})
                assert code == 200 and "Minesweeper" in body, name
            # A stale cookie next to a good one does not break auth.
            code, _c, _b = _req(srv.main_port, "/api/pair/status",
                                headers={**UI, "Cookie": f"{pair_name}=stale; {pair_name}={pv}"})
            assert code == 200
            # Forget clears both cookies.
            code, cookies, _b = _req(srv.main_port, "/api/pair/forget", "POST", {**UI, **JSON}, b"{}")
            assert code == 200
            assert any(c.startswith(pair_name + "=;") or "Max-Age=0" in c for c in cookies)
        finally:
            srv.close()


def test_lan_pair_request_asks_kiosk_never_returns_code(tmp_path):
    run, env = _setup(tmp_path, paired=True)
    gateway = _load(env, "stickllm_gateway_052_req")
    lan = _servers(gateway, loopback=False)
    kiosk = _servers(gateway, loopback=True)
    try:
        code, _c, body = _req(lan.main_port, "/api/pair/request", "POST", JSON, b"{}")
        assert code == 403  # UI header required
        code, _c, body = _req(lan.main_port, "/api/pair/request", "POST", {**UI, **JSON}, b"{}")
        assert code == 200, body
        doc = json.loads(body)
        assert doc["needs_confirm"] is True and CODE not in body
        # Rate limited (one request per 30 s).
        code, _c, body = _req(lan.main_port, "/api/pair/request", "POST", {**UI, **JSON}, b"{}")
        assert code == 429 and CODE not in body
        # The pairing is unchanged: a LAN request never reminted.
        auth = json.loads((run / "auth.json").read_text(encoding="utf-8"))
        assert auth["token_hash"] == hashlib.sha256(TOKEN.encode()).hexdigest()
        # Kiosk sees the request in health; LAN health never does.
        _s, _c, body = _req(kiosk.main_port, "/api/health", headers=UI)
        pr = json.loads(body)["connect"].get("pair_request")
        assert pr and pr["needs_confirm"] is True and pr["id"]
        _s, _c, body = _req(lan.main_port, "/api/health", headers=PAIRED_UI)
        assert "pair_request" not in (json.loads(body).get("connect") or {}) and CODE not in body
        # Kiosk itself cannot "request"; it presses F9.
        code, _c, _b = _req(kiosk.main_port, "/api/pair/request", "POST", {**UI, **JSON}, b"{}")
        assert code == 400
    finally:
        lan.close()
        kiosk.close()


def test_ui_pairing_is_robust_and_shows_not_paired_screen():
    remember = APP_JS.split("function rememberPairCookie()", 1)[1].split("\nfunction ", 1)[0]
    assert "max-age=0" not in remember and "document.cookie" not in remember
    connect = APP_JS.split("async function connect()", 1)[1].split("\nasync function ", 1)[0]
    assert "rememberPairCookie()" not in connect
    clear = APP_JS.split("function clearPairSession()", 1)[1].split("\nfunction ", 1)[0]
    assert "removeItem" in clear and "===" in clear
    assert 'addEventListener("storage"' in APP_JS
    assert '"/api/pair/request"' in APP_JS and "/api/pair/remint" in APP_JS
    assert 'id="notPaired"' in INDEX and 'id="npAsk"' in INDEX and 'class="pairLink"' in INDEX
    brand = INDEX.split('<div class="brand">', 1)[1].split("</div>", 1)[0]
    assert "pairLink" in brand
    # Load poll never awaits a slow control status and reports errors.
    poll = APP_JS.split("function startLoadPoll()", 1)[1].split("\nfunction ", 1)[0]
    assert "await refreshModels" not in poll and "control service" in poll
