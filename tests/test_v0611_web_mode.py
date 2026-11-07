"""0.6.11: Web mode (Internet / Tor / No internet) for stick Chromium."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay" / "usr" / "local" / "bin"
UI = ROOT / "ui"
LB = ROOT / "live-build"


def test_stickllm_json_is_0611():
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] == "0.6.11"


def test_about_and_cache_bust_0611():
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert "StickLLM v0.6.11" in html
    assert len(re.findall(r"\?v=v0611", html)) >= 5


def test_changelog_top_is_0611():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## (\S+)", log, re.M).group(1) == "0.6.11"
    assert "Web mode" in log.split("## 0.6.10", 1)[0]
    assert "Remote LAN clients" in log.split("## 0.6.10", 1)[0] or "remote" in log.split("## 0.6.10", 1)[0].lower()


def test_tor_package_and_boot_wiring():
    pkgs = (LB / "package-lists/stickllm.list.chroot").read_text(encoding="utf-8")
    assert re.search(r"^tor$", pkgs, re.M)
    hook = (LB / "hooks/normal/0100-stickllm-setup.hook.chroot").read_text(encoding="utf-8")
    assert "stickllm-web-mode.service" in hook
    assert "systemctl disable tor.service" in hook
    unit = (ROOT / "overlay/etc/systemd/system/stickllm-web-mode.service").read_text(encoding="utf-8")
    assert "stickllm-web-mode apply" in unit


def test_web_mode_helper_modes_and_scope():
    script = (BIN / "stickllm-web-mode").read_text(encoding="utf-8")
    assert "internet" in script and "socks5://" in script
    assert "URLBlocklist" in script
    assert "remote_clients" in script and "own_network" in script
    assert "stick_browser" in script
    assert "HTTPTunnelPort" in script


def test_control_and_gateway_web_mode_api():
    ctl = (BIN / "stickllm-control").read_text(encoding="utf-8")
    assert "def web_mode_set" in ctl and "def web_mode_status" in ctl
    assert 'action == "web_mode_set"' in ctl
    gw = (BIN / "stickllm-gateway").read_text(encoding="utf-8")
    assert 'path == "/api/web-mode"' in gw
    assert "get_web_mode" in gw and "_urlopen_web" in gw
    # Stick-origin fetches honour No internet / Tor.
    assert 'get_web_mode() == "none"' in gw
    assert "TOR_HTTP_PROXY" in gw


def test_desktop_web_tray_and_settings():
    desk = (UI / "desktop.js").read_text(encoding="utf-8")
    assert 'id = "trayWeb"' in desk or 'id="trayWeb"' in desk or "trayWeb" in desk
    assert "buildWebPop" in desk and 'data-web="tor"' in desk
    assert "Remote LAN clients use their own network" in desk
    css = (UI / "desktop.css").read_text(encoding="utf-8")
    assert 'trayWeb[data-state="internet"]' in css
    assert 'trayWeb[data-state="tor"]' in css
    assert 'trayWeb[data-state="none"]' in css
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert 'id="webModeSeg"' in html
    assert "Remote LAN clients" in html or "remote devices" in html.lower()
    app = (UI / "app.js").read_text(encoding="utf-8")
    assert "setWebMode" in app and "refreshWebMode" in app


def test_docs_web_mode_and_threat_model():
    doc = (ROOT / "docs/WEB-MODE.md").read_text(encoding="utf-8")
    assert "Remote LAN clients" in doc
    assert "stickllm-web-mode" in doc
    threat = (ROOT / "docs/THREAT-MODEL.md").read_text(encoding="utf-8")
    assert "Web mode (0.6.11)" in threat
    assert "stick-local Chromium" in threat
