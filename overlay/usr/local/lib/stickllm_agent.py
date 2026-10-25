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

import ipaddress
import json
import os
import socket
import subprocess
import sys
import threading
import urllib.request
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
LLAMA_BRIDGE_SUBNET = "172.30.0.0/24"
LLAMA_BRIDGE_IFACE = "stickllm-a0"
LLAMA_BASE = f"http://{LLAMA_BRIDGE_HOST}:{LLAMA_BRIDGE_PORT}/v1"
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


def nft_ruleset(
    bridge: str = LLAMA_BRIDGE_IFACE,
    subnet: str = LLAMA_BRIDGE_SUBNET,
    gateway: str = LLAMA_BRIDGE_HOST,
    llama_port: int = LLAMA_BRIDGE_PORT,
) -> str:
    """Forward rules owned by stickllm-agent. dockerd is started with --iptables=false.

    The bridge subnet is accepted before the RFC1918 drops, so the container
    can reach the llama relay and the bridge itself. Other addresses in
    192.168.0.0/16, 10.0.0.0/8, and 172.16.0.0/12 are dropped. Internet is
    allowed. The llama relay is not accepted from outside the bridge.
    """
    return (
        f"table inet {NFT_TABLE} {{\n"
        "  chain forward {\n"
        "    type filter hook forward priority 0; policy accept;\n"
        f'    iifname "{bridge}" jump agent_out\n'
        "  }\n"
        "  chain agent_out {\n"
        "    ct state established,related accept\n"
        f"    ip daddr {subnet} accept\n"
        "    ip daddr 192.168.0.0/16 drop\n"
        "    ip daddr 10.0.0.0/8 drop\n"
        "    ip daddr 172.16.0.0/12 drop\n"
        "    meta nfproto ipv6 drop\n"
        "    accept\n"
        "  }\n"
        "  chain input {\n"
        "    type filter hook input priority 0; policy accept;\n"
        # The host health check connects to the bridge address via lo.
        # Packets from any other interface are still dropped, so the relay
        # is not reachable from the LAN. The container uses the bridge.
        '    iifname "lo" accept\n'
        f'    iifname != "{bridge}" ip daddr {gateway} tcp dport {llama_port} drop\n'
        "  }\n"
        "  chain postrouting {\n"
        "    type nat hook postrouting priority srcnat; policy accept;\n"
        f'    ip saddr {subnet} oifname != "{bridge}" masquerade\n'
        "  }\n"
        "}\n"
    )


def nft_apply_text() -> str:
    """Ruleset script for ``nft -f``.

    Debian 12 ships nftables 1.0.6, which rejects ``destroy table`` (added in
    1.0.8) and then refuses the rest of the file. ``add`` plus ``delete`` is
    the older idempotent prelude: it creates the table when missing, then
    drops it so the definition below is a clean load.
    """
    return (
        f"add table inet {NFT_TABLE}\n"
        f"delete table inet {NFT_TABLE}\n"
        + nft_ruleset()
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
            client.close()
            return
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
    preset = root / "model-config" / "presets.yaml"
    preset.write_text(preset_text(model), encoding="utf-8")
    os.chmod(preset, 0o600)
    _sync_plugin_model_config(root, model)


def prepare_vault_dirs() -> None:
    if not docker_may_start():
        raise SystemExit("vault locked")
    for sub in ("state", "work", "memory", "logs"):
        (ADDON / sub).mkdir(parents=True, exist_ok=True)


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
    if cmd == "image-ref":
        print(image_ref())
        return 0
    if cmd == "prepare-vault":
        prepare_vault_dirs()
        return 0
    if cmd == "prepare-portable":
        prepare_portable()
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
