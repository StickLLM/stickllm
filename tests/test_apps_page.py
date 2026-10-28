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
    assert 'target="stickllm-agent-zero"' in side
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
    assert "Office" in names and "ONLYOFFICE Docs" not in names
    assert not any("whisper" in name.lower() or "kitten" in name.lower() for name in names)

    html = HTML.read_text(encoding="utf-8")
    listing = html.split('id="appsList"', 1)[1].split('id="settings"', 1)[0]
    assert listing.find("Agent Zero") < listing.find("ONLYOFFICE")
    assert listing.find('id="agentCatalogInstall"') < listing.find('data-app="onlyoffice"')
    assert ">Install Agent Zero</button>" in listing
    agent_row = listing.split('id="agentCatalogRow"', 1)[1].split("</section>", 1)[0]
    assert "Not available yet" not in agent_row
    assert "whisper" not in listing.lower()
    for app in apps.CATALOG:
        if apps.is_blocked(app["id"]):
            assert f'data-app="{app["id"]}"' not in listing  # blocked in v0.5.3
            continue
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
        assert result["state"] == ("blocked" if apps.is_blocked(app["id"]) else "not_available")
        if apps.is_blocked(app["id"]):
            assert result["error"] == "blocked_app" and "Nothing was installed" in result["message"]
        else:
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
            "id": "demo-app",
            "name": "ComfyUI",
            "group": "Creative and technical",
            "license": "GPL",
            "description": "Image generation on the 3090.",
            "installer": "test-only",
        }
    ]
    installed = apps.install_app(
        "demo-app", record_path=record_path, install_root=root, catalog=catalog
    )
    assert installed["ok"] is True
    assert installed["installed"] is True
    assert (root / "demo-app").is_dir()
    sibling = root / "other"
    sibling.mkdir()
    (sibling / "keep").write_text("sibling", encoding="utf-8")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["demo-app"]["paths"] = [str(outside), str(sibling)]
    record_path.write_text(json.dumps(record), encoding="utf-8")
    result = apps.uninstall_app(
        "demo-app", record_path=record_path, install_root=root, catalog=catalog
    )
    assert result["ok"] is True
    assert result["deleted"] == [str(root / "demo-app")]
    assert not (root / "demo-app").exists()
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


def _requirement_table(text: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    started = False
    for line in text.splitlines():
        if line.startswith("| id |"):
            started = True
            continue
        if not started:
            continue
        if not line.startswith("|"):
            break
        if not line.replace("|", "").replace("-", "").replace(":", "").strip():
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 6:
            continue
        rows[cells[0]] = cells
    return rows


def test_catalog_cards_show_requirements_and_low_disk_still_installs(tmp_path):
    apps = _load()
    html = HTML.read_text(encoding="utf-8")
    menu = html.split('id="appsMenu"', 1)[1]
    assert "solitaire" not in menu.lower()
    listing = html.split('id="appsList"', 1)[1].split('id="settings"', 1)[0]
    doc_rows = _requirement_table(DOC.read_text(encoding="utf-8"))
    assert set(doc_rows) == {app["id"] for app in apps.CATALOG} | {"agent-zero"}
    for app in apps.CATALOG:
        for field in ("disk_gb", "ram_gb", "vram_gb", "gpu", "note"):
            assert field in app
        assert app["gpu"] in {"none", "optional", "required"}
        assert "min" in app["ram_gb"] and "recommended" in app["ram_gb"]
        line = apps.requirement_line(app)
        assert "Disk" in line and "RAM" in line and "GPU:" in line and "approx." in line
        assert "(measured)" not in line
        if apps.is_blocked(app["id"]):
            assert f'data-app="{app["id"]}"' not in listing  # blocked in v0.5.3
        else:
            assert line in listing
            if app["note"]:
                assert app["note"] in listing
        row = doc_rows[app["id"]]
        vram = app["vram_gb"]
        vram_cell = apps.fmt_gb(vram) if isinstance(vram, (int, float)) else str(vram)
        assert row[1] == apps.fmt_gb(app["disk_gb"])
        assert row[2] == f"{apps.fmt_gb(app['ram_gb']['min'])} / {apps.fmt_gb(app['ram_gb']['recommended'])}"
        assert row[3] == vram_cell
        assert row[4] == app["gpu"]
        assert row[5] == app["note"]
    agent_line = apps.requirement_line(apps.AGENT_ZERO)
    assert "Disk 4 GB (measured)" in agent_line
    assert "RAM" in agent_line and "GPU:" in agent_line and "approx." in agent_line
    assert agent_line in listing
    assert listing.find("Agent Zero") < listing.find("ONLYOFFICE")
    assert ">Install Agent Zero</button>" in listing
    assert doc_rows["agent-zero"][1] == "4 (measured)"
    assert "0 or 1-2" in apps.requirement_line(apps.find_app("immich"))
    assert "8 / 12-24" in apps.requirement_line(apps.find_app("comfyui"))
    text = DOC.read_text(encoding="utf-8")
    assert apps.STARTER_FOOTPRINT in text
    assert "After the next test boot" in text
    assert "`du`" in text
    assert "docker stats" in text
    js = JS.read_text(encoding="utf-8")
    assert "VRAM is unavailable" in js
    assert "You can still install." in js
    assert "memory_total_mib" in js
    vram_fn = js.split("function freeVramLabel", 1)[1].split("function paintResourceWarnings", 1)[0]
    assert "hwInfo" not in vram_fn
    agent = js.split("async function installAgent", 1)[1].split("async function showApps", 1)[0]
    assert "if (warn) toast(warn);" in agent
    assert 'fetch("/api/agent/install"' in agent
    catalog = [
        {
            "id": "demo-app",
            "name": "ComfyUI",
            "group": "Creative and technical",
            "license": "GPL",
            "description": "Image generation on the 3090.",
            "installer": "test-only",
            "disk_gb": 8,
            "ram_gb": {"min": 8, "recommended": 16},
            "vram_gb": "8 / 12-24",
            "gpu": "required",
            "note": "models extra",
        }
    ]
    low = apps.install_app(
        "demo-app",
        record_path=tmp_path / "low.json",
        install_root=tmp_path / "low",
        catalog=catalog,
        resources={"free_disk_gb": 1, "ram_gb": 64},
    )
    assert low["ok"] is True
    assert low["installed"] is True
    assert low["warning"]
    assert "You can still install." in low["warning"]
    assert "below" in low["warning"]
    assert (tmp_path / "low" / "demo-app").is_dir()
    plenty = apps.install_app(
        "demo-app",
        record_path=tmp_path / "ok.json",
        install_root=tmp_path / "ok",
        catalog=catalog,
        resources={"free_disk_gb": 100, "ram_gb": 64},
    )
    assert plenty["ok"] is True
    assert plenty["installed"] is True
    assert plenty["warning"] == ""
    assert apps.resource_warning(catalog[0], {"free_disk_gb": None, "ram_gb": None}) == ""


def test_ui_refuses_a_successful_install_without_the_server_flag():
    js = JS.read_text(encoding="utf-8")
    assert 'fetch("/api/apps/" + action' in js
    assert "j.installed === true" in js
    assert "No installer yet. This app was not installed." in js
    assert "Nothing was removed." in js
    assert 'fetch("/api/agent/install"' in js
    assert "agentCatalogInstall" in js
    assert "/api/agent/uninstall" not in js
    assert "agentCatalogMsg" in js
    gateway = GATEWAY.read_text(encoding="utf-8")
    assert 'path == "/api/apps"' in gateway
    assert '"/api/apps/install"' in gateway
    assert '"/api/apps/uninstall"' in gateway
    source = APPS.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "os.system" not in source
    assert "persistent_install_root" in source
    assert 'INSTALL_ROOT = Path(os.environ.get("STICKLLM_APPS_ROOT"' not in source


def _marker_catalog():
    return (
        {
            "id": "persist-probe",
            "name": "Persist probe",
            "installer": "marker",
        },
    )


def test_install_lands_on_the_host_ssd_apps_dir(tmp_path, monkeypatch):
    host = tmp_path / "host"
    models = host / "disk" / "models"
    models.mkdir(parents=True)
    mounts = tmp_path / "mounts"
    mounts.write_text(f"ext4 {host} ext4 rw 0 0\n", encoding="utf-8")
    models_file = tmp_path / "models-dir.json"
    models_file.write_text(json.dumps({"path": str(models)}), encoding="utf-8")
    monkeypatch.setenv("STICKLLM_HOST_MNT", str(host))
    monkeypatch.setenv("STICKLLM_MOUNTS_FILE", str(mounts))
    monkeypatch.setenv("STICKLLM_MODELS_DIR_FILE", str(models_file))
    monkeypatch.setenv("STICKLLM_VAULT_MNT", str(tmp_path / "vault"))
    monkeypatch.setenv("STICKLLM_DATA_MNT", str(tmp_path / "data"))
    monkeypatch.delenv("STICKLLM_APPS_ROOT", raising=False)
    monkeypatch.delenv("STICKLLM_APPS_RECORD", raising=False)
    monkeypatch.delenv("STICKLLM_SSD_APPS", raising=False)
    monkeypatch.delenv("STICKLLM_MODELS_DIR", raising=False)
    apps = _load()
    result = apps.install_app("persist-probe", catalog=_marker_catalog())
    assert result["ok"] is True
    assert result["root"] == str(host / "disk" / "apps")
    assert (host / "disk" / "apps" / "persist-probe").is_dir()
    record = json.loads((host / "disk" / "apps-installed.json").read_text(encoding="utf-8"))
    assert record["persist-probe"]["installed_by"] == "apps"
    assert not str(result["root"]).endswith("/var/lib/stickllm/apps")


def test_install_falls_back_to_data_then_vault_and_refuses_ram(tmp_path, monkeypatch):
    data = tmp_path / "data"
    vault = tmp_path / "vault"
    data.mkdir()
    vault.mkdir()
    mounts = tmp_path / "mounts"
    mounts.write_text(f"ext4 {data} ext4 rw 0 0\n", encoding="utf-8")
    missing_models = tmp_path / "no-models.json"
    monkeypatch.setenv("STICKLLM_HOST_MNT", str(tmp_path / "host"))
    monkeypatch.setenv("STICKLLM_MOUNTS_FILE", str(mounts))
    monkeypatch.setenv("STICKLLM_MODELS_DIR_FILE", str(missing_models))
    monkeypatch.setenv("STICKLLM_DATA_MNT", str(data))
    monkeypatch.setenv("STICKLLM_VAULT_MNT", str(vault))
    monkeypatch.delenv("STICKLLM_APPS_ROOT", raising=False)
    monkeypatch.delenv("STICKLLM_APPS_RECORD", raising=False)
    monkeypatch.delenv("STICKLLM_SSD_APPS", raising=False)
    monkeypatch.delenv("STICKLLM_MODELS_DIR", raising=False)
    apps = _load()
    on_data = apps.install_app("persist-probe", catalog=_marker_catalog())
    assert on_data["ok"] is True
    assert on_data["root"] == str(data / "apps")
    mounts.write_text(f"ext4 {vault} ext4 rw 0 0\n", encoding="utf-8")
    on_vault = apps.install_app("persist-probe", catalog=_marker_catalog())
    assert on_vault["root"] == str(vault / "apps")
    mounts.write_text("", encoding="utf-8")
    refused = apps.install_app("persist-probe", catalog=_marker_catalog())
    assert refused["ok"] is False
    assert refused["error"] == "no_durable_disk"
    assert not (Path("/var/lib/stickllm/apps") / "persist-probe").exists()
