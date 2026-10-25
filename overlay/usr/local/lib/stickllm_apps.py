#!/usr/bin/env python3
"""Companion-app catalog for the StickLLM Apps page.

The rows match docs/APPS.md. Agent Zero is not a row: it keeps its own
sidebar entry and ``stickllm-agent install``. whisper.cpp and KittenTTS are
baked into the image, not companion apps.

No catalog app has an installer yet. Install must not claim success, and
uninstall must not delete anything this page did not install.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

RECORD_PATH = Path(os.environ.get("STICKLLM_APPS_RECORD", "/var/lib/stickllm/apps-installed.json"))
INSTALL_ROOT = Path(os.environ.get("STICKLLM_APPS_ROOT", "/var/lib/stickllm/apps"))

# installer is None until that app has a real installer. A truthy value is only
# a flag for tests of the uninstall scope. This module never runs a command.
CATALOG: tuple[dict, ...] = (
    {
        "id": "onlyoffice",
        "name": "ONLYOFFICE Docs",
        "group": "Core (starter apps)",
        "license": "AGPL",
        "description": "Documents, spreadsheets, and slides. The bot can edit open files live.",
        "installer": None,
    },
    {
        "id": "paperless-ngx",
        "name": "Paperless-ngx",
        "group": "Core (starter apps)",
        "license": "GPL",
        "description": "Scans and files receipts and documents, with text recognition and tagging, through a REST API.",
        "installer": None,
    },
    {
        "id": "snappymail",
        "name": "SnappyMail",
        "group": "Core (starter apps)",
        "license": "AGPL",
        "description": "Webmail over IMAP and SMTP, so the bot can triage and draft. Sending is the user\u2019s click.",
        "installer": None,
    },
    {
        "id": "radicale",
        "name": "Radicale",
        "group": "Core (starter apps)",
        "license": "GPL",
        "description": "Calendar and contacts (CalDAV and CardDAV), very light.",
        "installer": None,
    },
    {
        "id": "trilium",
        "name": "Trilium Notes",
        "group": "Core (starter apps)",
        "license": "AGPL",
        "description": "Notes and a knowledge base with an API.",
        "installer": None,
    },
    {
        "id": "vikunja",
        "name": "Vikunja",
        "group": "Productivity",
        "license": "AGPL",
        "description": "Tasks and projects.",
        "installer": None,
    },
    {
        "id": "actual",
        "name": "Actual Budget",
        "group": "Productivity",
        "license": "MIT",
        "description": "Budgeting and bank CSV import.",
        "installer": None,
    },
    {
        "id": "immich",
        "name": "Immich",
        "group": "Productivity",
        "license": "AGPL",
        "description": "Photos, with search that runs on your local GPU.",
        "installer": None,
    },
    {
        "id": "searxng",
        "name": "SearXNG",
        "group": "Productivity",
        "license": "AGPL",
        "description": "Private web search for the agent, which can run over Tor.",
        "installer": None,
    },
    {
        "id": "matrix",
        "name": "Matrix (Conduit + Element)",
        "group": "Communications",
        "license": "Apache",
        "description": "Encrypted chat and calls, with bridges to other messengers.",
        "installer": None,
    },
    {
        "id": "simplex",
        "name": "SimpleX Chat",
        "group": "Communications",
        "license": "AGPL",
        "description": "Anonymous messaging with no IDs, with self-hosted relays.",
        "installer": None,
    },
    {
        "id": "jitsi",
        "name": "Jitsi Meet",
        "group": "Communications",
        "license": "Apache",
        "description": "Browser video calls.",
        "installer": None,
    },
    {
        "id": "onionshare",
        "name": "OnionShare",
        "group": "Communications",
        "license": "GPL",
        "description": "Anonymous file sharing and a drop box over Tor.",
        "installer": None,
    },
    {
        "id": "postiz",
        "name": "Postiz",
        "group": "Publishing",
        "license": "AGPL",
        "description": "Posts to many social networks at once, with an API.",
        "installer": None,
    },
    {
        "id": "opentimestamps",
        "name": "OpenTimestamps + a signing tool",
        "group": "Publishing",
        "license": "LGPL or MIT",
        "description": "Proof that a published file hasn\u2019t been changed.",
        "installer": None,
    },
    {
        "id": "comfyui",
        "name": "ComfyUI",
        "group": "Creative and technical",
        "license": "GPL",
        "description": "Image generation on the 3090.",
        "installer": None,
    },
    {
        "id": "code-server-jupyter",
        "name": "code-server and Jupyter",
        "group": "Creative and technical",
        "license": "MIT and BSD",
        "description": "Coding and data analysis.",
        "installer": None,
    },
    {
        "id": "n8n",
        "name": "n8n",
        "group": "Creative and technical",
        "license": "fair-code (not OSI open source)",
        "description": "Automations. Prefer an OSI-friendly stack unless license posture is explicit.",
        "installer": None,
    },
    {
        "id": "node-red",
        "name": "Node-RED",
        "group": "Creative and technical",
        "license": "Apache",
        "description": "OSI-friendly automation alternative under consideration instead of (or beside) n8n.",
        "installer": None,
    },
)


def find_app(app_id: str, catalog: tuple | list | None = None) -> dict | None:
    rows = CATALOG if catalog is None else catalog
    for app in rows:
        if app.get("id") == app_id:
            return app
    return None


def load_record(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_record(path: Path, record: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _marked(record: dict, app_id: str) -> bool:
    entry = record.get(app_id)
    return isinstance(entry, dict) and entry.get("installed_by") == "apps"


def _contained_app_dir(install_root: Path, app_id: str) -> Path | None:
    """The one directory uninstall may remove. None when the path leaves the root."""
    if not isinstance(app_id, str) or not app_id or app_id in {".", ".."}:
        return None
    if any(sep in app_id for sep in ("/", "\\", "\x00")):
        return None
    root = Path(install_root)
    if root.is_symlink():
        return None
    candidate = root / app_id
    if candidate.is_symlink():
        return None
    try:
        resolved_root = root.resolve()
        resolved = candidate.resolve()
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        return None
    if resolved == resolved_root or resolved.name != app_id:
        return None
    return candidate


def _public_app(app: dict, record: dict) -> dict:
    installed = bool(app.get("installer")) and _marked(record, app["id"])
    if installed:
        state, label = "installed", "Installed"
    elif not app.get("installer"):
        state, label = "not_available", "Not available yet"
    else:
        state, label = "not_installed", "Not installed"
    return {
        "id": app["id"],
        "name": app["name"],
        "group": app["group"],
        "license": app["license"],
        "description": app["description"],
        "state": state,
        "label": label,
        "installed": installed,
        "not_installed": not installed,
    }


def catalog_document(record_path: Path | None = None, catalog: tuple | list | None = None) -> dict:
    path = RECORD_PATH if record_path is None else Path(record_path)
    rows = CATALOG if catalog is None else catalog
    record = load_record(path)
    apps = [_public_app(app, record) for app in rows]
    return {
        "ok": True,
        "note": "Install it first, then use it to install and configure these apps.",
        "installed_count": sum(1 for app in apps if app["installed"]),
        "apps": apps,
    }


def _fail(message: str, *, error: str, state: str = "not_available") -> dict:
    return {
        "ok": False,
        "installed": False,
        "state": state,
        "error": error,
        "message": message,
        "deleted": [],
    }


def install_app(
    app_id: str,
    record_path: Path | None = None,
    install_root: Path | None = None,
    catalog: tuple | list | None = None,
) -> dict:
    """Install one catalog app. Apps with no installer stay not installed."""
    path = RECORD_PATH if record_path is None else Path(record_path)
    root = INSTALL_ROOT if install_root is None else Path(install_root)
    rows = CATALOG if catalog is None else catalog
    app = find_app(str(app_id or ""), rows)
    if app is None:
        return _fail(
            "That app is not in the catalog. Nothing was installed.",
            error="unknown_app",
            state="unknown",
        )
    if not app.get("installer"):
        return _fail(
            f"{app['name']} has no installer yet. It was not installed.",
            error="no_installer",
            state="not_available",
        )
    own = _contained_app_dir(root, app["id"])
    if own is None:
        return _fail(
            f"{app['name']} could not be installed. Nothing was written.",
            error="bad_path",
            state="not_installed",
        )
    record = load_record(path)
    record[app["id"]] = {"installed_by": "apps"}
    own.mkdir(parents=True, exist_ok=True)
    save_record(path, record)
    return {
        "ok": True,
        "installed": True,
        "state": "installed",
        "error": "",
        "message": f"{app['name']} is installed.",
        "deleted": [],
    }


def _remove_own_tree(path: Path) -> bool:
    if path.is_symlink() or not path.exists():
        return False
    if path.is_dir():
        shutil.rmtree(path)
        return True
    if path.is_file():
        path.unlink()
        return True
    return False


def uninstall_app(
    app_id: str,
    record_path: Path | None = None,
    install_root: Path | None = None,
    catalog: tuple | list | None = None,
) -> dict:
    """Remove one app this page installed. Other files are left alone."""
    path = RECORD_PATH if record_path is None else Path(record_path)
    root = INSTALL_ROOT if install_root is None else Path(install_root)
    rows = CATALOG if catalog is None else catalog
    app = find_app(str(app_id or ""), rows)
    if app is None:
        return _fail(
            "That app is not in the catalog. Nothing was removed.",
            error="unknown_app",
            state="unknown",
        )
    record = load_record(path)
    if not _marked(record, app["id"]) or not app.get("installer"):
        return _fail(
            f"{app['name']} was not installed from the Apps page. Nothing was removed.",
            error="not_installed_by_apps",
            state="not_available" if not app.get("installer") else "not_installed",
        )
    deleted: list[str] = []
    own = _contained_app_dir(root, app["id"])
    if own is not None and _remove_own_tree(own):
        deleted.append(str(own))
    record.pop(app["id"], None)
    save_record(path, record)
    return {
        "ok": True,
        "installed": False,
        "state": "not_installed",
        "error": "",
        "message": f"{app['name']} was uninstalled.",
        "deleted": deleted,
    }
