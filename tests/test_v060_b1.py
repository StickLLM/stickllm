"""0.6.0 (B1): Terminal mode has no desktop, never waits, shows the real LAN IP."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay/usr/local/bin"


def _run_issue(tmp_path, ip, password):
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    if password:
        (run / "ssh-password.txt").write_text(password + "\n")
    lan = tmp_path / "lan-ip"
    lan.write_text("#!/bin/sh\nprintf '%s\\n' '" + ip + "'\n")
    lan.chmod(0o755)
    issue = tmp_path / "issue.d" / "50.issue"
    env = dict(os.environ, STICKLLM_RUN=str(run), STICKLLM_TERM_ISSUE=str(issue), STICKLLM_LAN_IP_BIN=str(lan))
    r = subprocess.run(["bash", str(BIN / "stickllm-term-issue"), "--once"], env=env, capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and (not password or password not in r.stdout + r.stderr)
    return issue


def test_issue_has_literal_lan_ip_and_no_agetty_escape(tmp_path):
    issue = _run_issue(tmp_path, "192.168.1.42", "s3cret-pass")
    text = issue.read_text()
    assert "LAN IP:    192.168.1.42" in text and "ssh stickllm@192.168.1.42" in text
    assert "\\4" not in text and "127.0.0.1" not in text
    assert "s3cret-pass" in text and oct(issue.stat().st_mode & 0o777) == "0o600"


def test_issue_without_network_never_claims_loopback(tmp_path):
    issue = _run_issue(tmp_path, "127.0.0.1", "")
    text = issue.read_text()
    assert "127.0.0.1" not in text and "waiting for the network" in text and "being set" in text


def test_terminal_fast_path_masks_desktop_and_does_not_wait():
    src = (BIN / "stickllm-bootstatus").read_text()
    body = src.split("term_fast_path() {", 1)[1].split("\n}\n", 1)[0]
    assert "mask --runtime stickllm-kiosk.service stickllm-local.service" in body
    assert "allow-local-chat" in body and "sleep" not in body and "seq 1 30" not in body
    assert "stickllm-term-issue --once" in body and "systemd-run --no-block" in body
    assert "getty@tty1.service" in body and "\\\\4" not in body
    # The password never goes to the serial line or the log from this path.
    assert "pass=" not in body.split("serial_only")[-1]


def test_live_config_cannot_start_x_on_tty1():
    hook = (ROOT / "live-build/hooks/normal/0100-stickllm-setup.hook.chroot").read_text()
    assert "rm -f /lib/live/config/0140-xinit" in hook
    placeholder = (ROOT / "overlay/etc/profile.d/zz-live-config_xinit.sh").read_text()
    assert "startx" not in placeholder.replace("run \"while true; do startx; done\"", "")
    for cfg in ("boot/grub.cfg", "boot/isolinux/live.cfg"):
        text = (ROOT / cfg).read_text()
        for line in text.splitlines():
            if "boot=live" in line:
                assert "live-config.noautologin" in line, (cfg, line)
