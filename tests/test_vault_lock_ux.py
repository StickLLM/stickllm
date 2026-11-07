"""Lock-while-in-use: A0 UI down before umount; no refuse-popup spam; unlock does not auto-open A0."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_lock_closes_a0_before_vault_lock():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    desk = (ROOT / "ui/desktop.js").read_text(encoding="utf-8")
    lock = app.split("async function lockVault()", 1)[1].split("$(\"#lockBtn\").onclick", 1)[0]
    assert "prepareForVaultLock" in lock or "closeAll" in lock
    assert 'control("vault_lock")' in lock
    # Screen / A0 tear-down before the lock RPC.
    prep = lock.find("prepareForVaultLock")
    if prep < 0:
        prep = lock.find("closeAll")
    assert 0 <= prep < lock.index('control("vault_lock")')
    assert "function prepareForVaultLock" in desk
    assert "about:blank" in desk
    assert "wm.close(CHAT, true)" in desk.split("function prepareForVaultLock", 1)[1].split(
        "window.stickDesk", 1
    )[0]


def test_lock_suppresses_a0_refuse_noise():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    gw = (ROOT / "overlay/usr/local/bin/stickllm-gateway").read_text(encoding="utf-8")
    assert "vaultLocking" in app
    assert "agent not responding" in app.lower() or "not responding" in app
    assert "refused to connect" in app
    assert "agent not responding" in gw
    assert "LOCKNOISE" in gw or "agent not responding" in gw


def test_unlock_does_not_auto_open_a0():
    desk = (ROOT / "ui/desktop.js").read_text(encoding="utf-8")
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    unlocked = desk.split('stickllm:vault-unlocked"', 1)[1].split(
        'stickllm:agent-status"', 1
    )[0]
    assert "openApp(CHAT)" not in unlocked
    assert "ensureAgentZeroStarted" not in unlocked
    assert "Never auto-open" in unlocked or "only explicit Open" in unlocked or "Never auto-open" in desk
    assert 'document.addEventListener("stickllm:vault-unlocked"' in app
    listener = app.split('document.addEventListener("stickllm:vault-unlocked"', 1)[1].split(
        "\ntry { hardenVaultPassFields", 1
    )[0]
    assert "ensureAgentZeroStarted" not in listener
    assert "a0OpenFull" not in listener


def test_vault_md_documents_lock_while_using():
    doc = (ROOT / "docs/VAULT.md").read_text(encoding="utf-8")
    assert "Lock while using the computer" in doc
    assert "does **not** auto-open Agent Zero" in doc or "does not auto-open Agent Zero" in doc
    assert "Ephemeral vs Vault" in doc
