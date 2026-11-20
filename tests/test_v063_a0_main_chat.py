"""0.6.3: Agent Zero is the main Chat window."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_a0_is_main_chat_ui():
    app = (ROOT / "ui/app.js").read_text(encoding="utf-8")
    html = (ROOT / "ui/index.html").read_text(encoding="utf-8")
    desk = (ROOT / "ui/desktop.js").read_text(encoding="utf-8")
    assert "moveAgentDrive" in app
    assert "Move Agent Zero to SSD" in app
    assert "ensureAgentZeroStarted" in app
    assert "a0MoveSsd" in html
    assert "Run from stick" in html
    assert "urlFor(\"agent\")" in desk or "urlFor('agent')" in desk
    assert 'id="agentCatalogInstall" hidden' in html



