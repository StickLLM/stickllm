"""Apps page: catalog from docs/APPS.md, no fake installs, uninstall stays in bounds."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPS = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_apps.py"
DOC = ROOT / "docs" / "APPS.md"
HTML = ROOT / "ui" / "index.html"
JS = ROOT / "ui" / "app.js"
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"


def _load(env: dict | None = None):
    if env:
        os.environ.update(env)
    loader = importlib.machinery.SourceFileLoader("stickllm_apps_page", str(APPS))
    spec = importlib.util.spec_from_loader("stickllm_apps_page", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _documented_rows(text: str) -> list[dict]:
    group = ""
    rows = []
    for line in text.splitlines():
        if line.startswith("## "):
            group = line[3:].strip()
            continue
        if not line.startswith("|") or "**" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        rows.append(
            {
                "group": group,
                "name": re.sub(r"\*\*", "", cells[0]).strip(),
                "license": cells[1].strip(),
                "description": cells[2].strip(),
            }
        )
    return rows


def test_sidebar_drops_comfy_and_word_processor():
    html = HTML.read_text(encoding="utf-8")
    side = html.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0]
    assert "comfyLink" not in side
    assert "writerLink" not in side
    assert "Comfy" not in side
    assert "Word processor" not in side
    assert 'id="appsLink"' in side
    assert 'id="agentLink"' in side
    assert 'target="_blank"' in side
    assert 'id="appsView"' in html


def test_apps_page_lists_the_documented_catalog():
    apps = _load()
    doc_rows = [
        row
        for row in _documented_rows(DOC.read_text(encoding="utf-8"))
        if row["name"] != "Agent Zero"
        and row["group"] != "Agent"
        and "not a companion app" not in row["description"].lower()
    ]
    catalog = [
        (app["name"], app["group"], app["license"], app["description"])
        for app in apps.CATALOG
    ]
    documented = [
        (row["name"], row["group"], row["license"], row["description"])
        for row in doc_rows
    ]
    assert catalog == documented
    assert all(app["installer"] is None for app in apps.CATALOG)
    names = {app["name"] for app in apps.CATALOG}
    assert "Agent Zero" not in names
    assert "ComfyUI" in names
    assert "ONLYOFFICE Docs" in names
    assert not any("whisper" in name.lower() or "kitten" in name.lower() for name in names)

    html = HTML.read_text(encoding="utf-8")
    listing = html.split('id="appsList"', 1)[1].split('id="settings"', 1)[0]
    assert "Agent Zero" not in listing
    assert "whisper" not in listing.lower()
    for app in apps.CATALOG:
        assert f'data-app="{app["id"]}"' in listing
        assert app["name"] in listing
        assert app["description"] in listing
    assert "Not available yet" in listing
    assert "Not installed" in listing
    menu = html.split('id="appsMenu"', 1)[1].split('id="settings"', 1)[0]
    assert "Nothing is installed from this page yet." not in menu
    assert "Select an app to install or uninstall it." not in menu
    assert "Install it first" not in menu
    assert "Agent Zero stays" not in menu
    assert "<h3>" not in menu
    assert 'id="appsDetail"' not in html


def test_install_does_not_claim_success_without_an_installer(tmp_path):
    apps = _load()
    record = tmp_path / "apps-installed.json"
    root = tmp_path / "apps"
    outside = tmp_path / "secret.txt"
    outside.write_text("keep", encoding="utf-8")
    for app in apps.CATALOG:
        result = apps.install_app(app["id"], record_path=record, install_root=root)
        assert result["ok"] is False
        assert result["installed"] is False
        assert result["state"] == "not_available"
        assert result["error"] == "no_installer"
        assert "was not installed" in result["message"]
        assert result["deleted"] == []
    assert not record.exists()
    assert not root.exists()
    assert outside.read_text(encoding="utf-8") == "keep"
    page = apps.catalog_document(record_path=record)
    assert page["installed_count"] == 0
    assert all(row["installed"] is False and row["state"] == "not_available" for row in page["apps"])
    assert apps.install_app("agent-zero", record_path=record, install_root=root)["ok"] is False


def test_uninstall_does_not_delete_unrelated_files(tmp_path):
    apps = _load()
    record_path = tmp_path / "apps-installed.json"
    root = tmp_path / "apps"
    own = root / "comfyui"
    own.mkdir(parents=True)
    (own / "marker").write_text("own", encoding="utf-8")
    sibling = root / "other"
    sibling.mkdir()
    (sibling / "keep").write_text("sibling", encoding="utf-8")
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    record_path.write_text(
        json.dumps(
            {
                "comfyui": {
                    "installed_by": "apps",
                    "paths": [str(outside), str(sibling), str(own)],
                }
            }
        ),
        encoding="utf-8",
    )
    result = apps.uninstall_app("comfyui", record_path=record_path, install_root=root)
    assert result["ok"] is False
    assert result["deleted"] == []
    assert "Nothing was removed" in result["message"]
    assert outside.read_text(encoding="utf-8") == "secret"
    assert (sibling / "keep").read_text(encoding="utf-8") == "sibling"
    assert (own / "marker").read_text(encoding="utf-8") == "own"
    missing = apps.uninstall_app("onlyoffice", record_path=record_path, install_root=root)
    assert missing["ok"] is False
    assert missing["deleted"] == []


def test_uninstall_removes_only_the_app_this_page_installed(tmp_path):
    apps = _load()
    record_path = tmp_path / "apps-installed.json"
    root = tmp_path / "apps"
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    catalog = [
        {
            "id": "comfyui",
            "name": "ComfyUI",
            "group": "Creative and technical",
            "license": "GPL",
            "description": "Image generation on the 3090.",
            "installer": "test-only",
        }
    ]
    installed = apps.install_app(
        "comfyui", record_path=record_path, install_root=root, catalog=catalog
    )
    assert installed["ok"] is True
    assert installed["installed"] is True
    assert (root / "comfyui").is_dir()
    sibling = root / "other"
    sibling.mkdir()
    (sibling / "keep").write_text("sibling", encoding="utf-8")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["comfyui"]["paths"] = [str(outside), str(sibling)]
    record_path.write_text(json.dumps(record), encoding="utf-8")
    result = apps.uninstall_app(
        "comfyui", record_path=record_path, install_root=root, catalog=catalog
    )
    assert result["ok"] is True
    assert result["deleted"] == [str(root / "comfyui")]
    assert not (root / "comfyui").exists()
    assert outside.read_text(encoding="utf-8") == "secret"
    assert (sibling / "keep").read_text(encoding="utf-8") == "sibling"


def test_uninstall_does_not_follow_a_symlink_out_of_the_app_dir(tmp_path):
    apps = _load()
    record_path = tmp_path / "apps-installed.json"
    root = tmp_path / "apps"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("secret", encoding="utf-8")
    link = root / "comfyui"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        return
    record_path.write_text(
        json.dumps({"comfyui": {"installed_by": "apps"}}),
        encoding="utf-8",
    )
    catalog = [
        {
            "id": "comfyui",
            "name": "ComfyUI",
            "group": "Creative and technical",
            "license": "GPL",
            "description": "Image generation on the 3090.",
            "installer": "test-only",
        }
    ]
    result = apps.uninstall_app(
        "comfyui", record_path=record_path, install_root=root, catalog=catalog
    )
    assert (outside / "keep").read_text(encoding="utf-8") == "secret"
    assert str(outside) not in result["deleted"]
    assert str(link) not in "".join(result["deleted"])


def test_ui_refuses_a_successful_install_without_the_server_flag():
    js = JS.read_text(encoding="utf-8")
    assert 'fetch("/api/apps/" + action' in js
    assert "j.installed === true" in js
    assert "No installer yet. This app was not installed." in js
    assert "Nothing was removed." in js
    gateway = GATEWAY.read_text(encoding="utf-8")
    assert 'path == "/api/apps"' in gateway
    assert '"/api/apps/install"' in gateway
    assert '"/api/apps/uninstall"' in gateway
    source = APPS.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "os.system" not in source
