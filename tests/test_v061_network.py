"""0.6.1 network fixes (items 10-11)."""
import importlib.machinery
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "overlay/usr/local/bin/stickllm-control"
CATALOG = ROOT / "config/models/catalog.toml"


def _load(monkeypatch):
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
    s = (ROOT / "overlay/usr/local/bin/stickllm-wifi-apply").read_text()
    assert '[[ "${3:-}" == "--hidden" ]] && HIDDEN=1' in s
    assert 'echo "hidden=true"' in s


def test_ui_refreshes_network_after_connect_and_has_scan():
    a = (ROOT / "ui/app.js").read_text()
    blk = a[a.index('$("#wifiBtn").onclick'):]
    assert blk.index("refreshNetwork()") < blk.index('$("#wifiScan")')
    assert 'control("wifi_scan")' in a
    h = (ROOT / "ui/index.html").read_text()
    assert 'id="wifiHidden"' in h and 'id="wifiScan"' in h and 'id="wifiList"' in h
