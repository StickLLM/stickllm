"""0.6.7: first-boot vault probe + create sequence markers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_boot_probes_ssd_before_wizard():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    assert "async function probeBootVault" in app
    assert "mount_host_partition" in app
    assert "openVaultUnlockOnly" in app
    # Fresh path: Open model → network/storage/vault (no welcome gate).
    assert "STEP_MODEL" in app and "STEP_NET" in app and "STEP_VAULT" in app
    assert "STEP_WELCOME" not in app
    assert "rescueStuckVaultWizard" in app
    assert "dismissSetupWizard" in app
    assert app.index("STEP_MODEL") < app.index("STEP_VAULT")
    assert "setupBlocksAgent" in app
    assert "setSetupChrome" in app


def test_vault_create_enters_mode_before_recovery():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    # create path must call enterVaultModeNow before showRecoveryPhraseOnce
    create_block = app.split("vault_setup", 1)[1].split("already exists", 1)[0]
    assert "enterVaultModeNow" in create_block or "enterVaultModeNow" in app
    assert "showRecoveryPhraseOnce" in app
    assert "vaultDone" in app
    assert "advanceAfterVaultCreate" in app
    assert "needsRecoveryPhrase" in app
    assert "createInFlight" in app
    assert "pollUnlocked" in app
    assert "st.blob && i > 2" not in app
    # Recovery is a wizard step (not #confirm behind setup z-index 9999)
    assert "STEP_RECOVERY" in app
    assert "wizRecoveryPhrase" in app
    adv = app.split("async function advanceAfterVaultCreate", 1)[1].split("\n  let overlay", 1)[0]
    assert "STEP_RECOVERY" in adv
    assert "showRecoveryPhraseOnce" not in adv
    # rescue must not dismiss past recovery / System ready
    rescue = app.split("async function rescueStuckVaultWizard", 1)[1].split("\nfunction ", 1)[0]
    assert "dismissSetupWizard()" not in rescue
    assert "markSetupDone(" not in rescue


def test_agent_panel_clears_locked_ctas():
    desk = (ROOT / "ui/desktop.js").read_text(encoding="utf-8")
    assert 'dataset.mode = "unlock"' in desk or 'dataset.mode="unlock"' in desk
    assert "Unlock vault" in desk
    assert "Starting…" in desk
    assert "store.hidden = needsUnlock || settingsGap || working" in desk
    # Open A0 only after setup; poll HTTP before iframe on explicit Open.
    assert "setupBlocksA0" in desk
    assert "agentHttpReady" in desk
    assert "ensureAgentZeroStarted" in desk
    # Ready panel keeps Open; do not auto-open/auto-start A0 on unlock/desktop start.
    assert 'dataset.mode = "open"' in desk
    assert "Open Agent Zero" in desk
    assert "openA0Flight" in desk and "openA0Busy" in desk
    unlock = desk.split("stickllm:vault-unlocked", 1)[1].split("stickllm:agent-status", 1)[0]
    assert "openApp(CHAT)" not in unlock
    assert "ensureAgentZeroStarted" not in unlock
    assert "startChatAgentPoll" not in unlock
    assert "Never auto-open" in unlock
    assert "Never auto-open Agent Zero on desktop start" in desk


def test_vault_unlock_opening_wording_and_no_save_password():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert "Opening vault, please wait" in app
    assert 'showVaultCreating(true, "open")' in app
    assert "hardenVaultPassFields" in app
    assert "wireVaultPassEnterToSetupNext" in app
    assert "autocomplete=\"current-password\"" not in app
    assert 'id="wizP1" type="password"' not in app
    assert 'id="vaultPass"' in html and "data-form-type=\"other\"" in html
    assert "readonly" in html.split('id="vaultPass"', 1)[1].split(">", 1)[0]
    # Unlock form must not clear passcode before unlock succeeds (Enter re-prompt bug).
    unlock = app.split('$("#unlockForm").onsubmit', 1)[1].split("\n}\n", 1)[0]
    assert unlock.index("vault_unlock") < unlock.index('$("#vaultPass").value = ""')


def test_setup_persist_still_present():
    ctl = (ROOT / "overlay/usr/local/bin/stickllm-control").read_text(encoding="utf-8")
    assert "def setup_status(" in ctl
    assert "stickllm-setup.json" in ctl


def test_desktop_icon_click_raises_open_window():
    desk = (ROOT / "ui/desktop.js").read_text(encoding="utf-8")
    assert "function raiseApp(id)" in desk
    assert "function winIdFor(id)" in desk
    assert 'id === "agent" ? CHAT' in desk
    assert "raiseApp(b.dataset.app)" in desk
    assert "wm.focus(wid)" in desk
    # Focus/restore only — not taskbarClick (which would minimise when focused).
    raise_fn = desk.split("function raiseApp(id)", 1)[1].split("\n  function ", 1)[0]
    assert "taskbarClick" not in raise_fn
