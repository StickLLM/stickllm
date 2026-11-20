"""0.5.2 fix 5: desktop icons come from the app catalog (/api/apps)."""
from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "ui"


def test_catalog_icons_rendered_from_api_apps():
    js = (UI / "app.js").read_text()
    assert "function syncCatalogDesktop(apps)" in js
    assert "syncCatalogDesktop(apps);" in js
    for app_id in ("onlyoffice", "tasks-md", "paisa", "trilium", "node-red", "comfyui"):
        assert f'{app_id}: {{ label' in js or f'"{app_id}": {{ label' in js
    # Removed apps lose their icon.
    assert 'querySelectorAll("a.deskIcon[data-catalog-app]")' in js


def test_app_tab_link_fallback_uses_catalog():
    js = (UI / "app.js").read_text()
    body = js.split("function appTabLink(id) {", 1)[1].split("\nfunction ", 1)[0]
    assert "catalogApps.get(cid)" in body
    assert 'docs: "onlyoffice"' in js
    assert "return null;" in body
    assert "if (!link) return null;" in js


def test_starter_icons_stay_static():
    html = (UI / "index.html").read_text()
    for sid in ("files", "notepad", "calculator", "monitor"):
        assert f'data-starter="{sid}"' in html


def test_app_tab_link_node_unit():
    import shutil, subprocess
    import pytest
    if not shutil.which("node"):
        pytest.skip("node not installed")
    out = subprocess.run(["node", str(Path(__file__).with_name("desk_link.test.js"))], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert "desk link ok" in out.stdout
