"""0.6.3 version markers — superseded; 0.6.11 is current (see test_v0611_web_mode)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stickllm_json_is_current():
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] in ("0.6.10", "0.6.11")


def test_about_and_cache_bust_current():
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert re.search(r"StickLLM v0\.6\.(10|11)", html)
    assert len(re.findall(r"\?v=v061[01]", html)) >= 5


def test_kiosk_fallback_and_build_default_current():
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text(encoding="utf-8")
    assert re.search(r"\|\| echo v0\.6\.(10|11)", kiosk)
    build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
    assert "STICKLLM_VERSION:-0.6.11" in build or "STICKLLM_VERSION:-0.6.10" in build


def test_changelog_top_is_current():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (\S+)", log, re.M).group(1)
    assert first in ("0.6.10", "0.6.11")
