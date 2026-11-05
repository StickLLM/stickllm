"""0.6.1: one version everywhere."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stickllm_json_is_061():
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] == "0.6.1"


def test_about_and_cache_bust_061():
    html = (ROOT / "ui/index.html").read_text()
    assert "StickLLM v0.6.1" in html
    assert "?v=v060" not in html
    assert len(re.findall(r"\?v=v061", html)) >= 5


def test_kiosk_fallback_and_build_default_061():
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text()
    assert "|| echo v0.6.1" in kiosk
    build = (ROOT / "scripts/build.sh").read_text()
    assert 'VERSION="${STICKLLM_VERSION:-0.6.1}"' in build


def test_changelog_top_is_061():
    log = (ROOT / "CHANGELOG.md").read_text()
    first = re.search(r"^## (\S+)", log, re.M).group(1)
    assert first == "0.6.1"
    for item in ("Agent Zero image on the ISO", "Unlock all plugins", "open_url"):
        assert item in log
