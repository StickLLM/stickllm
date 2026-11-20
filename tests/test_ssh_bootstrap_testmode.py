"""Test/Terminal SSH: random per-boot password (shown on READY / F10)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOT = ROOT / "overlay/usr/local/bin/stickllm-ssh-bootstrap"
STATUS = ROOT / "overlay/usr/local/bin/stickllm-bootstatus"


def test_bootstrap_mints_password_always():
    text = BOOT.read_text(encoding="utf-8")
    assert "ALPHABET=" in text
    assert "chpasswd" in text
    assert "ssh-password.txt" in text
    # Empty-password lab path must stay gone (no OCR shortcut).
    assert "passwd -d stickllm" not in text
    assert "PermitEmptyPasswords" not in text
    assert "99-stickllm-test-empty.conf" in text  # cleanup of stale drop-in only


def test_bootstatus_prints_password_not_empty_label():
    text = STATUS.read_text(encoding="utf-8")
    assert 'center "password: ${pass}"' in text
    assert "password: (empty — Test mode)" not in text
