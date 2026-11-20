"""0.6.9: vault wizard unstick + Open model first + version markers."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stickllm_json_is_069():
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] in ("0.6.10", "0.6.11", "0.6.12")


def test_about_and_cache_bust_069():
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert re.search(r"StickLLM v0\.6\.(10|11|12)", html)
    assert len(re.findall(r"\?v=v061[012]", html)) >= 5


def test_kiosk_fallback_and_build_default_069():
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text(encoding="utf-8")
    assert re.search(r"\|\| echo v0\.6\.(10|11|12)", kiosk)
    build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
    assert "STICKLLM_VERSION:-0.6.12" in build or "STICKLLM_VERSION:-0.6.11" in build or "STICKLLM_VERSION:-0.6.10" in build
    assert "v0.6.9" in build  # refuse list keeps prior ship


def test_changelog_top_is_069():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (\S+)", log, re.M).group(1)
    assert first in ("0.6.10", "0.6.11", "0.6.12")
    assert "rescueStuckVaultWizard" in (ROOT / "ui/app.js").read_text(encoding="utf-8")
    assert "unstick" in log.lower() or "rescue" in log.lower()


def test_wizard_open_model_first_and_rescue():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    assert "STEP_WELCOME" not in app
    assert "STEP_MODEL" in app
    assert "Our default installed model is" in app
    assert "rescueStuckVaultWizard" in app
    assert "dismissSetupWizard" in app
    assert "showRecoveryPhraseOnce" in app
    assert "noCancel: true" in app or "noCancel=true" in app
    assert "probeBootVault" in app
    assert "enterVaultModeNow" in app
