"""0.6.7 version markers — superseded; 0.6.12 is current (see test_v0611_web_mode)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stickllm_json_is_067():
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] in ("0.6.10", "0.6.11", "0.6.12")


def test_about_and_cache_bust_067():
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert re.search(r"StickLLM v0\.6\.(10|11|12)", html)
    # Hotfix cache busts stay on the 0.6.8 line (v068a).
    assert len(re.findall(r"\?v=v061[012]", html)) >= 5


def test_kiosk_fallback_and_build_default_067():
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text(encoding="utf-8")
    assert re.search(r"\|\| echo v0\.6\.(10|11|12)", kiosk)
    build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
    assert "STICKLLM_VERSION:-0.6.12" in build or "STICKLLM_VERSION:-0.6.11" in build or "STICKLLM_VERSION:-0.6.10" in build


def test_changelog_top_is_067():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (\S+)", log, re.M).group(1)
    assert first in ("0.6.10", "0.6.11", "0.6.12")
    assert "## 0.6.7" in log
    for item in ("Open model", "recovery phrase", "gpu-skip", "vault already exists", "Agent Zero"):
        assert item.lower() in log.lower()


def test_wizard_open_model_and_recovery_no_cancel():
    # 0.6.9+ drops the welcome gate; Open model is first (see test_v069_version).
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    assert "STEP_WELCOME" not in app
    assert "STEP_MODEL" in app
    assert "Our default installed model is" in app
    assert "STARTER_MODEL_ID" in app
    assert "qwen25-7b-q4km" in app
    assert 'STARTER_MODEL_ID = "qwen25-7b-q4km"' in app
    assert "showRecoveryPhraseOnce" in app
    assert "noCancel: true" in app or "noCancel=true" in app
    assert "probeBootVault" in app
    assert "enterVaultModeNow" in app
    assert "setupBlocksAgent" in app
    assert "setup-active" in app
    assert "stickllm:vault-unlocked" in app


def test_session_mode_idempotent_no_toast_loop():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    gw = (ROOT / "overlay/usr/local/bin/stickllm-gateway").read_text(encoding="utf-8")
    desk = (ROOT / "ui/desktop.js").read_text(encoding="utf-8")
    assert "next === prev" in app
    assert "prev == mode" in gw
    assert 'doc["unchanged"] = True' in gw
    assert "chatFrameReloadN" in desk
    assert "setupBlocksAgent" in desk
    assert "agentHttpReady" in app
    assert "/agent-zero/api/csrf_token" in app
    assert "setupBlocksA0" in desk
    assert "httpReady" in desk
    assert "chatUpgradeLock" in desk
    assert "unable to load agent zero" in desk
    reload_fn = desk.split("function reloadChatAgentFrame()", 1)[1].split("\n  function ", 1)[0]
    assert "wm.close(CHAT" not in reload_fn
    assert "frame.src" in reload_fn


def test_gpu_skip_never_fails_unit():
    script = (ROOT / "overlay/usr/local/bin/stickllm-gpu-skip").read_text(encoding="utf-8")
    assert "set -e" not in script.splitlines()[0:10] or "set -u" in script
    assert "exit 0" in script
    unit = (ROOT / "overlay/etc/systemd/system/stickllm-gpu-skip.service").read_text(encoding="utf-8")
    assert "SuccessExitStatus" in unit
    boot = (ROOT / "overlay/usr/local/bin/stickllm-bootstatus").read_text(encoding="utf-8")
    assert "stickllm-gpu-skip" in boot.split("refresh_failed()", 1)[1].split("\n}\n", 1)[0]
    assert "reset-failed stickllm-gpu-skip.service" in boot


def test_no_ssh_password_copy_button():
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    assert "sshCopy" not in html
    assert "Copy password" not in html
    assert "sshCopy" not in app
    assert "SSH password copied" not in app
