"""0.6.2 hotfix: vault on STICKLLM-DATA is first-class (no confirm gate)."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "overlay/usr/local/bin/stickllm-vault"
CTL = ROOT / "overlay/usr/local/bin/stickllm-control"
APP = ROOT / "ui/app.js"


def test_vault_script_allows_data_before_live_refuse():
    s = VAULT.read_text()
    i_data = s.index("if is_stick_data_path \"$probe\"")
    i_live = s.index("elif is_live_usb_path \"$probe\"")
    assert i_data < i_live
    # Env gate gone; allow is by is_stick_data_path alone.
    assert "STICKLLM_VAULT_ALLOW_STICK_DATA" not in s[i_data:i_live]
    assert subprocess.run(["bash", "-n", str(VAULT)], check=False).returncode == 0


def test_ui_skips_stick_data_preconfirm():
    s = APP.read_text()
    create = s.split('$("#createVault").onclick', 1)[1].split('$("#growVault")', 1)[0]
    assert 'title: "Store vault on this drive?"' not in create
    assert "vaultStickData = true" in create
    assert 'stick_data_confirm: "STICK-DATA"' in create


def test_control_no_longer_returns_needs_stick_data_confirm():
    src = CTL.read_text()
    assert '"needs": "stick_data_confirm"' not in src
