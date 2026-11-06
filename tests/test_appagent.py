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
CHECKER_SHA = "085e2a4058fee59d46f2a7a245734eecaaf66a683937425bd7a77129aec2ccff"  # stickman 7f3b75e service/checker.py (http-in -> http-response wire check)
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
    assert cfg["editorConfig"]["customization"]["layout"] == {"toolbar": {"plugins": False}}
    assert docs.jwt_verify(cfg["token"], SECRET)["editorConfig"]["plugins"]["pluginsData"] == [url]
    other = docs.editor_config("b.docx", SECRET, agent_plugin_url=url)["config"]
    assert "plugins" not in other["editorConfig"] and other["editorConfig"]["customization"]["plugins"] is False
    plain = docs.editor_config("a.pptx", SECRET)["config"]
    assert "plugins" not in plain["editorConfig"] and plain["editorConfig"]["customization"]["plugins"] is False


def test_docs_image_strips_bundled_plugins():
    src = (ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-docs").read_text(encoding="utf-8")
    strip = src.split("STRIP_PLUGINS='", 1)[1].split("\n", 1)[0]
    assert "sdkjs-plugins" in strip and '= v1 ] || rm -rf' in strip and 'printf "[]' in strip
    assert "-r false && ${STRIP_PLUGINS}" in src
    assert "PLUGINS_ENABLED=false" in src


def test_gateway_relays_appagent_for_paired_browsers_only():
    src = GATEWAY.read_text(encoding="utf-8")
    assert src.count('path.startswith("/appagent/")') == 2  # GET and POST
    body = src.split("def _appagent_proxy", 1)[1].split("\n    def ", 1)[0]
    assert "self._desktop_allowed()" in body and '"127.0.0.1", APPAGENT_PORT' in body
    assert 'method == "POST" and not stickllm_ui_client(self.headers) and not self._is_loopback()' in body
    js = (PKG / "plugin" / "plugin.js").read_text(encoding="utf-8")
    assert js.count('"X-StickLLM-Client": "ui"') == 2
    assert "agent_plugin_url=plugin_url" in src


def test_packaging():
    unit = UNIT.read_text(encoding="utf-8")
    assert "ExecStart=/usr/local/bin/stickllm-appagent" in unit and "DynamicUser=yes" in unit
    wrap = WRAPPER.read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in wrap and "8795" in wrap
    hook = HOOK.read_text(encoding="utf-8")
    # 0.5.6: nothing auto-loads; the user loads the app agent from the chat page
    assert "systemctl enable stickllm-appagent.service" not in hook
    assert "systemctl disable stickllm-appagent.service" in hook
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


def test_chat_ui_app_agent_wiring_js():
    out = subprocess.run(["node", str(Path(__file__).with_name("appagent_ui.test.js"))], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr


LLM_UNIT = ROOT / "overlay" / "etc" / "systemd" / "system" / "stickllm-appagent-llm.service"
LLM_WRAPPER = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-appagent-llm"


def test_appagent_shares_the_chat_model_and_helper_is_optional():
    """One baked base model for chat AND app control. The app agent talks to the chat llama-server;
    the separate 8796 helper stays shipped for advanced use but is never enabled or pulled in."""
    wrap = WRAPPER.read_text(encoding="utf-8")
    assert "STICKLLM_LLAMA_PORT:-8080" in wrap and "STICKLLM_APPAGENT_LLM_PORT" not in wrap
    src = LLM_WRAPPER.read_text(encoding="utf-8")
    assert "/opt/stickllm/models/appagent/qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf" in src
    assert "--host 127.0.0.1" in src and "8796" in src and "--jinja" in src
    assert "--n-gpu-layers 99" in src and "--n-gpu-layers 0" in src
    assert "llama-server-vulkan" in src and "mem_info_vram_total" in src  # AMD/Intel via Vulkan
    unit = LLM_UNIT.read_text(encoding="utf-8")
    assert "ExecStart=/usr/local/bin/stickllm-appagent-llm" in unit and "DynamicUser=yes" in unit
    assert "qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf" in unit
    agent_unit = UNIT.read_text(encoding="utf-8")
    assert "stickllm-appagent-llm" not in agent_unit.split("[Service]")[0].replace("Description", "")
    assert "Wants=stickllm-appagent-llm" not in agent_unit
    hook = HOOK.read_text(encoding="utf-8")
    assert "systemctl enable stickllm-appagent-llm.service" not in hook
    build = BUILD.read_text(encoding="utf-8")
    assert "models/appagent/${f}" in build and "sha256sum -c" in build
    assert "dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db" in build
    assert 'base_model_id = "qwen25-7b-q4km"' in (ROOT / "config/models/catalog.toml").read_text(encoding="utf-8")
    gw = GATEWAY.read_text(encoding="utf-8")
    assert "8796" not in gw.replace("APPAGENT_PORT = 8795", "")  # not exposed by the gateway


@pytest.mark.skipif(sys.platform == "win32", reason="bash")
def test_appagent_llm_launcher_picks_vulkan_for_amd(tmp_path):
    model = tmp_path / "m.gguf"
    model.write_bytes(b"x")
    fake = tmp_path / "vk"
    fake.write_text("#!/bin/sh\necho VK \"$@\"\n")
    fake.chmod(0o755)
    drm = tmp_path / "drm"
    for i, (tot, used) in enumerate(((8 << 30, 7 << 30), (16 << 30, 1 << 30))):
        d = drm / ("card%d" % i) / "device"
        d.mkdir(parents=True)
        (d / "mem_info_vram_total").write_text(str(tot))
        (d / "mem_info_vram_used").write_text(str(used))
    env = {"PATH": "/usr/bin:/bin", "STICKLLM_APPAGENT_MODEL": str(model), "STICKLLM_LLAMA_VULKAN": str(fake),
           "STICKLLM_LLAMA_CUDA": str(tmp_path / "missing"), "STICKLLM_LLAMA_CPU": str(tmp_path / "missing"),
           "STICKLLM_SYSFS_DRM": str(drm), "STICKLLM_LIB_VULKAN": str(tmp_path)}
    out = subprocess.run(["bash", str(LLM_WRAPPER)], capture_output=True, text=True, env=env, timeout=30)
    assert out.returncode == 0, out.stderr
    assert out.stdout.startswith("VK ") and "--device Vulkan1" in out.stdout and "--n-gpu-layers 99" in out.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="bash")
def test_appagent_llm_launcher_picks_cpu_without_gpu(tmp_path):
    model = tmp_path / "m.gguf"
    model.write_bytes(b"x")
    fake = tmp_path / "srv"
    fake.write_text("#!/bin/sh\necho \"$@\"\n")
    fake.chmod(0o755)
    env = {"PATH": "/usr/bin:/bin", "STICKLLM_APPAGENT_MODEL": str(model), "STICKLLM_LLAMA_CPU": str(fake),
           "STICKLLM_LLAMA_CUDA": str(tmp_path / "missing"), "STICKLLM_LIB_CPU": str(tmp_path),
           "STICKLLM_LLAMA_VULKAN": str(tmp_path / "missing")}
    out = subprocess.run(["bash", str(LLM_WRAPPER)], capture_output=True, text=True, env=env, timeout=30)
    assert out.returncode == 0, out.stderr
    assert "--n-gpu-layers 0" in out.stdout and "--port 8796" in out.stdout and "--host 127.0.0.1" in out.stdout
    missing = subprocess.run(["bash", str(LLM_WRAPPER)], capture_output=True, text=True,
                             env={**env, "STICKLLM_APPAGENT_MODEL": str(tmp_path / "none.gguf")}, timeout=30)
    assert missing.returncode == 1 and "model missing" in missing.stderr
