"""0.6.3: one version everywhere."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stickllm_json_is_063():
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] == "0.6.3"


def test_about_and_cache_bust_063():
    html = (ROOT / "ui/index.html").read_text()
    assert "StickLLM v0.6.3" in html
    assert "?v=v062" not in html
    assert len(re.findall(r"\?v=v063", html)) >= 5


def test_kiosk_fallback_and_build_default_063():
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text()
    assert "|| echo v0.6.3" in kiosk
    build = (ROOT / "scripts/build.sh").read_text()
    assert 'VERSION="${STICKLLM_VERSION:-0.6.3}"' in build


def test_changelog_top_is_063():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (\S+)", log, re.M).group(1)
    assert first == "0.6.3"
    for item in ("setup wizard", "status_light", "amdgpu", "STICKLLM-DATA"):
        assert item.lower() in log.lower()
