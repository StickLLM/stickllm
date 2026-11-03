"""0.5.6 app agent: browser apps (Notepad, Calculator, Solitaire), installed-only app list,
user load/unload control actions, shared chat model."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIBDIR = ROOT / "overlay" / "usr" / "local" / "lib"
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
CONTROL = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-control"
WRAPPER = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-appagent"
UNITS = ROOT / "overlay" / "etc" / "systemd" / "system"
HOOK = ROOT / "live-build" / "hooks" / "normal" / "0100-stickllm-setup.hook.chroot"
sys.path.insert(0, str(LIBDIR))

from stickllm_appagent.adapters.browser import (  # noqa: E402
    CLIENT_APPS, BrowserApp, CalculatorApp, MediaApp, MinesweeperApp, NotepadApp, SolitaireApp, TetrisApp,
)


def _load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_notepad_actions_and_undo():
    a = NotepadApp({"text": "hello"})
    a.begin_request("x")
    assert a.do('append "world"')[0]
    assert a.do('replace "hello" "hi"')[0]
    assert not a.do('replace "nope" "x"')[0]
    a.end_request()
    assert a.export()["client_actions"][-1] == {"set_text": "hi\nworld"}
    assert "hi\nworld" in a.state()
    a.set_client_state({"text": "hi\nworld"})
    a.begin_request("undo")
    ok, _ = a.do("undo")
    a.end_request()
    assert ok and a.done_actions == [{"set_text": "hello"}]
    a.begin_request("undo again")
    assert not a.do("undo")[0], "undo is not pushed onto the history"
    a.end_request()
    a.begin_request("save")
    assert a.do("saveas")[0] and a.actions == [{"save_as": True}]


def test_calculator_keys():
    c = CalculatorApp({"display": "0"})
    c.begin_request("x")
    assert c.do('keys "C12x7="')[0]
    assert c.actions == [{"expr": "C12*7="}]
    assert not c.do('keys "2^3"')[0]
    assert c.do("clear")[0] and c.actions[-1] == {"expr": "C"}
    assert "display: 0" in c.state()


def test_solitaire_moves():
    s = SolitaireApp({"piles": {"t1": "AS", "t2": "## TS", "t3": "TH", "t5": "JH", "f1": "-"}, "stock_count": 20, "score": "0"})
    s.begin_request("x")
    assert s.do("move t1->f1")[0]
    assert s.actions[-1] == {"move": "t1->f1"}
    assert s.do("move t2->t5")[0]
    assert not s.do("move t3->t5")[0], "same colour is illegal"
    assert not s.do("move t2->t5 10h")[0], "TH is not the face-up card on t2"
    assert not s.do("move t9->f1")[0]
    assert not s.do("move t2->t5 ZZ")[0]
    assert s.do("draw")[0] and s.do("undo")[0]
    assert "t1: AS" in s.state()
    assert "no state" in SolitaireApp().state()


def test_tetris_place_and_nudge():
    t = TetrisApp({"status": "playing", "mode": "turn", "score": 0, "lines": 0, "suggest": {"place": {"col": 3, "rot": 1}}})
    t.begin_request("x")
    assert t.do("place suggested")[0] and t.actions[-1] == {"place": "suggested"}
    assert t.do("place 4 2")[0] and t.actions[-1] == {"place": {"col": 4, "rot": 2}}
    assert t.do("left 2")[0] and t.actions[-1] == {"left": 2}
    assert not t.do("place 11 0")[0]
    assert "suggested place col=3 rot=1" in t.state()


def test_minesweeper_stays_on_the_board():
    g = "\n".join(["#####", "#1###", "#####"])
    m = MinesweeperApp({"grid": g})
    m.begin_request("x")
    assert m.do("reveal 0 0")[0] and m.actions[-1] == {"reveal": [0, 0]}
    assert not m.do("reveal 9 0")[0]
    assert not m.do("reveal 1 1")[0], "an open digit is not clicked again"
    assert m.do("flag 0 4")[0]


def test_media_opens_only_listed_names():
    a = MediaApp({"root": "vault", "path": "", "entries": [{"name": "cats.mp4", "dir": False}, {"name": "Holiday", "dir": True}], "kind": ""})
    a.begin_request("x")
    assert a.do('open "cats.mp4"')[0] and a.actions[-1] == {"open": "cats.mp4"}
    assert not a.do('open "missing.mp4"')[0]
    assert not a.do("play")[0]
    a.set_client_state({"kind": "video", "file": "cats.mp4", "entries": []})
    assert a.do("pause")[0] and a.actions[-1] == {"pause": True}


def test_browser_writes_a_page():
    b = BrowserApp({"windows": []})
    b.begin_request("write a Hello World page and display it in the browser")
    ok, msg = b.do('page Hello World ||| <!DOCTYPE html>\\n<html><body><h1>Hello World</h1></body></html>')
    assert ok, msg
    page = b.actions[-1]["page"]
    assert page["title"] == "Hello World"
    assert "<h1>Hello World</h1>" in page["html"]
    assert "\n" in page["html"]
    assert not b.do("page Hello ||| ")[0]
    assert not b.do('open "file:///etc/passwd"')[0]


def test_gateway_saves_browser_page(tmp_path, monkeypatch):
    monkeypatch.setenv("STICKLLM_BROWSER_PAGES", str(tmp_path))
    gw = _load(GATEWAY, "gw_v056_page")
    saved = gw.save_browser_page("Hello World", "<h1>Hello World</h1>")
    assert saved["ok"] and saved["url"].startswith("http://127.0.0.1:")
    token = saved["url"].rstrip("/").rsplit("/", 1)[-1]
    assert gw.load_browser_page(token) == b"<h1>Hello World</h1>"
    assert gw.load_browser_page("../" + token) is None
    assert gw.save_browser_page("x", "   ")["ok"] is False
    assert "connect-src 'none'" in gw.BROWSER_PAGE_CSP
    assert saved["vault"]["saved"] is False

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(gw, "VAULT_MNT", vault)
    monkeypatch.setattr(gw, "vault_unlocked", lambda: True)
    one = gw.save_browser_page("Hello/World", "<h1>Hello</h1>")
    two = gw.save_browser_page("Hello/World", "<h1>Again</h1>")
    assert one["vault"] == {"saved": True, "path": "vault/Programs/HelloWorld.html"}
    assert (vault / "Programs" / "HelloWorld.html").read_text(encoding="utf-8") == "<h1>Hello</h1>"
    assert two["vault"]["path"] == "vault/Programs/HelloWorld 2.html"
    name = gw.program_filename("../../etc/passwd")
    assert name.endswith(".html") and "/" not in name and "\\" not in name and ".." not in name


def test_browser_urls_and_windows():
    b = BrowserApp({"windows": [{"id": "abc123def456", "title": "Wikipedia", "url": "https://wikipedia.org"}]})
    b.begin_request("x")
    assert b.do('open "wikipedia.org"')[0]
    assert b.actions[-1]["open"] == "https://wikipedia.org"
    assert not b.do('open "file:///etc/passwd"')[0]
    assert b.do("focus wikipedia")[0] and b.actions[-1] == {"focus": "abc123def456"}
    assert b.do("close")[0] and b.actions[-1] == {"close": "abc123def456"}
    assert "id=abc123def456" in b.state()


def test_client_apps_have_manuals():
    for name, cls in CLIENT_APPS.items():
        man = cls().manual
        assert man and len(man) > 200, name
        for v in cls.verbs:
            assert v in man or v in cls.ACTIONS, (name, v)


def test_gateway_lists_installed_apps_only(tmp_path, monkeypatch):
    gw = _load(GATEWAY, "gw_v056_aa")
    ui = tmp_path / "ui"
    (ui / "apps" / "notepad").mkdir(parents=True)
    (ui / "apps" / "notepad" / "index.html").write_text("x", encoding="utf-8")
    monkeypatch.setattr(gw, "UI_ROOT", ui)

    class Docs:
        @staticmethod
        def is_installed():
            return False

    class Addons:
        @staticmethod
        def is_installed(name):
            return name == "node-red"

    monkeypatch.setattr(gw, "docs_lib", lambda: Docs)
    monkeypatch.setattr(gw, "addons_lib", lambda: Addons)
    data = json.dumps([{"name": n} for n in ("onlyoffice", "nodered", "notepad", "calculator", "solitaire", "slides", "tetris", "browser")]).encode()
    out = [a["name"] for a in json.loads(gw.appagent_filter_apps(data))]
    assert out == ["nodered", "notepad", "browser"]
    assert gw.appagent_filter_apps(b"not json") == b"not json"


def test_control_user_load_unload_and_shared_model():
    src = CONTROL.read_text(encoding="utf-8")
    for act in ("model_unload", "appagent_status", "appagent_load", "appagent_unload"):
        assert f'action == "{act}"' in src
    w = WRAPPER.read_text(encoding="utf-8")
    assert "STICKLLM_LLAMA_PORT:-8080" in w, "the app agent uses the chat llama-server"
    assert "--ui-url" not in w
    for n in ("onlyoffice", "nodered", "notepad", "calculator", "solitaire", "tetris", "minesweeper", "media", "browser"):
        assert n in w
    hook = HOOK.read_text(encoding="utf-8")
    assert "systemctl enable stickllm-appagent.service" not in hook
    unit = (UNITS / "stickllm-appagent.service").read_text(encoding="utf-8")
    assert "stickllm-appagent-llm" not in unit.split("[Install]")[0].split("After=")[-1].split("\n")[0]


# --- 0.5.6: vault tagged with the computer it lives on ------------------------

def test_vault_other_computer_ui_and_script():
    js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    vault = (ROOT / "overlay/usr/local/bin/stickllm-vault").read_text(encoding="utf-8")
    assert 'id="vaultOther"' in html and 'id="vaultOtherSearch"' in html and 'id="vaultOtherPick"' in html
    assert "Vault is on another computer" in js
    assert "showVaultOther(!open && !!v.other_computer" in js
    assert "VAULT_OTHER_RE.test(raw)" in js
    assert '"other_computer": vmatch == "other"' in vault
    assert 'tag_meta_machine' in vault and '"machine_id": os.environ.get("STICKLLM_LOC_MACHINE")' in vault
    assert "timeout=25" in vault          # a stuck host mount fails fast


def test_node_red_editor_autoreload_is_settings_only():
    share = ROOT / "overlay/usr/local/share/stickllm/addons"
    js = (share / "node-red-autoreload.js").read_text(encoding="utf-8")
    assert "RED.nodes.dirty()" in js and "location.reload()" in js
    assert 'page: { scripts: ["/data/stickllm-autoreload.js"] }' in (share / "node-red-settings.js").read_text(encoding="utf-8")
