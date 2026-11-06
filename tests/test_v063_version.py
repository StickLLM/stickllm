"""0.6.3 version markers — superseded; 0.6.8 is current (see test_v068_version)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stickllm_json_is_current():
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] == "0.6.8"


def test_about_and_cache_bust_current():
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert "StickLLM v0.6.8" in html
    assert len(re.findall(r"\?v=v068", html)) >= 5


def test_kiosk_fallback_and_build_default_current():
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text(encoding="utf-8")
    assert "|| echo v0.6.8" in kiosk
    build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
    assert 'VERSION="${STICKLLM_VERSION:-0.6.8}"' in build


def test_changelog_top_is_current():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (\S+)", log, re.M).group(1)
    assert first == "0.6.8"
