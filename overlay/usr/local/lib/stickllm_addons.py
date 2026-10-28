#!/usr/bin/env python3
"""StickLLM starter add-ons: Radicale, Vikunja, Actual Budget, Trilium, Node-RED.

Same rules as ONLYOFFICE Docs (stickllm_docs.py):

* the image is pinned by digest and pulled onto the host SSD docker data-root;
* everything the app writes lives in vault/addons/<id> only, so a locked
  vault means no app data on any disk;
* the container runs non-root, read-only, with no capabilities, no GPU,
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
    "radicale": {
        "name": "Radicale",
        "octet": 11,
        "user": (2999, 2999),
        "port": 5232,
        "local_port": 8101,
        # Console (kiosk) browser: gateway relay on 127.0.0.1, plain HTTP (v0.5.3).
        "kiosk_port": 8111,
        "tls_port": 5451,
        "dirs": ("data",),
        "binds": (("data", "/data"),),
        "share": (("radicale", "/config"),),
        "volumes": ("/config", "/data"),
        "env": (),
        "command": (),
        "tmpfs": (("/tmp", "16m"),),
        "pids": 128,
        "websocket": False,
        "webdav": True,
        "pin": {
            "image": "tomsquest/docker-radicale",
            "version": "3.9.0",
            "tag": "3.9.0.0",
            "manifest_digest": "sha256:2f215d0e6a78ff68c280975af6ce580b05976f70c62b51640397e3eb5a7aa0e9",
            "amd64_digest": "sha256:18a9ab6dc2ce458f2863a19f646fdc6934e6408f0d97d68275117a80ceef122e",
        },
    },
    "vikunja": {
        "name": "Vikunja",
        "octet": 12,
        "user": (1000, 1000),
        "port": 3456,
        "local_port": 8102,
        # Console (kiosk) browser: gateway relay on 127.0.0.1, plain HTTP (v0.5.3).
        "kiosk_port": 8112,
        "tls_port": 5452,
        "dirs": ("config", "db", "files"),
        "binds": (("config", "/etc/vikunja:ro"), ("db", "/db"), ("files", "/app/vikunja/files")),
        "share": (),
        "volumes": (),
        "env": (),
        "command": (),
        "tmpfs": (("/tmp", "64m"),),
        "pids": 256,
        "websocket": False,
        "webdav": False,
        "pin": {
            "image": "vikunja/vikunja",
            "version": "2.7.1",
            "manifest_digest": "sha256:f7dc8428d10aef17f3075886d3c1c022f566ec456f88985f02c137f4fc534576",
            "amd64_digest": "sha256:3a848c83404d59ba9df4d91b92af4c400c8876ccdbbf3b563d41019cee29df39",
        },
    },
    "actual": {
        "name": "Actual Budget",
        "octet": 13,
        "user": (1000, 1000),
        "port": 5006,
        "local_port": 8103,
        # Console (kiosk) browser: gateway relay on 127.0.0.1, plain HTTP (v0.5.3).
        "kiosk_port": 8113,
        "tls_port": 5453,
        "dirs": ("data",),
        "binds": (("data", "/data"),),
        "share": (),
        "volumes": (),
        "env": (),
        "command": (),
        "tmpfs": (("/tmp", "128m"),),
        "pids": 256,
        "websocket": False,
        "webdav": False,
        "pin": {
            "image": "actualbudget/actual-server",
            "version": "26.10.0",
            "manifest_digest": "sha256:24645e971da6bb1a1f953d6859e307a0b29be1e8b4130a35b3220c209b5b860c",
            "amd64_digest": "sha256:bdfbb624d5fe9df05481d8eb6791a00a4a78ab8152bce31e79c6f18917e6933e",
        },
    },
    "trilium": {
        "name": "Trilium Notes",
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
        "env": (),
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
}
ORDER = ("radicale", "vikunja", "actual", "trilium", "node-red")


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
    pin = load_pin(app_id)
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


def _vikunja_config(base: Path, uid: int, gid: int) -> None:
    """Vikunja needs a config.yml under read-only root. The JWT secret is
    generated once and kept in the vault, never printed."""
    path = base / "config" / "config.yml"
    if os.path.islink(path):
        raise AddonError("bad_path", f"{path} is a symlink.", 500)
    if path.exists():
        _chown(path, uid, gid)
        return
    body = (
        "# Written by StickLLM on first start. Lives in the vault only.\n"
        "service:\n"
        f'  secret: "{secrets.token_hex(32)}"\n'
        "  enableregistration: true\n"
        "  enabletaskattachments: true\n"
        "  timezone: UTC\n"
        "cors:\n"
        "  enable: false\n"
        "mailer:\n"
        "  enabled: false\n"
        "log:\n"
        "  level: WARNING\n"
        "  http: \"off\"\n"
        "  database: \"off\"\n"
        "  events: \"off\"\n"
        "  mail: \"off\"\n"
        "backgrounds:\n"
        "  providers:\n"
        "    unsplash:\n"
        "      enabled: false\n"
        "migration:\n"
        "  todoist:\n"
        "    enable: false\n"
        "  trello:\n"
        "    enable: false\n"
        "  microsofttodo:\n"
        "    enable: false\n"
        "avatar:\n"
        "  gravatarexpiration: 0\n"
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    _chown(path, uid, gid)


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
    if app_id == "vikunja":
        _vikunja_config(base, uid, gid)
    return {"ok": True, "addon": str(base)}


# ---------------------------------------------------------------- docker


def container_name(app_id: str) -> str:
    app(app_id)
    return f"stickllm-{app_id}"


def network(app_id: str) -> dict:
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
    args.append(image_ref(app_id))
    args += list(spec["command"])
    return args


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
