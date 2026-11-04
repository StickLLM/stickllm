"""0.6.0: A0 preset follows the loaded model (A4/bug 14), A0 speech (A3), shared chats bind (A2)."""
import importlib.machinery
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "overlay/usr/local/lib/stickllm_agent.py"
AGENT_SH = ROOT / "overlay/usr/local/bin/stickllm-agent"
CONTROL = ROOT / "overlay/usr/local/bin/stickllm-control"
GW = ROOT / "overlay/usr/local/bin/stickllm-gateway"
A0C = ROOT / "overlay/usr/local/lib/stickllm_a0client.py"


def _load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_sync_model_rewrites_default_preset(tmp_path, monkeypatch):
    a = _load(AGENT, "stickllm_agent_v060")
    monkeypatch.setattr(a, "PORTABLE", tmp_path)
    monkeypatch.setattr(a, "settings_mounted", lambda: True)
    (tmp_path / "model-config").mkdir()
    (tmp_path / "model-config" / "presets.yaml").write_text(a.preset_text("old-model.gguf"))
    (tmp_path / "settings.json").write_text(json.dumps(a.merge_model_settings({}, "old-model.gguf")))
    monkeypatch.setattr(a, "llama_model_ready_id", lambda: "Qwen3-32B-Q4_K_M.gguf")
    res = a.sync_model(wait=0)
    assert res["ok"] and res["model"] == "Qwen3-32B-Q4_K_M.gguf" and res["changed"]
    text = (tmp_path / "model-config" / "presets.yaml").read_text()
    assert "Qwen3-32B-Q4_K_M.gguf" in text and "old-model" not in text
    assert "http://172.30.0.1:8080/v1" in text
    assert "old-model" not in (tmp_path / "settings.json").read_text()


def test_sync_model_waits_for_llama(tmp_path, monkeypatch):
    a = _load(AGENT, "stickllm_agent_v060b")
    monkeypatch.setattr(a, "PORTABLE", tmp_path)
    monkeypatch.setattr(a, "settings_mounted", lambda: True)
    monkeypatch.setattr(a, "llama_model_ready_id", lambda: "")
    assert not a.sync_model(wait=0, poll=0)["ok"]


def test_model_change_spawns_sync():
    c = CONTROL.read_text()
    body = c[c.index("def activate_model("):]
    i = body.index('"systemctl", "restart", "stickllm-llama.service"')
    c = body
    assert '"/usr/local/bin/stickllm-agent", "sync-model"' in c[i:i + 600]
    sh = AGENT_SH.read_text()
    assert "sync-model) shift; cmd_sync_model" in sh
    assert 'sync-model 600' in sh


def test_agent_binds_shared_chats():
    sh = AGENT_SH.read_text()
    assert "a0-chats-dir" in sh and '"${CHATS_ARGS[@]}"' in sh
    assert sh.index('-v "${ADDON}/state:/a0/usr"') < sh.index('"${CHATS_ARGS[@]}"')


def test_speech_prefers_agent_zero_with_fallback():
    gw = GW.read_text()
    tr = gw[gw.index('if path == "/api/speech/transcribe":'):]
    tr = tr[: tr.index('if path == "/api/speech/speak":')]
    assert tr.index('a0_speech("stt"') < tr.index('run_speech("stt"')
    sp = gw[gw.index('if path == "/api/speech/speak":'):]
    sp = sp[: sp.index('if path == "/api/chat/stop":')]
    assert sp.index('a0_speech("tts"') < sp.index('run_speech("tts"')


class _FakeClient:
    pass


def test_a0_client_csrf_flow(monkeypatch):
    m = _load(A0C, "stickllm_a0client_t")
    c = m.A0Client()
    calls = []

    def req(method, path, body, timeout, headers=None):
        calls.append((method, path, dict(headers or {})))
        if path == "/api/csrf_token":
            return 200, {"ok": True, "token": "T1", "runtime_id": "r"}, ["session=abc; HttpOnly; Path=/"]
        if headers.get("X-CSRF-Token") != "T1" or "session=abc" not in headers.get("Cookie", ""):
            return 403, {}, []
        if path.endswith("/transcribe"):
            return 200, {"success": True, "text": " hi "}, []
        return 200, {"success": True, "audio": "data:audio/wav;base64,UklG"}, []

    monkeypatch.setattr(c, "_request", req)
    assert c.transcribe("AAAA") == " hi "
    assert c.synthesize("hello") == "UklG"
    assert calls[0][1] == "/api/csrf_token"
