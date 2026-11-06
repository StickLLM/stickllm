"""0.6.7: one version everywhere + first-boot / vault UX markers."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stickllm_json_is_067():
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] == "0.6.7"


def test_about_and_cache_bust_067():
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert "StickLLM v0.6.7" in html
    assert len(re.findall(r"\?v=v067", html)) >= 5  # v067 / v067b / v067c cache busts


def test_kiosk_fallback_and_build_default_067():
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text(encoding="utf-8")
    assert "|| echo v0.6.7" in kiosk
    build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
    assert 'VERSION="${STICKLLM_VERSION:-0.6.7}"' in build


def test_changelog_top_is_067():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (\S+)", log, re.M).group(1)
    assert first == "0.6.7"
    for item in ("Open model", "recovery phrase", "gpu-skip", "vault already exists", "Agent Zero"):
        assert item.lower() in log.lower()


def test_wizard_open_model_and_recovery_no_cancel():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    assert "STEP_MODEL" in app
    assert "STARTER_MODEL_ID" in app
    assert "qwen25-7b-q4km" in app
    assert 'STARTER_MODEL_ID = "qwen25-7b-q4km"' in app
    assert "showRecoveryPhraseOnce" in app
    assert "noCancel: true" in app or "noCancel=true" in app
    assert "probeBootVault" in app
    assert "enterVaultModeNow" in app
    assert "stickllm:vault-unlocked" in app


def test_gpu_skip_never_fails_unit():
    script = (ROOT / "overlay/usr/local/bin/stickllm-gpu-skip").read_text(encoding="utf-8")
    assert "set -e" not in script.splitlines()[0:10] or "set -u" in script
    assert "exit 0" in script
    unit = (ROOT / "overlay/etc/systemd/system/stickllm-gpu-skip.service").read_text(encoding="utf-8")
    assert "SuccessExitStatus" in unit
    # Splash reporter must not flag intentional gpu-skip even if the unit is sticky-failed.
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
