"""0.6.1 Agent Zero items (21-27)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay" / "usr" / "local" / "bin"
LIB = ROOT / "overlay" / "usr" / "local" / "lib"
UI = ROOT / "ui"


def _load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


sys.path.insert(0, str(LIB))
import stickllm_agent as AG  # noqa: E402

GW = _load(BIN / "stickllm-gateway", "gw_v061a")


def test_skill_lists_live_apps_browser_and_fast_path():
    text = AG.apps_skill_text()
    for app_id in AG.APPS_URL_IDS + ("docs", "node-red", "trilium"):
        assert f"- {app_id}:" in text
    assert "- browser:" in text and "open_url" in text
    assert "first and only tool" in text
    marked = AG.apps_skill_text(installed=["node-red"])
    assert "Node-RED (add-on, installed)" in marked
    assert "comfyui: ComfyUI (image generation) (add-on, not installed" in marked


def test_open_url_ok():
    ok = ["https://example.org/a?b=1", "http://192.168.1.5:1880/"]
    bad = ["", "file:///etc/passwd", "javascript:alert(1)", "http://127.0.0.1:8080/",
           "http://localhost/", "http://172.30.0.1:8081/", "https://user:pw@example.org/",
           "https://exa mple.org/", "x" * 3000, None, "http://[::1]/"]
    assert all(AG.open_url_ok(u) for u in ok)
    assert not any(AG.open_url_ok(u) for u in bad)


def test_open_tools_compile_and_are_registered():
    for src in (AG.open_url_tool_source(), AG.open_file_tool_source()):
        compile(src, "<tool>", "exec")
    assert "/open-url" in AG.open_url_tool_source()
    assert "### open_file" in AG.open_url_tool_prompt()
    plug = (LIB / "stickllm_agent.py").read_text(encoding="utf-8")
    assert 'root / "tools" / "open_file.py"' in plug
    gw = (BIN / "stickllm-gateway").read_text(encoding="utf-8")
    assert '"/api/ui/open-url"' in gw and 'kind == "open_url"' in gw


def test_plugins_setting_default_and_roundtrip(tmp_path):
    assert AG.plugins_unlocked_setting(tmp_path) is True
    out = AG.set_plugins_unlocked(False, root=tmp_path)
    assert out["ok"] and json.loads((tmp_path / "plugins.json").read_text())["unlocked"] is False
    assert AG.plugins_unlocked_setting(tmp_path) is False
    (tmp_path / "plugins.json").write_text("garbage")
    assert AG.plugins_unlocked_setting(tmp_path) is True


def test_handoff_page_may_be_framed_by_this_stick():
    csp = GW.csp_for_path("/__stickllm/handoff", "192.168.1.20:5443")
    assert "frame-ancestors" in csp and "https://192.168.1.20:*" in csp
    assert "frame-ancestors 'none'" not in csp


def test_ui_fallbacks_present():
    desk = (UI / "desktop.js").read_text(encoding="utf-8")
    assert "Open Agent Zero in a new tab" in desk and "openBrowser: (url, title)" in desk
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert 'id="a0Toggle"' in html and 'id="a0PluginsUnlocked"' in html and 'id="a0Welcome"' in html
    note = (UI / "apps/notepad/inline-scripts/fs-helpers.js").read_text(encoding="utf-8")
    assert note.count("STICKLLM_PICKER_ID") == 3
    assert "showOpenFilePicker({id: STICKLLM_PICKER_ID" in note
    docs = (UI / "apps/docs/docs.js").read_text(encoding="utf-8")
    assert "if (lastReady) open(j.path);" in docs


def test_open_fast_path_ids():
    app = (UI / "app.js").read_text(encoding="utf-8")
    start = app.index("const OPEN_FAST_ALIAS")
    end = app.index("function openFastPath(raw)")
    js = app[start:end] + """
const cases = ["open minesweep", "Open the calculator app", "start notepad.", "launch web browser",
  "open onlyoffice", "please open node red", "open my files", "what is 2+2", "open the pod bay doors now please ok"];
console.log(JSON.stringify(cases.map(openFastPathId)));
"""
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == ["minesweeper", "calculator", "notepad", "browser", "docs", "node-red", "files", "", ""]
