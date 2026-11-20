"""0.6.12 WIP: Agent Zero chats leave the vault while session mode is ephemeral."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHATS = ROOT / "overlay/usr/local/lib/stickllm_chats.py"
AGENT = ROOT / "overlay/usr/local/bin/stickllm-agent"
GW = ROOT / "overlay/usr/local/bin/stickllm-gateway"
CTL = ROOT / "overlay/usr/local/bin/stickllm-control"
VAULT_DOC = ROOT / "docs/VAULT.md"
CHATS_DOC = ROOT / "docs/CHATS.md"
JSON = ROOT / "overlay/opt/stickllm/ui/stickllm.json"


def test_version_is_0612_wip():
    assert '"version": "0.6.12"' in JSON.read_text(encoding="utf-8")
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    assert "v0612" in html and "v0.6.12" in html
    build = (ROOT / "scripts/build.sh").read_text(encoding="utf-8")
    assert "STICKLLM_VERSION:-0.6.12" in build
    log = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert log.lstrip().startswith("## 0.6.12")


def test_a0_chats_dir_defaults_ephemeral_path():
    text = CHATS.read_text(encoding="utf-8")
    assert "EPHEMERAL_A0_CHATS" in text
    assert "/run/stickllm/a0-chats" in text
    assert "session_mode" in text
    assert 'mode != "vault"' in text or "mode != 'vault'" in text
    # Migrate private state only into vault store, never into RAM.
    main = text[text.index("def main("):]
    assert 'mode == "vault"' in main
    assert "migrate_a0_state_chats" in main


def test_agent_and_mode_switch_remount():
    sh = AGENT.read_text(encoding="utf-8")
    assert "a0-chats-dir" in sh and "/run/stickllm/a0-chats" in sh
    gw = GW.read_text(encoding="utf-8")
    body = gw[gw.index("def set_session_mode("):gw.index("VAULT_MNT = Path(")]
    assert "try-restart" in body and "stickllm-agent.service" in body
    assert "agent_chats_remount" in body
    assert "ensure-addons" not in body
    ctl = CTL.read_text(encoding="utf-8")
    cbody = ctl[ctl.index("def set_session_mode("):ctl.index("\ndef vault_host_root(")]
    assert "try-restart" in cbody and "stickllm-agent.service" in cbody


def test_docs_note_ephemeral_a0_tmpfs():
    vault = VAULT_DOC.read_text(encoding="utf-8")
    chats = CHATS_DOC.read_text(encoding="utf-8")
    assert "/run/stickllm/a0-chats" in vault and "/run/stickllm/a0-chats" in chats
    assert "tmpfs" in chats.lower() or "tmpfs" in vault.lower()
