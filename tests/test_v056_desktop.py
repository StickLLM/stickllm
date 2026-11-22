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
    assert GW.control_action_allowed("terminal_open", True, True)
    assert not GW.control_action_allowed("terminal_open", False, True)
    assert GW.control_action_allowed("terminal_ssh_password_clipboard", True, True)
    assert not GW.control_action_allowed("terminal_ssh_password_clipboard", False, True)
    assert GW.control_action_allowed("terminal_ssh_password_paste", True, True)
    assert not GW.control_action_allowed("terminal_ssh_password_paste", False, True)
    assert GW.control_action_allowed("status", False, False)
    src = _text(BIN / "stickllm-gateway")
    assert 'control_action_allowed(action, self._is_loopback(), stickllm_ui_client(self.headers))' in src
    assert '"terminal_"' in src or "'terminal_'" in src


def test_terminal_open_spawns_fixed_argv(monkeypatch):
    seen = {}

    class P:
        pid = 4243

        def poll(self):
            return None

    def popen(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return P()

    monkeypatch.setattr(CTL, "_terminal_bin", lambda: "/usr/bin/xfce4-terminal")
    monkeypatch.setattr(CTL, "_kiosk_user", lambda: "stickllm")
    monkeypatch.setattr(CTL.Path, "is_socket", lambda self: str(self) == "/tmp/.X11-unix/X0")
    monkeypatch.setattr(CTL.subprocess, "Popen", popen)
    monkeypatch.setattr(CTL.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(CTL, "_TERMINALS", {})
    monkeypatch.setattr(CTL, "_wm_place_later", lambda *a, **k: None)
    r = CTL.handle("terminal_open", {})
    assert r["ok"] is True and r.get("id")
    assert seen["cmd"][0] == "/usr/bin/xfce4-terminal"
    assert "--disable-server" in seen["cmd"]
    assert f"--class=stickllm-terminal-{r['id']}" in seen["cmd"]
    assert "--title=StickLLM Terminal" in seen["cmd"]
    assert seen["kw"]["env"]["DISPLAY"] == ":0"
    assert seen["kw"]["start_new_session"] is True
    st = CTL.handle("terminal_status", {})
    assert [w["title"] for w in st["windows"]] == ["Terminal"]
    assert st["windows"][0]["id"] == r["id"]


def test_terminal_open_needs_binary(monkeypatch):
    called = []
    monkeypatch.setattr(CTL, "_terminal_bin", lambda: "")
    monkeypatch.setattr(CTL.subprocess, "Popen", lambda *a, **k: called.append(a))
    r = CTL.handle("terminal_open", {})
    assert r["ok"] is False and r["error"] == "no_terminal" and not called


def test_terminal_window_needs_tracked_id(monkeypatch):
    monkeypatch.setattr(CTL, "_TERMINALS", {})
    r = CTL.handle("terminal_window", {"id": "deadbeefcafe", "op": "minimise"})
    assert r["ok"] is False and r["error"] == "not_found"


def test_terminal_ssh_password_clipboard_bridges_x11(monkeypatch, tmp_path):
    put = []

    def fake_put(sel, data):
        put.append((sel, data))
        return True

    def fake_eq(sel, expected):
        return expected == "lab-secret-not-logged" and any(s == sel for s, _ in put)

    pw_file = tmp_path / "ssh-password.txt"
    pw_file.write_text("lab-secret-not-logged\n", encoding="utf-8")
    monkeypatch.setattr(CTL, "RUN", tmp_path)
    monkeypatch.setattr(CTL.Path, "is_socket", lambda self: str(self) == "/tmp/.X11-unix/X0")
    monkeypatch.setattr(CTL, "_x11_clipboard_put", fake_put)
    monkeypatch.setattr(CTL, "_clipboard_selection_equals", fake_eq)
    r = CTL.handle("terminal_ssh_password_clipboard", {})
    assert r["ok"] is True and r.get("hint") == "ctrl_shift_v"
    assert "lab-secret" not in str(r)
    assert ("clipboard", b"lab-secret-not-logged") in put
    assert ("primary", b"lab-secret-not-logged") in put


def test_terminal_ssh_password_paste_focuses_and_pastes(monkeypatch, tmp_path):
    keys = []

    def fake_run(argv, *, input_bytes=None, timeout=5.0):
        keys.append(list(argv))
        if argv[:1] == ["xdotool"] and "getactivewindow" in argv:
            return CTL.subprocess.CompletedProcess(argv, 0, b"424242\n", b"")
        return CTL.subprocess.CompletedProcess(argv, 0, b"", b"")

    class P:
        pid = 9911

        def poll(self):
            return None

    pw_file = tmp_path / "ssh-password.txt"
    pw_file.write_text("lab-secret-not-logged\n", encoding="utf-8")
    monkeypatch.setattr(CTL, "RUN", tmp_path)
    monkeypatch.setattr(CTL, "_TERMINALS", {"aabbccddeeff": {"proc": P(), "title": "Terminal", "bin": "/usr/bin/xfce4-terminal", "started": 0}})
    monkeypatch.setattr(CTL, "clipboard_set_x11", lambda text: {"ok": True, "clipboard": True, "primary": True})
    monkeypatch.setattr(CTL, "terminal_window", lambda params: {"ok": True, "id": params["id"], "op": params["op"]})
    monkeypatch.setattr(CTL, "_terminal_x11_window_id", lambda tid: 424242)
    monkeypatch.setattr(CTL, "_list_x11_terminals", lambda: [{"id": "aabbccddeeff", "wid": 424242, "minimised": False, "focused": True, "orphan": False}])
    monkeypatch.setattr(CTL, "_x11_run", fake_run)
    r = CTL.handle("terminal_ssh_password_paste", {})
    assert r["ok"] is True and r.get("method") == "ctrl_shift_v"
    assert r.get("id") == "aabbccddeeff"
    assert r.get("window") == 424242
    assert "lab-secret" not in str(r)
    assert "Enter" in (r.get("message") or "")
    assert any(a[:2] == ["xdotool", "windowactivate"] for a in keys)
    assert any(a[:2] == ["xdotool", "windowfocus"] for a in keys)
    assert any(a == ["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"] for a in keys)
    assert any(a == ["xdotool", "key", "--clearmodifiers", "Return"] for a in keys)
    assert not any(a[:2] == ["xdotool", "type"] for a in keys)


def test_terminal_ssh_password_paste_prefers_orphan_x11_window(monkeypatch, tmp_path):
    """After control restart, _TERMINALS is empty but the sudo Terminal still exists."""
    keys = []

    def fake_run(argv, *, input_bytes=None, timeout=5.0):
        keys.append(list(argv))
        if argv[:1] == ["xdotool"] and "getactivewindow" in argv:
            return CTL.subprocess.CompletedProcess(argv, 0, b"999001\n", b"")
        return CTL.subprocess.CompletedProcess(argv, 0, b"", b"")

    opened = []
    pw_file = tmp_path / "ssh-password.txt"
    pw_file.write_text("lab-secret-not-logged\n", encoding="utf-8")
    monkeypatch.setattr(CTL, "RUN", tmp_path)
    monkeypatch.setattr(CTL, "_TERMINALS", {})
    monkeypatch.setattr(CTL, "clipboard_set_x11", lambda text: {"ok": True, "clipboard": True, "primary": True})
    monkeypatch.setattr(CTL, "terminal_open", lambda params=None: opened.append(1) or {"ok": False, "error": "should_not_open"})
    monkeypatch.setattr(CTL, "terminal_window", lambda params: {"ok": True, "id": params["id"], "op": params["op"]})
    monkeypatch.setattr(CTL, "_terminal_x11_window_id", lambda tid: 999001)
    monkeypatch.setattr(
        CTL,
        "_list_x11_terminals",
        lambda: [{"id": "71e4ccb48dc3", "wid": 999001, "minimised": False, "focused": True, "orphan": True}],
    )
    monkeypatch.setattr(CTL, "_x11_run", fake_run)
    r = CTL.handle("terminal_ssh_password_paste", {})
    assert r["ok"] is True and r.get("id") == "71e4ccb48dc3" and not opened
    assert any(a == ["xdotool", "key", "--clearmodifiers", "ctrl+shift+v"] for a in keys)


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
    monkeypatch.setattr(CTL, "_wm_ipc", lambda: None)  # desktop not running: no window manager
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
    assert f["error"] == "wm_unavailable"
    prefs = json.loads((Path(prof) / "Default" / "Preferences").read_text())
    assert prefs["browser"]["custom_chrome_frame"] is False
    # Browser icon: a normal window with an address bar, not an app window.
    r2 = CTL.browser_open({"url": "", "title": "Browser"})
    assert r2["ok"] and "--new-window" in seen["cmd"] and not any(c.startswith("--app=") for c in seen["cmd"])


def test_browser_profile_is_in_ram():
    assert str(CTL.BROWSER_ROOT).startswith(str(CTL.RUN))


# --- UI ------------------------------------------------------------------

def test_desktop_browser_and_apps_wiring():
    js = _text(UI / "desktop.js")
    assert 'api.control("browser_open"' in js and "app: !!app" in js
    assert '"browser_window"' in js and '["close", "Close"]' in js and '"browser_status"' in js
    assert "openBrowser(u, appTitle(id), true)" in js
    assert 'api.control("terminal_open"' in js
    assert '"terminal_status"' in js and '"terminal_window"' in js
    assert "pollTerminal" in js and "terminalOp(" in js
    assert 'FRONT = ["agent", "browser", "terminal", "store"]' in js
    assert "openTerminal:" in js
    assert "wm.focus = (id) =>" in js and "yieldNative()" in js
    assert "nativeCovers()" in js
    app = _text(UI / "app.js")
    assert "deskCatalog" in app and "frame: a.frame !== false" in app
    assert 'id === "terminal"' in app
    assert "bridgeSshPasswordClipboard" in app
    assert 'control("terminal_ssh_password_clipboard"' in app
    assert 'control("terminal_ssh_password_paste"' in app
    assert "Ctrl+Shift+V" in app
    html = _text(UI / "index.html")
    assert 'data-starter="terminal"' in html and ">Terminal</span>" in html
    assert 'id="sshPastePass"' in html and "Paste into Terminal" in html
    assert 'id="sshPasteHint"' in html
    pkgs = _text(ROOT / "live-build" / "package-lists" / "stickllm.list.chroot")
    assert "xfce4-terminal" in pkgs and "\nxterm\n" in pkgs
    assert "\nxclip\n" in pkgs
    desk = _text(ROOT / "overlay/usr/local/share/stickllm/desktop/Terminal.desktop")
    assert "Type=Application" in desk and "Name=Terminal" in desk
    assert "xfce4-terminal" in desk and "StickLLM Terminal" in desk
    sess = _text(ROOT / "overlay/usr/local/bin/stickllm-xfce-session")
    assert "install_desktop_launchers" in sess and "metadata::trusted" in sess
    kiosk = _text(ROOT / "overlay/usr/local/bin/stickllm-kiosk")
    assert "Desktop/Terminal.desktop" in kiosk


def test_api_apps_rows_carry_frame_flag():
    src = _text(BIN / "stickllm-gateway")
    assert 'row["frame"] = True' in src
    assert 'row["frame"] = bool((addons.APPS.get(row["id"]) or {}).get("frame", True))' in src


def test_version_056():
    meta = json.loads(_text(ROOT / "overlay" / "opt" / "stickllm" / "ui" / "stickllm.json"))
    assert meta["version"] == "0.5.6"


def test_chat_has_no_example_prompts():
    app = _text(UI / "app.js")
    assert 'class="sugg"' not in app and "Summarize a long article" not in app
    css = _text(UI / "desktop.css")
    assert "body.deskMode #app #thread > .empty" in css


def test_desktop_chat_sidebar_collapsible_and_remembered():
    js = _text(UI / "desktop.js")
    assert 'const SIDE_KEY = "stickllm.desk.chatSidebar"' in js
    assert 'store.get(SIDE_KEY) === "collapsed"' in js
    assert 'store.set(SIDE_KEY, appEl.classList.contains("collapsed") ? "collapsed" : "open")' in js
    # Leaving the desktop puts Classic's sidebar state back.
    assert 'appEl.classList.toggle("collapsed", !!ui.sidePrev)' in js
    css = _text(UI / "desktop.css")
    assert "body.deskMode #app.collapsed #menuBtn{display:inline-grid}" in css
    assert "body.deskMode #app .sideFoot" in css  # footer nav stays hidden; the list stays
    assert "body.deskMode #app .convList" not in css
