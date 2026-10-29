#!/usr/bin/env python3
"""Agent Zero gates for StickLLM.

Docker starts only when the server vault is mounted. The public image lives in
a folder on the mounted host SSD, next to the models directory the product
already knows. Memory, work, logs, and state stay in the vault. Keys stay on
the USB settings partition.

The UI is not mounted under /agent. A paired TLS listener on port 5443 proxies
to the loopback UI with no path or body rewriting. This module does not log
API keys, vault passcodes, or chat text.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VAULT_MNT = Path(os.environ.get("STICKLLM_VAULT_MNT", "/var/lib/stickllm/vault"))
SETTINGS_MNT = Path(os.environ.get("STICKLLM_SETTINGS_MNT", "/mnt/stickllm-settings"))
HOST_MNT = Path(os.environ.get("STICKLLM_HOST_MNT", "/mnt/stickllm-host"))
ADDON = VAULT_MNT / "addons" / "agent-zero"
PORTABLE = SETTINGS_MNT / "agent-zero"
STATUS_PATH = Path(os.environ.get("STICKLLM_AGENT_STATUS", "/run/stickllm/agent-status.json"))
PULL_LOG = Path(os.environ.get("STICKLLM_AGENT_PULL_LOG", "/run/stickllm/agent-pull.log"))
PIN_PATH = Path(
    os.environ.get(
        "STICKLLM_AGENT_PIN",
        str(Path(__file__).resolve().parent.parent / "share" / "stickllm" / "agent-zero.pin"),
    )
)
# 12 GiB. The test boot used df's 1K blocks (12*1024*1024). Below this, do not pull.
MIN_FREE_BYTES = 12 * 1024 * 1024 * 1024
DOCKER_DIR_NAME = "stickllm-docker"
# llama-server stays on 127.0.0.1:8080. The container reaches it through a
# relay bound only to this bridge address, not through 0.0.0.0.
LLAMA_BRIDGE_HOST = "172.30.0.1"
LLAMA_BRIDGE_PORT = 8080
# Static StickLLM apps only. Same bridge address as the llama relay, never 0.0.0.0.
APPS_BRIDGE_PORT = 8081
# open_app control. Bridge and loopback only, never 0.0.0.0 and never the LAN.
OPEN_APP_PORT = 8082
EGRESS_PROXY_PORT = int(os.environ.get("STICKLLM_EGRESS_PROXY_PORT", "18080"))
EGRESS_EVENTS = Path(os.environ.get("STICKLLM_EGRESS_EVENTS", "/run/stickllm/agent-egress-events.json"))
SECCOMP_PROFILE = Path(os.environ.get(
    "STICKLLM_AGENT_SECCOMP",
    "/usr/local/share/stickllm/agent-zero-seccomp.json",
))
EGRESS_SCAN_LIB = Path(os.environ.get(
    "STICKLLM_EGRESS_SCAN",
    "/usr/local/lib/stickllm_egress_scan.py",
))
EGRESS_EXT_SRC = Path(os.environ.get(
    "STICKLLM_EGRESS_EXT",
    "/usr/local/share/stickllm/agent-zero-egress-extension.py",
))
ALWAYS_BLOCK_HOSTS = (
    "metadata.google.internal",
    "metadata.goog",
    "metadata",
    "instance-data",
    "instance-data.ec2.internal",
    "routify-file-proxy-sg.oss-ap-southeast-1.aliyuncs.com",
    "sanmaohe.oss-cn-beijing.aliyuncs.com",
)
LLAMA_BRIDGE_SUBNET = "172.30.0.0/24"
LLAMA_BRIDGE_IFACE = "stickllm-a0"
LLAMA_BASE = f"http://{LLAMA_BRIDGE_HOST}:{LLAMA_BRIDGE_PORT}/v1"
# Directory ids under ui/apps. The desktop label for minesweeper is minesweep.
APPS_URL_IDS = (
    "minesweeper",
    "solitaire",
    "tetris",
    "notepad",
    "calculator",
    "files",
    "media",
    "monitor",
)
# Catalog apps (0.5.2): open_app can open them once installed, install_app
# asks the user to install one (they confirm on their own screen). docs is
# ONLYOFFICE Docs at /apps/docs/. Everything goes through the open-app
# control on 172.30.0.1:8082 and the loopback gateway: the container's
# firewall only reaches 8080-8082 on the bridge, never the add-on ports.
CATALOG_APP_IDS = ("docs", "tasks-md", "paisa", "trilium", "node-red", "comfyui")
CATALOG_APP_NAMES = {
    "docs": "ONLYOFFICE Office (documents, spreadsheets, slides)",
    "tasks-md": "Tasks.md Tasks (task boards)",
    "paisa": "Paisa Budget (personal finance)",
    "trilium": "Trilium Notes",
    "node-red": "Node-RED",
    "comfyui": "ComfyUI (image generation)",
}
APP_ID_ALIASES = {
    "onlyoffice": "docs",
    "onlyoffice-docs": "docs",
    "office": "docs",
    "documents": "docs",
    "nodered": "node-red",
    "node_red": "node-red",
    "trilium-notes": "trilium",
    "notes": "trilium",
    "tasks.md": "tasks-md",
    "tasksmd": "tasks-md",
    "tasks": "tasks-md",
    "todo": "tasks-md",
    "budget": "paisa",
    "comfy": "comfyui",
    "comfy-ui": "comfyui",
}
# Gateway catalog row id for each agent id (docs is the onlyoffice row).
CATALOG_ROW_IDS = {"docs": "onlyoffice"}
APPS_NOTE = (
    "StickLLM apps are at http://172.30.0.1:8081/apps/<id>/ "
    "(minesweeper, solitaire, tetris, notepad, calculator, files, media, monitor)."
)
# Apps whose page sets window.stickllmApp, so app_state and app_act work.
# The rest open with open_app only.
APPS_PLAYABLE_IDS = ("minesweeper", "solitaire", "tetris", "notepad", "calculator")
APPS_PLAYABLE_NOTE = (
    "app_state and app_act work for minesweeper, solitaire, tetris, notepad, and calculator. "
    "files, media, and monitor open with open_app only. "
    "If an app was just added, start a new Agent Zero chat so old context does not hide it."
)
OPEN_APP_RULE = (
    "When the user says open/start/show an app, use open_app, not the browser tool."
)
# Pinned agent0ai/agent-zero v2.14 lists this chat provider in
# conf/model_providers.yaml. It speaks OpenAI /v1 through litellm hosted_vllm.
LOCAL_PROVIDER = "llama_cpp"
# A stuck model call must fail into the Agent Zero chat instead of spinning.
MODEL_TIMEOUT = 90
EMBED_REPO = "sentence-transformers/all-MiniLM-L6-v2"
AGENT_PORT = 5099
AGENT_TLS_PORT = 5443
NFT_TABLE = "stickllm_agent"
SSD_MISSING = "Mount a drive for Agent Zero"
LOW_SPACE_MESSAGE = "The host drive needs about 12 GB free before Agent Zero can be installed"
NEEDS_INSTALL_MESSAGE = "Agent Zero is not installed yet"


def parse_pin(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip()
    return out


def load_pin(path: Path | None = None) -> dict[str, str]:
    pin_path = path or PIN_PATH
    data = parse_pin(pin_path.read_text(encoding="utf-8"))
    digest = data.get("amd64_digest") or ""
    if not digest.startswith("sha256:") or len(digest) != 7 + 64:
        raise ValueError("agent-zero pin is missing an amd64 digest")
    if not data.get("version") or not data.get("image"):
        raise ValueError("agent-zero pin is missing image or version")
    return data


def image_ref(pin: dict[str, str] | None = None) -> str:
    data = pin or load_pin()
    return f"{data['image']}@{data['amd64_digest']}"


def _repo_names(image: str) -> set[str]:
    names = {image}
    short = image
    for prefix in ("docker.io/", "index.docker.io/", "registry-1.docker.io/"):
        if short.startswith(prefix):
            short = short[len(prefix):]
    names.add(short)
    if short.startswith("library/"):
        names.add(short[len("library/"):])
    names |= {"docker.io/" + n for n in list(names) if "/" in n and not n.startswith("docker.io/")}
    return names


def image_on_disk(root: Path | None = None, ref: str | None = None) -> bool | None:
    """Is the pinned image in the docker data-root, without starting dockerd?

    dockerd records ``repo@sha256:...`` for an image pulled by digest in
    ``<data-root>/image/<driver>/repositories.json``. None means unknown (no
    data-root, or a layout without that file); callers then ask dockerd.
    """
    if root is None:
        root = docker_data_root()
    if root is None:
        return None
    ref = ref or image_ref()
    image, _, digest = ref.partition("@")
    if not digest:
        return None
    image_dir = Path(root) / "image"
    if not image_dir.is_dir():
        return False  # dockerd never ran on this data-root: nothing is pulled
    files = sorted(image_dir.glob("*/repositories.json"))
    if not files:
        return None
    names = _repo_names(image)
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        repos = doc.get("Repositories") if isinstance(doc, dict) else None
        if not isinstance(repos, dict):
            continue
        for repo, refs in repos.items():
            if repo in names and isinstance(refs, dict) and f"{repo}@{digest}" in refs:
                return True
    return False


def _read_mounts(mounts_text: str | None = None) -> str:
    if mounts_text is not None:
        return mounts_text
    mounts_file = os.environ.get("STICKLLM_MOUNTS_FILE")
    if mounts_file:
        try:
            return Path(mounts_file).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    try:
        return Path("/proc/self/mounts").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def vault_mounted(path: Path | None = None, mounts_text: str | None = None) -> bool:
    """True only when path is a mount point. A plain directory is not enough."""
    target = str(path or VAULT_MNT)
    text = _read_mounts(mounts_text)
    if mounts_text is not None or os.environ.get("STICKLLM_MOUNTS_FILE"):
        for line in text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == target:
                return True
        return False
    try:
        if os.path.ismount(target):
            return True
    except OSError:
        return False
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == target:
            return True
    return False


def settings_mounted(path: Path | None = None, mounts_text: str | None = None) -> bool:
    return vault_mounted(path or SETTINGS_MNT, mounts_text)


def docker_may_start(is_mounted: bool | None = None) -> bool:
    """Vault locked => docker must not start."""
    if is_mounted is None:
        is_mounted = vault_mounted()
    return bool(is_mounted)


def agent_http_allowed(require_pair: bool, authorized: bool) -> bool:
    """Unpaired browsers are refused. Loopback callers are already authorized."""
    if require_pair and not authorized:
        return False
    return True


def pull_allowed(free_bytes: int | None) -> bool:
    """True when the host SSD folder (not the vault) has enough free space."""
    if free_bytes is None:
        return False
    try:
        return int(free_bytes) >= MIN_FREE_BYTES
    except (TypeError, ValueError):
        return False


def free_bytes(path: Path) -> int | None:
    target = path if path.exists() else path.parent
    try:
        st = os.statvfs(str(target))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None
    return int(st.f_bavail) * int(st.f_frsize)


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _under_vault(path: Path) -> bool:
    return _under(path, VAULT_MNT)


def host_mount_points(mounts_text: str | None = None) -> list[str]:
    """Mount points of the host SSD tree. An unmounted folder does not count."""
    root = str(HOST_MNT)
    found: list[str] = []
    for line in _read_mounts(mounts_text).splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        mp = parts[1]
        if mp == root or mp.startswith(root + os.sep) or mp.startswith(root + "/"):
            if mp not in found:
                found.append(mp)
    return found


def host_ssd_mounted(mounts_text: str | None = None) -> bool:
    return bool(host_mount_points(mounts_text))


def _recorded_model_dirs() -> list[Path]:
    """Models folders the product already recorded. Usernames are not hardcoded."""
    out: list[Path] = []
    env = os.environ.get("STICKLLM_MODELS_DIR", "").strip()
    if env:
        out.append(Path(env))
    models_file = Path(os.environ.get("STICKLLM_MODELS_DIR_FILE", "/run/stickllm/models-dir.json"))
    try:
        doc = json.loads(models_file.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and doc.get("path"):
            out.append(Path(str(doc["path"])))
    except (OSError, json.JSONDecodeError):
        pass
    root = ""
    vault_json = Path(os.environ.get("STICKLLM_VAULT_JSON", "/run/stickllm/vault.json"))
    try:
        doc = json.loads(vault_json.read_text(encoding="utf-8"))
        if isinstance(doc, dict):
            root = str(doc.get("root") or "").strip()
    except (OSError, json.JSONDecodeError):
        root = ""
    if not root:
        meta = Path(os.environ.get("STICKLLM_VAULT_META_ROOT", "/var/lib/stickllm/vault-meta/root"))
        try:
            root = meta.read_text(encoding="utf-8").strip()
        except OSError:
            root = ""
    if root and not root.startswith("/dev/"):
        rp = Path(root)
        if rp.name.lower() == "models":
            out.append(rp)
        else:
            out.append(rp / "models")
            out.append(rp.parent / "models")
    return out


def _path_on_mounts(path: Path, mounts: list[str]) -> bool:
    text = str(path)
    for mp in mounts:
        if text == mp or text.startswith(mp + "/") or text.startswith(mp + os.sep):
            return True
    return False


def discover_models_dir(mounts: list[str]) -> Path | None:
    for cand in _recorded_model_dirs():
        if cand.is_dir() and _path_on_mounts(cand, mounts) and not _under_vault(cand):
            return cand
    best: Path | None = None
    best_depth = 99
    skip = {"proc", "sys", "dev", "lost+found", DOCKER_DIR_NAME}
    for mp in mounts:
        root = Path(mp)
        if not root.is_dir():
            continue
        for dirpath, dirnames, _files in os.walk(root):
            current = Path(dirpath)
            try:
                rel = current.relative_to(root)
            except ValueError:
                dirnames[:] = []
                continue
            depth = 0 if str(rel) == "." else len(rel.parts)
            if depth > 4:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d not in skip and not d.startswith(".")]
            if current.name == "models" and depth < best_depth and not _under_vault(current):
                best = current
                best_depth = depth
                dirnames[:] = []
    return best


def docker_data_root(
    *,
    models: Path | None = None,
    mounts: list[str] | None = None,
    override: str | None = None,
    use_env: bool = True,
) -> Path | None:
    """Public image folder on the host SSD, beside the known models directory.

    ``<host mount>/home/<user>/stickllm-docker`` is one example of that layout.
    It is not the only allowed path, and no username is special-cased.
    """
    if override is None and use_env:
        override = os.environ.get("STICKLLM_DOCKER_DIR", "").strip() or None
    if override:
        path = Path(override)
        if _under_vault(path):
            return None
        return path
    if mounts is None:
        mounts = host_mount_points()
    if not mounts and models is None:
        return None
    chosen = models
    if chosen is None and mounts:
        chosen = discover_models_dir(mounts)
    if chosen is not None:
        dest = chosen.parent / DOCKER_DIR_NAME
        if not _under_vault(dest):
            return dest
    if mounts:
        dest = Path(mounts[0]) / DOCKER_DIR_NAME
        if not _under_vault(dest):
            return dest
    return None


# Agent Zero matches these with fnmatch. The loopback patterns are its own
# defaults. They have to be repeated here: once ALLOWED_ORIGINS is set, the
# image does not add the defaults itself. ``*://127.0.0.1:*`` is what lets
# the console keep using http://127.0.0.1:5099. Port 5099 stays on loopback.
_LOOPBACK_ORIGINS = (
    "*://localhost",
    "*://localhost:*",
    "*://127.0.0.1",
    "*://127.0.0.1:*",
    "*://0.0.0.0",
    "*://0.0.0.0:*",
)


def _non_loopback_ips(ips: list[str]) -> list[str]:
    found: list[str] = []
    for raw in ips:
        ip = (raw or "").strip()
        if not ip or ip in found:
            continue
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.version != 4 or addr.is_loopback or addr.is_unspecified:
            continue
        found.append(ip)
    return found


def allowed_origins(ips: list[str] | None = None) -> str:
    """Origins for a paired browser on https://<lan-ip>:5443.

    fnmatch does not treat ``https://<ip>`` as ``https://<ip>:5443``. Each
    current non-loopback address is listed with the gateway port and as
    ``*://<ip>:*``, the same port-wildcard form Agent Zero already uses for
    localhost.
    """
    origins = list(_LOOPBACK_ORIGINS)
    for ip in _non_loopback_ips(ips or []):
        for origin in (f"https://{ip}:{AGENT_TLS_PORT}", f"*://{ip}:*"):
            if origin not in origins:
                origins.append(origin)
    return ",".join(origins)


def _local_ipv4s() -> list[str]:
    found: list[str] = []
    try:
        probed = subprocess.run(
            ["ip", "-4", "-o", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        for line in (probed.stdout or "").splitlines():
            parts = line.split()
            if "inet" not in parts:
                continue
            addr = parts[parts.index("inet") + 1].split("/", 1)[0]
            if addr and addr not in found:
                found.append(addr)
    except (OSError, subprocess.SubprocessError, IndexError, ValueError):
        return ["127.0.0.1"]
    return found or ["127.0.0.1"]


PUBLIC_DNS = ("1.1.1.1", "9.9.9.9")
RESOLV_FILES = ("/run/systemd/resolve/resolv.conf", "/etc/resolv.conf")


def host_dns_servers(files=None, override: str | None = None) -> list[str]:
    """DNS servers for the Agent Zero container: the host's LAN/DHCP resolvers
    first (at most 2), then public fallbacks; 3 total like resolv.conf.

    Pinning only public DNS broke Hugging Face and pip on networks that block
    outside DNS. Loopback stubs are skipped (127.0.0.53 is not reachable from
    the bridge). STICKLLM_AGENT_DNS="a b" overrides the list.
    """
    override = os.environ.get("STICKLLM_AGENT_DNS", "") if override is None else override
    out: list[str] = []

    def add(raw: str) -> None:
        try:
            ip = ipaddress.ip_address(raw.strip())
        except ValueError:
            return
        if ip.is_loopback or ip.is_unspecified or ip.is_link_local or ip.is_multicast:
            return
        if str(ip) not in out:
            out.append(str(ip))

    if override.strip():
        for part in override.split():
            add(part)
        return out[:3]
    for name in files if files is not None else RESOLV_FILES:
        try:
            text = Path(name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            bits = line.split()
            if len(bits) >= 2 and bits[0] == "nameserver":
                add(bits[1])
        if out:
            break
    out = out[:2]
    for pub in PUBLIC_DNS:
        if pub not in out:
            out.append(pub)
    return out[:3]


def private_dns_v4(servers) -> list[str]:
    """Resolvers inside the RFC1918 ranges the forward chain drops."""
    keep = []
    for raw in servers or ():
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if ip.version == 4 and ip.is_private and not ip.is_loopback and str(ip) not in keep:
            keep.append(str(ip))
    return keep


def nft_ruleset(
    bridge: str = LLAMA_BRIDGE_IFACE,
    subnet: str = LLAMA_BRIDGE_SUBNET,
    gateway: str = LLAMA_BRIDGE_HOST,
    llama_port: int = LLAMA_BRIDGE_PORT,
    apps_port: int = APPS_BRIDGE_PORT,
    open_app_port: int = OPEN_APP_PORT,
    egress_port: int = EGRESS_PROXY_PORT,
    dns_servers=(),
) -> str:
    """Forward rules owned by stickllm-agent. dockerd is started with --iptables=false.

    Default-deny egress from the Agent Zero container (v0.5.3 hardening):

    - Always drop cloud metadata (169.254.0.0/16, 100.100.100.200) and all IPv6.
    - Always drop other RFC1918 (LAN) except the agent bridge and LAN DNS.
    - Allow DNS to the container's configured resolvers (LAN + public).
    - Allow TCP to the host egress proxy on the bridge gateway (HTTP_PROXY).
      The proxy is what lets SearXNG / web search out when enabled; uploads and
      always-blocked hosts are refused there.
    - Everything else from the bridge is dropped (no raw internet).

    From the bridge, the host accepts only the llama relay, the static apps
    server, the open-app control port, and the egress proxy. Loopback still
    reaches the relay for the host health check. LAN clients cannot open those
    ports, and the container cannot open any other host port.
    """
    ports = f"{{ {int(llama_port)}, {int(apps_port)}, {int(open_app_port)}, {int(egress_port)} }}"
    dns_all = []
    for raw in dns_servers or ():
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if ip.version == 4 and not ip.is_loopback and str(ip) not in dns_all:
            dns_all.append(str(ip))
    dns_rules = ""
    if dns_all:
        dset = "{ " + ", ".join(dns_all) + " }"
        dns_rules = f"    ip daddr {dset} udp dport 53 accept\n    ip daddr {dset} tcp dport 53 accept\n"
    return (
        f"table inet {NFT_TABLE} {{\n"
        "  chain forward {\n"
        "    type filter hook forward priority 0; policy accept;\n"
        f'    iifname "{bridge}" jump agent_out\n'
        "  }\n"
        "  chain agent_out {\n"
        "    ct state established,related accept\n"
        f"    ip daddr {subnet} accept\n"
        "    ip daddr 169.254.0.0/16 drop\n"
        "    ip daddr 100.100.100.200 drop\n"
        + dns_rules +
        "    ip daddr 192.168.0.0/16 drop\n"
        "    ip daddr 10.0.0.0/8 drop\n"
        "    ip daddr 172.16.0.0/12 drop\n"
        "    meta nfproto ipv6 drop\n"
        f"    ip daddr {gateway} tcp dport {int(egress_port)} accept\n"
        "    drop\n"
        "  }\n"
        "  chain input {\n"
        "    type filter hook input priority 0; policy accept;\n"
        '    iifname "lo" accept\n'
        f'    iifname "{bridge}" ct state established,related accept\n'
        f'    iifname "{bridge}" ip daddr {gateway} tcp dport {ports} accept\n'
        f'    iifname "{bridge}" drop\n'
        f"    ip daddr {gateway} tcp dport {ports} drop\n"
        "  }\n"
        "  chain postrouting {\n"
        "    type nat hook postrouting priority srcnat; policy accept;\n"
        f'    ip saddr {subnet} oifname != "{bridge}" masquerade\n'
        "  }\n"
        "}\n"
    )


def nft_apply_text(dns_servers=None) -> str:
    """Ruleset script for ``nft -f``.

    Debian 12 ships nftables 1.0.6, which rejects ``destroy table`` (added in
    1.0.8) and then refuses the rest of the file. ``add`` plus ``delete`` is
    the older idempotent prelude: it creates the table when missing, then
    drops it so the definition below is a clean load.
    """
    return (
        f"add table inet {NFT_TABLE}\n"
        f"delete table inet {NFT_TABLE}\n"
        + nft_ruleset(dns_servers=host_dns_servers() if dns_servers is None else dns_servers)
    )


def nft_apply() -> int:
    # A second start still has the table. ``add table`` fails with "File
    # exists" on 1.0.6 unless it was removed first. "No such file" is success.
    nft_delete()
    text = nft_apply_text()
    proc = subprocess.run(
        ["nft", "-f", "-"],
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "nft failed").strip()
        print(err, file=sys.stderr)
    return proc.returncode


def nft_delete() -> int:
    proc = subprocess.run(
        ["nft", "delete", "table", "inet", NFT_TABLE],
        capture_output=True,
        text=True,
        check=False,
    )
    return 0 if proc.returncode in (0, 1) else proc.returncode



def _load_egress_scan():
    """Import stickllm_egress_scan from disk (ISO path or test override)."""
    import importlib.util
    path = EGRESS_SCAN_LIB
    if not path.is_file():
        raise FileNotFoundError(str(path))
    spec = importlib.util.spec_from_file_location("stickllm_egress_scan", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def agent_web_fetch_enabled(settings: Path | None = None) -> bool:
    """Whether the agent egress proxy may fetch the public web (SearXNG).

    Default True so Agent Zero's built-in search works. Set
    ``{"web_fetch": false}`` in the portable egress.json to shut it off.
    Metadata, Alibaba Cloud, and uploads stay blocked either way.
    """
    root = settings if settings is not None else PORTABLE
    for path in (root / "egress.json", Path("/run/stickllm/agent-egress.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(doc, dict) and "web_fetch" in doc:
            return bool(doc["web_fetch"])
    return True


_EGRESS_LOCK = threading.Lock()
_EGRESS_EVENTS: list[dict] = []


def record_egress_event(obj: dict) -> None:
    """Persist a blocked (or noted) outbound attempt. Never stores secrets."""
    item = {
        "ts": int(obj.get("ts") or time.time()),
        "tool": str(obj.get("tool") or "")[:80],
        "findings": list(obj.get("findings") or [])[:8],
        "via": str(obj.get("via") or "agent")[:40],
    }
    with _EGRESS_LOCK:
        _EGRESS_EVENTS.append(item)
        del _EGRESS_EVENTS[:-32]
        snapshot = list(_EGRESS_EVENTS)
    try:
        EGRESS_EVENTS.parent.mkdir(parents=True, exist_ok=True)
        EGRESS_EVENTS.write_text(json.dumps({"events": snapshot}) + "\n", encoding="utf-8")
        os.chmod(EGRESS_EVENTS, 0o644)
    except OSError:
        return


def read_egress_events() -> list[dict]:
    with _EGRESS_LOCK:
        if _EGRESS_EVENTS:
            return list(_EGRESS_EVENTS)
    try:
        doc = json.loads(EGRESS_EVENTS.read_text(encoding="utf-8"))
        events = doc.get("events") if isinstance(doc, dict) else None
        return list(events) if isinstance(events, list) else []
    except (OSError, ValueError, TypeError):
        return []


def _egress_host_allowed(host: str, method: str, web_fetch: bool) -> str:
    """Empty string when the proxy may continue; else a short reason."""
    try:
        scan = _load_egress_scan()
    except Exception:
        # Fail closed if the scanner is missing.
        return "egress scanner unavailable"
    h = scan.norm_host(host)
    reason = scan.always_blocked(h) or scan.default_blocked(h)
    if reason:
        return reason
    if scan.is_local(h):
        return "proxy must not target the stick itself"
    if not web_fetch:
        return "web fetch is off for the agent"
    m = (method or "GET").upper()
    if m in ("PUT", "PATCH", "DELETE"):
        return "uploads and mutating methods are blocked from the agent"
    return ""


def run_egress_proxy(listen_host: str = LLAMA_BRIDGE_HOST, listen_port: int = EGRESS_PROXY_PORT) -> None:
    """HTTP/HTTPS CONNECT proxy for the Agent Zero container only.

    Listens on the stickllm-a0 bridge address. The container is pointed at it
    with HTTP_PROXY/HTTPS_PROXY. Direct internet from the container is dropped
    by nftables; this is the only way out, and it refuses metadata, Alibaba
    Cloud, and uploads.
    """
    if listen_host in ("0.0.0.0", "::", ""):
        raise SystemExit("egress proxy must not listen on all interfaces")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((listen_host, int(listen_port)))
    srv.listen(64)

    def pump(a: socket.socket, b: socket.socket) -> None:
        try:
            while True:
                data = a.recv(65536)
                if not data:
                    break
                b.sendall(data)
        except OSError:
            pass
        try:
            b.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    def handle(conn: socket.socket, addr) -> None:
        peer = addr[0] if addr else ""
        try:
            # Only accept clients on the agent bridge.
            if not (peer.startswith("172.30.0.") and peer != LLAMA_BRIDGE_HOST):
                conn.close()
                return
            conn.settimeout(30)
            buf = b""
            while b"\r\n\r\n" not in buf and len(buf) < 65536:
                chunk = conn.recv(4096)
                if not chunk:
                    conn.close()
                    return
                buf += chunk
            head, _, rest = buf.partition(b"\r\n\r\n")
            lines = head.decode("latin-1", "replace").split("\r\n")
            if not lines:
                conn.close()
                return
            parts = lines[0].split()
            if len(parts) < 2:
                conn.close()
                return
            method, target = parts[0].upper(), parts[1]
            headers = {}
            for line in lines[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            web = agent_web_fetch_enabled()
            if method == "CONNECT":
                hostport = target
                host, _, port_s = hostport.partition(":")
                port = int(port_s or "443")
                reason = _egress_host_allowed(host, "CONNECT", web)
                if reason or port not in (443, 80):
                    record_egress_event({
                        "tool": "proxy",
                        "via": "connect",
                        "findings": [{"kind": "proxy", "target": hostport, "reason": reason or "port not allowed"}],
                    })
                    conn.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                    conn.close()
                    return
                remote = socket.create_connection((host, port), timeout=20)
                conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                t = threading.Thread(target=pump, args=(conn, remote), daemon=True)
                t.start()
                pump(remote, conn)
                try:
                    remote.close()
                except OSError:
                    pass
                conn.close()
                return
            # Absolute-form HTTP proxy request: GET http://host/path
            if not target.startswith("http://") and not target.startswith("https://"):
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                conn.close()
                return
            from urllib.parse import urlsplit, urlunsplit
            split = urlsplit(target)
            host = split.hostname or ""
            port = split.port or (443 if split.scheme == "https" else 80)
            reason = _egress_host_allowed(host, method, web)
            if reason:
                record_egress_event({
                    "tool": "proxy",
                    "via": "http",
                    "findings": [{"kind": "proxy", "target": host, "reason": reason}],
                })
                body = (reason + "\n").encode()
                conn.sendall(
                    b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\n"
                    + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                    + body
                )
                conn.close()
                return
            path = urlunsplit(("", "", split.path or "/", split.query, split.fragment))
            if not path.startswith("/"):
                path = "/" + path
            out_headers = []
            for line in lines[1:]:
                low = line.lower()
                if low.startswith("proxy-") or low.startswith("connection:"):
                    continue
                out_headers.append(line)
            out_headers.append("Connection: close")
            out_headers.append(f"Host: {host}" if not any(h.lower().startswith("host:") for h in out_headers) else "")
            out_headers = [h for h in out_headers if h]
            req = f"{method} {path} HTTP/1.1\r\n" + "\r\n".join(out_headers) + "\r\n\r\n"
            remote = socket.create_connection((host, port), timeout=20)
            if split.scheme == "https":
                import ssl
                remote = ssl.create_default_context().wrap_socket(remote, server_hostname=host)
            remote.sendall(req.encode("latin-1") + rest)
            # Forward any remaining request body for POST (search engines).
            cl = int(headers.get("content-length") or 0)
            have = len(rest)
            while have < cl:
                chunk = conn.recv(min(65536, cl - have))
                if not chunk:
                    break
                remote.sendall(chunk)
                have += len(chunk)
            while True:
                data = remote.recv(65536)
                if not data:
                    break
                conn.sendall(data)
            try:
                remote.close()
            except OSError:
                pass
            conn.close()
        except Exception:
            try:
                conn.close()
            except OSError:
                pass

    while True:
        c, a = srv.accept()
        threading.Thread(target=handle, args=(c, a), daemon=True).start()


def block_add_hosts() -> list[str]:
    """docker --add-host lines that sinkhole always-blocked names to loopback."""
    out = []
    for host in ALWAYS_BLOCK_HOSTS:
        if host in ("metadata",):  # too generic as a hosts entry alone is fine
            pass
        out.append(f"{host}:127.0.0.1")
    # Also pin common metadata IPv6 name when resolvers invent AAAA (IPv6 is dropped anyway).
    return out


NO_MODEL_MESSAGE = (
    "No AI model is loaded on StickLLM right now, so I can't answer yet. "
    "Open Models on the StickLLM home screen, load a model, wait until it shows Running, "
    "then send your message again."
)


def no_model_reply(request: bytes) -> bytes:
    """HTTP reply the llama relay sends when llama-server is not listening.

    Chat completions get a normal answer in Agent Zero's tool format (the
    response tool), so the chat shows a plain sentence instead of a
    "connection refused" traceback. Streaming requests get server-sent events.
    Anything else gets 503 with an OpenAI-style error.
    """
    head, _, body = request.partition(b"\r\n\r\n")
    line = head.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    parts = line.split()
    path = parts[1] if len(parts) > 1 else "/"
    try:
        doc = json.loads(body.decode("utf-8", "replace") or "{}")
    except ValueError:
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    model = str(doc.get("model") or "stickllm")[:120]
    if not path.split("?", 1)[0].rstrip("/").endswith("/chat/completions"):
        payload = json.dumps({"error": {"message": NO_MODEL_MESSAGE, "type": "no_model_loaded",
                                        "code": 503}}).encode("utf-8")
        return (b"HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\n"
                b"Content-Length: " + str(len(payload)).encode() + b"\r\nConnection: close\r\n\r\n" + payload)
    text = json.dumps({
        "thoughts": ["No model is loaded on StickLLM."],
        "headline": "No model loaded",
        "tool_name": "response",
        "tool_args": {"text": NO_MODEL_MESSAGE},
    })
    created = int(time.time())
    if doc.get("stream"):
        chunks = [
            {"id": "stickllm-no-model", "object": "chat.completion.chunk", "created": created, "model": model,
             "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}]},
            {"id": "stickllm-no-model", "object": "chat.completion.chunk", "created": created, "model": model,
             "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        ]
        payload = b"".join(b"data: " + json.dumps(c).encode("utf-8") + b"\n\n" for c in chunks) + b"data: [DONE]\n\n"
        ctype = b"text/event-stream"
    else:
        payload = json.dumps({
            "id": "stickllm-no-model", "object": "chat.completion", "created": created, "model": model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }).encode("utf-8")
        ctype = b"application/json"
    return (b"HTTP/1.1 200 OK\r\nContent-Type: " + ctype + b"\r\nContent-Length: " + str(len(payload)).encode()
            + b"\r\nConnection: close\r\n\r\n" + payload)


def _read_request(client: socket.socket, limit: int = 4 * 1024 * 1024) -> bytes:
    """Read one HTTP request (headers + Content-Length body) or what arrives in 5 s."""
    client.settimeout(5)
    data = b""
    try:
        while b"\r\n\r\n" not in data and len(data) < limit:
            got = client.recv(65536)
            if not got:
                return data
            data += got
        head, _, body = data.partition(b"\r\n\r\n")
        length = 0
        for raw in head.split(b"\r\n")[1:]:
            name, _, value = raw.partition(b":")
            if name.strip().lower() == b"content-length":
                try:
                    length = int(value.strip())
                except ValueError:
                    length = 0
        while len(body) < min(length, limit):
            got = client.recv(65536)
            if not got:
                break
            body += got
        return head + b"\r\n\r\n" + body
    except OSError:
        return data


def run_tcp_relay(listen_host: str, listen_port: int, target_host: str, target_port: int) -> None:
    """Copy bytes between a bridge listener and llama-server. Does not bind 0.0.0.0."""
    if listen_host in ("0.0.0.0", "::", ""):
        raise SystemExit("llama relay must not listen on all interfaces")
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((listen_host, listen_port))
    srv.listen(64)

    def pump(src: socket.socket, dst: socket.socket) -> None:
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except OSError:
            pass
        try:
            dst.shutdown(socket.SHUT_WR)
        except OSError:
            pass

    def handle(client: socket.socket) -> None:
        try:
            upstream = socket.create_connection((target_host, target_port), timeout=10)
        except OSError:
            # llama-server is not listening: no model loaded (or still
            # starting). Answer in plain words instead of dropping the call.
            try:
                req = _read_request(client)
                if req:
                    client.sendall(no_model_reply(req))
            except OSError:
                pass
            client.close()
            return
        upstream.settimeout(None)
        left = threading.Thread(target=pump, args=(client, upstream), daemon=True)
        right = threading.Thread(target=pump, args=(upstream, client), daemon=True)
        left.start()
        right.start()
        left.join()
        right.join()
        try:
            client.close()
        except OSError:
            pass
        try:
            upstream.close()
        except OSError:
            pass

    while True:
        try:
            conn, _addr = srv.accept()
        except OSError:
            return
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


_APPS_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".txt": "text/plain; charset=utf-8",
    ".map": "application/json",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".wasm": "application/wasm",
}


def apps_ui_root() -> Path:
    """Host directory of static apps. Not the vault, home, or the chat UI."""
    return Path(os.environ.get("STICKLLM_UI", "/opt/stickllm/ui")) / "apps"


def apps_target(root: Path, raw_path: str) -> Path | None:
    """Map /apps/<id>/... onto a file under root. Anything else is absent."""
    parsed = urllib.parse.urlsplit(raw_path or "")
    path = urllib.parse.unquote(parsed.path or "")
    if path != "/apps" and not path.startswith("/apps/"):
        return None
    rel = path[len("/apps") :].lstrip("/")
    parts = [part for part in rel.split("/") if part]
    if any(part in {".", ".."} for part in parts):
        return None
    try:
        base = root.resolve()
        target = base.joinpath(*parts).resolve() if parts else base
        if target != base and base not in target.parents:
            return None
        if target.is_dir():
            target = (target / "index.html").resolve()
        if target != base and base not in target.parents:
            return None
        if not target.is_file():
            return None
    except OSError:
        return None
    return target


def apps_prompt_text() -> str:
    """Always-included profile note. The URL id is minesweeper; the label is minesweep."""
    lines = [
        "{{include original}}",
        "",
        "## StickLLM apps",
        APPS_NOTE,
        "The desktop label minesweep uses URL id minesweeper: "
        "http://172.30.0.1:8081/apps/minesweeper/",
        "URL ids and no others:",
    ]
    for app_id in APPS_URL_IDS:
        lines.append(f"- {app_id}: http://172.30.0.1:8081/apps/{app_id}/")
    lines.append(OPEN_APP_RULE)
    lines.append(
        "open_app takes an id only. The desktop label minesweep is id minesweeper. "
        "Do not pass a URL, a path, or any id outside this list."
    )
    lines.append(
        "Fetch only these static pages. Do not use other host ports or LAN addresses."
    )
    lines.append(
        "Installed catalog apps (docs = ONLYOFFICE, tasks-md, paisa, trilium, node-red, comfyui) "
        "open with open_app too; install_app asks the user to install one. "
        "Make documents with create_spreadsheet / create_document, open them with open_document."
    )
    lines.append(NO_GUI_RULE)
    return "\n".join(lines) + "\n"


APP_PLAY_RULE = (
    "Use open_app / app_state / app_act for StickLLM apps. "
    "Never use your own browser or external sites for them. "
    "At most 30 actions, then summarise."
)
APP_ACTIONS_TEXT = (
    "Minesweeper: {\"reveal\":[row,col]} or {\"flag\":[row,col]}.\n"
    "Solitaire: {\"move\":\"t3->f1\"}, {\"move\":\"t2->t5\",\"card\":\"9H\"}, "
    "{\"draw\":true}, {\"click\":\"t4\"}, {\"undo\":true}, or {\"new_game\":true}. "
    "Piles are stock, waste, f1-f4 (foundations), t1-t7 (tableau). "
    "Cards are rank A 2-9 T J Q K plus suit S H D C; # is face down; the last card is on top. "
    "An illegal move returns ok false and changes nothing.\n"
    "Tetris: {\"new_game\":true}, then {\"place\":\"suggested\"} or "
    "{\"place\":{\"col\":3,\"rot\":1}} (rotate, shift so the piece's leftmost cell is in col, hard drop). "
    "Also {\"left\":2}, {\"right\":1}, {\"rotate\":1}, {\"soft_drop\":1}, {\"hard_drop\":true}, "
    "{\"pause\":true}, {\"resume\":true}. "
    "Turn mode: after your first action the piece does not fall on its own, so take your time. "
    "{\"mode\":\"realtime\"} turns gravity back on. "
    "state has board (20 rows x 10 cols, # settled), view (@ = falling piece), current, next, "
    "rotations (cols each rotation can use), and suggest (a good placement). "
    "Cols are 0-9.\n"
    "Notepad: {\"set_text\":\"...\"} or {\"save_as\":\"notes.txt\"}.\n"
    "Calculator: {\"expr\":\"12+3=\"}.\n"
)


def apps_skill_text() -> str:
    body = apps_prompt_text().split("## StickLLM apps\n", 1)[1]
    return (
        "---\n"
        "name: stickllm-apps\n"
        "description: Play StickLLM apps on the user's screen with open_app, "
        "app_state, and app_act. URL ids are minesweeper, solitaire, tetris, "
        "notepad, calculator, files, media, and monitor. The desktop label "
        "minesweep is URL id minesweeper.\n"
        "---\n\n"
        + APP_PLAY_RULE
        + "\n\n"
        + OPEN_APP_RULE
        + "\n\n"
        + APPS_PLAYABLE_NOTE
        + "\n\n"
        + "Actions for app_act:\n"
        + APP_ACTIONS_TEXT
        + "\n"
        + body
    )


NO_GUI_RULE = (
    "Your container has no screen. Never start GUI programs or office suites "
    "(libreoffice, soffice, onlyoffice, xdg-open, firefox, chromium, gedit, "
    "x11 or vnc tools) with code_execution or the terminal, and do not apt/pip "
    "install them. To make or show a document use create_spreadsheet, "
    "create_document and open_document; to open an app use open_app."
)
TOOL_RETRY_RULE = (
    "If one of these StickLLM tools fails twice for the same request, stop "
    "retrying: tell the user what failed and what they can do."
)


def _guarded_tool_source(class_name: str, tool_name: str, path: str, fields: tuple[str, ...], fixed: dict) -> str:
    """Agent Zero tool that POSTs its args to the open-app control (8082).

    Loop guard: the same failing call is refused after two tries, so a small
    model cannot spin on it.
    """
    return f'''from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from helpers.tool import Response, Tool

_TOKEN_FILE = Path("/stickllm-open-app.token")
_URL = "http://172.30.0.1:8082{path}"
_FIELDS = {fields!r}
_FIXED = {fixed!r}
_FAILS: dict = {{}}
_MAX_TRIES = 2


class {class_name}(Tool):
    async def execute(self, **kwargs):
        args = self.args if isinstance(self.args, dict) else {{}}
        payload = dict(_FIXED)
        for key in _FIELDS:
            if key in args:
                payload[key] = args[key]
            elif key in kwargs:
                payload[key] = kwargs[key]
        sig = json.dumps(payload, sort_keys=True, default=str)[:2000]
        if _FAILS.get(sig, 0) >= _MAX_TRIES:
            return Response(
                message="{tool_name} already failed twice for this request. Do not call it again; "
                "tell the user what went wrong.",
                break_loop=False,
            )
        try:
            token = _TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            token = ""
        if not token:
            return Response(message="{tool_name} failed: control token is missing", break_loop=False)
        request = urllib.request.Request(
            _URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={{"Authorization": "Bearer " + token, "Content-Type": "application/json"}},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as resp:
                raw = resp.read().decode("utf-8", "replace")
            ok = True
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")[:600]
            ok = False
        except Exception as exc:
            raw = "{tool_name} failed: " + str(exc)
            ok = False
        if not ok:
            _FAILS[sig] = _FAILS.get(sig, 0) + 1
            left = _MAX_TRIES - _FAILS[sig]
            raw = raw.strip() + (" (one retry left)" if left > 0 else " (do not retry; tell the user)")
        else:
            _FAILS.pop(sig, None)
        return Response(message=raw.strip() or "ok", break_loop=False)
'''


def install_app_tool_source() -> str:
    return _guarded_tool_source("InstallApp", "install_app", "/install", ("id",), {})


def create_spreadsheet_tool_source() -> str:
    return _guarded_tool_source("CreateSpreadsheet", "create_spreadsheet", "/docs", ("name", "rows", "open"), {"op": "create", "kind": "xlsx"})


def create_document_tool_source() -> str:
    return _guarded_tool_source("CreateDocument", "create_document", "/docs", ("name", "title", "text", "open"), {"op": "create", "kind": "docx"})


def open_document_tool_source() -> str:
    return _guarded_tool_source("OpenDocument", "open_document", "/docs", ("path",), {"op": "open"})


def install_app_tool_prompt() -> str:
    names = "; ".join(f"{k} = {v}" for k, v in CATALOG_APP_NAMES.items())
    return (
        "### install_app\n"
        "Ask the user to install a StickLLM app. Ids: " + names + ".\n"
        "Nothing installs until the user clicks Install on their own screen (the StickLLM "
        "tab they chat from, else the stick's screen). The reply says whether it is already "
        "installed or waiting for that click. When waiting, tell the user to click Install "
        "and stop; do not call install_app again for the same app in this task.\n"
        "Every app is hash pinned. The reply's verification is verified, changed (upstream "
        "changed: only the last verified version can be installed, the screen offers it) or "
        "unverified (the screen warns first). Tell the user which one it is; never try to "
        "get around the warning or the confirm.\n"
        "Never install apps yourself with code_execution, apt, pip, docker or podman.\n"
        + TOOL_RETRY_RULE + "\n\n"
        'Example: {"tool_name":"install_app","tool_args":{"id":"docs"}}\n'
    )


def docs_tools_prompt() -> str:
    return (
        "### create_spreadsheet\n"
        "Make an .xlsx in the user's vault (vault/Documents) and open it in ONLYOFFICE on the "
        "user's screen. rows is a list of rows; each row is a list of cells (numbers stay "
        "numbers, text, or formulas starting with =). Column A is the first cell of each row.\n"
        'Example (numbers 1 to 10 in column A): {"tool_name":"create_spreadsheet","tool_args":'
        '{"name":"Numbers","rows":[[1],[2],[3],[4],[5],[6],[7],[8],[9],[10]]}}\n\n'
        "### create_document\n"
        "Make a .docx in vault/Documents and open it in ONLYOFFICE. text is the body; each "
        "line becomes a paragraph. title is optional.\n"
        'Example: {"tool_name":"create_document","tool_args":{"name":"Letter","title":"Hello","text":"Line one\\nLine two"}}\n\n'
        "### open_document\n"
        "Open an existing file from vault/Documents in ONLYOFFICE on the user's screen. "
        "path is relative to vault/Documents, as create_* returned it.\n"
        'Example: {"tool_name":"open_document","tool_args":{"path":"Numbers.xlsx"}}\n\n'
        "These tools need the vault unlocked. If the Office app is not installed the file is "
        "still saved; call install_app with id docs (the Office app) once and tell the user to click Install.\n"
        + NO_GUI_RULE + "\n" + TOOL_RETRY_RULE + "\n"
    )


def open_app_tool_prompt() -> str:
    ids = ", ".join(APPS_URL_IDS + CATALOG_APP_IDS)
    return (
        "### open_app\n"
        "Open or focus a StickLLM app in the user's browser tab.\n\n"
        + OPEN_APP_RULE
        + "\n\n"
        "The headless browser tool stays for your own page work. It does not "
        "show an app on the user's screen.\n"
        f"Allowed ids only: {ids}.\n"
        "The desktop label minesweep is id minesweeper. docs is the Office app (ONLYOFFICE); tasks-md, "
        "paisa, trilium, node-red and comfyui are add-ons and open only once installed "
        "(otherwise use install_app).\n"
        "Pass the id and nothing else. Reject URLs and paths yourself by not sending them.\n"
        + NO_GUI_RULE + "\n\n"
        'Example: {"tool_name":"open_app","tool_args":{"id":"minesweeper"}}\n'
    )


def open_app_plugin_yaml() -> str:
    return (
        "name: stickllm_apps\n"
        "title: StickLLM apps\n"
        "description: Open a StickLLM app on the user's screen.\n"
        "version: 1.0.0\n"
        "settings_sections: []\n"
        "per_project_config: false\n"
        "per_agent_config: false\n"
        "always_enabled: true\n"
    )


def open_app_tool_source() -> str:
    """Plugin tool loaded from /a0/usr/plugins. The token stays in a mounted file."""
    return '''from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from helpers.tool import Response, Tool

_TOKEN_FILE = Path("/stickllm-open-app.token")
_OPEN_URL = "http://172.30.0.1:8082/open"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class OpenApp(Tool):
    async def execute(self, id: str = "", **kwargs):
        app_id = self.args.get("id") if isinstance(self.args, dict) else None
        if not isinstance(app_id, str) or not app_id.strip():
            app_id = id if isinstance(id, str) else ""
        app_id = str(app_id or "").strip()
        try:
            token = _TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            return Response(message="open_app failed: control token is missing", break_loop=False)
        if not token:
            return Response(message="open_app failed: control token is missing", break_loop=False)
        body = json.dumps({"id": app_id}).encode("utf-8")
        request = urllib.request.Request(
            _OPEN_URL,
            data=body,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            with opener.open(request, timeout=2) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            return Response(
                message=f"open_app failed: HTTP {exc.code} {detail}",
                break_loop=False,
            )
        except Exception as exc:
            return Response(message=f"open_app failed: {exc}", break_loop=False)
        return Response(message=raw.strip() or "opened", break_loop=False)
'''


def ensure_open_app_plugin(root: Path | None = None) -> None:
    """Write the v2.14 plugin into the assembled plugin dir. No token is stored here.

    The assembled dir (ADDON/plugins) is mounted read-only at /a0/usr/plugins.
    """
    if not vault_mounted():
        return
    if root is None:
        root = PLUGINS_RO / "stickllm_apps"
    egress_scan = ""
    egress_ext = ""
    try:
        if EGRESS_SCAN_LIB.is_file():
            egress_scan = EGRESS_SCAN_LIB.read_text(encoding="utf-8")
        if EGRESS_EXT_SRC.is_file():
            egress_ext = EGRESS_EXT_SRC.read_text(encoding="utf-8")
    except OSError:
        egress_scan = egress_ext = ""
    files = {
        root / "plugin.yaml": open_app_plugin_yaml(),
        root / "tools" / "open_app.py": open_app_tool_source(),
        root / "tools" / "app_state.py": app_state_tool_source(),
        root / "tools" / "app_act.py": app_act_tool_source(),
        root / "prompts" / "agent.system.tool.open_app.md": open_app_tool_prompt(),
        root / "prompts" / "agent.system.tool.app_state.md": app_state_tool_prompt(),
        root / "prompts" / "agent.system.tool.app_act.md": app_act_tool_prompt(),
        root / "tools" / "install_app.py": install_app_tool_source(),
        root / "tools" / "create_spreadsheet.py": create_spreadsheet_tool_source(),
        root / "tools" / "create_document.py": create_document_tool_source(),
        root / "tools" / "open_document.py": open_document_tool_source(),
        root / "prompts" / "agent.system.tool.install_app.md": install_app_tool_prompt(),
        root / "prompts" / "agent.system.tool.docs.md": docs_tools_prompt(),
        root / "skills" / "stickllm-apps" / "SKILL.md": apps_skill_text(),
    }
    if egress_scan:
        files[root / "helpers" / "egress_scan.py"] = egress_scan
    if egress_ext:
        files[root / "extensions" / "python" / "tool_execute_before" / "_30_stickllm_egress.py"] = egress_ext
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        current = ""
        if path.is_file():
            current = path.read_text(encoding="utf-8", errors="replace")
        if current != text:
            path.write_text(text, encoding="utf-8")
            try:
                os.chmod(path, 0o644)
            except OSError:
                pass


def ensure_apps_instructions() -> None:
    """Write the apps note onto mounts the container already has.

    The profile prompt is under the vault state directory that is already
    mounted at /a0/usr. The skill is on the settings partition mounted at
    /a0/usr/skills. No new host path is mounted.
    """
    if vault_mounted():
        prompt_dir = ADDON / "state" / "agents" / "agent0" / "prompts"
        prompt_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = prompt_dir / "agent.system.main.specifics.md"
        text = apps_prompt_text()
        current = ""
        if prompt_path.is_file():
            current = prompt_path.read_text(encoding="utf-8", errors="replace")
        if current != text:
            prompt_path.write_text(text, encoding="utf-8")
    if settings_mounted():
        skill_dir = PORTABLE / "skills" / "stickllm-apps"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"
        text = apps_skill_text()
        current = ""
        if skill_path.is_file():
            current = skill_path.read_text(encoding="utf-8", errors="replace")
        if current != text:
            skill_path.write_text(text, encoding="utf-8")
    # The stickllm_apps plugin is written by assemble_plugins (read-only dir).


def apps_server(listen_host: str, listen_port: int, root: Path | None = None) -> ThreadingHTTPServer:
    """Read-only static server for ui/apps. Refuses every interface address."""
    if listen_host in ("0.0.0.0", "::", ""):
        raise SystemExit("apps bridge must not listen on all interfaces")
    apps = root or apps_ui_root()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)

        def _serve(self) -> None:
            if self.command not in ("GET", "HEAD"):
                self._send(404, b"not found\n", "text/plain; charset=utf-8")
                return
            target = apps_target(apps, self.path)
            if target is None:
                self._send(404, b"not found\n", "text/plain; charset=utf-8")
                return
            try:
                data = target.read_bytes()
            except OSError:
                self._send(404, b"not found\n", "text/plain; charset=utf-8")
                return
            ctype = _APPS_TYPES.get(target.suffix.lower(), "application/octet-stream")
            self._send(200, data, ctype)

        def do_GET(self) -> None:
            self._serve()

        def do_HEAD(self) -> None:
            self._serve()

        def do_POST(self) -> None:
            self._send(404, b"not found\n", "text/plain; charset=utf-8")

        do_PUT = do_POST
        do_DELETE = do_POST
        do_PATCH = do_POST

        def log_message(self, fmt: str, *args: object) -> None:
            return

        def version_string(self) -> str:
            return "StickLLM"

    return ThreadingHTTPServer((listen_host, int(listen_port)), Handler)


def run_apps_bridge(listen_host: str, listen_port: int, root: Path | None = None) -> None:
    """Serve ui/apps on the bridge address. Read-only. No chat, vault, or control API."""
    srv = apps_server(listen_host, listen_port, root)
    try:
        srv.serve_forever()
    except OSError:
        return
    finally:
        try:
            srv.server_close()
        except OSError:
            pass


def open_app_token_file() -> Path:
    raw = os.environ.get("STICKLLM_OPEN_APP_TOKEN_FILE", "").strip()
    if raw:
        return Path(raw)
    settings = Path(os.environ.get("STICKLLM_SETTINGS_MNT", str(SETTINGS_MNT)))
    return settings / "agent-zero" / "open-app.token"


def ensure_open_app_token(path: Path | None = None) -> Path:
    """Create the stick token if needed. Never print it."""
    dest = path or open_app_token_file()
    dest.parent.mkdir(parents=True, exist_ok=True)
    current = ""
    if dest.is_file():
        current = dest.read_text(encoding="utf-8", errors="replace").strip()
    if len(current) < 24 or any(ch.isspace() for ch in current):
        current = secrets.token_urlsafe(32)
        dest.write_text(current + "\n", encoding="utf-8")
    try:
        os.chmod(dest, 0o600)
    except OSError:
        pass
    return dest


def read_open_app_token(path: Path | None = None) -> str:
    dest = path or open_app_token_file()
    try:
        return dest.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def open_app_token_ok(presented: str | None, expected: str) -> bool:
    """True only when the bearer matches. Missing and wrong tokens are refused."""
    if not expected or not presented:
        return False
    got = str(presented).strip()
    if got.lower().startswith("bearer "):
        got = got[7:].strip()
    if not got or len(got) != len(expected):
        return False
    return hmac.compare_digest(got, expected)


def open_app_id_ok(app_id: object) -> bool:
    """Allowlist of real app ids. Rejects labels, URLs, and path traversal."""
    if not isinstance(app_id, str):
        return False
    if app_id not in APPS_URL_IDS:
        return False
    if not app_id.isascii() or not app_id.isalpha() or not app_id.islower():
        return False
    return True


def normalize_app_id(app_id: object) -> str:
    """Lower-case id with the known aliases folded in ("" when not a string)."""
    if not isinstance(app_id, str):
        return ""
    text = app_id.strip().lower()
    return APP_ID_ALIASES.get(text, text)


_VERIFY = None


def app_blocked(app_id: object) -> bool:
    """Hard blocklist (stickllm_verify). Fails closed when it cannot load."""
    global _VERIFY
    try:
        if _VERIFY is None:
            import importlib.machinery
            import importlib.util

            path = Path(__file__).resolve().with_name("stickllm_verify.py")
            loader = importlib.machinery.SourceFileLoader("stickllm_verify_agent", str(path))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            mod = importlib.util.module_from_spec(spec)
            loader.exec_module(mod)
            _VERIFY = mod
        return bool(_VERIFY.app_blocked(app_id))
    except Exception:
        return True


def catalog_app_id_ok(app_id: object) -> bool:
    return isinstance(app_id, str) and app_id in CATALOG_APP_IDS and not app_blocked(app_id)


def open_target_ok(app_id: object) -> bool:
    """open_app ids: the static apps plus the catalog apps (docs, add-ons)."""
    return open_app_id_ok(app_id) or catalog_app_id_ok(app_id)


def open_app_window(app_id: str) -> str:
    return "stickllm-" + app_id


def catalog_app_path(app_id: str) -> str:
    return "/apps/docs/" if app_id == "docs" else ""


def open_app_path(app_id: str) -> str:
    return f"/apps/{app_id}/"


def open_app_page_ready(root: Path, app_id: str) -> bool:
    """True when the id is allowlisted and that app's index.html is on disk."""
    if not open_app_id_ok(app_id):
        return False
    try:
        base = root.resolve()
        target = (base / app_id / "index.html").resolve()
    except OSError:
        return False
    if base not in target.parents:
        return False
    return target.is_file()


def app_state_tool_prompt() -> str:
    return (
        "### app_state\n"
        "Read the visible StickLLM app tab. Returns JSON from window.stickllmApp.state().\n"
        "Call open_app first so the tab is on screen.\n"
        + APPS_PLAYABLE_NOTE
        + "\n"
        'Example: {"tool_name":"app_state","tool_args":{"id":"minesweeper"}}\n'
    )


def app_act_tool_prompt() -> str:
    return (
        "### app_act\n"
        "Act in the visible StickLLM app tab. Do not use the browser tool.\n"
        + APPS_PLAYABLE_NOTE
        + "\n"
        + APP_ACTIONS_TEXT
        + "At most 30 actions, then summarise.\n"
        'Example: {"tool_name":"app_act","tool_args":{"id":"minesweeper","action":{"reveal":[0,0]}}}\n'
    )


def _relay_tool_source(class_name: str, path: str, with_action: bool) -> str:
    action_lines = ""
    if with_action:
        action_lines = """
        action = self.args.get("action") if isinstance(self.args, dict) else None
        if not isinstance(action, dict):
            return Response(message="app_act failed: action must be an object", break_loop=False)
        payload["action"] = action
"""
    return f'''from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from helpers.tool import Response, Tool

_TOKEN_FILE = Path("/stickllm-open-app.token")
_URL = "http://172.30.0.1:8082{path}"


class {class_name}(Tool):
    async def execute(self, id: str = "", **kwargs):
        app_id = self.args.get("id") if isinstance(self.args, dict) else None
        if not isinstance(app_id, str) or not app_id.strip():
            app_id = id if isinstance(id, str) else ""
        app_id = str(app_id or "").strip()
        try:
            token = _TOKEN_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            return Response(message="{class_name} failed: control token is missing", break_loop=False)
        if not token:
            return Response(message="{class_name} failed: control token is missing", break_loop=False)
        payload = {{"id": app_id}}
{action_lines}        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            _URL,
            data=body,
            headers={{
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            }},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            return Response(message=f"{class_name} failed: HTTP {{exc.code}} {{detail}}", break_loop=False)
        except Exception as exc:
            return Response(message=f"{class_name} failed: {{exc}}", break_loop=False)
        return Response(message=raw.strip() or "ok", break_loop=False)
'''


def app_state_tool_source() -> str:
    return _relay_tool_source("AppState", "/state", False)


def app_act_tool_source() -> str:
    return _relay_tool_source("AppAct", "/act", True)


class AppNotInstalled(OSError):
    """open_app for a catalog app that is not installed (message for the agent)."""


AGENT_DOCS_MAX_BODY = 262144


# Bridge replies used to be 409 for every failed install/docs call. Use the
# gateway's own status when it sent one, else a code that fits the error. (v0.5.3)
_BRIDGE_ERROR_STATUS = {
    "bad_id": 400,
    "bad_op": 400,
    "bad_json": 400,
    "bad_action": 400,
    "bad_kind": 400,
    "bad_name": 400,
    "bad_rows": 400,
    "bad_path": 400,
    "unauthorized": 401,
    "apps_locked": 403,
    "not_found": 404,
    "vault_locked": 423,
    "unverified": 428,
    "blocked": 451,
    "bad_reply": 502,
    "ui_unavailable": 502,
}


def bridge_status(result: dict) -> int:
    """HTTP status for a gateway reply relayed by the bridge. Drops the private _http_status key."""
    upstream = result.pop("_http_status", None)
    if result.get("ok"):
        return 200
    if isinstance(upstream, int) and 400 <= upstream <= 599:
        return upstream
    return _BRIDGE_ERROR_STATUS.get(str(result.get("error") or ""), 409)


def gateway_post(name: str, body: dict, token: str, url: str | None = None, timeout: float = 15.0) -> dict:
    """POST to /api/ui/<name> on the loopback gateway; 4xx JSON reasons are returned, not raised."""
    target = url or os.environ.get("STICKLLM_OPEN_APP_NOTIFY", "http://127.0.0.1/api/ui/open-app")
    base = target[: -len("open-app")] if target.endswith("open-app") else target.rsplit("/", 1)[0] + "/"
    request = urllib.request.Request(
        base + name,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            data = json.loads(exc.read().decode("utf-8") or "{}")
        except (UnicodeError, ValueError, OSError):
            raise exc from None
        if not isinstance(data, dict):
            raise exc from None
        data["ok"] = False
        data["_http_status"] = exc.code
        return data
    if not isinstance(data, dict):
        raise OSError("ui returned a bad reply")
    return data


def notify_gateway_open_app(app_id: str, token: str, url: str | None = None) -> dict:
    """Tell the UI gateway, on loopback, to push the open-tab event."""
    target = url or os.environ.get("STICKLLM_OPEN_APP_NOTIFY", "http://127.0.0.1/api/ui/open-app")
    body = json.dumps({"id": app_id}).encode("utf-8")
    request = urllib.request.Request(
        target,
        data=body,
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1.5) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            try:
                why = json.loads(exc.read().decode("utf-8") or "{}")
            except (UnicodeError, ValueError, OSError):
                why = {}
            if isinstance(why, dict) and why.get("error") == "not_installed":
                raise AppNotInstalled(str(why.get("message") or "not installed")) from None
        raise
    data = json.loads(raw.decode("utf-8") or "{}")
    if not isinstance(data, dict) or not data.get("ok"):
        raise OSError("ui did not accept open_app")
    return data


def gateway_app_call(kind: str, app_id: str, token: str, action: dict | None = None, url: str | None = None) -> dict:
    """Ask the loopback gateway to relay state or an action to the visible tab."""
    target = url or os.environ.get("STICKLLM_OPEN_APP_NOTIFY", "http://127.0.0.1/api/ui/open-app")
    if target.endswith("open-app"):
        base = target[: -len("open-app")]
    else:
        base = target.rsplit("/", 1)[0] + "/"
    endpoint = base + ("app-act" if kind == "app_act" else "app-state")
    body_obj: dict = {"id": app_id}
    if action is not None:
        body_obj["action"] = action
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(body_obj).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        # The gateway answers 4xx/5xx with a JSON reason (illegal_move,
        # no_adapter, timeout, no_subscriber). Pass it on so the agent sees it.
        try:
            data = json.loads(exc.read().decode("utf-8") or "{}")
        except (UnicodeError, ValueError, OSError):
            raise exc from None
        if not isinstance(data, dict) or not data.get("error"):
            raise exc from None
        data["ok"] = False
        return data
    if not isinstance(data, dict):
        raise OSError("ui returned a bad app reply")
    return data


_OPEN_APP_LAST: dict = {}
_OPEN_APP_LOCK = threading.Lock()
_OPEN_APP_CHECKS: list[dict] = []


def record_open_app_check(peer: str, code: int, obj: dict) -> None:
    """Public result of a control call. Never includes the token."""
    item = {
        "code": int(code),
        "from": peer,
        "error": str(obj.get("error") or ""),
        "id": str(obj.get("id") or "") if obj.get("ok") else "",
        "dry_run": bool(obj.get("dry_run")),
    }
    with _OPEN_APP_LOCK:
        _OPEN_APP_CHECKS.append(item)
        del _OPEN_APP_CHECKS[:-8]
        snapshot = list(_OPEN_APP_CHECKS)
    try:
        path = Path("/run/stickllm/open-app-check.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"events": snapshot}) + "\n", encoding="utf-8")
        os.chmod(path, 0o644)
    except OSError:
        return


def open_app_server(
    listen_host: str,
    listen_port: int,
    root: Path | None = None,
    token_file: Path | None = None,
    notify=None,
    relay=None,
) -> ThreadingHTTPServer:
    """Token-authenticated open_app control. Refuses every interface address."""
    if listen_host in ("0.0.0.0", "::", ""):
        raise SystemExit("open app control must not listen on all interfaces")
    apps = root or apps_ui_root()
    token_path = token_file or open_app_token_file()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code: int, obj: dict) -> None:
            if urllib.parse.urlsplit(self.path).path == "/open":
                peer = self.client_address[0] if self.client_address else ""
                record_open_app_check(peer, code, obj)
            body = (json.dumps(obj) + "\n").encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)

        def _token(self) -> str:
            return read_open_app_token(token_path)

        def _authorized(self) -> bool:
            return open_app_token_ok(self.headers.get("Authorization"), self._token())

        def do_GET(self) -> None:  # noqa: N802
            path = urllib.parse.urlsplit(self.path).path
            if path != "/last":
                self._send(404, {"ok": False, "error": "not_found"})
                return
            if not self._authorized():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            with _OPEN_APP_LOCK:
                last = dict(_OPEN_APP_LAST)
            self._send(200, {"ok": True, "last": last})

        def do_POST(self) -> None:  # noqa: N802
            path = urllib.parse.urlsplit(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            limit = AGENT_DOCS_MAX_BODY if path == "/docs" else 8192
            if length < 0 or length > limit:
                self._send(413, {"ok": False, "error": "too_large"})
                return
            raw = self.rfile.read(length) if length else b""
            if path not in ("/open", "/state", "/act", "/install", "/docs", "/egress-event"):
                self._send(404, {"ok": False, "error": "not_found"})
                return
            if not self._authorized():
                self._send(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                req = json.loads(raw.decode("utf-8") or "{}")
            except (UnicodeError, json.JSONDecodeError):
                self._send(400, {"ok": False, "error": "bad_json"})
                return
            if not isinstance(req, dict):
                self._send(400, {"ok": False, "error": "bad_json"})
                return
            if path == "/egress-event":
                if not isinstance(req, dict):
                    self._send(400, {"ok": False, "error": "bad_json"})
                    return
                record_egress_event({**req, "via": "bridge"})
                self._send(200, {"ok": True})
                return
            if path in ("/install", "/docs"):
                if path == "/install":
                    app_id = normalize_app_id(req.get("id"))
                    if app_blocked(app_id):
                        self._send(403, {
                            "ok": False,
                            "error": "blocked_app",
                            "message": "That app is blocked on StickLLM and cannot be installed. "
                            "Tell the user; do not try another way. install_app ids: "
                            + ", ".join(CATALOG_APP_IDS) + ".",
                        })
                        return
                    if not catalog_app_id_ok(app_id):
                        self._send(400, {
                            "ok": False,
                            "error": "bad_id",
                            "message": "install_app ids: " + ", ".join(CATALOG_APP_IDS) + ".",
                        })
                        return
                    body = {"id": app_id}
                else:
                    op = req.get("op")
                    if op not in ("create", "open"):
                        self._send(400, {"ok": False, "error": "bad_op"})
                        return
                    body = {k: req[k] for k in ("op", "kind", "name", "rows", "text", "title", "path", "open") if k in req}
                try:
                    if relay is None:
                        result = gateway_post("install-request" if path == "/install" else "docs-agent", body, self._token())
                    else:
                        result = relay(path, body.get("id", ""), body)
                except Exception:
                    self._send(502, {"ok": False, "error": "ui_unavailable"})
                    return
                if not isinstance(result, dict):
                    result = {"ok": False, "error": "bad_reply"}
                self._send(bridge_status(result), result)
                return
            app_id = normalize_app_id(req.get("id"))
            if not open_target_ok(app_id):
                self._send(400, {"ok": False, "error": "bad_id"})
                return
            if not catalog_app_id_ok(app_id) and not open_app_page_ready(apps, app_id):
                self._send(404, {"ok": False, "error": "not_found"})
                return
            if path in ("/state", "/act"):
                if app_id not in APPS_PLAYABLE_IDS:
                    self._send(409, {
                        "ok": False,
                        "error": "no_adapter",
                        "id": app_id,
                        "hint": APPS_PLAYABLE_NOTE,
                    })
                    return
                action = req.get("action")
                if path == "/act" and not isinstance(action, dict):
                    self._send(400, {"ok": False, "error": "bad_action"})
                    return
                try:
                    if relay is None:
                        result = gateway_app_call(
                            "app_act" if path == "/act" else "app_state",
                            app_id,
                            self._token(),
                            action if path == "/act" else None,
                        )
                    else:
                        result = relay(path, app_id, action)
                except Exception:
                    self._send(502, {"ok": False, "error": "ui_unavailable"})
                    return
                if not isinstance(result, dict):
                    result = {"ok": False, "error": "bad_reply"}
                self._send(200 if result.get("ok") else 502, result)
                return
            peer = self.client_address[0] if self.client_address else ""
            opened = {
                "ok": True,
                "id": app_id,
                "path": catalog_app_path(app_id) if catalog_app_id_ok(app_id) else open_app_path(app_id),
                "window": open_app_window(app_id),
                "from": peer,
            }
            # dry_run checks the token and id without telling the UI to open a tab.
            if req.get("dry_run") is True:
                opened["dry_run"] = True
                with _OPEN_APP_LOCK:
                    _OPEN_APP_LAST.clear()
                    _OPEN_APP_LAST.update(opened)
                self._send(200, opened)
                return
            try:
                if notify is None:
                    notify_gateway_open_app(app_id, self._token())
                else:
                    notify(app_id)
            except AppNotInstalled as exc:
                self._send(409, {"ok": False, "error": "not_installed", "id": app_id, "message": str(exc)})
                return
            except Exception:
                self._send(502, {"ok": False, "error": "ui_unavailable"})
                return
            with _OPEN_APP_LOCK:
                _OPEN_APP_LAST.clear()
                _OPEN_APP_LAST.update(opened)
            self._send(200, opened)

        def do_PUT(self) -> None:  # noqa: N802
            self._send(404, {"ok": False, "error": "not_found"})

        do_DELETE = do_PUT
        do_PATCH = do_PUT

        def log_message(self, fmt: str, *args: object) -> None:
            return

        def version_string(self) -> str:
            return "StickLLM"

    return ThreadingHTTPServer((listen_host, int(listen_port)), Handler)


def run_open_app_bridge(
    hosts: tuple[str, ...] = (LLAMA_BRIDGE_HOST, "127.0.0.1"),
    listen_port: int = OPEN_APP_PORT,
) -> None:
    """Listen on the bridge and on loopback. Do not bind all interfaces."""
    for host in hosts:
        if host in ("0.0.0.0", "::", ""):
            raise SystemExit("open app control must not listen on all interfaces")
    servers = [open_app_server(host, listen_port) for host in hosts]
    threads: list[threading.Thread] = []
    for srv in servers[:-1]:
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    try:
        servers[-1].serve_forever()
    except OSError:
        return
    finally:
        for srv in servers:
            try:
                srv.shutdown()
            except OSError:
                pass
            try:
                srv.server_close()
            except OSError:
                pass


def read_status() -> dict:
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def pull_log_tail(limit: int = 40) -> str:
    try:
        data = PULL_LOG.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [ln for ln in data.replace("\r", "\n").splitlines() if ln.strip()]
    return "\n".join(lines[-limit:])


def write_status(state: str, **extra: object) -> dict:
    doc: dict = {"state": state}
    for key, value in extra.items():
        if key in ("api_key", "token", "password", "passcode"):
            continue
        doc[key] = value
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(doc) + "\n", encoding="utf-8")
        os.chmod(STATUS_PATH, 0o644)
    except OSError:
        pass
    return doc


def status_document(
    *,
    vault_open: bool,
    settings_open: bool,
    upstream_up: bool,
    saved: dict | None = None,
    mounts: list[str] | None = None,
) -> dict:
    saved = saved if saved is not None else read_status()
    image_present = bool(saved.get("image_present")) and vault_open
    low_space = bool(saved.get("low_space"))
    ssd = host_ssd_mounted() if mounts is None else bool(mounts)
    installing = saved.get("state") == "installing" and not upstream_up
    pull_failed = saved.get("state") == "pull_failed" and not upstream_up
    if not vault_open:
        message = "Unlock vault to use Agent"
        state = "locked"
    elif not settings_open:
        message = "Unlock the USB settings partition to use Agent"
        state = "settings_missing"
    elif not ssd:
        message = SSD_MISSING
        state = "no_ssd"
    elif low_space:
        message = LOW_SPACE_MESSAGE
        state = "low_space"
    elif installing:
        message = "Installing Agent Zero"
        state = "installing"
    elif pull_failed:
        message = "Agent Zero image pull failed"
        state = "pull_failed"
    elif not image_present and saved.get("state") != "error":
        message = NEEDS_INSTALL_MESSAGE
        state = "needs_install"
    elif not upstream_up and saved.get("state") == "error":
        detail = str(saved.get("message") or "").strip()
        message = detail or "Agent failed to start"
        state = "error"
    elif not image_present:
        message = NEEDS_INSTALL_MESSAGE
        state = "needs_install"
    elif not upstream_up:
        message = "Agent is starting"
        state = "starting"
    else:
        message = "Agent"
        state = "running"
    needs_install = (
        vault_open
        and settings_open
        and ssd
        and not image_present
        and not low_space
        and state not in ("installing", "error")
    )
    return {
        "ok": True,
        "state": state,
        "vault_unlocked": vault_open,
        "settings_mounted": settings_open,
        "host_ssd": ssd,
        "image_present": image_present,
        "running": bool(upstream_up) and vault_open and settings_open and ssd,
        "needs_install": needs_install,
        "egress_blocks": read_egress_events()[-8:],
        "web_fetch": agent_web_fetch_enabled(),
        "low_space": low_space,
        "message": message,
        "pull_log": pull_log_tail() if state in ("installing", "pull_failed") else "",
        "port": AGENT_PORT,
        "gateway_port": AGENT_TLS_PORT,
    }


def host_from_header(host_header: str) -> str:
    """Hostname from a Host header, without a port."""
    raw = (host_header or "").strip()
    if not raw:
        return ""
    if raw.startswith("["):
        end = raw.find("]")
        if end > 1:
            return raw[: end + 1]
        return ""
    if ":" in raw:
        host, sep, port = raw.rpartition(":")
        if sep and port.isdigit():
            return host
    return raw


def _safe_http_host(host: str) -> bool:
    if not host or host in {"0.0.0.0", "[::]", "::"}:
        return False
    if host.startswith("[") and host.endswith("]") and len(host) > 2:
        inner = host[1:-1]
        return ":" in inner and all(ch in "0123456789abcdefABCDEF:." for ch in inner)
    if len(host) > 253:
        return False
    labels = host.split(".")
    if not labels or any(not label or len(label) > 63 for label in labels):
        return False
    for label in labels:
        if label.startswith("-") or label.endswith("-"):
            return False
        if not all(ch.isalnum() or ch == "-" for ch in label):
            return False
    return True


def stickllm_home_url(host_header: str = "", fallback: str = "127.0.0.1") -> str:
    """StickLLM UI origin (https port 443). Never the Agent port."""
    host = host_from_header(host_header)
    if not _safe_http_host(host):
        host = fallback if _safe_http_host(fallback) else "127.0.0.1"
    return f"https://{host}/"


def _home_href(home: str | None) -> str:
    if isinstance(home, str):
        text = home.strip()
        if (
            text.startswith("https://")
            and text.endswith("/")
            and ":5443" not in text
            and not any(ch in text for ch in " \t\r\n\"'<>\\")
        ):
            return text
    return "https://127.0.0.1/"


def status_html(doc: dict, home: str | None = None) -> str:
    message = str(doc.get("message") or "Agent")
    href = _html(_home_href(home))
    refresh = ""
    if doc.get("state") in ("installing", "starting", "error"):
        refresh = '<meta http-equiv="refresh" content="2">'
    install = ""
    if doc.get("needs_install") or doc.get("state") == "pull_failed":
        install = (
            '<form method="post" action="/install">'
            '<button type="submit">Install Agent Zero</button>'
            "</form>"
            "<p>The image is stored on the host drive, next to your models. "
            "Memory and work stay in the vault.</p>"
        )
    log = str(doc.get("pull_log") or "")
    log_html = f"<pre>{_html(log)}</pre>" if log else ""
    heading = f"<h1>{_html(message)}</h1>"
    if doc.get("state") == "error":
        heading = "<h1>Agent failed to start</h1>"
        if message:
            log_html = f"<pre>{_html(message)}</pre>" + log_html
    if doc.get("state") in ("locked", "settings_missing"):
        heading = (
            f'<h1><a href="{href}">{_html(message)}</a></h1>'
            "<p>Vault unlock is on the StickLLM page.</p>"
        )
    bar = (
        '<header style="display:flex;align-items:center;justify-content:space-between;'
        "gap:16px;padding:12px 16px;background:#141414;color:#f5f5f5;"
        'font:600 15px/1.2 sans-serif">'
        "<span>StickLLM</span>"
        f'<a href="{href}" style="display:inline-block;padding:10px 14px;border-radius:8px;'
        'background:#f5f5f5;color:#141414;text-decoration:none">Back to StickLLM</a>'
        "</header>"
    )
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"{refresh}<title>StickLLM Agent</title></head>"
        '<body style="margin:0;font-family:sans-serif;background:#fff;color:#141414">'
        f"{bar}<main style=\"padding:24px\">"
        f"{heading}{install}{log_html}"
        f'<p><a href="{href}">Back to StickLLM</a></p>'
        "</main></body></html>\n"
    )


def _html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _model_path() -> str:
    """Full GGUF path from the running StickLLM model, when one is recorded."""
    override = os.environ.get("STICKLLM_AGENT_MODEL", "").strip()
    if override:
        return override
    env_path = Path(os.environ.get("STICKLLM_MODEL_ENV", "/run/stickllm/model.env"))
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("STICKLLM_MODEL="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value:
                    return value
    except OSError:
        pass
    return ""


def _model_name() -> str:
    path = _model_path()
    name = Path(path).name if path else ""
    return name or "stickllm"


def model_id_from_list(payload: object, fallback: str) -> str:
    """Use the first id from an OpenAI /v1/models document."""
    if isinstance(payload, dict):
        rows = payload.get("data")
        if isinstance(rows, list):
            for item in rows:
                if isinstance(item, dict):
                    model_id = str(item.get("id") or "").strip()
                    if model_id:
                        return model_id
    return fallback


def llama_model_id(fallback: str | None = None) -> str:
    """Exact id llama-server advertises. Fall back to the loaded GGUF path."""
    name = (fallback or "").strip() or _model_path() or _model_name()
    urls = (
        f"http://127.0.0.1:{LLAMA_BRIDGE_PORT}/v1/models",
        f"{LLAMA_BASE}/models",
    )
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                payload = json.loads(resp.read().decode("utf-8", "replace"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        found = model_id_from_list(payload, "")
        if found:
            return found
    return name


def _model_kwargs() -> dict[str, object]:
    return {"api_base": LLAMA_BASE, "api_key": "dummy", "timeout": MODEL_TIMEOUT}


def model_settings(model_name: str) -> dict[str, object]:
    """Legacy settings.json fields this Agent Zero image still migrates.

    v2.14 reads the active model from the model-config preset. On first start
    it also copies these fields into the plugin config when they are present.
    """
    kwargs = _model_kwargs()
    return {
        "chat_model_provider": LOCAL_PROVIDER,
        "chat_model_name": model_name,
        "chat_model_api_base": LLAMA_BASE,
        "chat_model_ctx_length": 32768,
        "chat_model_ctx_history": 0.7,
        "chat_model_vision": False,
        "chat_model_kwargs": dict(kwargs),
        "util_model_provider": LOCAL_PROVIDER,
        "util_model_name": model_name,
        "util_model_api_base": LLAMA_BASE,
        "util_model_ctx_length": 32768,
        "util_model_ctx_input": 0.7,
        "util_model_kwargs": dict(kwargs),
    }


def merge_model_settings(existing: dict, model_name: str) -> dict:
    """Set the StickLLM model fields and leave every other user field in place."""
    merged = dict(existing) if isinstance(existing, dict) else {}
    merged.update(model_settings(model_name))
    return merged


def preset_text(model_name: str) -> str:
    # device: cpu keeps the small MiniLM embedding off the GPU.
    # Chat and utility use the llama-server relay on the agent bridge.
    # The server process itself stays on 127.0.0.1:8080.
    # timeout makes a dead relay a chat error instead of an endless spinner.
    name = json.dumps(model_name)
    return (
        "- name: Default\n"
        "  chat:\n"
        f"    provider: {LOCAL_PROVIDER}\n"
        f"    name: {name}\n"
        f"    api_base: {LLAMA_BASE}\n"
        "    ctx_length: 32768\n"
        "    ctx_history: 0.7\n"
        "    vision: false\n"
        "    kwargs:\n"
        f"      api_base: {LLAMA_BASE}\n"
        "      api_key: dummy\n"
        f"      timeout: {MODEL_TIMEOUT}\n"
        "  utility:\n"
        f"    provider: {LOCAL_PROVIDER}\n"
        f"    name: {name}\n"
        f"    api_base: {LLAMA_BASE}\n"
        "    ctx_length: 32768\n"
        "    ctx_input: 0.7\n"
        "    kwargs:\n"
        f"      api_base: {LLAMA_BASE}\n"
        "      api_key: dummy\n"
        f"      timeout: {MODEL_TIMEOUT}\n"
        "  embedding:\n"
        "    provider: huggingface\n"
        f"    name: {EMBED_REPO}\n"
        "    api_base: \"\"\n"
        "    kwargs:\n"
        "      device: cpu\n"
    )


def embedding_cache_root() -> Path:
    override = os.environ.get("STICKLLM_EMBED_CACHE", "").strip()
    if override:
        return Path(override)
    return ADDON / "state" / ".cache" / "sentence-transformers"


def embedding_cached(root: Path | None = None) -> bool:
    """True when MiniLM weights are already in the container cache."""
    base = root or embedding_cache_root()
    if not base.is_dir():
        return False
    try:
        for path in base.rglob("model.safetensors"):
            if path.is_file() and path.stat().st_size > 1_000_000:
                return True
    except OSError:
        return False
    return False


def _sync_plugin_model_config(root: Path, model_name: str) -> None:
    """Update an already-migrated plugin config. Leave preset selection alone."""
    path = root / "model-config" / "config.json"
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    changed = False
    slots = (
        ("chat_model", "ctx_history", 0.7),
        ("utility_model", "ctx_input", 0.7),
    )
    for section, ratio_key, ratio in slots:
        slot = data.get(section)
        if not isinstance(slot, dict):
            continue
        slot["provider"] = LOCAL_PROVIDER
        slot["name"] = model_name
        slot["api_base"] = LLAMA_BASE
        slot["ctx_length"] = 32768
        slot[ratio_key] = ratio
        if section == "chat_model":
            slot["vision"] = False
        kwargs = slot.get("kwargs")
        if not isinstance(kwargs, dict):
            kwargs = {}
        kwargs.update(_model_kwargs())
        slot["kwargs"] = kwargs
        data[section] = slot
        changed = True
    if changed:
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def agent_proxy_headers(incoming: dict, *, websocket: bool = False) -> dict[str, str]:
    """Headers for the loopback Agent Zero proxy.

    The browser Origin is the stick's :5443 address. Agent Zero's websocket
    check compares that origin to Host, and this proxy used to replace Host
    with 127.0.0.1:5099. Forward the browser host so a failed model call is
    delivered to the chat instead of leaving the spinner up.
    """
    skip = {"host", "content-length", "transfer-encoding"}
    if not websocket:
        skip.add("connection")
    headers: dict[str, str] = {}
    browser_host = ""
    for key, value in incoming.items():
        if key.lower() == "host":
            browser_host = str(value)
        if key.lower() in skip:
            continue
        headers[str(key)] = str(value)
    headers["Host"] = "127.0.0.1:5099"
    if browser_host and not any(key.lower() == "x-forwarded-host" for key in headers):
        headers["X-Forwarded-Host"] = browser_host
    if not any(key.lower() == "x-forwarded-proto" for key in headers):
        headers["X-Forwarded-Proto"] = "https"
    return headers


_ENV_KEYS = (
    "API_KEY_LLAMA_CPP=dummy\n",
    "LLAMA_CPP_API_KEY=dummy\n",
    "API_KEY_HOSTED_VLLM=dummy\n",
    "HOSTED_VLLM_API_KEY=dummy\n",
)


def _env_key_name(line: str) -> str | None:
    stripped = line.strip()
    if stripped.startswith("export "):
        stripped = stripped[len("export ") :].strip()
    name, sep, _value = stripped.partition("=")
    if sep != "=":
        return None
    name = name.strip()
    return name or None


def _upsert_env_key(text: str, key: str, value: str) -> str:
    """Replace every ``key=`` line with one current value. Do not print ``text``."""
    replaced = False
    out: list[str] = []
    for line in text.splitlines():
        if _env_key_name(line) == key:
            if not replaced:
                out.append(f"{key}={value}")
                replaced = True
            continue
        out.append(line)
    if not replaced:
        out.append(f"{key}={value}")
    rendered = "\n".join(out)
    if rendered and not rendered.endswith("\n"):
        rendered += "\n"
    return rendered


def ensure_env_file(path: Path, origins: str | None = None) -> None:
    """Create the portable env if needed. Never print its contents.

    Agent Zero loads this file with ``override=True``, so a stale
    ``ALLOWED_ORIGINS`` line replaces the container environment. Rewrite that
    one key on every start. Leave every other line alone.
    """
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8", errors="replace")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
    missing = []
    for line in _ENV_KEYS:
        key = line.split("=", 1)[0]
        if f"{key}=" not in existing:
            missing.append(line)
    text = existing
    if missing:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "".join(missing)
    value = origins if origins is not None else allowed_origins(_local_ipv4s())
    text = _upsert_env_key(text, "ALLOWED_ORIGINS", value)
    if text != existing or not path.is_file():
        path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_settings(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def prepare_portable(model_name: str | None = None) -> None:
    """Write portable config only on the mounted settings partition.

    Kokoro TTS and Whisper STT stay at the Agent Zero image defaults.
    StickLLM's own whisper.cpp and KittenTTS are not pointed at from here.
    The active chat and utility models are merged into settings.json. Other
    keys the user already saved stay as they are.
    """
    if not settings_mounted():
        raise SystemExit("settings partition is not mounted")
    root = PORTABLE
    for sub in ("prompts", "instruments", "skills", "model-config"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    model = (model_name or "").strip() or llama_model_id()
    settings = root / "settings.json"
    base = {
        "update_check_enabled": False,
        "rfc_auto_docker": False,
        "a2a_server_enabled": False,
        "mcp_server_enabled": False,
        "workdir_path": "/a0/usr/workdir",
    }
    if not settings.is_file() or settings.stat().st_size == 0:
        _write_settings(settings, merge_model_settings(base, model))
    else:
        try:
            current = json.loads(settings.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = None
        if isinstance(current, dict):
            merged = merge_model_settings(current, model)
            if merged != current:
                _write_settings(settings, merged)
    ensure_env_file(root / ".env")
    egress = root / "egress.json"
    if not egress.is_file():
        egress.write_text(
            json.dumps(
                {
                    "web_fetch": True,
                    "note": "Set web_fetch false to disable SearXNG outbound.",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(egress, 0o600)
        except OSError:
            pass
    ensure_apps_instructions()
    preset = root / "model-config" / "presets.yaml"
    preset.write_text(preset_text(model), encoding="utf-8")
    os.chmod(preset, 0o600)
    _sync_plugin_model_config(root, model)


def prepare_vault_dirs() -> None:
    if not docker_may_start():
        raise SystemExit("vault locked")
    for sub in ("state", "work", "memory", "logs"):
        (ADDON / sub).mkdir(parents=True, exist_ok=True)


# --- Agent Zero plugin lockdown -------------------------------------------
# /a0/usr/plugins is assembled on the host on every start and mounted
# read-only. It holds only: our own stickllm_apps plugin, data-only files for
# Agent Zero's built-in plugins, and empty mountpoints. Third-party plugins
# are gone since v0.5.4 (THIRD_PARTY_PLUGINS, empty allowlist), and the
# container entrypoint deletes the built-in plugin installer/scan/validator. Anything else found in the old writable plugins dir is moved to
# the vault quarantine folder (never deleted) and logged by name.
PLUGINS_RO = ADDON / "plugins"
PLUGIN_DATA = ADDON / "plugin-data"
QUARANTINE = ADDON / "quarantine"
EMPTY_RO = ADDON / "empty-ro"
A0_PLUGIN_ALLOW = Path(
    os.environ.get("STICKLLM_A0_PLUGIN_ALLOW", "/usr/local/share/stickllm/agent-zero-plugins.allow")
)
A0_BAKED_PLUGINS = Path(
    os.environ.get("STICKLLM_A0_BAKED_PLUGINS", "/usr/local/share/stickllm/agent-zero-plugins")
)
OWN_PLUGINS = ("stickllm_apps",)
# Built-in plugin names that hold settings only. Agent Zero writes their
# config.json and .toggle-* under /a0/usr/plugins/<name>/.
BUILTIN_NAME_RE = re.compile(r"^_[a-z0-9_]+$")
PLUGIN_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
BUILTIN_DATA_FILES = ("config.json", ".toggle-0", ".toggle-1")
# Built-in plugins that keep runtime data in a sub folder. These get a nested
# read-write mount; plugin.yaml must sit at the read-only plugin root, so a
# file dropped here cannot become a plugin.
BUILTIN_DATA_DIRS = (("_goal", "goals"), ("_orchestrator", "data"))
# Built-in plugins switched off (the installer is always_enabled upstream, so
# the gateway also denies its API; see agent_request_denied).
DISABLED_BUILTINS = ("_plugin_scan",)
MODEL_CONFIG_FILES = ("config.json", "presets.yaml", ".toggle-0", ".toggle-1")
# Other user code paths Agent Zero loads. Mounted as empty read-only dirs.
USR_CODE_DIRS = ("api", "extensions")
# Upstream skills that teach the agent to install, create, or publish plugins.
HIDDEN_SKILLS = ("a0-manage-plugin", "a0-create-plugin")


def read_plugin_allowlist(path: Path | None = None) -> dict[str, dict]:
    """name -> {repo, commit, license, tree}. Bad lines are skipped here; the
    ISO build refuses them (scripts/lib/a0_plugins.py)."""
    path = path or A0_PLUGIN_ALLOW
    out: dict[str, dict] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            continue
        name, repo, commit, lic, tree = parts
        if not PLUGIN_NAME_RE.match(name) or name in OWN_PLUGINS:
            continue
        if not re.fullmatch(r"[0-9a-f]{40}", commit) or not re.fullmatch(r"[0-9a-f]{64}", tree):
            continue
        out[name] = {"repo": repo, "commit": commit, "license": lic, "tree": tree}
    return out


def plugin_tree_hash(root: Path) -> str:
    """Same hash as scripts/lib/a0_plugins.py tree_hash (sorted file sha256 list)."""
    rels: list[str] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if rel.parts and rel.parts[0] == ".git":
            continue
        if path.is_symlink():
            raise ValueError(f"symlink in plugin: {rel.as_posix()}")
        if path.is_file():
            rels.append(rel.as_posix())
    lines: list[bytes] = []
    for rel in sorted(rels, key=lambda r: r.encode("utf-8")):
        digest = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        lines.append(f"{digest}  {rel}\n".encode("utf-8"))
    return hashlib.sha256(b"".join(lines)).hexdigest()


def _quarantine_log(line: str) -> None:
    QUARANTINE.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
    with (QUARANTINE / "quarantine.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{stamp} {line}\n")
    print(f"stickllm-agent: {line}", file=sys.stderr)


def _quarantine(entry: Path, kind: str, stamp: str) -> None:
    dest_dir = QUARANTINE / stamp / kind
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / entry.name
    n = 1
    while dest.exists() or dest.is_symlink():
        dest = dest_dir / f"{entry.name}.{n}"
        n += 1
    shutil.move(str(entry), str(dest))
    safe = re.sub(r"[^A-Za-z0-9._-]", "?", entry.name)[:80]
    _quarantine_log(f"quarantined {kind}/{safe} -> quarantine/{stamp}/{kind}/{dest.name}")


def _is_empty_dir(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink() and not any(path.iterdir())


def migrate_user_plugins(stamp: str | None = None) -> list[str]:
    """Empty the old writable plugin/api/extension dirs under state/.

    Built-in plugin settings (config.json, .toggle-*) and the _goal and
    _orchestrator data folders move to plugin-data. Everything else goes to
    quarantine. Returns quarantined names.
    """
    stamp = stamp or time.strftime("%Y%m%d-%H%M%S")
    moved: list[str] = []
    old = ADDON / "state" / "plugins"
    if old.is_dir() and not old.is_symlink():
        for entry in sorted(old.iterdir()):
            name = entry.name
            if name == ".gitkeep" and entry.is_file():
                continue
            real_dir = entry.is_dir() and not entry.is_symlink()
            if real_dir and BUILTIN_NAME_RE.match(name):
                keep = PLUGIN_DATA / name
                for fn in BUILTIN_DATA_FILES:
                    src = entry / fn
                    if src.is_file() and not src.is_symlink():
                        keep.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(src), str(keep / fn))
                for plug, sub in BUILTIN_DATA_DIRS:
                    src = entry / sub
                    if plug == name and src.is_dir() and not src.is_symlink():
                        dest = keep / sub
                        if not dest.exists():
                            keep.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(src), str(dest))
                        elif _is_empty_dir(dest):
                            dest.rmdir()
                            shutil.move(str(src), str(dest))
                for plug, sub in BUILTIN_DATA_DIRS:
                    if plug == name and _is_empty_dir(entry / sub):
                        (entry / sub).rmdir()
            if name in OWN_PLUGINS and real_dir:
                # Regenerated from this file on every start.
                shutil.rmtree(entry)
                continue
            if _is_empty_dir(entry):
                entry.rmdir()
                continue
            _quarantine(entry, "plugins", stamp)
            moved.append(name)
    for sub in USR_CODE_DIRS:
        old_dir = ADDON / "state" / sub
        if not old_dir.is_dir() or old_dir.is_symlink():
            continue
        for entry in sorted(old_dir.iterdir()):
            _quarantine(entry, sub, stamp)
            moved.append(f"{sub}/{entry.name}")
    return moved


def sanitize_model_config() -> list[str]:
    """model-config is a writable nested mount at /a0/usr/plugins/_model_config.
    Only data files may live there. A plugin.yaml there would replace the
    built-in plugin's code, so anything else goes to quarantine."""
    moved: list[str] = []
    if not settings_mounted():
        return moved
    root = PORTABLE / "model-config"
    if not root.is_dir():
        return moved
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for entry in sorted(root.iterdir()):
        if entry.name in MODEL_CONFIG_FILES and entry.is_file() and not entry.is_symlink():
            continue
        if vault_mounted():
            _quarantine(entry, "model-config", stamp)
        elif entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
        moved.append(entry.name)
    return moved


def _copy_plugin_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if rel.parts and rel.parts[0] == ".git":
            continue
        target = dest / rel
        if path.is_symlink():
            raise ValueError(f"symlink in plugin: {rel.as_posix()}")
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            os.chmod(target, 0o755)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            os.chmod(target, 0o644)


# v0.5.4 (Nink): no third-party Agent Zero plugins on any path. Even if a
# baked copy or an allowlist line shows up, nothing but stickllm_apps loads.
THIRD_PARTY_PLUGINS = False


def baked_plugins() -> dict[str, Path]:
    """Allowlisted plugins baked into the ISO whose pin and hash still match.
    Always empty while THIRD_PARTY_PLUGINS is False."""
    if not THIRD_PARTY_PLUGINS:
        return {}
    allow = read_plugin_allowlist()
    manifest: dict[str, tuple[str, str]] = {}
    try:
        for raw in (A0_BAKED_PLUGINS / "MANIFEST").read_text(encoding="utf-8").splitlines():
            parts = raw.split()
            if len(parts) == 3:
                manifest[parts[0]] = (parts[1], parts[2])
    except OSError:
        return {}
    out: dict[str, Path] = {}
    for name, pin in allow.items():
        src = A0_BAKED_PLUGINS / name
        if manifest.get(name) != (pin["commit"], pin["tree"]):
            print(f"stickllm-agent: plugin {name} skipped (not baked at the pinned commit)", file=sys.stderr)
            continue
        if not (src / "plugin.yaml").is_file():
            continue
        try:
            if plugin_tree_hash(src) != pin["tree"]:
                print(f"stickllm-agent: plugin {name} skipped (hash mismatch)", file=sys.stderr)
                continue
        except ValueError:
            continue
        out[name] = src
    return out


def assemble_plugins() -> Path:
    """Rebuild ADDON/plugins (mounted read-only at /a0/usr/plugins)."""
    if not vault_mounted():
        raise SystemExit("vault locked")
    ADDON.mkdir(parents=True, exist_ok=True)
    migrate_user_plugins()
    sanitize_model_config()
    stage = ADDON / ".plugins.new"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    # copy_A0.sh copies /git/agent-zero/usr/plugins/.gitkeep with cp -n.
    # It must already exist or the copy fails on the read-only mount.
    (stage / ".gitkeep").write_text("", encoding="utf-8")
    ensure_open_app_plugin(stage / "stickllm_apps")
    for name, src in baked_plugins().items():
        _copy_plugin_tree(src, stage / name)
    # Data-only files for built-in plugins.
    if PLUGIN_DATA.is_dir():
        for entry in sorted(PLUGIN_DATA.iterdir()):
            if not entry.is_dir() or entry.is_symlink() or not BUILTIN_NAME_RE.match(entry.name):
                continue
            for fn in BUILTIN_DATA_FILES:
                src = entry / fn
                if src.is_file() and not src.is_symlink():
                    (stage / entry.name).mkdir(exist_ok=True)
                    shutil.copyfile(src, stage / entry.name / fn)
                    os.chmod(stage / entry.name / fn, 0o644)
    for name in DISABLED_BUILTINS:
        (stage / name).mkdir(exist_ok=True)
        (stage / name / ".toggle-1").unlink(missing_ok=True)
        (stage / name / ".toggle-0").write_text("", encoding="utf-8")
    # Mountpoints for the nested writable mounts must exist before docker
    # mounts the parent read-only.
    (stage / "_model_config").mkdir(exist_ok=True)
    for plug, sub in BUILTIN_DATA_DIRS:
        (stage / plug / sub).mkdir(parents=True, exist_ok=True)
        (PLUGIN_DATA / plug / sub).mkdir(parents=True, exist_ok=True)
    EMPTY_RO.mkdir(parents=True, exist_ok=True)
    for entry in list(EMPTY_RO.iterdir()):
        _quarantine(entry, "empty-ro", time.strftime("%Y%m%d-%H%M%S"))
    for path in [stage, *stage.rglob("*")]:
        if path.is_dir():
            os.chmod(path, 0o555)
        else:
            os.chmod(path, 0o444)
    old = ADDON / ".plugins.old"
    if old.exists():
        _make_writable(old)
        shutil.rmtree(old)
    if PLUGINS_RO.exists():
        PLUGINS_RO.rename(old)
    stage.rename(PLUGINS_RO)
    if old.exists():
        _make_writable(old)
        shutil.rmtree(old)
    return PLUGINS_RO


def _make_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        if path.is_symlink():
            continue
        try:
            os.chmod(path, 0o755 if path.is_dir() else 0o644)
        except OSError:
            pass


def assembled_plugin_names() -> list[str]:
    if not PLUGINS_RO.is_dir():
        return []
    return sorted(p.name for p in PLUGINS_RO.iterdir() if (p / "plugin.yaml").is_file())


# Paths on the :5443 Agent proxy that install, scan, publish, or remove plugins.
PLUGIN_DENY_PREFIXES = (
    "/api/plugins/_plugin_installer/",
    "/api/plugins/_plugin_scan/",
    "/api/plugins/_plugin_validator/",
    "/api/plugins/_a0_connector/v1/installed_plugins",
    "/plugins/_plugin_installer/extensions/",
    "/plugins/_plugin_installer/webui/install-index.html",
    "/plugins/_plugin_installer/webui/install-detail.html",
    "/plugins/_plugin_installer/webui/install-git.html",
    "/plugins/_plugin_installer/webui/install-zip.html",
    "/plugins/_plugin_installer/webui/main.html",
    "/plugins/_plugin_scan/extensions/",
    "/plugins/_plugin_scan/webui/",
    "/plugins/_plugin_validator/extensions/",
    "/plugins/_plugin_validator/webui/",
)
PLUGIN_DENY_ACTIONS = ("delete_plugin", "run_execute_script")


def _norm_proxy_path(path: str) -> str:
    raw = path or "/"
    for _ in range(3):
        nxt = urllib.parse.unquote(raw)
        if nxt == raw:
            break
        raw = nxt
    raw = raw.replace("\\", "/")
    raw = re.sub(r"/{2,}", "/", raw)
    parts: list[str] = []
    for part in raw.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    norm = "/" + "/".join(parts)
    if raw.endswith("/") and norm != "/":
        norm += "/"
    return norm


def agent_request_denied(method: str, path: str, body: bytes | None = None) -> str:
    """Reason string when the Agent proxy must refuse this request, else ''."""
    norm = _norm_proxy_path(path)
    probe = norm if norm.endswith("/") else norm + "/"
    for prefix in PLUGIN_DENY_PREFIXES:
        if norm.startswith(prefix) or (prefix.endswith("/") and probe == prefix):
            return "plugins_locked"
        if norm.lower().startswith(prefix.lower()):
            return "plugins_locked"
    if norm.rstrip("/").lower() == "/api/plugins" and (method or "").upper() not in ("GET", "HEAD", "OPTIONS"):
        text = (body or b"")[:1_000_000].decode("utf-8", "replace")
        action = ""
        try:
            doc = json.loads(text) if text.strip() else {}
            if isinstance(doc, dict):
                action = str(doc.get("action") or "")
        except json.JSONDecodeError:
            doc = None
        if doc is None:
            # Not JSON: refuse when a deny-listed action name appears at all.
            if any(a in text for a in PLUGIN_DENY_ACTIONS):
                return "plugins_locked"
        elif action.strip().lower() in PLUGIN_DENY_ACTIONS:
            return "plugins_locked"
    return ""


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "docker-may-start":
        if docker_may_start():
            return 0
        print("vault locked: docker not started", file=sys.stderr)
        return 2
    if cmd == "settings-mounted":
        return 0 if settings_mounted() else 3
    if cmd == "docker-dir":
        path = docker_data_root()
        if path is None:
            print(SSD_MISSING, file=sys.stderr)
            return 4
        print(path)
        return 0
    if cmd == "pull-allowed":
        path = docker_data_root()
        if path is None:
            print(SSD_MISSING, file=sys.stderr)
            return 4
        free = free_bytes(path)
        if pull_allowed(free):
            print(free if free is not None else 0)
            return 0
        print(free if free is not None else -1)
        return 3
    if cmd == "dns-servers":
        print("\n".join(host_dns_servers()))
        return 0
    if cmd == "allowed-origins":
        print(allowed_origins(_local_ipv4s()))
        return 0
    if cmd == "nft-apply":
        return nft_apply()
    if cmd == "nft-delete":
        return nft_delete()
    if cmd == "llama-relay":
        run_tcp_relay(LLAMA_BRIDGE_HOST, LLAMA_BRIDGE_PORT, "127.0.0.1", LLAMA_BRIDGE_PORT)
        return 0
    if cmd == "apps-bridge":
        run_apps_bridge(LLAMA_BRIDGE_HOST, APPS_BRIDGE_PORT)
        return 0
    if cmd == "ensure-open-app-token":
        ensure_open_app_token()
        return 0
    if cmd == "open-app-bridge":
        run_open_app_bridge()
        return 0
    if cmd == "egress-proxy":
        run_egress_proxy()
        return 0
    if cmd == "image-on-disk":
        # 0 = present, 1 = absent, 2 = unknown (ask dockerd).
        try:
            found = image_on_disk()
        except Exception:
            found = None
        if found is None:
            return 2
        return 0 if found else 1
    if cmd == "image-ref":
        print(image_ref())
        return 0
    if cmd == "prepare-vault":
        prepare_vault_dirs()
        return 0
    if cmd == "prepare-portable":
        prepare_portable()
        return 0
    if cmd == "assemble-plugins":
        assemble_plugins()
        names = assembled_plugin_names()
        print("plugins: " + (" ".join(names) if names else "-"))
        return 0
    if cmd == "embedding-cached":
        return 0 if embedding_cached() else 1
    if cmd == "write-status":
        state = "unknown"
        extra: dict[str, object] = {}
        args = argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--state" and i + 1 < len(args):
                state = args[i + 1]
                i += 2
                continue
            if args[i].startswith("--") and i + 1 < len(args):
                key = args[i][2:].replace("-", "_")
                value: object = args[i + 1]
                if value in ("true", "false"):
                    value = value == "true"
                extra[key] = value
                i += 2
                continue
            i += 1
        write_status(state, **extra)
        return 0
    if cmd == "status":
        doc = status_document(
            vault_open=docker_may_start(),
            settings_open=settings_mounted(),
            upstream_up=False,
        )
        print(json.dumps(doc))
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
