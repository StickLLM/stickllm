"""0.6.0 display fixes: B2 (RX 570 + NVIDIA), B6 (borderless desktop), B7 (timing)."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIOSK = (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text()
OPEN = (ROOT / "overlay/usr/local/bin/stickllm-xfce-open").read_text()


def _fn(src, name):
    return src.split(name + "() {", 1)[1].split("\n}\n", 1)[0]


def test_b2_polaris_firmware_listed_and_checked():
    pk = (ROOT / "live-build/package-lists/stickllm.list.chroot").read_text().split()
    assert "firmware-amd-graphics" in pk
    hook = (ROOT / "live-build/hooks/normal/0100-stickllm-setup.hook.chroot").read_text()
    assert "polaris10_mc.bin" in hook


def test_b2_simpledrm_does_not_block_nvidia_kms():
    body = _fn(KIOSK, "ensure_nvidia_kms")
    assert "is_weak_drm" in body and "card_connected" in body
    # The old any-connector loop (simpledrm counted as a monitor) is gone.
    assert "/sys/class/drm/card*-*/status" not in body


def test_b2_xorg_never_binds_second_gpu():
    body = _fn(KIOSK, "write_xorg_conf")
    assert '"AutoAddGPU" "false"' in body and '"AutoBindGPU" "false"' in body


def test_b7_timing_marks_and_fast_xorg_fail():
    for phase in ("start", "ui-ready", "kms", "pick-", "xorg-up-"):
        assert re.search(r'kiosk_mark "?' + re.escape(phase), KIOSK), phase
    assert "Fatal server error" in _fn(KIOSK, "start_xorg")


def test_b6_hints_after_state_changes_and_watchdog():
    bare = _fn(OPEN, "bare_desktop")
    assert bare.index("maximized_vert") < bare.index("_MOTIF_WM_HINTS")
    keep = _fn(OPEN, "keep_desktop_bare")
    assert "frame_extents_zero" in keep and "bare_desktop" in keep
    assert 'keep_desktop_bare "$_wid" "$pid" &' in OPEN


def test_b6_frame_extents_parser():
    fn = OPEN.split("frame_extents_zero() {", 1)[1].split("\n}\n", 1)[0]
    script = "frame_extents_zero() {" + fn + "\n}\n"
    def run(out):
        sh = 'xprop() { printf "%s\\n" "$XP"; }\n' + script + 'frame_extents_zero 0x1'
        return subprocess.run(["bash", "-c", sh], env={"XP": out, "PATH": "/usr/bin:/bin"}).returncode
    assert run("_NET_FRAME_EXTENTS(CARDINAL) = 0, 0, 0, 0") == 0
    assert run("_NET_FRAME_EXTENTS(CARDINAL) = 1, 1, 24, 1") != 0
    assert run("_NET_FRAME_EXTENTS:  not found.") == 0
