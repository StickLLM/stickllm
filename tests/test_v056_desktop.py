"""StickLLM 0.5.6: desktop UI — app windows may frame relayed apps, Browser opens real Chromium windows."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay" / "usr" / "local" / "bin"
UI = ROOT / "ui"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def _load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


GW = _load(BIN / "stickllm-gateway", "gw_v056")
CTL = _load(BIN / "stickllm-control", "ctl_v056")


# --- gateway: frame-src for desktop windows ------------------------------

def test_main_csp_allows_only_stick_frames():
    csp = GW.csp_for_path("/", "127.0.0.1:8080")
    assert "frame-src 'self' http://127.0.0.1:* http://localhost:*;" in csp
    assert "frame-ancestors 'none'" in csp
    assert "https://" not in csp.split("frame-src", 1)[1].split(";", 1)[0]
    lan = GW.csp_for_path("/", "192.168.1.20:5443")
    assert "https://192.168.1.20:*" in lan.split("frame-src", 1)[1].split(";", 1)[0]


def test_frame_host_rejects_injection():
    base = "'self' http://127.0.0.1:* http://localhost:*"
    for bad in ("evil.com; script-src *", "a b", "x'y", "0.0.0.0", "localhost:8080", ""):
        assert GW.ui_frame_sources(bad) == base, bad
    assert GW.ui_frame_sources("[::1]:8080") == base + " https://[::1]:*"
    assert GW.ui_frame_sources("stick.local:5443") == base + " https://stick.local:*"


def test_app_pages_keep_self_framing():
    csp = GW.csp_for_path("/apps/docs/", "127.0.0.1")
    assert "frame-ancestors 'self'" in csp
    assert "frame-src 'self' http://127.0.0.1:*" not in csp


def test_addon_frame_headers_drop_xfo_and_rewrite_ancestors():
    framers = GW.addon_framers("127.0.0.1:8080")
    out = GW.addon_frame_headers([("X-Frame-Options", "DENY"), ("Content-Type", "text/html")], framers)
    names = [k.lower() for k, _ in out]
    assert "x-frame-options" not in names
    csp = [v for k, v in out if k.lower() == "content-security-policy"]
    assert csp == ["frame-ancestors " + framers]
    out = GW.addon_frame_headers(
        [("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'"), ("X-Frame-Options", "SAMEORIGIN")],
        framers,
    )
    assert [k.lower() for k, _ in out] == ["content-security-policy"]
    assert out[0][1] == "default-src 'self'; frame-ancestors " + framers
    # Nothing to do for a page that never refused framing.
    plain = [("Content-Type", "text/html")]
    assert GW.addon_frame_headers(plain, framers) == plain
    assert "*" not in framers.replace(":*", "")


def test_control_browser_actions_local_ui_only():
    assert GW.control_action_allowed("browser_open", True, True)
    assert not GW.control_action_allowed("browser_open", False, True)
    assert not GW.control_action_allowed("browser_status", True, False)
    assert GW.control_action_allowed("status", False, False)
    src = _text(BIN / "stickllm-gateway")
    assert 'control_action_allowed(action, self._is_loopback(), stickllm_ui_client(self.headers))' in src


# --- control: browser windows --------------------------------------------

def test_browser_url_validation():
    ok = CTL.browser_url_ok
    assert ok("https://example.org/a?b=1") and ok("http://127.0.0.1:8095/") and ok("about:blank")
    for bad in ("", "file:///etc/passwd", "javascript:alert(1)", "chrome://settings", "data:text/html,x",
                "https://exa mple.org", "https://a\n.org", "http://", "https://" + "a" * 5000):
        assert not ok(bad), bad


def test_browser_open_rejects_bad_url_without_spawning(monkeypatch):
    called = []
    monkeypatch.setattr(CTL.subprocess, "Popen", lambda *a, **k: called.append(a))
    r = CTL.handle("browser_open", {"url": "file:///etc/shadow"})
    assert r["ok"] is False and r["error"] == "bad_url" and not called


def test_browser_open_needs_download_policy(monkeypatch, tmp_path):
    called = []
    monkeypatch.setattr(CTL, "_browser_bin", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(CTL, "_wayland_env", lambda u: {"XDG_RUNTIME_DIR": "/run/user/1000", "WAYLAND_DISPLAY": "wayland-0"})
    monkeypatch.setattr(CTL, "BROWSER_ROOT", tmp_path / "browser")
    monkeypatch.setattr(CTL, "sh", lambda cmd, timeout=600: {"ok": False, "stdout": ""})
    monkeypatch.setattr(CTL.subprocess, "Popen", lambda *a, **k: called.append(a))
    r = CTL.browser_open({"url": "https://example.org/"})
    assert r["ok"] is False and r["error"] == "download_policy" and not called


def test_browser_open_spawns_chromium_in_ram_profile(monkeypatch, tmp_path):
    seen = {}

    class P:
        pid = 4242

        def poll(self):
            return None

    def popen(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return P()

    monkeypatch.setattr(CTL, "_browser_bin", lambda: "/usr/bin/chromium")
    monkeypatch.setattr(CTL, "_wayland_env", lambda u: {"XDG_RUNTIME_DIR": "/run/user/1000", "WAYLAND_DISPLAY": "wayland-0"})
    monkeypatch.setattr(CTL, "BROWSER_ROOT", tmp_path / "browser")
    monkeypatch.setattr(CTL, "sh", lambda cmd, timeout=600: {"ok": True, "stdout": "downloads=unlocked\n"})
    monkeypatch.setattr(CTL.subprocess, "Popen", popen)
    monkeypatch.setattr(CTL, "_BROWSERS", {})
    r = CTL.browser_open({"url": "http://127.0.0.1:8095/", "title": "Trilium", "app": True,
                          "geometry": {"x": 10, "y": 20, "w": 1000, "h": 700}})
    assert r["ok"] and r["downloads"] == "vault"
    cmd = seen["cmd"]
    assert "--app=http://127.0.0.1:8095/" in cmd
    assert "--window-size=1000,700" in cmd and "--window-position=10,20" in cmd
    prof = [c for c in cmd if c.startswith("--user-data-dir=")][0].split("=", 1)[1]
    assert prof.startswith(str(tmp_path / "browser"))
    assert seen["kw"]["env"]["WAYLAND_DISPLAY"] == "wayland-0"
    assert seen["kw"]["start_new_session"] is True
    st = CTL.handle("browser_status", {})
    assert [w["title"] for w in st["windows"]] == ["Trilium"]
    f = CTL.handle("browser_focus", {"id": r["id"]})
    assert f["error"] == "focus_unsupported"
    # Browser icon: a normal window with an address bar, not an app window.
    r2 = CTL.browser_open({"url": "", "title": "Browser"})
    assert r2["ok"] and "--new-window" in seen["cmd"] and not any(c.startswith("--app=") for c in seen["cmd"])


def test_browser_profile_is_in_ram():
    assert str(CTL.BROWSER_ROOT).startswith(str(CTL.RUN))


# --- UI ------------------------------------------------------------------

def test_desktop_browser_and_apps_wiring():
    js = _text(UI / "desktop.js")
    assert 'api.control("browser_open"' in js and "app: !!app" in js
    assert '"browser_focus"' in js and '"browser_close"' in js and '"browser_status"' in js
    assert "openBrowser(u, appTitle(id), true)" in js
    app = _text(UI / "app.js")
    assert "deskCatalog" in app and "frame: a.frame !== false" in app


def test_api_apps_rows_carry_frame_flag():
    src = _text(BIN / "stickllm-gateway")
    assert 'row["frame"] = True' in src
    assert 'row["frame"] = bool((addons.APPS.get(row["id"]) or {}).get("frame", True))' in src


def test_version_056():
    meta = json.loads(_text(ROOT / "overlay" / "opt" / "stickllm" / "ui" / "stickllm.json"))
    assert meta["version"] == "0.5.6"
