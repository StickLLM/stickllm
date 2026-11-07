"""0.6.6 version markers — superseded; 0.6.11 is current (see test_v0611_web_mode)."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stickllm_json_is_066():
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] in ("0.6.10", "0.6.11")


def test_about_and_cache_bust_066():
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert re.search(r"StickLLM v0\.6\.(10|11)", html)
    assert len(re.findall(r"\?v=v061[01]", html)) >= 5


def test_kiosk_fallback_and_build_default_066():
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text(encoding="utf-8")
    assert re.search(r"\|\| echo v0\.6\.(10|11)", kiosk)
    build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
    assert "STICKLLM_VERSION:-0.6.11" in build or "STICKLLM_VERSION:-0.6.10" in build


def test_changelog_top_is_066():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    first = re.search(r"^## (\S+)", log, re.M).group(1)
    assert first in ("0.6.10", "0.6.11")
    assert "## 0.6.6" in log
    for item in ("wifi_connect", "monologue_end", "use-angle=gl", "32k", "Permissions-Policy"):
        assert item.lower() in log.lower()


def test_chat_naming_deferral_files_and_bind():
    start = ROOT / "overlay/usr/local/share/stickllm/a0-chat-naming/monologue_start/_60_rename_chat.py"
    end = ROOT / "overlay/usr/local/share/stickllm/a0-chat-naming/monologue_end/_60_rename_chat.py"
    assert start.is_file()
    assert end.is_file()
    start_txt = start.read_text(encoding="utf-8")
    end_txt = end.read_text(encoding="utf-8")
    assert "return" in start_txt
    assert "monologue_end" in start_txt or "no-op" in start_txt.lower() or "StickLLM 0.6.6" in start_txt
    assert "generate_name" in end_txt
    assert "_RETRY_DELAYS_S" in end_txt or "asyncio.sleep" in end_txt
    agent = (ROOT / "overlay/usr/local/bin/stickllm-agent").read_text(encoding="utf-8")
    assert "a0-chat-naming" in agent
    assert "monologue_end" in agent
    assert "CHAT_NAMING_ARGS" in agent
