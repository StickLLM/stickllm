#!/usr/bin/env python3
"""Companion-app catalog for the StickLLM Apps page.

The placeholder rows match docs/APPS.md except Agent Zero. Agent Zero is a
real install on the Apps page and calls ``stickllm-agent install``, the same
action as Settings. It is not one of these placeholder rows, so this module
must not report it installed or delete its image. whisper.cpp and KittenTTS
are baked into the image, not companion apps.

No placeholder catalog app has an installer yet. Install must not claim
success, and uninstall must not delete anything this page did not install.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

# /var/lib/stickllm/apps is on the live overlay and disappears at reboot.
# Catalog installs go to a durable disk instead. STICKLLM_APPS_ROOT and
# STICKLLM_APPS_RECORD still override that for tests and a manual path.
DATA_MNT = Path(os.environ.get("STICKLLM_DATA_MNT", "/mnt/stickllm-data"))
VAULT_MNT = Path(os.environ.get("STICKLLM_VAULT_MNT", "/var/lib/stickllm/vault"))
RAM_INSTALL_ROOT = Path("/var/lib/stickllm/apps")

# installer is None until that app has a real installer. A truthy value is only
# a flag for tests of the uninstall scope. This module never runs a command.
CATALOG: tuple[dict, ...] = (
    {
        "id": "onlyoffice",
        "name": "Office",
        "group": "Core (starter apps)",
        "license": "AGPL",
        "description": "Documents, spreadsheets, and slides (ONLYOFFICE). The bot can edit open files live.",
        "disk_gb": 3,
        "ram_gb": {"min": 2, "recommended": 4},
        "vram_gb": 0,
        "gpu": "none",
        "note": "Heavy for an office suite; 4 GB RAM for smooth editing",
        "installer": None,
    },
    {
        "id": "paperless-ngx",
        "name": "Paperless-ngx",
        "group": "Core (starter apps)",
        "license": "GPL",
        "description": "Scans and files receipts and documents, with text recognition and tagging, through a REST API.",
        "disk_gb": 1.5,
        "ram_gb": {"min": 1, "recommended": 2},
        "vram_gb": 0,
        "gpu": "none",
        "note": "+ Redis; OCR spikes RAM/CPU; documents stored extra",
        "hidden": "Needs Redis plus OCR worker containers; StickLLM add-ons are one locked-down container each.",
        "installer": None,
    },
    {
        "id": "snappymail",
        "name": "SnappyMail",
        "group": "Core (starter apps)",
        "license": "AGPL",
        "description": "Webmail over IMAP and SMTP, so the bot can triage and draft. Sending is the user\u2019s click.",
        "disk_gb": 0.1,
        "ram_gb": {"min": 0.1, "recommended": 0.25},
        "vram_gb": 0,
        "gpu": "none",
        "note": "Very light",
        "hidden": "Webmail needs outbound IMAP/SMTP, and add-on containers have no network by design.",
        "installer": None,
    },
    {
        "id": "radicale",
        "name": "Radicale",
        "group": "Core (starter apps)",
        "license": "GPL",
        "description": "Calendar and contacts (CalDAV and CardDAV), very light.",
        "disk_gb": 0.05,
        "ram_gb": {"min": 0.05, "recommended": 0.1},
        "vram_gb": 0,
        "gpu": "none",
        "note": "Very light",
        "installer": None,
    },
    {
        "id": "trilium",
        "name": "Trilium Notes",
        "group": "Core (starter apps)",
        "license": "AGPL",
        "description": "Notes and a knowledge base with an API.",
        "disk_gb": 0.5,
        "ram_gb": {"min": 0.25, "recommended": 0.5},
        "vram_gb": 0,
        "gpu": "none",
        "note": "",
        "installer": None,
    },
    {
        "id": "vikunja",
        "name": "Vikunja",
        "group": "Productivity",
        "license": "AGPL",
        "description": "Tasks and projects.",
        "disk_gb": 0.15,
        "ram_gb": {"min": 0.1, "recommended": 0.25},
        "vram_gb": 0,
        "gpu": "none",
        "note": "",
        "installer": None,
    },
    {
        "id": "actual",
        "name": "Actual Budget",
        "group": "Productivity",
        "license": "MIT",
        "description": "Budgeting and bank CSV import.",
        "disk_gb": 0.3,
        "ram_gb": {"min": 0.15, "recommended": 0.3},
        "vram_gb": 0,
        "gpu": "none",
        "note": "",
        "installer": None,
    },
    {
        "id": "immich",
        "name": "Immich",
        "group": "Productivity",
        "license": "AGPL",
        "description": "Photos, with search that runs on your local GPU.",
        "disk_gb": 5,
        "ram_gb": {"min": 6, "recommended": 8},
        "vram_gb": "0 or 1-2",
        "gpu": "optional",
        "note": "Server + ML + Postgres + Redis; photo library stored extra; GPU ML search uses ~1-2 GB VRAM",
        "hidden": "Needs Postgres, Redis and a machine-learning container (four containers) plus a GPU for search.",
        "installer": None,
    },
    {
        "id": "searxng",
        "name": "SearXNG",
        "group": "Productivity",
        "license": "AGPL",
        "description": "Private web search for the agent, which can run over Tor.",
        "disk_gb": 0.2,
        "ram_gb": {"min": 0.25, "recommended": 0.5},
        "vram_gb": 0,
        "gpu": "none",
        "note": "+ Valkey/Redis; Tor adds ~0.1 GB",
        "hidden": "Already built into Agent Zero (its own private search); a second copy adds nothing.",
        "installer": None,
    },
    {
        "id": "matrix",
        "name": "Matrix (Conduit + Element)",
        "group": "Communications",
        "license": "Apache",
        "description": "Encrypted chat and calls, with bridges to other messengers.",
        "disk_gb": 0.2,
        "ram_gb": {"min": 0.25, "recommended": 0.5},
        "vram_gb": 0,
        "gpu": "none",
        "note": "Conduit + Element web; bridges add more",
        "hidden": "Federation and bridges need internet and LAN access; add-on containers have no network.",
        "installer": None,
    },
    {
        "id": "simplex",
        "name": "SimpleX Chat",
        "group": "Communications",
        "license": "AGPL",
        "description": "Anonymous messaging with no IDs, with self-hosted relays.",
        "disk_gb": 0.1,
        "ram_gb": {"min": 0.1, "recommended": 0.25},
        "vram_gb": 0,
        "gpu": "none",
        "note": "SMP/XFTP relay servers; clients are phone/desktop apps",
        "hidden": "Relay servers only, used from phone and desktop apps; nothing to open in a browser tab.",
        "installer": None,
    },
    {
        "id": "jitsi",
        "name": "Jitsi Meet",
        "group": "Communications",
        "license": "Apache",
        "description": "Browser video calls.",
        "disk_gb": 2,
        "ram_gb": {"min": 2, "recommended": 4},
        "vram_gb": 0,
        "gpu": "none",
        "note": "4 containers incl. Java video bridge; CPU heavy with many callers",
        "hidden": "Four containers including the Java video bridge, and calls need LAN/internet UDP.",
        "installer": None,
    },
    {
        "id": "onionshare",
        "name": "OnionShare",
        "group": "Communications",
        "license": "GPL",
        "description": "Anonymous file sharing and a drop box over Tor.",
        "disk_gb": 0.1,
        "ram_gb": {"min": 0.1, "recommended": 0.25},
        "vram_gb": 0,
        "gpu": "none",
        "note": "CLI + Tor",
        "hidden": "Command line plus Tor, which needs internet; no web app to open.",
        "installer": None,
    },
    {
        "id": "postiz",
        "name": "Postiz",
        "group": "Publishing",
        "license": "AGPL",
        "description": "Posts to many social networks at once, with an API.",
        "disk_gb": 2.5,
        "ram_gb": {"min": 2, "recommended": 4},
        "vram_gb": 0,
        "gpu": "none",
        "note": "Node + Postgres + Redis",
        "hidden": "Node, Postgres and Redis, and posting needs internet access to the social networks.",
        "installer": None,
    },
    {
        "id": "opentimestamps",
        "name": "OpenTimestamps + a signing tool",
        "group": "Publishing",
        "license": "LGPL or MIT",
        "description": "Proof that a published file hasn\u2019t been changed.",
        "disk_gb": 0.05,
        "ram_gb": {"min": 0.05, "recommended": 0.05},
        "vram_gb": 0,
        "gpu": "none",
        "note": "Client + minisign; negligible",
        "hidden": "Command-line tools with no web app; timestamping needs internet calendars.",
        "installer": None,
    },
    {
        "id": "comfyui",
        "name": "ComfyUI",
        "group": "Creative and technical",
        "license": "GPL",
        "description": "Image generation on the 3090.",
        "disk_gb": 8,
        "ram_gb": {"min": 8, "recommended": 16},
        "vram_gb": "8 / 12-24",
        "gpu": "required",
        "note": "PyTorch+CUDA install; models extra (SDXL ~7 GB, Flux 12-24 GB); unload or shrink the LLM to free VRAM",
        "hidden": "Needs CUDA, PyTorch and the GPU the model is using; not containerised for the stick yet.",
        "installer": None,
    },
    {
        "id": "code-server-jupyter",
        "name": "code-server and Jupyter",
        "group": "Creative and technical",
        "license": "MIT and BSD",
        "description": "Coding and data analysis.",
        "disk_gb": 1.5,
        "ram_gb": {"min": 1, "recommended": 2},
        "vram_gb": 0,
        "gpu": "optional",
        "note": "GPU only if notebooks use it",
        "hidden": "Not packaged and security-reviewed for the stick yet (a full terminal and package installs).",
        "installer": None,
    },
    {
        "id": "n8n",
        "name": "n8n",
        "group": "Creative and technical",
        "license": "fair-code (not OSI open source)",
        "description": "Automations. Prefer an OSI-friendly stack unless license posture is explicit.",
        "disk_gb": 0.5,
        "ram_gb": {"min": 0.5, "recommended": 1},
        "vram_gb": 0,
        "gpu": "none",
        "note": "Pick n8n or Node-RED, not both by default",
        "hidden": "Fair-code licence (not OSI open source) and it duplicates Node-RED, which ships.",
        "installer": None,
    },
    {
        "id": "node-red",
        "name": "Node-RED",
        "group": "Creative and technical",
        "license": "Apache",
        "description": "Flow-based automation. Flows can run code; no palette installs, no internet.",
        "disk_gb": 0.3,
        "ram_gb": {"min": 0.2, "recommended": 0.5},
        "vram_gb": 0,
        "gpu": "none",
        "note": "",
        "installer": None,
    },
)


# Agent Zero is a real install on the Apps page, not a placeholder row.
# Disk is the one catalog figure measured on the stick. RAM stays an estimate.
AGENT_ZERO = {
    "id": "agent-zero",
    "name": "Agent Zero",
    "group": "Agent",
    "license": "MIT",
    "description": "The operator that drives the above through each app's tool layer.",
    "disk_gb": 4,
    "disk_measured": True,
    "ram_gb": {"min": 2, "recommended": 4},
    "vram_gb": 0,
    "gpu": "none",
    "note": "Uses llama-server for the model; Kokoro TTS on CPU ~0.5-1 GB RAM; needs a few GB free while unpacking",
    "installer": None,
}

# Measured on the stick: base image plus the desktop starters, with a model loaded.
STARTER_FOOTPRINT = "Base StickLLM with starter apps: ~25 MB extra, <3 GB RAM with a model loaded (measured on the stick)."


def find_app(app_id: str, catalog: tuple | list | None = None) -> dict | None:
    rows = CATALOG if catalog is None else catalog
    for app in rows:
        if app.get("id") == app_id:
            return app
    return None


def fmt_gb(value) -> str:
    number = float(value)
    if number == int(number):
        return str(int(number))
    return f"{number:.4f}".rstrip("0").rstrip(".")


def gpu_phrase(app: dict) -> str:
    """Keep a VRAM range intact. A single number would drop the note."""
    gpu = str(app.get("gpu") or "none")
    vram = app.get("vram_gb")
    if isinstance(vram, str) and vram.strip() and vram.strip() != "0":
        if gpu == "none":
            return "none"
        return f"{gpu} {vram} GB"
    if gpu == "optional":
        return "optional"
    if gpu == "required":
        return "required"
    return "none"


def requirement_line(app: dict) -> str:
    """Card line. Minimum RAM is the main figure. Estimates stay marked approx."""
    disk = f"Disk {fmt_gb(app['disk_gb'])} GB"
    if app.get("disk_measured"):
        disk += " (measured)"
    ram = app.get("ram_gb") or {}
    minimum = ram.get("min") if isinstance(ram, dict) else None
    recommended = ram.get("recommended") if isinstance(ram, dict) else None
    if minimum is None:
        ram_text = "RAM"
    elif recommended is None or float(minimum) == float(recommended):
        ram_text = f"RAM {fmt_gb(minimum)} GB"
    else:
        ram_text = f"RAM {fmt_gb(minimum)} GB ({fmt_gb(recommended)} GB recommended)"
    line = f"{disk} · {ram_text} · GPU: {gpu_phrase(app)}"
    # Agent Zero's disk is measured. Its RAM is still an estimate, so the line
    # keeps approx. Every other catalog app is an estimate end to end.
    line += " · approx."
    return line


def _as_float(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def host_ssd_path() -> Path | None:
    """Mounted host SSD, or the recorded apps directory. A bare mountpoint does not count."""
    override = os.environ.get("STICKLLM_SSD_APPS", "").strip()
    if override:
        path = Path(override)
        try:
            if path.exists() and not path.is_symlink():
                return path
        except OSError:
            return None
    host = Path(os.environ.get("STICKLLM_HOST_MNT", "/mnt/stickllm-host"))
    try:
        mounted = os.path.ismount(host)
    except OSError:
        mounted = False
    if not mounted:
        mounts_file = Path(os.environ.get("STICKLLM_MOUNTS_FILE", "/proc/mounts"))
        try:
            text = mounts_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        target = str(host)
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].replace("\\040", " ") == target:
                mounted = True
                break
    if not mounted:
        return None
    try:
        if host.exists() and not host.is_symlink():
            return host
    except OSError:
        return None
    return None


def read_host_resources() -> dict:
    """Free host-SSD gigabytes and total RAM gigabytes. Missing numbers stay None."""
    free_disk = None
    path = host_ssd_path()
    if path is not None:
        try:
            free_disk = shutil.disk_usage(path).free / (1024 ** 3)
        except OSError:
            free_disk = None
    ram = None
    meminfo = Path(os.environ.get("STICKLLM_MEMINFO", "/proc/meminfo"))
    try:
        text = meminfo.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    for line in text.splitlines():
        if not line.startswith("MemTotal:"):
            continue
        parts = line.split()
        try:
            ram = int(parts[1]) / (1024 ** 2)
        except (IndexError, ValueError):
            ram = None
        break
    return {"free_disk_gb": free_disk, "ram_gb": ram}


def resource_warning(app: dict, resources: dict | None = None) -> str:
    """Warn when free host SSD or total RAM is under the minimum. This does not block install."""
    disk_min = _as_float(app.get("disk_gb")) if "disk_gb" in app else None
    ram = app.get("ram_gb")
    ram_min = _as_float(ram.get("min")) if isinstance(ram, dict) else None
    if disk_min is None and ram_min is None:
        return ""
    stats = read_host_resources() if resources is None else resources
    if not isinstance(stats, dict):
        stats = {}
    parts: list[str] = []
    free = _as_float(stats.get("free_disk_gb"))
    total = _as_float(stats.get("ram_gb"))
    name = str(app.get("name") or app.get("id") or "This app")
    if disk_min is not None and free is not None and free < disk_min:
        parts.append(
            f"Host SSD has about {fmt_gb(free)} GB free, below the {fmt_gb(disk_min)} GB minimum for {name}."
        )
    if ram_min is not None and total is not None and total < ram_min:
        parts.append(
            f"This machine has about {fmt_gb(total)} GB RAM, below the {fmt_gb(ram_min)} GB minimum for {name}."
        )
    if not parts:
        return ""
    return " ".join(parts) + " You can still install."


def _path_mounted(path: Path) -> bool:
    """True when path is a real mount. A plain directory does not count."""
    mounts = os.environ.get("STICKLLM_MOUNTS_FILE", "").strip()
    if mounts:
        try:
            text = Path(mounts).read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        target = str(path)
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].replace("\\040", " ") == target:
                return True
        return False
    try:
        return os.path.ismount(path)
    except OSError:
        return False


def _ssd_apps_dir() -> Path | None:
    """Host-SSD apps folder beside the recorded models directory, if any."""
    import importlib.util

    path = Path(__file__).resolve().with_name("stickllm_files.py")
    spec = importlib.util.spec_from_file_location("stickllm_files_apps_root", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    found = mod.ssd_apps_dir()
    return found if isinstance(found, Path) else None


def persistent_install_root() -> Path | None:
    """Durable catalog directory. Never the RAM overlay under /var/lib/stickllm/apps.

    Order: the host SSD apps folder beside models, then the USB DATA partition,
    then the unlocked vault. docs/APPS.md names DATA and the vault; the host
    SSD folder is the same durable disk the file manager already calls SSD apps.
    """
    override = os.environ.get("STICKLLM_APPS_ROOT", "").strip()
    if override:
        return Path(override)
    ssd = _ssd_apps_dir()
    if ssd is not None and ssd != RAM_INSTALL_ROOT:
        return ssd
    if _path_mounted(DATA_MNT):
        return DATA_MNT / "apps"
    if _path_mounted(VAULT_MNT):
        return VAULT_MNT / "apps"
    return None


def resolve_store(
    record_path: Path | None = None,
    install_root: Path | None = None,
) -> tuple[Path, Path | None]:
    """Record file and install directory. The directory is None when no disk is mounted."""
    if install_root is not None:
        root: Path | None = Path(install_root)
    else:
        root = persistent_install_root()
    if record_path is not None:
        path = Path(record_path)
    else:
        override = os.environ.get("STICKLLM_APPS_RECORD", "").strip()
        if override:
            path = Path(override)
        elif root is not None:
            path = Path(root).parent / "apps-installed.json"
        else:
            path = Path("/run/stickllm/apps-installed.json")
    return path, root


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
    public = {
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
    for key in ("disk_gb", "ram_gb", "vram_gb", "gpu", "note"):
        if key in app:
            public[key] = app[key]
    if "disk_gb" in app and isinstance(app.get("ram_gb"), dict) and app.get("gpu"):
        public["requirement"] = requirement_line(app)
        public["disk_measured"] = bool(app.get("disk_measured"))
    return public


def catalog_document(record_path: Path | None = None, catalog: tuple | list | None = None) -> dict:
    path, _root = resolve_store(record_path, None)
    rows = CATALOG if catalog is None else catalog
    record = load_record(path)
    # Rows with a "hidden" reason have no working installer on the stick and are
    # left off the Apps page (v0.5.3). The reasons are listed for docs and agents.
    apps = [_public_app(app, record) for app in rows if not app.get("hidden")]
    hidden = [{"id": app["id"], "name": app["name"], "reason": app["hidden"]} for app in rows if app.get("hidden")]
    return {
        "ok": True,
        "note": "Install it first, then use it to install and configure these apps.",
        "installed_count": sum(1 for app in apps if app["installed"]),
        "apps": apps,
        "hidden": hidden,
        "agent_zero": {
            "id": AGENT_ZERO["id"],
            "name": AGENT_ZERO["name"],
            "disk_gb": AGENT_ZERO["disk_gb"],
            "disk_measured": True,
            "ram_gb": AGENT_ZERO["ram_gb"],
            "vram_gb": AGENT_ZERO["vram_gb"],
            "gpu": AGENT_ZERO["gpu"],
            "note": AGENT_ZERO["note"],
            "requirement": requirement_line(AGENT_ZERO),
        },
        "resources": read_host_resources(),
        "starter_footprint": STARTER_FOOTPRINT,
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
    resources: dict | None = None,
) -> dict:
    """Install one catalog app. Apps with no installer stay not installed.

    The directory is the host SSD, USB DATA, or the unlocked vault.
    /var/lib/stickllm/apps is not used: that path is the live overlay.
    """
    path, root = resolve_store(record_path, install_root)
    if root is None:
        return _fail(
            "No data partition or unlocked vault is available. Nothing was installed.",
            error="no_durable_disk",
            state="not_installed",
        )
    if Path(root) == RAM_INSTALL_ROOT and not os.environ.get("STICKLLM_APPS_ROOT", "").strip():
        return _fail(
            "Refusing to install onto the live overlay. Nothing was installed.",
            error="no_durable_disk",
            state="not_installed",
        )
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
    warning = resource_warning(app, resources)
    record = load_record(path)
    record[app["id"]] = {"installed_by": "apps"}
    own.mkdir(parents=True, exist_ok=True)
    save_record(path, record)
    message = f"{app['name']} is installed."
    if warning:
        message = f"{message} {warning}"
    return {
        "ok": True,
        "installed": True,
        "state": "installed",
        "error": "",
        "message": message,
        "warning": warning,
        "deleted": [],
        "root": str(root),
        "record": str(path),
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
    path, root = resolve_store(record_path, install_root)
    if root is None:
        return _fail(
            "No data partition or unlocked vault is available. Nothing was removed.",
            error="no_durable_disk",
            state="not_installed",
        )
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
