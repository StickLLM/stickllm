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


class _FakeAddons:
    def __init__(self, state="stopped", vault=True, installed=True, running=False):
        self.saved = {"state": state, "updated": 1}
        self.vault, self.installed, self.running = vault, installed, running

    def status_document(self, app_id):
        st = self.saved.get("state")
        return {"vault_open": self.vault, "installed": self.installed, "running": self.running,
                "state": "locked" if not self.vault else st, "message": st}

    def read_status(self, app_id):
        return dict(self.saved)

    def write_status(self, app_id, state, **extra):
        self.saved = {"state": state, "updated": 2, **extra}

    def app(self, app_id):
        return {"name": "Node-RED"}


def test_launcher_starts_stopped_addon(monkeypatch):
    gw = _load(GW, "gw_v060_kick")
    fake = _FakeAddons()
    runs = []
    monkeypatch.setattr(gw, "addons_lib", lambda: fake)
    monkeypatch.setattr(gw.subprocess, "run",
                        lambda cmd, **k: runs.append(cmd) or type("R", (), {"returncode": 0})())
    st = gw.addon_ensure_started("node-red")
    assert runs == [["systemctl", "start", "--no-block", "stickllm-addon@node-red.service"]]
    assert st["state"] == "starting" and fake.saved["state"] == "starting"
    gw.addon_ensure_started("node-red")          # throttled: no second start
    assert len(runs) == 1


def test_launcher_never_starts_with_locked_vault(monkeypatch):
    gw = _load(GW, "gw_v060_kick2")
    fake = _FakeAddons(vault=False)
    monkeypatch.setattr(gw, "addons_lib", lambda: fake)
    monkeypatch.setattr(gw.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("started")))
    assert gw.addon_ensure_started("node-red")["state"] == "locked"


def test_dead_addon_page_reloads_and_ui_starts_first():
    gw = GW.read_text()
    down = gw[gw.index("def _addon_down"):gw.index("def _addon_progress_page")]
    assert "addon_ensure_started(app_id)" in down
    assert 'http-equiv="refresh" content="2"' in gw
    js = (ROOT / "ui/app.js").read_text()
    d = js[js.index("async function deskAppUrl"):]
    assert "await startAddon(id, a)" in d[:900]
    assert '"/api/apps/start"' in js
