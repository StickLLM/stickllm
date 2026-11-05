"""0.6.2 (A): Agent Zero installs, starts and opens reliably."""
import importlib.machinery
import importlib.util
import json
import socket
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "overlay/usr/local/lib/stickllm_agent.py"
AGENT_SH = ROOT / "overlay/usr/local/bin/stickllm-agent"
A0CLIENT = ROOT / "overlay/usr/local/lib/stickllm_a0client.py"
GATEWAY = ROOT / "overlay/usr/local/bin/stickllm-gateway"


def _load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_bridge_bind_never_does_reverse_dns(monkeypatch):
    """Root cause of the 8081 restart loop: HTTPServer.server_bind calls
    socket.getfqdn(), which blocks on the stick (no PTR, no resolver)."""
    a = _load(AGENT, "stickllm_agent_v062a")
    def boom(*_a, **_k):
        raise AssertionError("getfqdn must not be called")
    monkeypatch.setattr(socket, "getfqdn", boom)
    srv = a.QuickBindHTTPServer(("127.0.0.1", 0), a.BaseHTTPRequestHandler if hasattr(a, "BaseHTTPRequestHandler") else __import__("http.server").server.BaseHTTPRequestHandler)
    try:
        assert srv.server_name == "127.0.0.1" and srv.server_port > 0
    finally:
        srv.server_close()


def test_bind_with_retry_logs_and_retries(capsys):
    a = _load(AGENT, "stickllm_agent_v062b")
    calls = []
    def factory():
        calls.append(1)
        if len(calls) < 3:
            raise OSError(99, "Cannot assign requested address")
        return "ok"
    assert a.bind_with_retry(factory, "apps bridge", attempts=5, delay=0) == "ok"
    assert len(calls) == 3
    assert "apps bridge" in capsys.readouterr().err


def test_install_progress_bands_reach_100_only_when_running():
    a = _load(AGENT, "stickllm_agent_v062c")
    assert a.install_progress("loading", 0) == 0
    assert a.install_progress("loading", 100) <= a.install_progress("unpacking", 0)
    assert a.install_progress("health", 100) < 100
    assert a.INSTALL_STEPS == 6


def test_minilm_seed_into_hub_layout(tmp_path):
    a = _load(AGENT, "stickllm_agent_v062d")
    bundle = tmp_path / "medium"
    files = bundle / "minilm" / "files"
    (files / "1_Pooling").mkdir(parents=True)
    (files / "model.safetensors").write_bytes(b"w" * 1_100_000)
    (files / "config.json").write_text("{}")
    (files / "1_Pooling" / "config.json").write_text("{}")
    rev = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    (bundle / "minilm" / "minilm.json").write_text(json.dumps({"revision": rev}))
    root, hf = tmp_path / "st", tmp_path / "hf"
    assert a.seed_embedding(root=root, hf_home=hf, dirs=(bundle,)) is True
    for base in (root, hf / "hub"):
        snap = base / "models--sentence-transformers--all-MiniLM-L6-v2"
        assert (snap / "refs" / "main").read_text().strip() == rev
        assert (snap / "snapshots" / rev / "model.safetensors").stat().st_size == 1_100_000
        assert (snap / "snapshots" / rev / "1_Pooling" / "config.json").is_file()
    assert a.seed_embedding(root=root, hf_home=hf, dirs=(tmp_path / "none",)) is False


def test_start_order_egress_before_network_steps():
    text = AGENT_SH.read_text()
    run = text.split("cmd_run_container()", 1)[1].split("\n}\n", 1)[0]
    order = ["ensure_egress", "ensure_relay", "ensure_apps", "cache_embedding", "docker_cli run"]
    idx = [run.index(x) for x in order if x in run]
    assert idx == sorted(idx) and len(idx) >= 4
    emb = text.split("cache_embedding()", 1)[1].split("\n}\n", 1)[0]
    assert "seed-embedding" in emb and "timeout" in emb and "18080" in emb
    assert 'HF_HUB_OFFLINE="${STICKLLM_HF_OFFLINE:-0}"' in text


def test_build_bundles_minilm():
    build = (ROOT / "scripts/lib/docker-build-live.sh").read_text()
    assert "minilm_bundle.py pack" in build and '"$A0_BUNDLE_OUT/minilm"' in build
    mb = _load(ROOT / "scripts/lib/minilm_bundle.py", "minilm_bundle_v062")
    assert mb.REVISION == "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    assert mb.PINNED["model.safetensors"][1] == 90868376


def test_agent_window_never_iframes_before_running():
    desk = (ROOT / "ui/desktop.js").read_text()
    body = desk.split("function openAgent()", 1)[1].split("\n  function renderAgentPanel", 1)[0]
    assert "ag.installed && ag.running" in body and "setInterval(tick, 1500)" in body
    assert "It installs onto the vault" not in desk
    assert "/mnt/stickllm-data/stickllm-docker" in desk
    assert "apRetry" in desk and "/api/agent/start" in desk


def test_chat_routes_to_agent_zero_inline():
    app = (ROOT / "ui/app.js").read_text()
    assert "return sendToAgentZero(raw.trim());" in app
    body = app.split("async function sendToAgentZero", 1)[1].split("\ndocument.addEventListener", 1)[0]
    assert '"ask"' in body and '"poll"' in body and "a0Looping" in body
    gw = GATEWAY.read_text()
    assert '"/api/agent/ask", "/api/agent/poll", "/api/agent/stop"' in gw
    c = _load(A0CLIENT, "stickllm_a0client_v062")
    assert c.repeat_loop(["same", "x", "Same ", "same", "same"]) is True
    assert c.repeat_loop(["a", "b", "a"]) is False


def test_no_typed_confirm_words_in_ui():
    app = (ROOT / "ui/app.js").read_text()
    html = (ROOT / "ui/index.html").read_text()
    assert 'id="cfInput"' not in html and "to confirm</span>" not in html
    assert 'id="cfCheck"' in html
    assert "cfInput" not in app
