"""0.5.2: kiosk Chromium downloads go to vault/Downloads; blocked while locked."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "overlay/usr/local/bin/stickllm-download-policy"


def run(tmp_path, state, mounted):
    shim = tmp_path / "bin"
    shim.mkdir(exist_ok=True)
    mp = shim / "mountpoint"
    mp.write_text("#!/bin/sh\nexit %d\n" % (0 if mounted else 1))
    mp.chmod(0o755)
    pol = tmp_path / "pol"
    env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}", STICKLLM_VAULT_MNT=str(tmp_path / "vault"),
               STICKLLM_CHROMIUM_POLICY_DIRS=str(pol), STICKLLM_KIOSK_USER=os.environ.get("USER", "root"))
    (tmp_path / "vault").mkdir(exist_ok=True)
    out = subprocess.run(["bash", str(SCRIPT), state], env=env, capture_output=True, text=True, timeout=20)
    data = json.loads((pol / "stickllm-downloads.json").read_text()) if (pol / "stickllm-downloads.json").exists() else None
    return out, data


def test_unlocked_points_at_vault_downloads(tmp_path):
    out, data = run(tmp_path, "auto", True)
    assert out.returncode == 0 and "downloads=unlocked" in out.stdout
    assert data["DownloadDirectory"] == str(tmp_path / "vault" / "Downloads")
    assert data["DownloadRestrictions"] == 0 and data["PromptForDownloadLocation"] is False
    assert (tmp_path / "vault" / "Downloads").is_dir()


def test_locked_blocks_downloads(tmp_path):
    out, data = run(tmp_path, "auto", False)
    assert "downloads=locked" in out.stdout
    assert data == {"DownloadRestrictions": 3, "PromptForDownloadLocation": False}
    # "unlocked" with no vault mounted still fails closed.
    out, data = run(tmp_path, "unlocked", False)
    assert data["DownloadRestrictions"] == 3


def test_symlinked_downloads_fails_closed(tmp_path):
    (tmp_path / "vault").mkdir()
    (tmp_path / "vault" / "Downloads").symlink_to(tmp_path)
    out, data = run(tmp_path, "unlocked", True)
    assert data["DownloadRestrictions"] == 3 and "DownloadDirectory" not in data


def test_boot_default_and_hooks():
    shipped = json.loads((ROOT / "overlay/etc/chromium/policies/managed/stickllm-downloads.json").read_text())
    assert shipped["DownloadRestrictions"] == 3
    vault = (ROOT / "overlay/usr/local/bin/stickllm-vault").read_text()
    lock = vault[vault.index("cmd_lock() {"):]
    assert lock.index("download_policy locked") < lock.index("stop_vault_addons")
    refresh = vault[vault.index("refresh_gateway_vault_view() {"):]
    assert "download_policy unlocked" in refresh[:600]
    assert "stickllm-download-policy auto" in (ROOT / "overlay/usr/local/bin/stickllm-kiosk").read_text()
