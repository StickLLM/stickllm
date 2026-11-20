"""0.6.10: version markers + A0 readiness / USB settings recovery fixes."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_stickllm_json_is_0610():
    # Superseded as tree tip by 0.6.11; keep A0 readiness assertions below.
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] in ("0.6.10", "0.6.11", "0.6.12")


def test_about_and_cache_bust_0610():
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert re.search(r"StickLLM v0\.6\.(10|11|12)", html)
    assert len(re.findall(r"\?v=v061[012]", html)) >= 5
    assert "v069k" not in html


def test_kiosk_fallback_and_build_default_0610():
    kiosk = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text(encoding="utf-8")
    assert re.search(r"\|\| echo v0\.6\.(10|11|12)", kiosk)
    build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
    assert "STICKLLM_VERSION:-0.6.12" in build or "STICKLLM_VERSION:-0.6.11" in build or "STICKLLM_VERSION:-0.6.10" in build
    # Published ships must not be overwritten.
    assert "v0.6.9|" in build or "v0.6.9)" in build
    assert "v0.6.10|" in build or "v0.6.10)" in build


def test_changelog_top_is_0610():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## (\S+)", log, re.M).group(1) in ("0.6.10", "0.6.11", "0.6.12")


def test_agent_running_requires_http_not_open_port():
    """A TCP connect to 5099 is docker-proxy, not Agent Zero.

    Reporting running=true on a connect test is what made the UI embed a dead
    endpoint and paint "127.0.0.1 refused to connect" on the first open.
    """
    gw = (ROOT / "overlay/usr/local/bin/stickllm-gateway").read_text(encoding="utf-8")
    assert "_agent_http_ready" in gw
    assert "docker-proxy" in gw
    # Every status document must use the HTTP probe, never the bare connect.
    assert "upstream_up=_agent_http_ready()" in gw
    assert "upstream_up=_agent_port_open()" not in gw
    ready = gw.split("def _agent_http_ready", 1)[1].split("\ndef ", 1)[0]
    assert "HTTPConnection" in ready
    assert "resp.status < 500" in ready
    # The embed proxy gate must agree with the status it just reported.
    embed = gw.split("def _agent_embed_proxy", 1)[1].split("\n    def ", 1)[0]
    assert "_agent_http_ready(5099)" in embed
    assert "agent_not_running" in embed


def test_usb_settings_recovers_stale_mapper_and_half_init():
    s = (ROOT / "overlay/usr/local/bin/stickllm-usb-settings").read_text(encoding="utf-8")
    assert "adopt_open_mapper" in s
    assert "mount_mapper" in s
    adopt = s.split("adopt_open_mapper() {", 1)[1].split("\n}\n", 1)[0]
    assert "cryptsetup status" in adopt
    assert "cryptsetup close" in adopt
    # open never formats; only open-or-init may finish an interrupted init.
    open_fn = s.split("cmd_open() {", 1)[1].split("\ncmd_", 1)[0]
    assert "adopt_open_mapper" in open_fn
    assert "mkfs" not in open_fn
    init_fn = s.split("cmd_open_or_init() {", 1)[1].split("\ncmd_", 1)[0]
    assert "adopt_open_mapper" in init_fn
    assert "STICKLLM_SETTINGS_INIT" in init_fn
    assert "mkfs.ext4" in init_fn


def test_no_stray_overlay_backups():
    """overlay/ is rsynced wholesale into the ISO: no editor leftovers."""
    bad = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "overlay").rglob("*")
        if p.is_file() and re.search(r"(\.(bak|orig|rej|swp)$|\.bak-|~$)", p.name)
    ]
    assert bad == []
