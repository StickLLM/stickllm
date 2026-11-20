"""README tip + embed shim keep first Open A0 off raw :5099."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_a0_refused_tip_readable():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Troubleshooting" in readme
    assert "127.0.0.1 refused to connect" in readme or "refused to connect" in readme
    assert "Reload" in readme
    assert "Agent Zero" in readme
    # Must not bury the tip in tiny-font HTML.
    assert "font-size:0.0001" not in readme.lower()
    assert 'style="font-size:0' not in readme.lower()


def test_troubleshooting_doc_a0_refused():
    doc = (ROOT / "docs/TROUBLESHOOTING.md").read_text(encoding="utf-8")
    assert "127.0.0.1 refused to connect" in doc
    assert "Reload the desktop" in doc or "Reload" in doc


def test_embed_shim_rewrites_loopback_5099():
    gw = (ROOT / "overlay/usr/local/bin/stickllm-gateway").read_text(encoding="utf-8")
    shim = gw.split("_EMBED_SHIM = ", 1)[1].split('"""', 2)[1]
    assert 'port==="5099"' in shim or 'port === "5099"' in shim.replace(" ", "")
    assert "location.assign" in shim
    assert "127.0.0.1" in shim
