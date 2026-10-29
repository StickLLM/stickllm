#!/usr/bin/env python3
"""StickLLM add-ons: Tasks.md, Paisa, Trilium, Node-RED, ComfyUI.

Same rules as ONLYOFFICE Docs (stickllm_docs.py):

* the image is pinned by digest and pulled onto the host SSD docker data-root;
* everything the app writes lives in vault/addons/<id> only, so a locked
  vault means no app data on any disk;
* the container runs non-root, read-only, with no capabilities, no GPU
  (ComfyUI alone may get the NVIDIA device nodes, read-only driver libs),
  ``--log-driver none`` and tmpfs for scratch;
* the app port is published on 127.0.0.1 only; LAN browsers reach it through
  the StickLLM gateway (paired, its own TLS port per app);
* each app has its own bridge, and nft drops every packet the container
  starts: no internet, no LAN, no host, no other app.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

VAULT_MNT = Path(os.environ.get("STICKLLM_VAULT_MNT", "/var/lib/stickllm/vault"))
RUN_DIR = Path(os.environ.get("STICKLLM_RUN", "/run/stickllm"))
MOUNTS_FILE = os.environ.get("STICKLLM_MOUNTS_FILE", "")
SHARE_DIR = Path(os.environ.get("STICKLLM_ADDONS_SHARE", "/usr/local/share/stickllm/addons"))
ADDONS_REL = "addons"
NFT_TABLE = "stickllm_addons"
VAULT_LOCKED_MESSAGE = "Vault is locked. Unlock the vault to use this app; its data lives only in the vault."

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_ID_RE = re.compile(r"[a-z][a-z0-9-]{1,23}")

# Every bind source is below vault/addons/<id> (rw) or SHARE_DIR (ro, from
# the ISO). ``volumes`` lists the image's own VOLUME entries: each one must be
# covered by a bind so docker never creates an anonymous volume on the host.
APPS: dict[str, dict] = {
    # Tasks.md (MIT): kanban board stored as Markdown files. The stock
    # entrypoint runs "npm run build" as root on every start, so StickLLM
    # builds the web UI once at install (root, --network none, no mounts)
    # and commits a local wrapper image that runs node as uid 1000 on a
    # read-only root. The pin below is the upstream base image.
    "tasks-md": {
        "name": "Tasks.md",
        "tile": "Tasks",
        "octet": 12,
        "user": (1000, 1000),
        "port": 8080,
        "local_port": 8102,
        "kiosk_port": 8112,
        "tls_port": 5452,
        "dirs": ("config", "tasks"),
        "binds": (("config", "/config"), ("tasks", "/tasks")),
        "share": (),
        "volumes": ("/config", "/tasks"),
        "env": (("CONFIG_DIR", "/config"), ("TASKS_DIR", "/tasks"), ("TITLE", "Tasks"), ("HOME", "/tmp")),
        "command": (),
        "tmpfs": (("/tmp", "64m"),),
        "pids": 256,
        "websocket": False,
        "webdav": False,
        "build": "tasks-md",
        "pin": {
            "image": "baldissaramatheus/tasks.md",
            "version": "3.3.0",
            "manifest_digest": "sha256:fd3e212fd5619794598418c049feda17810dae4438a84c00a0fb06fe3621b97a",
            "amd64_digest": "sha256:72939fac5d0d111dcc8a134e9e0c923e5da18ed0af67f9761d5eeaa0d732f6b8",
        },
    },
    # Paisa (AGPL): ledger-based personal finance. user_accounts: [] in the
    # seeded paisa.yaml means no app login; config, journal and database
    # live in vault/addons/paisa/data.
    "paisa": {
        "name": "Paisa",
        "tile": "Budget",
        "octet": 13,
        "user": (1000, 1000),
        "port": 7500,
        "local_port": 8103,
        "kiosk_port": 8113,
        "tls_port": 5453,
        "dirs": ("data",),
        "binds": (("data", "/data"),),
        "share": (),
        "volumes": (),
        "env": (("PAISA_CONFIG", "/data/paisa.yaml"), ("PAISA_DISABLE_LOG_FILE", "true"), ("HOME", "/tmp")),
        "command": ("paisa", "serve", "--port", "7500"),
        "tmpfs": (("/tmp", "64m"),),
        "pids": 256,
        "websocket": False,
        "webdav": False,
        "pin": {
            "image": "ananthakumaran/paisa",
            "version": "v0.7.8",
            "manifest_digest": "sha256:67842be2d055a1d79a37ee161f39987977037c4d8741c72434e582edd6d08a5d",
            "amd64_digest": "sha256:e05a0af58c7bfd953a9ca4b781827e8fee4e4aae50a285844a3c13ab79958345",
        },
    },
    "trilium": {
        "name": "Trilium",
        "tile": "Notes",
        "octet": 14,
        "user": (1000, 1000),
        "port": 8080,
        "local_port": 8104,
        # Console (kiosk) browser: gateway relay on 127.0.0.1, plain HTTP (v0.5.3).
        "kiosk_port": 8114,
        "tls_port": 5454,
        "dirs": ("data",),
        "binds": (("data", "/home/node/trilium-data"),),
        "share": (),
        "volumes": (),
        # No Trilium password: the vault unlock and the paired gateway are
        # the login. post_start creates the empty document on first start so
        # the setup wizard never shows.
        "env": (("TRILIUM_GENERAL_NOAUTHENTICATION", "true"),),
        "post_start": "trilium-setup",
        # start-docker.sh chowns and drops to "node" with su; we already run
        # as uid 1000, so start the server directly (no capabilities needed).
        "command": ("node", "./main.mjs"),
        "tmpfs": (("/tmp", "128m"),),
        "pids": 256,
        "websocket": True,
        "webdav": False,
        "pin": {
            "image": "triliumnext/trilium",
            "version": "v0.106.1",
            "manifest_digest": "sha256:d87d810fdcb549db65710a40933acaa16bc75c9426a9164c547f7ba95592941b",
            "amd64_digest": "sha256:871e9332d2e29a4ca29b3337ac7568235e0326584db8828ba86a3c0b8eacd7a7",
        },
    },
    "node-red": {
        "name": "Node-RED",
        "tile": "",
        "octet": 15,
        "user": (1000, 1000),
        "port": 1880,
        "local_port": 8105,
        # Console (kiosk) browser: gateway relay on 127.0.0.1, plain HTTP (v0.5.3).
        "kiosk_port": 8115,
        "tls_port": 5455,
        "dirs": ("data",),
        "binds": (("data", "/data"),),
        # Read-only settings.js over the one in /data: palette installs,
        # npm modules in function nodes, telemetry and diagnostics stay off.
        "share": (("node-red-settings.js", "/data/settings.js"),),
        "volumes": ("/data",),
        "env": (("NODE_RED_ENABLE_SAFE_MODE", "false"), ("NODE_RED_ENABLE_PROJECTS", "false")),
        "command": (),
        "tmpfs": (("/tmp", "64m"),),
        "pids": 256,
        "websocket": True,
        "webdav": False,
        "pin": {
            "image": "nodered/node-red",
            "version": "5.0.9",
            "manifest_digest": "sha256:e085d4a06591fd0aca2ea2a91364d27f1a0e31e885675f77935e10f95412a963",
            "amd64_digest": "sha256:051b217b585013c692006e238faa1067adc52f7ded972cbca3d944f5f9563d80",
        },
    },
    # ComfyUI (GPL): node-based image generation. Uses the NVIDIA GPU when
    # the host driver is loaded (device nodes and driver libraries bound
    # read-only, see gpu_args), CPU otherwise. Models, inputs, outputs and the
    # user folder live in the vault. Custom nodes, and ComfyUI-Manager which
    # would install them, are never loaded.
    "comfyui": {
        "name": "ComfyUI",
        "tile": "",
        "octet": 16,
        "user": (1000, 1000),
        "port": 8188,
        "local_port": 8106,
        "kiosk_port": 8116,
        "tls_port": 5456,
        "dirs": ("home", "data", "data/models", "data/input", "data/output", "data/user",
                 "data/temp", "data/custom_nodes"),
        "binds": (("home", "/root"), ("data", "/data")),
        "share": (),
        "volumes": ("/root",),
        "env": (("HOME", "/root"), ("PYTHONDONTWRITEBYTECODE", "1"), ("HF_HUB_OFFLINE", "1"),
                ("TRANSFORMERS_OFFLINE", "1"), ("DO_NOT_TRACK", "1"), ("CLI_ARGS", "")),
        "workdir": "/default-comfyui-bundle/ComfyUI",
        # The host driver libraries (gpu_args) go first on the library path;
        # with no GPU passed in, ComfyUI runs on the CPU.
        "command": ("/bin/sh", "-c",
                    'export LD_LIBRARY_PATH="/usr/local/nvidia/lib64:$LD_LIBRARY_PATH"; '
                    '[ "$STICKLLM_GPU" = nvidia ] || set -- --cpu; '
                    'exec python3 main.py --listen 0.0.0.0 --port 8188 --base-directory /data '
                    '--disable-all-custom-nodes --disable-auto-launch "$@"', "comfyui"),
        "tmpfs": (("/tmp", "1g"),),
        "shm": "1g",
        "pids": 1024,
        "websocket": True,
        "webdav": False,
        "gpu": "optional",
        "vram_gb": 6,
        "pin": {
            "image": "yanwk/comfyui-boot",
            "version": "cu126-slim-20261026",
            "manifest_digest": "sha256:0a355cd7fe20af79c67f01b3d9bb31c12d2c09617e0847e53dd88af4f7da8106",
            "amd64_digest": "sha256:0b4ff81b9d6159debf9ec430d7de5ed10486d407efc998181566e6d4324de1a4",
        },
    },
}
ORDER = ("tasks-md", "paisa", "trilium", "node-red", "comfyui")


class AddonError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def document(self) -> dict:
        return {"ok": False, "error": self.code, "message": self.message}


_VERIFY = None


def _blocked(app_id: object) -> bool:
    """Hard blocklist from stickllm_verify (defence in depth: APPS is already an allowlist)."""
    global _VERIFY
    try:
        if _VERIFY is None:
            import importlib.machinery
            import importlib.util

            path = Path(__file__).resolve().with_name("stickllm_verify.py")
            loader = importlib.machinery.SourceFileLoader("stickllm_verify_addons", str(path))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            mod = importlib.util.module_from_spec(spec)
            loader.exec_module(mod)
            _VERIFY = mod
        return bool(_VERIFY.app_blocked(app_id))
    except Exception:
        return False


def app(app_id: str) -> dict:
    if _blocked(app_id):
        raise AddonError("blocked_app", "That app is blocked on StickLLM and cannot be installed.", 403)
    if not isinstance(app_id, str) or not _ID_RE.fullmatch(app_id) or app_id not in APPS:
        raise AddonError("unknown_app", "Unknown app.", 404)
    return APPS[app_id]


def ids() -> tuple[str, ...]:
    return ORDER


def by_tls_port(port: int) -> str | None:
    for app_id in ORDER:
        if APPS[app_id]["tls_port"] == port:
            return app_id
    return None


# ---------------------------------------------------------------- pin


def parse_pin(text: str) -> dict:
    doc: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        doc[key.strip()] = value.strip()
    for key in ("image", "version", "amd64_digest"):
        if not doc.get(key):
            raise ValueError(f"pin is missing {key}")
    if not _DIGEST_RE.fullmatch(doc["amd64_digest"]):
        raise ValueError("pin amd64_digest is not a sha256 digest")
    return doc


def pin_path(app_id: str) -> Path:
    app(app_id)
    return SHARE_DIR / f"{app_id}.pin"


def load_pin(app_id: str) -> dict:
    spec = app(app_id)
    try:
        return parse_pin(pin_path(app_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(spec["pin"])


def image_ref(app_id: str) -> str:
    """What docker runs: the pinned image, or for apps with a local build
    step the wrapper image committed from it at install."""
    pin = load_pin(app_id)
    if app(app_id).get("build"):
        short = pin["amd64_digest"].split(":", 1)[1][:12]
        return f"stickllm-local/{app_id}:{pin['version']}-{short}"
    return f"{pin['image']}@{pin['amd64_digest']}"


# ---------------------------------------------------------------- mounts



def _read_mounts() -> str:
    try:
        return Path(MOUNTS_FILE or "/proc/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def is_mounted(path: Path) -> bool:
    target = str(path)
    if not MOUNTS_FILE:
        try:
            if os.path.ismount(target):
                return True
        except OSError:
            return False
    for line in _read_mounts().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].replace("\\040", " ") == target:
            return True
    return False


def vault_open() -> bool:
    return is_mounted(VAULT_MNT)


def require_vault() -> None:
    if not vault_open():
        raise AddonError("vault_locked", VAULT_LOCKED_MESSAGE, 423)


# ---------------------------------------------------------------- vault


def addon_dir(app_id: str) -> Path:
    app(app_id)
    return VAULT_MNT / ADDONS_REL / app_id


def _mkdir_safe(path: Path) -> None:
    if os.path.islink(path):
        raise AddonError("bad_path", f"{path} is a symlink.", 500)
    if not path.exists():
        os.mkdir(path, 0o750)
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise AddonError("bad_path", f"{path} is not a folder.", 500)
    if st.st_dev != os.stat(VAULT_MNT).st_dev:
        raise AddonError("bad_root", f"{path} is not on the vault filesystem.", 500)


def _check_dir(path: Path) -> None:
    """An existing real folder on the vault filesystem (never created here)."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise AddonError("bad_path", f"{path} is missing. Install the app again.", 500) from None
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise AddonError("bad_path", f"{path} is not a folder.", 500)
    if st.st_dev != os.stat(VAULT_MNT).st_dev:
        raise AddonError("bad_root", f"{path} is not on the vault filesystem.", 500)


def _chown(path: Path, uid: int, gid: int) -> None:
    if os.geteuid() != 0:
        return  # tests and dry runs; on the stick this runs as root
    os.lchown(path, uid, gid)


def _write_new(path: Path, body: str, uid: int, gid: int, mode: int = 0o640) -> None:
    """Write a file once (O_EXCL, no symlinks); an existing file is kept."""
    if os.path.islink(path):
        raise AddonError("bad_path", f"{path} is a symlink.", 500)
    if path.exists():
        _chown(path, uid, gid)
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    _chown(path, uid, gid)


PAISA_CONFIG = (
    "# Written by StickLLM on first install. Lives in the vault only.\n"
    "# Single user: the vault unlock is the only login, so user_accounts is empty.\n"
    "journal_path: /data/main.ledger\n"
    "db_path: /data/paisa.db\n"
    "ledger_cli: ledger\n"
    "default_currency: CAD\n"
    "locale: en-CA\n"
    "financial_year_starting_month: 1\n"
    "week_starting_day: 1\n"
    "strict: \"no\"\n"
    "user_accounts: []\n"
)
PAISA_JOURNAL = (
    "; Paisa journal (ledger format). Lives in the vault only.\n"
    "; Add transactions in Paisa (Ledger > Editor) or import a bank CSV.\n"
)


def _seed_files(app_id: str, base: Path, uid: int, gid: int) -> None:
    if app_id == "paisa":
        _write_new(base / "data" / "paisa.yaml", PAISA_CONFIG, uid, gid)
        _write_new(base / "data" / "main.ledger", PAISA_JOURNAL, uid, gid)


# Tasks.md wrapper: built once at install inside the pinned base image, as
# root, with --network none and no mounts, then committed to a local tag.
TASKS_MD_BUILD = (
    "set -e\n"
    "cd /app\n"
    "npm run build -- --base=/ >/dev/null\n"
    "rm -f dist/stylesheets/custom.css\n"
    "rm -rf /api/static\n"
    "mv dist /api/static\n"
    "cat > /stickllm-start.sh <<'STICKLLM_EOF'\n"
    "#!/bin/sh\n"
    "set -e\n"
    "mkdir -p /config/stylesheets /config/images /config/sort /tasks\n"
    "[ -f /config/stylesheets/custom.css ] || "
    "echo '@import url(/stylesheets/color-themes/adwaita.css);' > /config/stylesheets/custom.css\n"
    "cp -r /api/static/stylesheets/. /config/stylesheets/\n"
    "cd /api\n"
    "exec node /api/server.js\n"
    "STICKLLM_EOF\n"
    "chmod 755 /stickllm-start.sh\n"
    "rm -rf /root/.npm /tmp/* 2>/dev/null || true\n"
)
BUILDS = {
    "tasks-md": {
        "script": TASKS_MD_BUILD,
        "changes": (
            "USER 1000:1000",
            "WORKDIR /api",
            'ENTRYPOINT ["/bin/sh", "/stickllm-start.sh"]',
            "CMD []",
        ),
    },
}


def has_build(app_id: str) -> bool:
    return bool(app(app_id).get("build"))


def base_ref(app_id: str) -> str:
    """The pinned upstream image (pulled by digest)."""
    pin = load_pin(app_id)
    return f"{pin['image']}@{pin['amd64_digest']}"


def build_spec(app_id: str) -> dict:
    spec = app(app_id)
    if not spec.get("build"):
        raise AddonError("no_build", "This app has no local build step.", 400)
    return BUILDS[spec["build"]]


def prepare_vault(app_id: str) -> dict:
    """Create vault/addons/<id>/<dirs>, owned by the container user.

    Refuses symlinks and anything that is not on the vault filesystem."""
    spec = app(app_id)
    require_vault()
    uid, gid = spec["user"]
    _mkdir_safe(VAULT_MNT / ADDONS_REL)
    base = addon_dir(app_id)
    _mkdir_safe(base)
    for name in spec["dirs"]:
        path = base / name
        _mkdir_safe(path)
        _chown(path, uid, gid)
    _seed_files(app_id, base, uid, gid)
    return {"ok": True, "addon": str(base)}


# ---------------------------------------------------------------- docker


def container_name(app_id: str) -> str:
    app(app_id)
    return f"stickllm-{app_id}"


def network(app_id: str) -> dict:
    # Plain data: a blocked app still gets its bridge named in the nft drop
    # rules (stricter, never looser). Unknown ids still raise.
    spec = APPS.get(app_id) if isinstance(app_id, str) else None
    if spec is None:
        spec = app(app_id)
    n = spec["octet"]
    return {
        "name": f"stickllm-{app_id}",
        "bridge": f"stickllm-a{n - 10}",
        "subnet": f"172.30.{n}.0/24",
        "gateway": f"172.30.{n}.1",
        "ip": f"172.30.{n}.2",
    }


def docker_args(app_id: str) -> list[str]:
    """``docker run`` arguments, one per list item, image last."""
    spec = app(app_id)
    require_vault()
    net = network(app_id)
    base = addon_dir(app_id)
    for path in [VAULT_MNT / ADDONS_REL, base] + [base / sub for sub, _target in spec["binds"]]:
        _check_dir(path)
    uid, gid = spec["user"]
    args = [
        "--name", container_name(app_id),
        "--rm",
        "-d",
        "--read-only",
        "--log-driver", "none",
        "--network", net["name"],
        "--ip", net["ip"],
        "-p", f"127.0.0.1:{spec['local_port']}:{spec['port']}",
        "--user", f"{uid}:{gid}",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges=true",
        "--pids-limit", str(spec["pids"]),
        "--stop-timeout", "30",
        "--hostname", app_id,
        "--dns", "127.0.0.1",
    ]
    for path, size in spec["tmpfs"]:
        args += ["--tmpfs", f"{path}:rw,nosuid,nodev,size={size}"]
    for name, value in spec["env"]:
        args += ["-e", f"{name}={value}"]
    for sub, target in spec["binds"]:
        args += ["-v", f"{base / sub}:{target}"]
    for rel, target in spec["share"]:
        args += ["-v", f"{SHARE_DIR / rel}:{target}:ro"]
    if spec.get("workdir"):
        args += ["-w", spec["workdir"]]
    if spec.get("shm"):
        args += ["--shm-size", spec["shm"]]
    args += gpu_args(app_id)
    args.append(image_ref(app_id))
    args += list(spec["command"])
    return args



# ---------------------------------------------------------------- gpu

DEV_DIR = Path(os.environ.get("STICKLLM_DEV_DIR", "/dev"))
NVIDIA_LIB_DIRS = tuple(
    Path(p) for p in os.environ.get(
        "STICKLLM_NVIDIA_LIB_DIRS",
        "/usr/lib/x86_64-linux-gnu:/usr/lib/x86_64-linux-gnu/nvidia/current:/usr/lib64:/usr/lib",
    ).split(":") if p
)
# User-space driver pieces CUDA needs inside the container (what
# nvidia-container-toolkit would inject). The CUDA runtime itself ships in
# the image; these must match the host kernel module, so they come from the host.
NVIDIA_LIBS = (
    "libcuda.so.1",
    "libnvidia-ml.so.1",
    "libnvidia-ptxjitcompiler.so.1",
    "libnvidia-nvvm.so.4",
    "libnvidia-gpucomp.so",
)
NVIDIA_CONTAINER_LIB = "/usr/local/nvidia/lib64"


def nvidia_devices() -> list[str]:
    out = []
    for name in ("nvidiactl", "nvidia-uvm", "nvidia-uvm-tools", "nvidia-modeset"):
        p = DEV_DIR / name
        if p.exists():
            out.append(str(p))
    for p in sorted(DEV_DIR.glob("nvidia[0-9]*")):
        out.append(str(p))
    return out


def _find_lib(name: str) -> Path | None:
    for d in NVIDIA_LIB_DIRS:
        p = d / name
        if p.exists():
            return p.resolve()
        if name.endswith(".so"):
            hits = sorted(d.glob(name + ".*"))
            if hits:
                return hits[-1].resolve()
    return None


def gpu_args(app_id: str) -> list[str]:
    """NVIDIA device nodes and driver libraries, read-only. Empty without a GPU."""
    spec = app(app_id)
    if not spec.get("gpu"):
        return []
    devs = nvidia_devices()
    if not any(Path(d).name[6:].isdigit() for d in devs):
        return []
    libcuda = _find_lib("libcuda.so.1")
    if libcuda is None:
        return []
    args: list[str] = []
    for d in devs:
        args += ["--device", d]
    for name in NVIDIA_LIBS:
        p = _find_lib(name)
        if p is None:
            continue
        target_name = name if not name.endswith(".so") else p.name
        args += ["-v", f"{p}:{NVIDIA_CONTAINER_LIB}/{target_name}:ro"]
    args += ["-e", "STICKLLM_GPU=nvidia"]
    return args


def vram_free_mib() -> int | None:
    """Free VRAM on the emptiest NVIDIA GPU, or None when unknown."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    vals = [int(x.strip()) for x in out.splitlines() if x.strip().isdigit()]
    return max(vals) if vals else None


def gpu_check(app_id: str) -> dict:
    """Pre-start hardware check. Warns, never refuses."""
    spec = app(app_id)
    if not spec.get("gpu"):
        return {"ok": True, "gpu": "none", "warning": ""}
    want = int(spec.get("vram_gb") or 0) * 1024
    if not gpu_args(app_id):
        return {"ok": True, "gpu": "cpu",
                "warning": f"{spec['name']}: no NVIDIA GPU found, running on CPU (very slow)."}
    free = vram_free_mib()
    if free is None:
        return {"ok": True, "gpu": "nvidia", "warning": f"{spec['name']}: could not read free GPU memory."}
    if want and free < want:
        return {"ok": True, "gpu": "nvidia", "vram_free_mib": free,
                "warning": (f"{spec['name']}: only {free / 1024:.1f} GB GPU memory free; about "
                            f"{want // 1024} GB is recommended. The local AI model may be using it. "
                            "Starting anyway; large models may fail or fall back to slow modes.")}
    return {"ok": True, "gpu": "nvidia", "vram_free_mib": free, "warning": ""}
# ---------------------------------------------------------------- nft


def nft_ruleset() -> str:
    """Containers answer the loopback publish and nothing else.

    Packets a container starts are dropped: forwarded (internet, LAN, other
    apps) and to the host itself. Replies to connections the host opened
    (docker-proxy on 127.0.0.1) are allowed."""
    bridges = ", ".join(f'"{network(a)["bridge"]}"' for a in ORDER)
    return (
        f"table inet {NFT_TABLE} {{\n"
        "  chain forward {\n"
        "    type filter hook forward priority 0; policy accept;\n"
        f"    iifname {{ {bridges} }} drop\n"
        f"    oifname {{ {bridges} }} ct state established,related accept\n"
        f"    oifname {{ {bridges} }} drop\n"
        "  }\n"
        "  chain input {\n"
        "    type filter hook input priority 0; policy accept;\n"
        f"    iifname {{ {bridges} }} ct state established,related accept\n"
        f"    iifname {{ {bridges} }} drop\n"
        "  }\n"
        "}\n"
    )


def nft_apply_text() -> str:
    return f"add table inet {NFT_TABLE}\ndelete table inet {NFT_TABLE}\n" + nft_ruleset()


def nft_apply() -> int:
    proc = subprocess.run(["nft", "-f", "-"], input=nft_apply_text(), text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        print((proc.stderr or proc.stdout or "nft failed").strip(), file=sys.stderr)
    return proc.returncode


# ---------------------------------------------------------------- status


def status_path(app_id: str) -> Path:
    app(app_id)
    return RUN_DIR / f"addon-{app_id}-status.json"


def read_status(app_id: str) -> dict:
    try:
        doc = json.loads(status_path(app_id).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(app_id: str, state: str, **extra: object) -> dict:
    doc = {"state": state, "updated": int(time.time())}
    for key, value in extra.items():
        if value is not None:
            doc[key] = value
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        path = status_path(app_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except OSError:
        pass
    return doc


def installed_marker(app_id: str) -> Path:
    return addon_dir(app_id) / "installed.json"


def is_installed(app_id: str) -> bool:
    if not vault_open():
        return False
    try:
        doc = json.loads(installed_marker(app_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(doc, dict) and doc.get("amd64_digest") == load_pin(app_id)["amd64_digest"]


def mark_installed(app_id: str) -> None:
    pin = load_pin(app_id)
    installed_marker(app_id).write_text(
        json.dumps({"image": pin["image"], "version": pin["version"], "amd64_digest": pin["amd64_digest"],
                    "installed": int(time.time())}) + "\n",
        encoding="utf-8",
    )


def unmark_installed(app_id: str) -> None:
    try:
        installed_marker(app_id).unlink()
    except FileNotFoundError:
        pass


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def status_document(app_id: str, *, upstream_up: bool | None = None) -> dict:
    spec = app(app_id)
    name = spec["name"]
    vault = vault_open()
    saved = read_status(app_id)
    installed = is_installed(app_id) if vault else False
    up = port_open(spec["local_port"]) if upstream_up is None else bool(upstream_up)
    state = saved.get("state") or ("stopped" if installed else "not_installed")
    if not vault:
        state, message = "locked", VAULT_LOCKED_MESSAGE
    elif state == "installing":
        message = f"Installing {name}. The image is pulled onto the host drive."
    elif state == "removing" and installed:
        message = f"Removing {name}. Its data in the vault is kept."
    elif state == "install_failed":
        message = str(saved.get("message") or f"{name} install failed.")[:300]
    elif not installed:
        state, message = "not_installed", f"{name} is not installed yet."
    elif up and state in ("running", "starting", "stopped"):
        state, message = "running", f"{name} is running."
    elif state == "error":
        message = str(saved.get("message") or f"{name} failed to start.")[:300]
    elif state == "stopped":
        message = f"{name} is stopped."
    else:
        state, message = "starting", f"{name} is starting."
    return {
        "ok": True,
        "id": app_id,
        "state": state,
        "message": message,
        "vault_open": vault,
        "installed": installed,
        "running": bool(vault and installed and up),
        "data": f"vault/addons/{app_id}",
        "version": load_pin(app_id)["version"],
        "local_port": spec["local_port"],
        "tls_port": spec["tls_port"],
    }


# ---------------------------------------------------------------- post-start


def _http(method: str, port: int, path: str, timeout: float = 10.0) -> tuple[int, bytes]:
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        conn.request(method, path, body=b"" if method == "POST" else None,
                     headers={"Content-Type": "application/json"} if method == "POST" else {})
        resp = conn.getresponse()
        return resp.status, resp.read()
    finally:
        conn.close()


def _trilium_setup(app_id: str, wait: float) -> dict:
    """First start: create an empty document so Trilium opens straight to
    the notes (no setup wizard, no demo notes). A no-op once initialised."""
    spec = app(app_id)
    port = spec["local_port"]
    deadline = time.time() + wait
    status = None
    while time.time() < deadline:
        try:
            code, body = _http("GET", port, "/api/setup/status")
            if code == 200:
                status = json.loads(body.decode("utf-8") or "{}")
                break
        except (OSError, ValueError):
            pass
        time.sleep(2)
    if status is None:
        return {"ok": False, "error": "not_ready"}
    if status.get("isInitialized"):
        return {"ok": True, "initialized": True, "created": False}
    code, body = _http("POST", port, "/api/setup/new-document?skipDemoDb=true", timeout=120)
    if code >= 300:
        return {"ok": False, "error": f"http_{code}", "body": body[:200].decode("utf-8", "replace")}
    for _ in range(60):
        try:
            c2, b2 = _http("GET", port, "/api/setup/status")
            if c2 == 200 and json.loads(b2.decode("utf-8") or "{}").get("isInitialized"):
                return {"ok": True, "initialized": True, "created": True}
        except (OSError, ValueError):
            pass
        time.sleep(1)
    return {"ok": False, "error": "not_initialized"}


POST_START = {"trilium-setup": _trilium_setup}


def post_start(app_id: str, wait: float = 180.0) -> dict:
    spec = app(app_id)
    hook = spec.get("post_start")
    if not hook:
        return {"ok": True, "hook": ""}
    out = POST_START[hook](app_id, wait)
    out["hook"] = hook
    return out


# ---------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    app_id = argv[2] if len(argv) > 2 else ""
    try:
        if cmd == "ids":
            print("\n".join(ORDER))
            return 0
        if cmd == "vault-open":
            return 0 if vault_open() else 2
        if cmd == "nft-apply":
            return nft_apply()
        if cmd == "nft-text":
            print(nft_apply_text(), end="")
            return 0
        app(app_id)
        if cmd == "image-ref":
            print(image_ref(app_id))
            return 0
        if cmd == "base-ref":
            print(base_ref(app_id))
            return 0
        if cmd == "has-build":
            return 0 if has_build(app_id) else 1
        if cmd == "build-script":
            print(build_spec(app_id)["script"], end="")
            return 0
        if cmd == "build-changes":
            print("\n".join(build_spec(app_id)["changes"]))
            return 0
        if cmd == "gpu-check":
            doc = gpu_check(app_id)
            print(json.dumps(doc))
            return 0
        if cmd == "post-start":
            doc = post_start(app_id)
            print(json.dumps(doc))
            return 0 if doc.get("ok") else 1
        if cmd == "name":
            print(APPS[app_id]["name"])
            return 0
        if cmd == "addon-dir":
            print(addon_dir(app_id))
            return 0
        if cmd == "prepare-vault":
            prepare_vault(app_id)
            return 0
        if cmd == "docker-args":
            require_vault()
            print("\n".join(docker_args(app_id)))
            return 0
        if cmd == "network":
            net = network(app_id)
            print("\n".join(net[k] for k in ("name", "bridge", "subnet", "gateway")))
            return 0
        if cmd == "container":
            print(container_name(app_id))
            return 0
        if cmd == "installed":
            return 0 if is_installed(app_id) else 1
        if cmd == "mark-installed":
            require_vault()
            mark_installed(app_id)
            return 0
        if cmd == "unmark-installed":
            require_vault()
            unmark_installed(app_id)
            return 0
        if cmd == "write-status":
            args = argv[3:]
            state, extra, i = "unknown", {}, 0
            while i < len(args):
                if args[i] == "--state" and i + 1 < len(args):
                    state = args[i + 1]
                    i += 2
                elif args[i] == "--message" and i + 1 < len(args):
                    extra["message"] = args[i + 1][:300]
                    i += 2
                else:
                    i += 1
            write_status(app_id, state, **extra)
            return 0
        if cmd == "status":
            print(json.dumps(status_document(app_id)))
            return 0
    except AddonError as exc:
        print(f"stickllm-addon: {exc.message}", file=sys.stderr)
        return 2 if exc.status == 423 else 1
    print("usage: stickllm_addons.py {ids|vault-open|nft-apply|nft-text} | "
          "{image-ref|name|addon-dir|prepare-vault|docker-args|network|container|installed|"
          "mark-installed|unmark-installed|write-status|status} <id>", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
