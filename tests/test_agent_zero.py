"""Agent Zero gates: unpaired /agent is refused, and a locked vault does not start Docker."""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
AGENT = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_agent.py"
SCRIPT = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-agent"
PIN = ROOT / "overlay" / "usr" / "local" / "share" / "stickllm" / "agent-zero.pin"


def _load(path: Path, name: str, env: dict | None = None):
    if env:
        os.environ.update(env)
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_pin_is_a_real_digest():
    agent = _load(AGENT, "stickllm_agent_pin")
    pin = agent.load_pin(PIN)
    assert pin["image"] == "agent0ai/agent-zero"
    assert pin["version"] == "v2.14"
    assert pin["amd64_digest"] == (
        "sha256:307a2ceffc8501ba05a1e7253e8b6e4d656d2e1c3b97f0eb943c18b9c40a30fd"
    )
    assert agent.image_ref(pin).endswith("@" + pin["amd64_digest"])


def test_locked_vault_does_not_allow_docker(tmp_path):
    agent = _load(AGENT, "stickllm_agent_gate")
    assert agent.docker_may_start(False) is False
    assert agent.docker_may_start(True) is True
    mounts = tmp_path / "mounts"
    mounts.write_text("/dev/sda1 /mnt/other ext4 rw 0 0\n", encoding="utf-8")
    vault = tmp_path / "vault"
    vault.mkdir()
    assert agent.vault_mounted(vault, mounts.read_text(encoding="utf-8")) is False
    assert agent.pull_allowed(14_000_000_000) is False
    assert agent.pull_allowed(15_000_000_000) is True
    assert agent.pull_allowed(None) is False


def test_agent_script_checks_the_vault_before_dockerd():
    text = SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n")
    body = text.split("cmd_run_container()", 1)[1].split("\ncmd_run()", 1)[0]
    assert "docker-may-start" in body
    assert body.index("docker-may-start") < body.index("ensure_dockerd")
    daemon = text.split("ensure_dockerd()", 1)[1].split("\nimage_present()", 1)[0]
    assert daemon.index("docker-may-start") < daemon.index("\n  dockerd")


def test_rewrite_keeps_agent_under_its_prefix():
    agent = _load(AGENT, "stickllm_agent_rewrite")
    text = agent.rewrite_text(
        'import "/js/api.js"; fetch("/api/csrf_token"); const p = "/socket.io"; "/agent/js/already.js"'
    )
    assert '"/agent/js/api.js"' in text
    assert '"/agent/api/csrf_token"' in text
    assert '"/agent/socket.io"' in text
    assert "/agent/agent/" not in text
    assert agent.rewrite_location("/login") == "/agent/login"
    assert agent.upstream_path("/agent/js/api.js") == "/js/api.js"
    preset = agent.preset_text("qwen.gguf")
    assert "http://127.0.0.1:8080/v1" in preset
    assert "device: cpu" in preset
    assert "llama_cpp" in preset


def test_unpaired_agent_route_is_refused(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html></html>", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    token = "paired-token"
    auth = {
        "require_pair": True,
        "paired": True,
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
    }
    (run / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    env = {
        "STICKLLM_UI": str(ui),
        "STICKLLM_RUN": str(run),
        "STICKLLM_VAULT_MNT": str(tmp_path / "vault"),
        "STICKLLM_SETTINGS_MNT": str(tmp_path / "settings"),
        "STICKLLM_AGENT_STATUS": str(run / "agent-status.json"),
        "STICKLLM_AGENT_PIN": str(PIN),
        "STICKLLM_MOUNTS_FILE": str(tmp_path / "empty-mounts"),
    }
    (tmp_path / "empty-mounts").write_text("", encoding="utf-8")
    (tmp_path / "vault").mkdir()
    gateway = _load(GATEWAY, "stickllm_gateway_agent", env)

    class LanHandler(gateway.Handler):
        def _is_loopback(self) -> bool:
            return False

    httpd = gateway.ThreadingHTTPServer(("127.0.0.1", 0), LanHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/agent", timeout=5)
            raise AssertionError("unpaired /agent was allowed")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            assert exc.code == 401
            assert "pair_required" in body

        status_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/agent/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(status_req, timeout=5) as resp:
            doc = json.loads(resp.read().decode())
        assert doc["vault_unlocked"] is False
        assert doc["message"] == "Unlock vault to use Agent"

        page_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/agent",
            headers={"Cookie": f"stickllm_pair={token}"},
        )
        with urllib.request.urlopen(page_req, timeout=5) as resp:
            html = resp.read().decode()
        assert "Unlock vault to use Agent" in html
    finally:
        httpd.shutdown()
