"""0.6.1 storage fixes (items 12-15, 28)."""
import importlib.machinery
import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "overlay/usr/local/bin/stickllm-control"
VAULT = ROOT / "overlay/usr/local/bin/stickllm-vault"
PERSIST = ROOT / "overlay/usr/local/bin/stickllm-persist"
UPDATE = ROOT / "overlay/usr/local/bin/stickllm-update"
GRUB = ROOT / "boot/grub.cfg"
APP = ROOT / "ui/app.js"
GW = ROOT / "overlay/usr/local/bin/stickllm-gateway"
CATALOG = ROOT / "config/models/catalog.toml"


def _ctl(monkeypatch):
    monkeypatch.setenv("STICKLLM_CATALOG", str(CATALOG))
    loader = importlib.machinery.SourceFileLoader("stickllm_control_v061s", str(CTL))
    spec = importlib.util.spec_from_loader("stickllm_control_v061s", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _addons(monkeypatch, tmp_path):
    monkeypatch.setenv("STICKLLM_DATA_MNT", str(tmp_path / "data"))
    monkeypatch.setenv("STICKLLM_HOST_MNT", str(tmp_path / "host"))
    sys.path.insert(0, str(ROOT / "overlay/usr/local/lib"))
    try:
        sys.modules.pop("stickllm_addons", None)
        import stickllm_addons as mod  # noqa: E402
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(mod, "RUN_ADDONS", tmp_path / "run")
    return mod


def test_vault_allows_stick_data_as_first_class():
    # 0.6.2 hotfix: DATA needs no STICK-DATA env; live ISO still refused.
    s = VAULT.read_text()
    assert "is_stick_data_path()" in s
    assert "NOTE: vault on STICKLLM-DATA" in s
    assert 'elif is_live_usb_path "$probe"' in s
    # Old gate must not remain (allow only with env).
    assert 'STICKLLM_VAULT_ALLOW_STICK_DATA:-}" == "STICK-DATA"' not in s
    assert "luksFormat" in s  # LUKS file kept, no partitioning added
    assert subprocess.run(["bash", "-n", str(VAULT)]).returncode == 0


def test_control_auto_allows_data_path_without_confirm():
    src = CTL.read_text()
    assert "_on_data" in src and 'env["STICKLLM_VAULT_ALLOW_STICK_DATA"] = "STICK-DATA"' in src
    assert '"needs": "stick_data_confirm"' not in src
    # Keep backward-compatible stick_data_confirm still sets the env.
    assert 'params.get("stick_data_confirm")' in src


def test_control_passes_stick_data_confirm_and_offer(monkeypatch, tmp_path):
    ctl = _ctl(monkeypatch)
    src = CTL.read_text()
    assert 'params.get("stick_data_confirm")' in src and 'env.pop("STICKLLM_VAULT_ALLOW_STICK_DATA"' in src
    monkeypatch.setattr(ctl, "MNT", tmp_path)
    monkeypatch.setattr(ctl.os.path, "ismount", lambda p: True)
    opt = ctl.stick_data_vault_option({"devices": []})
    assert opt["path"] == str(tmp_path / "vault") and opt["no_internal_drive"] is True
    assert "No internal drive found – store vault on this drive?" in opt["warning"]
    opt2 = ctl.stick_data_vault_option({"selectable": [{"mount_path": "/mnt/stickllm-host/nvme0n1p2"}]})
    assert opt2["no_internal_drive"] is False
    monkeypatch.setattr(ctl.os.path, "ismount", lambda p: False)
    assert ctl.stick_data_vault_option({}) is None


def test_ui_store_vault_on_this_drive():
    s = APP.read_text()
    assert "No internal drive found – store vault on this drive?" in s
    assert 'stick_data_confirm: "STICK-DATA"' in s and "data-stickdata" in s


def test_persist_accepts_usb_transport():
    s = PERSIST.read_text()
    assert '[[ "$rm" == "1" || "$tran" == "usb" ]]' in s
    assert "is not marked removable" not in s
    assert subprocess.run(["bash", "-n", str(PERSIST)]).returncode == 0


def test_usb_claim_outcome_explains(monkeypatch):
    ctl = _ctl(monkeypatch)
    ok = ctl.usb_claim_outcome({"ok": True, "stdout": "", "storage": {"mounted": True, "free_gb": 40, "mount": "/mnt/stickllm-data"}})
    assert ok["ok"] is True and "40 GiB free" in ok["message"]
    bad = ctl.usb_claim_outcome({"ok": True, "stdout": "", "storage": {"mounted": False, "note": "Free space only 200 MiB — need ≥1 GiB"}})
    assert bad["ok"] is False and "not enough unpartitioned space" in bad["error"]
    unk = ctl.usb_claim_outcome({"ok": True, "stdout": "", "storage": None})
    assert unk["ok"] is False and unk["error"].startswith("Couldn't use free stick space")
    assert '"Claim finished"' not in APP.read_text()


def test_updater_verifies_sha_and_keeps_rollback():
    s = UPDATE.read_text()
    assert "sha256 mismatch" in s and "refusing plain http://" in s
    assert 'mv -f "$DIR/next.iso" "$DIR/prev.iso"' in s
    for bad in ("mkfs", "parted", "sgdisk", "dd if="):
        assert bad not in s
    assert subprocess.run(["bash", "-n", str(UPDATE)]).returncode == 0
    g = GRUB.read_text()
    assert "findiso=/stickllm-update/next.iso" in g and "6 Previous update (rollback)" in g
    assert 'menuentry "1 Server / Local"' in g


def test_updater_rejects_bad_sha(tmp_path):
    r = subprocess.run(["bash", str(UPDATE), str(tmp_path / "x.iso"), "nothex"],
                       capture_output=True, text=True,
                       env={"PATH": "/usr/bin:/bin", "STICKLLM_UPDATE_STATUS": str(tmp_path / "u.json")})
    assert r.returncode != 0


def test_vault_needed_message_single_drive(monkeypatch, tmp_path):
    mod = _addons(monkeypatch, tmp_path)
    data = str(tmp_path / "data")
    mounts = f"/dev/sda3 {data} ext4 rw 0 0\n"
    msg = mod.vault_needed_message(mounts, free_gb=271)
    assert "Store vault on this drive" in msg and "271" in msg
    assert "full" in mod.vault_needed_message(mounts, free_gb=0.5)
    none = mod.vault_needed_message("", free_gb=0)
    assert "No writable space" in none and "Use free space on the stick" in none
    host = f"/dev/nvme0n1p2 {tmp_path}/host/nvme0n1p2 ext4 rw 0 0\n"
    assert "Create vault" in mod.vault_needed_message(host)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/stickllm-vault-location.json").write_text("{}")
    assert mod.vault_needed_message(mounts) == mod.VAULT_LOCKED_MESSAGE


def test_gateway_uses_vault_needed_message():
    s = GW.read_text()
    assert "def vault_needed_message(" in s
    assert '"code":"vault_needed"' in s.replace(" ", "")
