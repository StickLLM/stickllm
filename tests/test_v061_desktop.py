"""0.6.1 desktop/kiosk fixes (items 7-9)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
OV = ROOT / "overlay"


def test_xfwm4_titleless_maximize_baked_in():
    x = (OV / "etc/stickllm/xfce/xdg/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml").read_text()
    assert '<property name="titleless_maximize" type="bool" value="true"/>' in x


def test_keep_desktop_bare_is_bounded_and_logs_to_run():
    s = (OV / "usr/local/bin/stickllm-xfce-open").read_text()
    body = s[s.index("keep_desktop_bare() {"):]
    body = body[:body.index("\n}\n")]
    assert "while true" not in body and "seq 1 15" in body
    assert "/run/stickllm/desktop-frame.log" in body


def test_power_endpoint_is_stick_screen_only_and_needs_confirm():
    g = (OV / "usr/local/bin/stickllm-gateway").read_text()
    i = g.index('if path == "/api/system/power":')
    blk = g[i:i + 1500]
    assert "self._is_loopback()" in blk and "stickllm_ui_client" in blk
    assert 'req.get("confirm") is True' in blk
    assert '("poweroff", "reboot")' in blk


def test_desktop_power_button_confirms():
    d = (ROOT / "ui/desktop.js").read_text()
    assert 'footBtn("power", "Power off"' in d
    fn = d[d.index("function powerOff()"):]
    assert fn.index("window.confirm(") < fn.index('fetch("/api/system/power"')


def test_ctx_slider_no_reflow_while_dragging():
    a = (ROOT / "ui/app.js").read_text()
    assert "requestAnimationFrame(() => { ctxRaf = 0;" in a
    assert 'note.style.visibility' in a
    css = (ROOT / "ui/style.css").read_text()
    assert "::-webkit-slider-thumb" in css and ".advBody{contain:layout paint}" in css
