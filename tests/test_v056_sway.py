"""StickLLM 0.5.6 round 3: floating-window desktop on stock sway (MIT).

Covers our own i3-ipc client (stickllm_wm), the sway config we ship, the
kiosk's sway-first ladder with cage/weston fallback, and stickllm-control's
browser_window endpoint against a fake compositor.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import socket
import struct
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OV = ROOT / "overlay"
BIN = OV / "usr" / "local" / "bin"
LIB = OV / "usr" / "local" / "lib" / "stickllm_wm.py"
CONF = OV / "etc" / "stickllm" / "sway" / "config"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def _load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


WM = _load(LIB, "stickllm_wm_t")
CTL = _load(BIN / "stickllm-control", "ctl_v056_sway")

WORK = {"x": 0, "y": 0, "w": 1280, "h": 672, "scale": 1.0}


def _win(cid, app_id, *, marks=(), floating=True, focused=False, minimised=False, rect=(50, 55, 800, 500), deco=25, pid=100):
    return {"id": cid, "app_id": app_id, "marks": list(marks), "floating": floating, "focused": focused,
            "minimised": minimised, "pid": pid, "name": app_id,
            "rect": {"x": rect[0], "y": rect[1], "width": rect[2], "height": rect[3]},
            "deco_rect": {"x": 0, "y": 0, "width": rect[2], "height": deco}}


def _tree(*floating, desktop=True, scratch=()):
    ws_nodes = []
    if desktop:
        ws_nodes.append({"type": "con", "id": 5, "app_id": "stickllm-desktop", "pid": 10, "marks": ["stickllm_desktop"],
                         "rect": {"x": 0, "y": 0, "width": 1280, "height": 720}, "nodes": [], "floating_nodes": []})
    return {"type": "root", "nodes": [
        {"type": "output", "name": "__i3", "nodes": [
            {"type": "workspace", "name": "__i3_scratch", "nodes": [], "floating_nodes": list(scratch)}]},
        {"type": "output", "name": "HDMI-A-1", "nodes": [
            {"type": "workspace", "name": "1", "nodes": ws_nodes, "floating_nodes": list(floating)}]},
    ]}


def _fc(cid, app_id, **kw):
    w = _win(cid, app_id, **kw)
    w.pop("floating"); w.pop("minimised")
    w.update(type="floating_con", nodes=[], floating_nodes=[])
    return w


# --- wire format -----------------------------------------------------------

def test_pack_matches_i3_ipc_wire_format():
    b = WM.pack(WM.RUN_COMMAND, "focus")
    assert b[:6] == b"i3-ipc"
    assert struct.unpack("=II", b[6:14]) == (5, 0)
    assert b[14:] == b"focus"
    assert WM.unpack_header(WM.pack(4)[:14]) == (0, 4)
    with pytest.raises(WM.WMError):
        WM.unpack_header(b"xx-ipc" + b"\0" * 8)


def test_ipc_roundtrip_against_fake_sway(tmp_path):
    path = str(tmp_path / "sway-ipc.1000.1.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path); srv.listen(1)
    seen = []

    def serve():
        c, _ = srv.accept()
        for _ in range(2):
            head = c.recv(14)
            n, t = struct.unpack("=II", head[6:])
            body = c.recv(n) if n else b""
            seen.append((t, body.decode()))
            reply = json.dumps([{"success": True}] if t == 0 else _tree()).encode()
            c.sendall(b"i3-ipc" + struct.pack("=II", len(reply), t) + reply)
        c.close()

    th = threading.Thread(target=serve, daemon=True); th.start()
    assert WM.find_socket([str(tmp_path)]) == path
    with WM.SwayIPC(path) as ipc:
        assert WM.command_ok(ipc.command("[con_id=6] focus"))
        assert WM.window_by(ipc.tree(), app_id="stickllm-desktop")["id"] == 5
    th.join(2); srv.close()
    assert seen == [(0, "[con_id=6] focus"), (4, "")]


def test_find_socket_reports_missing_sway(tmp_path, monkeypatch):
    monkeypatch.delenv("SWAYSOCK", raising=False)
    with pytest.raises(WM.WMError):
        WM.find_socket([str(tmp_path)])


# --- window lookup ---------------------------------------------------------

def test_iter_windows_marks_scratchpad_as_minimised():
    t = _tree(_fc(6, "stickllm-browser-aa11"), scratch=[_fc(7, "stickllm-browser-bb22")])
    ws = {w["id"]: w for w in WM.iter_windows(t)}
    assert ws[7]["minimised"] and not ws[6]["minimised"] and ws[6]["floating"]
    assert not ws[5]["floating"] and WM.is_desktop(ws[5])


def test_browser_ids_are_validated():
    assert WM.browser_app_id("96e010b0aa98") == "stickllm-browser-96e010b0aa98"
    for bad in ("", "../x", "a b", "x" * 65, "A]; exec foot"):
        with pytest.raises(WM.WMError):
            WM.browser_app_id(bad)
    with pytest.raises(WM.WMError):
        WM.bid_mark("bad id")


def test_app_windows_found_by_owner_then_marked():
    # Chromium --app windows ignore --class on Wayland: app_id is derived from the URL.
    app = _fc(7, "chrome-127.0.0.1__apps_notepad_-Default", pid=777)
    t = _tree(_fc(6, "stickllm-browser-aa11", pid=666), app)
    assert WM.window_for(t, "aa11")["id"] == 6
    assert WM.window_for(t, "cc33") is None
    assert WM.window_for(t, "cc33", owns=lambda pid: pid == 777)["id"] == 7
    assert WM.adopt_cmd(app, "cc33") == "[con_id=7] mark --add stickllm_bid_cc33"
    marked = _tree(_fc(7, "chrome-x", marks=["stickllm_bid_cc33"]))
    assert WM.window_for(marked, "cc33")["id"] == 7
    assert WM.bid_of(WM.window_for(marked, "cc33")) == "cc33"
    # The desktop and windows owned by another id are never adopted.
    assert WM.window_for(_tree(), "cc33", owns=lambda pid: True) is None
    assert WM.window_for(_tree(_fc(8, "stickllm-browser-dd44")), "cc33", owns=lambda pid: True) is None


class FakeIPC:
    def __init__(self, tree, outputs=None):
        self._tree, self.cmds = tree, []
        self._outputs = outputs or [{"active": True, "rect": {"x": 0, "y": 0, "width": 1280, "height": 720}, "scale": 1.0}]

    def tree(self):
        return self._tree

    def outputs(self):
        return self._outputs

    def command(self, c):
        self.cmds.append(c)
        return [{"success": True}]

    def close(self):
        pass


def test_wait_for_marks_and_states_key_by_id():
    ipc = FakeIPC(_tree(_fc(7, "chrome-x", pid=9)))
    w = WM.wait_for(ipc, "cc33", owns=lambda pid: pid == 9, timeout=0.3)
    assert w["id"] == 7 and ipc.cmds == ["[con_id=7] mark --add stickllm_bid_cc33"]
    ipc2 = FakeIPC(_tree(_fc(6, "stickllm-browser-aa11"), _fc(7, "chrome-x", marks=["stickllm_bid_cc33"])))
    st = WM.states(ipc2)
    assert set(st) == {"aa11", "cc33"}


# --- geometry and plans ----------------------------------------------------

def test_work_area_excludes_taskbar_and_honours_scale():
    outs = [{"active": True, "rect": {"x": 0, "y": 0, "width": 1280, "height": 800}, "scale": 2.0}]
    wa = WM.work_area(outs, 96)
    assert wa == {"x": 0, "y": 0, "w": 1280, "h": 752, "scale": 2.0}
    assert WM.work_area([{"active": True, "rect": {"x": 0, "y": 0, "width": 1920, "height": 1080}}])["h"] == 1032


def test_clamp_keeps_window_on_screen_and_above_minimum():
    g = WM.clamp_to_work({"x": 5000, "y": -300, "w": 100, "h": 9000}, WORK)
    assert g["w"] >= WM.MIN_W and g["h"] <= WORK["h"]
    assert 0 <= g["x"] <= WORK["w"] - g["w"] and 0 <= g["y"]


def test_rect_mark_roundtrip_with_negative_coords():
    m = WM.rect_mark({"x": -20, "y": 30, "w": 800, "h": 500})
    assert m.startswith("stickllm_rect_") and "-" not in m
    assert WM.saved_rect({"marks": ["other", m]}) == {"x": -20, "y": 30, "w": 800, "h": 500}


def test_place_converts_physical_to_logical_pixels():
    w = _win(6, "stickllm-browser-aa11")
    cmds = WM.plan("place", w, dict(WORK, scale=2.0), {"x": 200, "y": 100, "w": 1200, "h": 800})
    assert cmds[0] == WM.place_cmd(6, {"x": 100, "y": 50, "w": 600, "h": 400})
    assert "floating enable" in cmds[0] and "move absolute position 100 px 50 px" in cmds[0]
    assert cmds[-1] == "[con_id=6] focus"


def test_minimise_restore_toggle_and_maximise_plans():
    w = _win(6, "stickllm-browser-aa11", focused=True, rect=(330, 145, 860, 445), deco=25)
    mini = WM.plan("minimise", w, WORK)
    assert mini[-1] == "[con_id=6] move scratchpad"
    assert any("mark --add stickllm_rect_330_120_860_470" in c for c in mini)
    assert WM.plan("toggle", w, WORK)[-1] == "[con_id=6] move scratchpad"  # focused -> minimise
    m = _win(6, "stickllm-browser-aa11", minimised=True, marks=["stickllm_rect_330_120_860_470"])
    rest = WM.plan("toggle", m, WORK)  # minimised -> restore at the saved rect
    assert rest[0] == "[con_id=6] scratchpad show"
    assert rest[1] == WM.place_cmd(6, {"x": 330, "y": 120, "w": 860, "h": 470})
    unf = _win(6, "stickllm-browser-aa11", focused=False)
    assert WM.plan("toggle", unf, WORK) == ["[con_id=6] focus"]  # behind -> to front
    mx = WM.plan("maximise", w, WORK)
    assert WM.place_cmd(6, {"x": 0, "y": 0, "w": 1280, "h": 672}) in mx
    full = _win(6, "stickllm-browser-aa11", rect=(0, 25, 1280, 647), deco=25, marks=["stickllm_rect_330_120_860_470"])
    assert WM.is_maximised(full, WORK)
    back = WM.plan("maximise", full, WORK)  # second maximise restores the old size
    assert back[0] == WM.place_cmd(6, {"x": 330, "y": 120, "w": 860, "h": 470})
    assert WM.plan("close", w, WORK) == ["[con_id=6] kill"]
    with pytest.raises(WM.WMError):
        WM.plan("fly", w, WORK)
    with pytest.raises(WM.WMError):
        WM.plan("place", w, WORK, None)


def test_desktop_window_is_never_moved_minimised_or_closed():
    desk = next(WM.iter_windows(_tree()))
    for op in WM.OPS:
        with pytest.raises(WM.WMError):
            WM.plan(op, desk, WORK)


def test_desktop_rules_keep_one_tiled_desktop():
    extra = _fc(9, "stickllm-desktop")
    t = _tree(extra)
    assert WM.desktop_rules(t) == ["[con_id=9] floating enable, border normal 2"]
    fresh = _tree(desktop=False)
    fresh["nodes"][1]["nodes"][0]["nodes"] = [{"type": "con", "id": 5, "app_id": "stickllm-desktop", "pid": 3,
                                               "marks": [], "nodes": [], "floating_nodes": [],
                                               "rect": {"x": 0, "y": 0, "width": 1, "height": 1}}]
    assert WM.desktop_rules(fresh) == ["[con_id=5] floating disable, border none, mark --add stickllm_desktop"]


def test_desktop_rules_find_app_window_by_launch_pid():
    fresh = _tree(desktop=False)
    fresh["nodes"][1]["nodes"][0]["nodes"] = [{"type": "con", "id": 5, "app_id": "chrome-127.0.0.1__-Default",
                                               "pid": 4242, "marks": [], "nodes": [], "floating_nodes": [],
                                               "rect": {"x": 0, "y": 0, "width": 1, "height": 1}}]
    assert WM.desktop_rules(fresh) == []  # unknown pid: not the desktop
    rule = WM.desktop_rules(fresh, 4200, is_child=lambda pid, root: (pid, root) == (4242, 4200))
    assert rule == ["[con_id=5] floating disable, border none, mark --add stickllm_desktop"]
    # once a desktop exists, more windows of the desktop Chromium (Ctrl+N, target=_blank) float
    t = _tree(_fc(9, "chrome-127.0.0.1__-Default"))
    t_rules = WM.desktop_rules(t, 1, is_child=lambda pid, root: True)
    assert t_rules == ["[con_id=9] floating enable, border normal 2"]


def test_descends_walks_proc(tmp_path):
    me = os.getpid()
    assert WM.descends(me, me)
    assert WM.descends(me, os.getppid())
    assert not WM.descends(me, 999999999)
    assert not WM.descends("x", 1)


def test_desktop_pid_file(tmp_path, monkeypatch):
    f = tmp_path / "d.pid"
    monkeypatch.setenv("STICKLLM_DESKTOP_PIDFILE", str(f))
    assert WM.read_desktop_pid() is None
    f.write_text("1234\n")
    assert WM.read_desktop_pid() == 1234
    f.write_text("1\n")
    assert WM.read_desktop_pid() is None


# --- the sway config we ship -------------------------------------------------

def _conf_lines():
    return [ln.strip() for ln in _text(CONF).splitlines() if ln.strip() and not ln.strip().startswith("#")]


def test_sway_config_has_no_escape_hatch():
    lines = _conf_lines()
    body = "\n".join(lines)
    binds = [ln for ln in lines if ln.startswith(("bindsym", "bindcode", "bindswitch", "bindgesture"))]
    assert len(binds) == 3
    assert all("exec /usr/local/bin/stickllm-wm " in b for b in binds)
    for bad in ("foot", "alacritty", "xterm", "terminal", "dmenu", "wmenu", "bemenu", "swaybar", "bar {",
                "reload", "restart", " exit", "swaymsg", "swaynag -", "include"):
        assert bad not in body, bad
    assert "xwayland disable" in lines and "swaynag_command -" in lines
    execs = [ln for ln in lines if ln.startswith("exec")]
    assert execs == ["exec /usr/local/bin/stickllm-sway-session"]
    assert 'for_window [app_id="^stickllm-desktop$"] floating disable, border none' in lines
    assert "show_marks no" in lines  # internal ids never appear in title bars


def test_session_and_kiosk_never_use_distribution_config():
    k = _text(BIN / "stickllm-kiosk")
    assert 'sway --unsupported-gpu -c "$SWAY_CONFIG"' in k
    assert "/etc/sway/config" not in k.replace("never read /etc/sway/config", "")
    s = _text(BIN / "stickllm-sway-session")
    assert "--class=stickllm-desktop" in s and "--kiosk" not in s
    assert '--app="$URL" &' in s  # chrome-less desktop: no tab strip or address bar
    assert 'echo "$desk" >"$STICKLLM_DESKTOP_PIDFILE"' in s and 'wait "$desk"' in s
    assert "stickllm-wm exit" in s


def test_wm_cli_only_targets_focused_non_desktop(monkeypatch):
    calls = []

    class I(FakeIPC):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    t = _tree(_fc(6, "stickllm-browser-aa11", focused=True))
    monkeypatch.setattr(WM, "find_socket", lambda dirs=None: "/x")
    monkeypatch.setattr(WM, "SwayIPC", lambda path, timeout=3.0: calls.append(I(t)) or calls[-1])
    assert WM.main(["stickllm-wm", "minimise-focused"]) == 0
    assert calls[-1].cmds[-1] == "[con_id=6] move scratchpad"
    td = _tree()
    td["nodes"][1]["nodes"][0]["nodes"][0]["focused"] = True
    monkeypatch.setattr(WM, "SwayIPC", lambda path, timeout=3.0: calls.append(I(td)) or calls[-1])
    WM.main(["stickllm-wm", "close-focused"])
    assert calls[-1].cmds == []  # Alt+F4 never closes the desktop


# --- kiosk ladder --------------------------------------------------------------

def test_kiosk_tries_sway_first_then_falls_back():
    k = _text(BIN / "stickllm-kiosk")
    i_sway = k.index('run_stack_forever "sway+$BROWSER')
    i_cage = k.index('run_stack_forever "cage+$BROWSER')
    i_west = k.index('run_stack_forever "weston+$BROWSER')
    assert i_sway < i_cage < i_west
    assert "STICKLLM_KIOSK_SWAY_FALLBACK" in k
    fn = k[k.index("sway_enabled() {"):k.index("\n}\n", k.index("sway_enabled() {"))]
    assert 'STICKLLM_KIOSK_SWAY:-1}" != "0"' in fn
    assert "stickllm\\.compositor=(cage|weston)" in fn
    assert "command -v sway" in fn and '-r "$SWAY_CONFIG"' in fn
    assert "rc=70" in k and "rc=71" in k
    assert '"custom_chrome_frame":false' in k


def test_package_list_ships_stock_sway():
    pl = _text(ROOT / "live-build" / "package-lists" / "stickllm.list.chroot").splitlines()
    assert "sway" in pl and "cage" in pl  # cage stays as the fallback
    for no in ("foot", "swaylock", "swayidle", "sway-backgrounds", "labwc", "wlrctl"):
        assert no not in pl


def test_third_party_notices_list_sway_stack():
    n = _text(ROOT / "THIRD_PARTY_NOTICES.md")
    for pkg in ("sway", "swaybg", "wlroots"):
        assert pkg in n
    assert "unmodified" in n.lower()


# --- control: browser_window --------------------------------------------------

class P:
    pid = 4242

    def poll(self):
        return None


def _ctl_with_window(monkeypatch, tree):
    ipc = FakeIPC(tree)
    monkeypatch.setattr(CTL, "_BROWSERS", {"aa11": {"proc": P(), "profile": Path("/nonexistent"), "title": "Browser",
                                                     "url": "about:blank", "app": False, "started": 0}})
    monkeypatch.setattr(CTL, "_wm_ipc", lambda: ipc)
    monkeypatch.setattr(CTL, "_wm", lambda: WM)
    return ipc


def test_browser_window_ops_go_through_compositor(monkeypatch):
    ipc = _ctl_with_window(monkeypatch, _tree(_fc(6, "stickllm-browser-aa11", focused=True)))
    r = CTL.handle("browser_window", {"id": "aa11", "op": "minimise"})
    assert r["ok"] and r["op"] == "minimise" and ipc.cmds[-1] == "[con_id=6] move scratchpad"
    r = CTL.handle("browser_window", {"id": "aa11", "op": "place", "geometry": {"x": 10, "y": 20, "w": 640, "h": 400}})
    assert r["ok"] and any("move absolute position 10 px 20 px" in c for c in ipc.cmds)
    st = CTL.handle("browser_status", {})
    assert st["wm"] is True and st["windows"][0]["mapped"] is True and "minimised" in st["windows"][0]


def test_browser_window_rejects_bad_input(monkeypatch):
    _ctl_with_window(monkeypatch, _tree(_fc(6, "stickllm-browser-aa11")))
    assert CTL.handle("browser_window", {"id": "aa11", "op": "exec foot"})["error"] == "bad_op"
    assert CTL.handle("browser_window", {"id": "zz99", "op": "focus"})["code"] == 404
    assert CTL.handle("browser_window", {"id": "aa11", "op": "place", "geometry": {"x": "a"}})["error"] == "bad_geometry"


def test_browser_window_without_sway_reports_fallback(monkeypatch):
    _ctl_with_window(monkeypatch, _tree())
    monkeypatch.setattr(CTL, "_wm_ipc", lambda: None)
    r = CTL.handle("browser_window", {"id": "aa11", "op": "minimise"})
    assert r["ok"] is False and r["error"] == "wm_unavailable"


def test_browser_owner_match_uses_launch_session(monkeypatch):
    _ctl_with_window(monkeypatch, _tree())
    monkeypatch.setattr(CTL.os, "getsid", lambda pid: 4242 if pid == 77 else 1)
    owns = CTL._browser_owns("aa11")
    assert owns(77) and not owns(78)
    assert not CTL._browser_owns("nope")(77)


def test_seeded_profile_uses_system_frame(tmp_path):
    CTL.browser_seed_prefs(tmp_path)
    prefs = json.loads((tmp_path / "Default" / "Preferences").read_text())
    assert prefs["browser"]["custom_chrome_frame"] is False
    (tmp_path / "Default" / "Preferences").write_text("{}")
    CTL.browser_seed_prefs(tmp_path)  # never overwrites
    assert (tmp_path / "Default" / "Preferences").read_text() == "{}"
