"""0.6.1 network fixes (items 10-11) + ethernet-prefer Wi‑Fi optional."""
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "overlay/usr/local/bin/stickllm-control"
CATALOG = ROOT / "config/models/catalog.toml"


def _load(monkeypatch):
    # stickllm-control imports fcntl (Linux-only); stub on Windows hosts.
    if "fcntl" not in sys.modules:
        sys.modules["fcntl"] = types.ModuleType("fcntl")
    monkeypatch.setenv("STICKLLM_CATALOG", str(CATALOG))
    loader = importlib.machinery.SourceFileLoader("stickllm_control_v061n", str(CTL))
    spec = importlib.util.spec_from_loader("stickllm_control_v061n", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_parse_wifi_scan_dedupes_sorts_and_unescapes(monkeypatch):
    ctl = _load(monkeypatch)
    out = "\n".join([
        "Home:40:WPA2:",
        "Home:72:WPA2:",
        "Cafe\\:Guest:55:--:",
        ":80:WPA2:",          # hidden network: no name
        "Office:30:WPA2 WPA3:*",
    ])
    nets = ctl.parse_wifi_scan(out)
    assert [n["ssid"] for n in nets] == ["Office", "Home", "Cafe:Guest"]
    assert nets[0]["in_use"] and nets[1]["signal"] == 72
    assert nets[2]["secure"] is False and nets[1]["secure"] is True


def test_wifi_connect_passes_hidden_and_returns_net(monkeypatch):
    ctl = _load(monkeypatch)
    seen = {}
    monkeypatch.setattr(ctl, "sh", lambda cmd, timeout=600: seen.setdefault("cmd", cmd) and {"ok": True, "code": 0})
    monkeypatch.setattr(ctl, "net_info", lambda: {"ip": "192.168.1.20", "type": "WiFi"})
    monkeypatch.setattr(ctl.subprocess, "run", lambda *a, **k: type("P", (), {"returncode": 1})())
    r = ctl.wifi_connect("Secret", "pw", True)
    assert seen["cmd"][-1] == "--hidden"
    assert r["net"]["ip"] == "192.168.1.20"


def test_wifi_apply_writes_hidden_flag():
    s = (ROOT / "overlay/usr/local/bin/stickllm-wifi-apply").read_text(encoding="utf-8")
    assert '[[ "${3:-}" == "--hidden" ]] && HIDDEN=1' in s
    assert 'echo "hidden=true"' in s


def test_ui_refreshes_network_after_connect_and_has_scan():
    a = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    blk = a[a.index('$("#wifiBtn").onclick'):]
    assert blk.index("refreshNetwork()") < blk.index('$("#wifiScan")')
    assert 'control("wifi_scan")' in a
    h = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert 'id="wifiSsidHint"' in h and 'id="wifiScan"' in h and 'id="wifiList"' in h and 'id="ssid"' in h


def test_net_info_prefers_ethernet_and_marks_wifi_optional(monkeypatch):
    ctl = _load(monkeypatch)
    monkeypatch.setattr(ctl, "sh", lambda cmd, timeout=5: {
        "ok": True,
        "stdout": (
            "default via 192.168.1.1 dev wlan0\n"
            if "route" in cmd
            else "1: wlan0    inet 192.168.1.20/24\n2: enp1s0    inet 192.168.1.30/24\n"
        ),
    })
    monkeypatch.setattr(ctl, "ethernet_status", lambda: {
        "ok": True, "carrier": True, "up": True, "iface": "enp1s0", "ip": "192.168.1.30",
    })
    n = ctl.net_info()
    assert n["type"] == "Ethernet" and n["ip"] == "192.168.1.30"
    assert n["ethernet_ok"] and n["wifi_optional"]


def test_wifi_scan_soft_error_when_ethernet_ok(monkeypatch):
    ctl = _load(monkeypatch)
    monkeypatch.setattr(ctl, "sh", lambda *a, **k: {"ok": False, "stderr": "Error: No Wi-Fi device found."})
    monkeypatch.setattr(ctl, "ethernet_status", lambda: {
        "ok": True, "carrier": True, "up": True, "iface": "enp1s0", "ip": "10.0.0.2",
    })
    r = ctl.wifi_scan()
    assert r["ok"] is False and r["ethernet_ok"] and r["wifi_optional"]
    assert "optional" in r["error"].lower() or "ethernet" in r["error"].lower()


def test_wizard_skips_wifi_when_ethernet_connected():
    a = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    assert "Connected via Ethernet" in a
    assert "Wi‑Fi is optional while a cable is connected" in a
    assert "continuing on Ethernet" in a
    assert 'id="wifiSectionTitle"' in (ROOT / "ui/index.html").read_text(encoding="utf-8")
