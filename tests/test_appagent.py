"""App agent (stickllm-appagent): frozen checker, service API with a fake model, docs plugin wiring, packaging."""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_docs import POSIX, SECRET, _docs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_appagent"
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
UNIT = ROOT / "overlay" / "etc" / "systemd" / "system" / "stickllm-appagent.service"
WRAPPER = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-appagent"
BUILD = ROOT / "scripts" / "lib" / "docker-build-live.sh"
HOOK = ROOT / "live-build" / "hooks" / "normal" / "0100-stickllm-setup.hook.chroot"
CHECKER_SHA = "6efd3e887772abba2dbb1ebf8228c5cdc08d67ad245118a3d6e8401c476188fa"
GUID = "asc.{5A1C0E2B-7D4F-4E8A-9B6C-511C4A11A0E1}"


def test_checker_is_the_frozen_one():
    assert hashlib.sha256((PKG / "checker.py").read_bytes()).hexdigest() == CHECKER_SHA


def test_plugin_matches_docs_guid_and_is_system():
    cfg = json.loads((PKG / "plugin" / "config.json.tmpl").read_text(encoding="utf-8"))
    assert cfg["guid"] == GUID
    var = cfg["variations"][0]
    assert var["isSystem"] is True and var["EditorsSupport"] == ["slide"]
    js = (PKG / "plugin" / "plugin.js").read_text(encoding="utf-8")
    assert "/oo/poll" in js and "callCommand" in js and "location.origin" not in js  # prefix-aware base


@POSIX
def test_editor_config_attaches_agent_plugin_only_to_editable_slides(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_appagent")
    docs.prepare_vault()
    for name in ("a.pptx", "b.docx"):
        (tmp_path / "vault" / "Documents" / name).write_bytes(b"x")
    url = "http://stick.local/appagent/oo/plugin/config.json"
    cfg = docs.editor_config("a.pptx", SECRET, agent_plugin_url=url)["config"]
    assert cfg["editorConfig"]["plugins"] == {"autostart": [GUID], "pluginsData": [url]}
    # ONLYOFFICE starts no plugin at all while customization.plugins is false.
    assert cfg["editorConfig"]["customization"]["plugins"] is True
    assert docs.jwt_verify(cfg["token"], SECRET)["editorConfig"]["plugins"]["pluginsData"] == [url]
    other = docs.editor_config("b.docx", SECRET, agent_plugin_url=url)["config"]
    assert "plugins" not in other["editorConfig"] and other["editorConfig"]["customization"]["plugins"] is False
    plain = docs.editor_config("a.pptx", SECRET)["config"]
    assert "plugins" not in plain["editorConfig"] and plain["editorConfig"]["customization"]["plugins"] is False


def test_gateway_relays_appagent_for_paired_browsers_only():
    src = GATEWAY.read_text(encoding="utf-8")
    assert src.count('path.startswith("/appagent/")') == 2  # GET and POST
    body = src.split("def _appagent_proxy", 1)[1].split("\n    def ", 1)[0]
    assert "self._desktop_allowed()" in body and '"127.0.0.1", APPAGENT_PORT' in body
    assert "agent_plugin_url=plugin_url" in src


def test_packaging():
    unit = UNIT.read_text(encoding="utf-8")
    assert "ExecStart=/usr/local/bin/stickllm-appagent" in unit and "DynamicUser=yes" in unit
    wrap = WRAPPER.read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in wrap and "8795" in wrap
    assert "systemctl enable stickllm-appagent.service" in HOOK.read_text(encoding="utf-8")
    assert "stickllm_appagent/service.py" in BUILD.read_text(encoding="utf-8")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _FakeLLM(BaseHTTPRequestHandler):
    """OpenAI-compatible stand-in: always plans 'add a red rect'."""
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _FakeLLM.seen.append(body)
        plan = {"understanding": "add a red box", "plan": ["add rect fill=red size=0.2 at=center"]}
        out = json.dumps({"choices": [{"message": {"content": json.dumps(plan)}}], "usage": {}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def _call(base, path, body=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def test_service_act_and_undo_with_fake_model():
    llm = ThreadingHTTPServer(("127.0.0.1", 0), _FakeLLM)
    threading.Thread(target=llm.serve_forever, daemon=True).start()
    port = _free_port()
    proc = subprocess.Popen([sys.executable, str(PKG / "service.py"), "--host", "127.0.0.1", "--port", str(port),
                             "--llm-url", f"http://127.0.0.1:{llm.server_port}", "--apps", "slides"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(50):
            try:
                apps = _call(base, "/apps")
                break
            except OSError:
                time.sleep(0.1)
        assert [a["name"] for a in apps] == ["slides"]
        r = _call(base, "/act", {"app": "slides", "session": "t", "request": "add a red box"})
        assert r["plan"] == ["add rect fill=red size=0.2 at=center"]
        assert r["results"][0]["ok"] and "s1 rect fill=red" in r["state"]
        # Thinking off, manual first (stable prefix), grammar-free JSON schema plan, prompt cache on.
        sent = _FakeLLM.seen[0]
        assert sent["cache_prompt"] is True and sent["chat_template_kwargs"] == {"enable_thinking": False}
        assert sent["messages"][0]["role"] == "system" and "MANUAL" in sent["messages"][0]["content"]
        assert _call(base, "/undo", {"app": "slides", "session": "t"})["ok"]
        assert _call(base, "/state?app=slides&session=t")["objs"] == []
    finally:
        proc.terminate()
        proc.wait(5)
        llm.shutdown()
