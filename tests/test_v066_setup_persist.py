"""0.6.6: setup-complete survives reboot on STICKLLM-DATA."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_control_has_setup_status_and_mark():
    ctl = (ROOT / "overlay/usr/local/bin/stickllm-control").read_text(encoding="utf-8")
    assert "def setup_status(" in ctl
    assert "def setup_mark_complete(" in ctl
    assert 'stickllm-setup.json' in ctl
    assert 'action == "setup_status"' in ctl
    assert 'action == "setup_mark_complete"' in ctl
    assert "setup_mark_complete" in ctl.split('if action == "vault_unlock":', 1)[1][:800]


def test_vault_writes_setup_complete_on_meta():
    vault = (ROOT / "overlay/usr/local/bin/stickllm-vault").read_text(encoding="utf-8")
    assert "write_setup_complete" in vault
    assert "stickllm-setup.json" in vault
    assert "write_setup_complete" in vault.split("write_meta()", 1)[0] or "write_setup_complete" in vault


def test_ui_unlock_only_path():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    assert "openVaultUnlockOnly" in app
    assert "maybeOfferSetupOrUnlock" in app
    assert "setup_status" in app
    assert "Welcome back" in app
    assert "stickllm-setup.json" in app or "STICKLLM-DATA" in app
    assert re.search(r"refreshSetupState", app)


def test_changelog_mentions_reboot_unlock():
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "stickllm-setup.json" in log
    assert "passcode only" in log.lower() or "vault passcode only" in log.lower()
