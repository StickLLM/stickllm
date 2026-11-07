"""0.6.11 Web mode (Internet / Tor / No internet) for stick Chromium.

Version tip may be 0.6.12+ WIP; keep feature asserts. See test_v0612_a0_ephemeral_chats.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay" / "usr" / "local" / "bin"
UI = ROOT / "ui"
LB = ROOT / "live-build"


def test_stickllm_json_is_0611_or_newer():
    doc = json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())
    assert doc["version"] in ("0.6.11", "0.6.12")


def test_about_and_cache_bust_0611_or_newer():
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert re.search(r"StickLLM v0\.6\.1[12]", html)
    assert len(re.findall(r"\?v=v061[12]", html)) >= 5


def test_changelog_has_0611_web_mode():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    top = re.search(r"^## (\S+)", log, re.M).group(1)
    assert top in ("0.6.11", "0.6.12")
    # Web mode shipped in 0.6.11; still present above 0.6.10.
    assert "Web mode" in log.split("## 0.6.10", 1)[0]
    assert "Remote LAN clients" in log.split("## 0.6.10", 1)[0] or "remote" in log.split("## 0.6.10", 1)[0].lower()
    assert "## 0.6.11" in log


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
    assert "internet" in script
    assert "URLBlocklist" in script
    assert "remote_clients" in script and "own_network" in script
    assert "stick_browser" in script
    assert "HTTPTunnelPort" in script
    assert 'mode="$1" body' in script or "write_policy" in script
    # Tor uses PAC (LAN DIRECT + SOCKS5) — managed ProxyMode=direct overrode Browser flags.
    assert "pac_script" in script
    assert "tor_pac_policy_json" in script
    assert "SOCKS5" in script
    assert "192.168.0.0/16" in script
    assert "reload_stick_browser" in script
    assert "start --no-block" in script
    assert "http://192.168.*" in script
    assert "try-restart stickllm-kiosk" not in script
    assert "pkill -x chromium" not in script
    assert "Intentionally a no-op" in script
    assert "IsTor" in script
    assert "close_stick_browsers" in script
    assert "/run/stickllm/browser/" in script


def test_control_browser_tor_proxy_flags():
    ctl = (BIN / "stickllm-control").read_text(encoding="utf-8")
    assert "_web_mode_for_browser" in ctl
    assert "--proxy-server=socks5://127.0.0.1:9050" in ctl
    assert "--proxy-bypass-list=" in ctl


def test_browser_home_page_and_start_url():
    home = (UI / "browser-home.html").read_text(encoding="utf-8")
    js = (UI / "browser-home.js").read_text(encoding="utf-8")
    assert "StickLLM" in home
    # Gateway CSP is script-src 'self' — no inline script on this page.
    assert "<script src=\"/browser-home.js\">" in home
    assert "fetch(" not in home
    assert "/api/web-mode" in js
    assert "Tor mode" in js and "No internet" in js and "Internet" in js
    ctl = (BIN / "stickllm-control").read_text(encoding="utf-8")
    assert "browser-home.html" in ctl
    hotfix = (BIN / "stickllm-hotfix").read_text(encoding="utf-8")
    assert "browser-home.html" in hotfix and "browser-home.js" in hotfix


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
    assert "Web mode (0.6.11" in threat
    assert "stick-local Chromium" in threat
    assert "private LAN" in threat or "RFC1918" in threat or "loopback" in threat.lower()
