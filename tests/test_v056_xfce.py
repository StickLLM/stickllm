"""StickLLM 0.5.6: stock Xfce desktop on the stick's own screen.

Xfce is unmodified Debian packages; StickLLM ships only settings (xfconf XML,
kioskrc, panel launchers written at session start) and its own scripts.
"""
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OV = ROOT / "overlay"
BIN = OV / "usr" / "local" / "bin"
XDG = OV / "etc" / "stickllm" / "xfce" / "xdg"


def _text(p):
    return Path(p).read_text(encoding="utf-8")


def test_package_list_ships_stock_xfce_without_escape_hatches():
    pl = [l.strip() for l in _text(ROOT / "live-build" / "package-lists" / "stickllm.list.chroot").splitlines()]
    for need in ("xserver-xorg-core", "xserver-xorg-input-libinput", "x11-xserver-utils", "dbus-x11",
                 "xfwm4", "xfce4-panel", "xfce4-session", "xfce4-settings", "xfdesktop4", "xfconf"):
        assert need in pl, need
    for no in ("xfce4", "xfce4-terminal", "xterm", "thunar", "xfce4-appfinder", "xfce4-goodies",
               "lightdm", "xfce4-whiskermenu-plugin", "xinit"):
        assert no not in pl, no
    assert "sway" in pl and "cage" in pl  # fallbacks stay


def test_kiosk_ladder_xfce_first_then_sway_cage_weston():
    k = _text(BIN / "stickllm-kiosk")
    i_x = k.index('run_stack_forever "xfce+$BROWSER')
    i_s = k.index('run_stack_forever "sway+$BROWSER')
    i_c = k.index('run_stack_forever "cage+$BROWSER')
    assert i_x < i_s < i_c
    fn = k[k.index("xfce_enabled() {"):k.index("\n}\n", k.index("xfce_enabled() {"))]
    assert 'STICKLLM_KIOSK_XFCE:-1}" != "0"' in fn
    assert "stickllm\\.compositor=(sway|cage|weston)" in fn
    assert "STICKLLM_KIOSK_XFCE_FALLBACK" in k
    # long-running session is never killed by the QEMU try timeout
    assert '[[ "$comp" == "xfce" ]] && run_timeout=0' in k
    # Xorg: only the picked GPU, no VT switch / zap, local user only
    assert '"AutoAddGPU" "false"' in k and '"DontVTSwitch" "true"' in k and '"DontZap" "true"' in k
    assert "-nolisten tcp" in k and 'xhost "+SI:localuser:${KIOSK_USER}"' in k
    assert "_run 1 /usr/local/bin/stickllm-xfce-session" in k  # session as the kiosk user
    assert "trap 'stop_xorg' EXIT" in k
    subprocess.run(["bash", "-n", str(BIN / "stickllm-kiosk")], check=True)


def test_xorg_conf_busid_and_driver(tmp_path):
    k = _text(BIN / "stickllm-kiosk")
    s = k.index("write_xorg_conf() {")
    fn = k[s:k.index("\n}\n", s) + 3]
    sysroot = tmp_path / "sys"
    dev = tmp_path / "pci" / "0000:2b:00.0"
    dev.mkdir(parents=True)
    script = f"""
set -u
RUN={tmp_path}; XORG_CONF={tmp_path}/x.conf
fail_note() {{ :; }}
is_nvidia_path() {{ return 1; }}
readlink() {{ echo {dev}; }}
{fn}
write_xorg_conf /dev/dri/card1
"""
    subprocess.run(["bash", "-c", script], check=True)
    conf = (tmp_path / "x.conf").read_text()
    assert 'Driver "modesetting"' in conf
    assert 'BusID "PCI:43:0:0"' in conf
    assert 'Option "kmsdev" "/dev/dri/card1"' in conf


def test_xfconf_defaults_are_valid_and_locked_down():
    files = sorted((XDG / "xfce4" / "xfconf" / "xfce-perchannel-xml").glob("*.xml"))
    names = {f.name for f in files}
    assert {"xfce4-session.xml", "xfwm4.xml", "xsettings.xml", "xfce4-keyboard-shortcuts.xml"} <= names
    for f in files:
        ET.parse(f)
    sess = _text(XDG / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-session.xml")
    cmds = re.findall(r'Client\d_Command" type="array"><value type="string" value="([^"]+)"', sess)
    assert cmds == ["xfwm4", "xfsettingsd", "xfce4-panel", "xfdesktop"]
    assert 'name="SaveOnExit" type="bool" value="false"' in sess
    ks = _text(XDG / "xfce4" / "xfconf" / "xfce-perchannel-xml" / "xfce4-keyboard-shortcuts.xml")
    assert 'name="override" type="bool" value="true"' in ks and "<value" not in ks
    kiosk = _text(OV / "etc" / "xdg" / "xfce4" / "kiosk" / "kioskrc")
    for line in ("SaveSession=NONE", "CustomizePanel=NONE", "CustomizeDesktopMenu=NONE"):
        assert line in kiosk
    auto = _text(XDG / "autostart" / "stickllm-home.desktop")
    assert "Exec=/usr/local/bin/stickllm-xfce-open home" in auto


def _run_session(tmp_path, apps):
    ui = tmp_path / "ui"
    for a in apps:
        (ui / "apps" / a).mkdir(parents=True)
        (ui / "apps" / a / "index.html").write_text("x")
    home = tmp_path / "home"
    home.mkdir()
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "xrandr").write_text("#!/bin/sh\necho 'Screen 0: minimum'\necho 'Virtual-1 connected primary 1280x800+0+0'\necho 'Virtual-2 disconnected'\n")
    (fake / "dbus-launch").write_text("#!/bin/sh\necho \"$@\" > \"$HOME/launched\"\n")
    for f in fake.iterdir():
        f.chmod(0o755)
    src = _text(BIN / "stickllm-xfce-session")
    src = src.replace("XDGDIR=/etc/stickllm/xfce/xdg", f"XDGDIR={XDG}")
    sp = tmp_path / "session.sh"
    sp.write_text(src)
    env = dict(os.environ, HOME=str(home), PATH=f"{fake}:{os.environ['PATH']}",
               XDG_RUNTIME_DIR=str(tmp_path), STICKLLM_UI_ROOT=str(ui))
    subprocess.run(["bash", str(sp)], check=True, env=env)
    return home


def test_session_writes_panel_with_installed_apps_only(tmp_path):
    home = _run_session(tmp_path, ["notepad", "calculator"])
    assert (home / "launched").read_text().strip() == "--exit-with-session xfce4-session"
    xml = home / ".config" / "xfce4" / "xfconf" / "xfce-perchannel-xml"
    panel = _text(xml / "xfce4-panel.xml")
    ET.fromstring(panel)
    panel_dir = home / ".config" / "xfce4" / "panel"
    items = sorted(p.name for p in panel_dir.glob("launcher-*/*.desktop"))
    assert items == ["browser.desktop", "calculator.desktop", "home.desktop", "notepad.desktop"]
    for p in panel_dir.glob("launcher-*/*.desktop"):
        assert re.search(r"^Exec=/usr/local/bin/stickllm-xfce-open [a-z]+$", _text(p), re.M)
    assert "solitaire" not in panel and "applicationsmenu" not in panel and "actions" not in panel
    for plug in ("tasklist", "systray", "clock"):
        assert f'value="{plug}"' in panel
    desk = _text(xml / "xfce4-desktop.xml")
    ET.fromstring(desk)
    assert 'name="monitorVirtual-1"' in desk and "Virtual-2" not in desk
    assert "wallpaper.png" in desk
    assert re.search(r'name="desktop-menu".*?value="false"', desk, re.S)
    assert "rc=0" in (tmp_path / "stickllm-xfce-session.rc").read_text()
    # system defaults copied for the user
    assert (xml / "xfce4-keyboard-shortcuts.xml").is_file()


def test_opener_shares_one_profile_and_rejects_bad_ids(tmp_path):
    o = _text(BIN / "stickllm-xfce-open")
    assert o.count('--user-data-dir="$PROFILE"') == 1  # one common arg list for every window
    assert '--app="$BASE/?shell=xfce"' in o and '--app="$BASE/apps/$id/"' in o
    fake = tmp_path / "chromium"
    fake.write_text("#!/bin/sh\necho \"$@\"\n")
    fake.chmod(0o755)
    env = dict(os.environ, STICKLLM_SESSION_BROWSER=str(fake), STICKLLM_SESSION_PROFILE="/p")
    out = subprocess.run(["bash", str(BIN / "stickllm-xfce-open"), "notepad"], env=env, capture_output=True, text=True)
    assert "--app=http://127.0.0.1/apps/notepad/" in out.stdout and "--user-data-dir=/p" in out.stdout
    bad = subprocess.run(["bash", str(BIN / "stickllm-xfce-open"), "../x"], env=env, capture_output=True, text=True)
    assert bad.returncode == 2


def test_ui_keeps_classic_page_and_opens_app_windows_on_xfce():
    d = _text(ROOT / "ui" / "desktop.js")
    assert 'hostShell() === "xfce" && core.readOverride(store) === "auto"' in d
    a = _text(ROOT / "ui" / "app.js")
    assert 'onXfceShell()' in a and '"popup,width="' in a


def test_wallpaper_and_icons_are_ours():
    share = OV / "usr" / "local" / "share" / "stickllm" / "xfce"
    assert (share / "wallpaper.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    for i in ("stickllm", "browser", "notepad", "calculator", "solitaire"):
        assert (share / "icons" / f"{i}.png").is_file()
