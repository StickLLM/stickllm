"""0.6.1 boot / Terminal items 1-6 (static + small shell checks)."""
import os, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay/usr/local/bin"


def test_grub_bios_skips_theme_and_has_safe_entry():
    g = (ROOT / "boot/grub.cfg").read_text()
    assert 'if [ "${grub_platform}" = "efi" ]' in g
    efi_block = g.split('if [ "${grub_platform}" = "efi" ]; then\n  if loadfont', 1)[1].split("\nfi\n", 1)[0]
    assert "set theme=" in efi_block and "gfxpayload=text" in g
    assert 'menuentry "4 Safe boot' in g


def test_terminal_autologin_dropin_gated():
    d = (ROOT / "overlay/etc/systemd/system/getty@tty1.service.d/stickllm-autologin.conf").read_text()
    assert "--autologin root" in d and "ExecStart=\n" in d
    gate = (ROOT / "overlay/etc/systemd/system/getty@tty1.service.d/stickllm-conflict.conf").read_text()
    assert "allow-getty-tty1" in gate


def test_terminal_profile_binds_f10_f9():
    p = (ROOT / "overlay/etc/profile.d/stickllm-terminal.sh").read_text()
    assert r'"\e[21~"' in p and r'"\e[20~"' in p and "stickllm-show-secrets" in p
    assert "ssh-password" not in p


def test_show_secrets_prints_only_requested(tmp_path):
    (tmp_path / "ssh-password.txt").write_text("pw123\n")
    (tmp_path / "pair-code.txt").write_text("123456\n")
    env = dict(os.environ, STICKLLM_RUN=str(tmp_path))
    out = subprocess.run(["bash", str(BIN / "stickllm-show-secrets"), "pair"], env=env, capture_output=True, text=True).stdout
    assert "123456" in out and "pw123" not in out
    out = subprocess.run(["bash", str(BIN / "stickllm-show-secrets"), "ssh"], env=env, capture_output=True, text=True).stdout
    assert "pw123" in out and "127.0.0.1" not in out


def test_bootstatus_loading_screen_keys_usb2_and_centred_ssh():
    s = (BIN / "stickllm-bootstatus").read_text()
    assert "key_wait 2" in s and "[21~" in s and "[20~" in s
    assert "usb_speed_check" in s and ">= 5000" in s and "USB 2 port" in s
    body = s.split("ssh_password_line() {", 1)[1].split("\n}\n", 1)[0]
    assert 'center "password: ${pass}"' in body and "or 127.0.0.1" not in body


def test_gateway_never_advertises_loopback_ssh_host():
    g = (BIN / "stickllm-gateway").read_text()
    assert '"ssh_host": ip or "127.0.0.1"' not in g
