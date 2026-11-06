"""Auto preload / first-token warmup after Activate and vault unlock."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "overlay/usr/local/bin/stickllm-control"
VAULT = ROOT / "overlay/usr/local/bin/stickllm-vault"
GW = ROOT / "overlay/usr/local/bin/stickllm-gateway"
UI = ROOT / "ui/app.js"


def test_control_has_warmup_and_restore():
    c = CONTROL.read_text(encoding="utf-8")
    assert "def llama_warmup(" in c
    assert "def restore_last_model(" in c
    assert "def remember_last_model(" in c
    assert "spawn_llama_warmup" in c
    assert "def _open_warmup_log(" in c
    assert "WARMUP_LOG" in c
    assert "WARMUP_LOG_FALLBACK" in c
    assert "/run/stickllm/warmup.log" in c or 'RUN / "warmup.log"' in c
    assert '/tmp/stickllm-warmup.log' in c
    assert "0o666" in c[c.index("def _open_warmup_log(") : c.index("def _last_model_paths(")]
    assert '_open_warmup_log()' in c[c.index("def spawn_llama_warmup(") : c.index("def restore_last_model(")]
    assert '--warmup"' in c or "sys.argv[1] == \"--warmup\"" in c
    assert "--restore-last-model" in c
    assert "WARMUP_PATH_FALLBACK" in c
    assert "/v1/chat/completions" in c
    assert '"ready"' in c or "'ready'" in c
    body = c[c.index("def activate_model(") :]
    i = body.index('"systemctl", "restart", "stickllm-llama.service"')
    chunk = body[i : i + 900]
    assert "remember_last_model" in chunk
    assert "spawn_llama_warmup" in chunk


def test_unload_clears_last_model():
    c = CONTROL.read_text(encoding="utf-8")
    body = c[c.index("def model_unload(") : c.index("APPAGENT_UNIT")]
    assert "clear_last_model" in body


def test_vault_unlock_restores_last_model():
    v = VAULT.read_text(encoding="utf-8")
    body = v[v.index("start_agent_addon()") : v.index("stop_vault_addons()")]
    assert "--restore-last-model" in body


def test_gateway_exposes_warmup():
    g = GW.read_text(encoding="utf-8")
    assert "def llama_warmup_info" in g
    assert '"llama_warmup"' in g or "'llama_warmup'" in g
    assert "stickllm-llama-warmup.json" in g


def test_ui_shows_warming_up():
    js = UI.read_text(encoding="utf-8")
    assert "Warming up…" in js
    assert "llama_warmup" in js
