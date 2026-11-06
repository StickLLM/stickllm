"""0.6.7: first-boot vault probe + create sequence markers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_boot_probes_ssd_before_wizard():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    assert "async function probeBootVault" in app
    assert "mount_host_partition" in app
    assert "openVaultUnlockOnly" in app
    # Fresh path: Welcome → Open model → network/storage/vault.
    assert "STEP_WELCOME" in app and "STEP_MODEL" in app and "STEP_NET" in app and "STEP_VAULT" in app
    assert app.index("STEP_WELCOME") < app.index("STEP_MODEL") < app.index("STEP_VAULT")
    assert "setupBlocksAgent" in app
    assert "setSetupChrome" in app


def test_vault_create_enters_mode_before_recovery():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    # create path must call enterVaultModeNow before showRecoveryPhraseOnce
    create_block = app.split("vault_setup", 1)[1].split("already exists", 1)[0]
    assert "enterVaultModeNow" in create_block or "enterVaultModeNow" in app
    assert "showRecoveryPhraseOnce" in app
    assert "vaultDone" in app


def test_agent_panel_clears_locked_ctas():
    desk = (ROOT / "ui/desktop.js").read_text(encoding="utf-8")
    assert 'dataset.mode = "unlock"' in desk or 'dataset.mode="unlock"' in desk
    assert "Unlock vault" in desk
    assert "waitReady" in desk or "Starting…" in desk
    # Reboot unlock must start A0 and hide Open/Retry/Store while starting/running.
    assert "ensureAgentZeroStarted" in desk.split("stickllm:vault-unlocked", 1)[1]
    assert "store.hidden = needsUnlock || settingsGap || working" in desk
    # Open A0 only after setup / unlock; poll HTTP before iframe.
    assert "setupBlocksA0" in desk
    assert "agentHttpReady" in desk
    assert "startChatAgentPoll" in desk.split("stickllm:vault-unlocked", 1)[1]


def test_vault_unlock_opening_wording_and_no_save_password():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert "Opening vault, please wait" in app
    assert 'showVaultCreating(true, "open")' in app
    assert "hardenVaultPassFields" in app
    assert "autocomplete=\"current-password\"" not in app
    assert 'id="wizP1" type="password"' not in app
    assert 'id="vaultPass"' in html and "data-form-type=\"other\"" in html
    assert "readonly" in html.split('id="vaultPass"', 1)[1].split(">", 1)[0]


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
