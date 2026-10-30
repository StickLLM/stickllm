"""Desktop layout: WinBox.js vendoring, licence notices, wiring, window logic."""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "ui"
VENDOR = UI / "vendor" / "winbox-0.2.82"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_window_manager_logic():
    node = shutil.which("node")
    assert node, "node is required to run the desktop layout logic"
    subprocess.run([node, str(ROOT / "tests" / "desktop_ui.test.js")], cwd=ROOT, check=True)


def test_winbox_vendored_pinned_and_unmodified():
    meta = _read(VENDOR / "VENDOR.txt")
    assert "0.2.82" in meta and "Apache License 2.0" in meta
    listed = re.findall(r"^\s+([0-9a-f]{64})\s+(\S+)$", meta, re.M)
    names = {n for _, n in listed}
    assert {"winbox.bundle.min.js", "LICENSE", "package.json"} <= names
    for digest, name in listed:
        got = hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()
        assert got == digest, f"{name} changed from the pinned upstream copy"
    pkg = _read(VENDOR / "package.json")
    assert '"version": "0.2.82"' in pkg and '"license": "Apache-2.0"' in pkg


def test_winbox_licence_and_header_kept():
    lic = _read(VENDOR / "LICENSE")
    assert "Apache License" in lic and "Version 2.0, January 2004" in lic
    head = (VENDOR / "winbox.bundle.min.js").read_bytes()[:400].decode("utf-8")
    assert "WinBox.js v0.2.82" in head and "Licence: Apache-2.0" in head
    assert "Thomas Wilkerling" in head
    attrs = _read(ROOT / ".gitattributes")
    assert "ui/vendor/** -text" in attrs


def test_third_party_notices_listed_and_shipped():
    notices = _read(ROOT / "THIRD_PARTY_NOTICES.md")
    assert "WinBox.js" in notices and "0.2.82" in notices and "Apache" in notices
    assert "ui/vendor/winbox-0.2.82/LICENSE" in notices
    for script in ("scripts/lib/docker-build-live.sh", "scripts/lib/docker-patch-iso-local.sh"):
        body = _read(ROOT / script)
        assert "THIRD_PARTY_NOTICES.md" in body, f"{script} must ship the notices"


def test_no_cdn_and_local_winbox():
    html = _read(UI / "index.html")
    desk = _read(UI / "desktop.js")
    for text in (html, desk, _read(UI / "desktop-core.js"), _read(UI / "desktop.css")):
        assert not re.search(r"(cdn\.|unpkg|jsdelivr|cdnjs|rawgit)", text, re.I)
    assert "vendor/winbox-0.2.82/winbox.bundle.min.js" in desk
    # Mobile/classic never downloads WinBox: it is loaded on demand, not from index.html.
    assert "winbox" not in html.lower()
    i_core, i_desk, i_app = (html.index(s) for s in ('src="desktop-core.js', 'src="desktop.js', 'src="app.js'))
    assert i_app < i_core < i_desk
    assert 'href="desktop.css' in html
    assert 'id="layoutSeg"' in html


def test_app_js_hooks():
    app = _read(UI / "app.js")
    assert app.count("window.stickDesk.handles(id)") >= 2, "starter apps open as desktop windows"
    assert "window.stickDesk.closeAll()" in app, "lock closes app windows"
    m = re.search(r"window\.stickApp = Object\.freeze\(\{([^}]*)\}\)", app)
    assert m, "app.js publishes the actions desktop.js needs"
    for fn in ("openSettings", "lockVault", "showApps", "toast"):
        assert fn in m.group(1)
    desk = _read(UI / "desktop.js")
    assert "typeof openSettings" not in desk and "appApi()" in desk


def test_desktop_scope_bundled_apps_only():
    desk = _read(UI / "desktop.js")
    for big in ("onlyoffice", "nodered", "node-red", "agent-zero", "agentzero"):
        assert not re.search(rf"['\"]{big}['\"]\s*:", desk, re.I), f"{big} must stay a tab"
    css = re.sub(r"/\*.*?\*/", "", _read(UI / "desktop.css"), flags=re.S)
    rules = [r.strip() for r in re.split(r"[{}]", css)[0::2] if r.strip()]
    assert len(rules) > 20
    unscoped = [r for r in rules if "body.deskMode" not in r]
    assert not unscoped, f"desktop.css rules must be scoped to body.deskMode: {unscoped[:3]}"
