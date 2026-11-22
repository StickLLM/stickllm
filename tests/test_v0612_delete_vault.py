"""0.6.12: Delete vault — Settings UI, control/gateway, CLI destroy, VAULT.md."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VAULT = ROOT / "overlay/usr/local/bin/stickllm-vault"
CTL = ROOT / "overlay/usr/local/bin/stickllm-control"
GW = ROOT / "overlay/usr/local/bin/stickllm-gateway"
APP = ROOT / "ui/app.js"
HTML = ROOT / "ui/index.html"
DOC = ROOT / "docs/VAULT.md"
LOG = ROOT / "CHANGELOG.md"


def test_vault_cli_destroy_requires_delete_vault_confirm():
    s = VAULT.read_text(encoding="utf-8")
    assert "cmd_destroy()" in s
    assert "DELETE_VAULT" in s
    assert 'confirm_phrase "DELETE_VAULT"' in s or "DELETE_VAULT" in s.split("cmd_destroy", 1)[1]
    destroy = s.split("cmd_destroy()", 1)[1].split("cmd_set_wipe_after", 1)[0]
    assert "is_block_device_path" in destroy
    assert "refusing block device" in destroy.lower() or "refusing block device path" in destroy
    assert "luksErase" in destroy or "rm -f" in destroy
    assert "clear_config_after_destroy" in destroy
    assert "stickllm-setup.json" in destroy or "STICKLLM_CLR_SETUP" in s
    assert "sibling models" in destroy.lower() or "Kept:" in destroy
    # Never format disks / run wipefs / partition in destroy path (comment OK).
    assert not re.search(r"(?m)^\s*wipefs\b", destroy)
    assert "mkfs." not in destroy and not re.search(r"(?m)^\s*mkfs\b", destroy)
    bash = "bash"
    for cand in (
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
    ):
        if cand.is_file():
            bash = str(cand)
            break
    assert subprocess.run([bash, "-n", str(VAULT)], check=False, capture_output=True).returncode == 0


def test_vault_cli_registers_destroy_command():
    s = VAULT.read_text(encoding="utf-8")
    assert "destroy|delete|delete-vault)" in s
    assert "stickllm-vault destroy" in s


def test_control_vault_delete_wires_destroy():
    s = CTL.read_text(encoding="utf-8")
    assert 'action == "vault_delete"' in s or 'action == "vault_delete" or action == "vault_destroy"' in s
    assert 'vault_action("destroy"' in s
    destroy = s.split('if cmd == "destroy":', 1)[1].split('if cmd == "find-vault":', 1)[0]
    assert 'confirm != "DELETE_VAULT"' in destroy
    assert "passcode required" in destroy
    assert "refusing block device" in destroy.lower() or "Refusing block device" in destroy
    assert 'env["STICKLLM_VAULT_CONFIRM"] = "DELETE_VAULT"' in destroy
    assert 'env["STICKLLM_VAULT_PASS"] = passcode' in destroy
    # Lock teardown before destroy when open.
    assert "stickllm-agent" in destroy and "lock" in destroy
    # Clear pass from env after the subprocess (never log/print it).
    assert 'env.pop("STICKLLM_VAULT_PASS"' in destroy
    assert "print(passcode" not in destroy
    assert "print(pass" not in destroy


def test_gateway_timeout_covers_vault_delete():
    gw = GW.read_text(encoding="utf-8")
    m = re.search(
        r'elif action in \(([^)]*"vault_delete"[^)]*)\):\s*\n(?:\s*#.*\n)*\s*timeout = (\d+)',
        gw,
    )
    assert m, "gateway needs a long timeout for vault_delete (lock + destroy)"
    assert int(m.group(2)) >= 480


def test_ui_delete_vault_panel():
    html = HTML.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    assert 'id="deleteVaultPanel"' in html
    assert "DELETE_VAULT" in html
    assert "This will erase all your data" in html
    assert "There is no backup" in html
    assert 'id="deleteVaultSelect"' in html
    assert 'id="deleteVaultPass"' in html
    assert 'id="deleteVaultConfirm"' in html
    assert 'id="deleteVaultBtn"' in html
    assert "async function deleteVaultAction" in app
    assert 'control("vault_delete"' in app
    assert 'confirm: "DELETE_VAULT"' in app
    delete_fn = app.split("async function deleteVaultAction", 1)[1].split(
        "if ($(\"#deleteVaultConfirm\"))", 1
    )[0]
    assert "prepareForVaultLock" in delete_fn
    assert "clearVaultPresenceCache" in delete_fn
    assert "openSetupWizard" in delete_fn
    assert "refreshDeleteVaultList" in app
    assert "vaultDeleteLabel" in app
    assert 'deleteVaultPass' in app
    # Readonly must clear before focus settles (label-click / kiosk Chromium).
    harden = app.split("function hardenVaultPassFields", 1)[1].split(
        "function wireVaultPassEnterToSetupNext", 1
    )[0]
    assert 'closest("label")' in harden
    assert "once: true" not in harden
    toggle = app.split('deleteVaultPanel").addEventListener("toggle"', 1)[1].split(
        "async function refreshMovableLive", 1
    )[0]
    assert 'removeAttribute("readonly")' in toggle


def test_ui_no_stale_unlock_after_delete():
    """After delete / on Settings reopen: re-probe; no vault → full setup, not unlock."""
    app = APP.read_text(encoding="utf-8")
    assert "function clearVaultPresenceCache" in app
    unlock = app.split("async function openVaultUnlockOnly", 1)[1].split(
        "async function openSetupWizard", 1
    )[0]
    assert "probeBootVault" in unlock
    assert "openSetupWizard({ force: true })" in unlock or 'openSetupWizard({ force: true })' in unlock
    gate = app.split("async function maybeOfferSetupOrUnlock", 1)[1].split(
        "async function refreshStatus", 1
    )[0]
    assert "probe.found || st.blob || st.blob_exists" in gate
    assert "st.setup_complete || st.vault_configured" in gate
    assert "clearVaultPresenceCache" in gate
    # Must not open unlock-only from setup_complete alone.
    assert "probe.found || st.setup_complete || st.vault_configured" not in gate
    ctl = CTL.read_text(encoding="utf-8")
    status = ctl.split("def setup_status(", 1)[1].split("def setup_mark_complete(", 1)[0]
    assert "blob_exists" in status
    assert "Only a real blob on disk" in status or "orphan" in status.lower()
    vault = VAULT.read_text(encoding="utf-8")
    destroy_clr = vault.split("clear_config_after_destroy()", 1)[1].split("cmd_destroy()", 1)[0]
    assert "not leave unlock-only" in destroy_clr or "still =" in destroy_clr


def test_vault_md_documents_delete():
    doc = DOC.read_text(encoding="utf-8")
    assert "Delete vault" in doc
    assert "DELETE_VAULT" in doc
    assert "vault_delete" in doc
    assert "stickllm-vault.img" in doc
    assert "sibling" in doc.lower() or "models/" in doc
    assert "USB settings" in doc or "settings LUKS" in doc
    assert "pairing" in doc.lower()


def test_changelog_mentions_delete_vault():
    log = LOG.read_text(encoding="utf-8")
    assert "## 0.6.12" in log
    section = log.split("## 0.6.12", 1)[1].split("## 0.6.11", 1)[0]
    assert "Delete vault" in section
    assert "DELETE_VAULT" in section
    # 0.8.1+: stale unlock after delete
    assert "no stale unlock" in log.lower() or "re-probe" in log.lower()
