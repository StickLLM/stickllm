#!/usr/bin/env python3
"""Agent Zero gates for StickLLM.

Docker starts only when the server vault is mounted. /agent is refused for an
unpaired browser the same way other UI APIs are. This module does not log
API keys, vault passcodes, or chat text.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

VAULT_MNT = Path(os.environ.get("STICKLLM_VAULT_MNT", "/var/lib/stickllm/vault"))
SETTINGS_MNT = Path(os.environ.get("STICKLLM_SETTINGS_MNT", "/mnt/stickllm-settings"))
ADDON = VAULT_MNT / "addons" / "agent-zero"
PORTABLE = SETTINGS_MNT / "agent-zero"
STATUS_PATH = Path(os.environ.get("STICKLLM_AGENT_STATUS", "/run/stickllm/agent-status.json"))
PIN_PATH = Path(
    os.environ.get(
        "STICKLLM_AGENT_PIN",
        str(Path(__file__).resolve().parent.parent / "share" / "stickllm" / "agent-zero.pin"),
    )
)
# 15 GB. Below this, do not pull the image.
MIN_FREE_BYTES = 15_000_000_000
LLAMA_BASE = "http://127.0.0.1:8080/v1"
AGENT_PORT = 5099


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


def vault_mounted(path: Path | None = None, mounts_text: str | None = None) -> bool:
    """True only when path is a mount point. A plain directory is not enough."""
    target = str(path or VAULT_MNT)
    if mounts_text is None:
        mounts_file = os.environ.get("STICKLLM_MOUNTS_FILE")
        if mounts_file:
            try:
                mounts_text = Path(mounts_file).read_text(encoding="utf-8", errors="replace")
            except OSError:
                mounts_text = ""
    if mounts_text is not None:
        for line in mounts_text.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == target:
                return True
        return False
    try:
        if os.path.ismount(target):
            return True
    except OSError:
        return False
    try:
        with open("/proc/self/mounts", encoding="utf-8", errors="replace") as fh:
            return vault_mounted(Path(target), fh.read())
    except OSError:
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
    if free_bytes is None:
        return False
    try:
        return int(free_bytes) >= MIN_FREE_BYTES
    except (TypeError, ValueError):
        return False


def vault_free_bytes(path: Path | None = None) -> int | None:
    target = str(path or VAULT_MNT)
    try:
        st = os.statvfs(target)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None
    return int(st.f_bavail) * int(st.f_frsize)


def upstream_path(url_path: str) -> str:
    path = url_path or "/"
    if path == "/agent":
        return "/"
    if path.startswith("/agent/"):
        rest = path[len("/agent") :]
        return rest if rest.startswith("/") else "/" + rest
    return path


_REWRITE_PREFIXES = (
    "/js/",
    "/api/",
    "/css/",
    "/vendor/",
    "/public/",
    "/components/",
    "/login",
    "/socket.io",
    "/sw.js",
    "/index",
    "/safe",
    "/favicon",
    "/webui/",
    "/assets/",
)


def should_rewrite(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return "html" in ct or "javascript" in ct or "css" in ct


def rewrite_text(text: str) -> str:
    """Prefix Agent Zero's root-absolute URLs so they stay under /agent."""
    for prefix in _REWRITE_PREFIXES:
        text = text.replace('"' + prefix, '"/agent' + prefix)
        text = text.replace("'" + prefix, "'/agent" + prefix)
        text = text.replace("`" + prefix, "`/agent" + prefix)
    text = text.replace('from "/', 'from "/agent/')
    text = text.replace("from '/", "from '/agent/")
    return text


def rewrite_bytes(data: bytes) -> bytes:
    return rewrite_text(data.decode("utf-8", errors="surrogateescape")).encode("utf-8", errors="surrogateescape")


def rewrite_location(value: str) -> str:
    location = value.strip()
    for origin in ("http://127.0.0.1:5099", "http://localhost:5099"):
        if location.startswith(origin):
            location = location[len(origin) :] or "/"
    if location.startswith("/agent"):
        return location
    if location.startswith("/"):
        return "/agent" + location
    return value


def rewrite_cookie(value: str) -> str:
    # Keep the session on the proxied UI. Do not widen it to the whole origin.
    return value.replace("Path=/", "Path=/agent").replace("path=/", "path=/agent")


def read_status() -> dict:
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


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
) -> dict:
    saved = saved if saved is not None else read_status()
    image_present = bool(saved.get("image_present")) and vault_open
    low_space = bool(saved.get("low_space"))
    if not vault_open:
        message = "Unlock vault to use Agent"
        state = "locked"
    elif not settings_open:
        message = "Unlock the USB settings partition to use Agent"
        state = "settings_missing"
    elif low_space:
        message = "The vault needs about 15 GB free before Agent Zero can be installed"
        state = "low_space"
    elif not image_present:
        message = "Agent Zero is not in this server's vault yet"
        state = "needs_install"
    elif not upstream_up:
        message = "Agent is starting"
        state = "starting"
    else:
        message = "Agent"
        state = "running"
    return {
        "ok": True,
        "state": state,
        "vault_unlocked": vault_open,
        "settings_mounted": settings_open,
        "image_present": image_present,
        "running": bool(upstream_up) and vault_open and settings_open,
        "needs_install": vault_open and settings_open and not image_present and not low_space,
        "low_space": low_space,
        "message": message,
        "port": AGENT_PORT,
    }


def status_html(doc: dict) -> str:
    message = str(doc.get("message") or "Agent")
    install = ""
    if doc.get("needs_install"):
        install = (
            "<form method=\"post\" action=\"/api/agent/install\">"
            "<button type=\"submit\">Install Agent Zero into this vault</button>"
            "</form>"
            "<p>The image stays in this server's vault. It is not on the USB data partition.</p>"
        )
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>StickLLM Agent</title></head><body>"
        f"<h1>{_html(message)}</h1>"
        f"{install}"
        "<p><a href=\"/\">Back to StickLLM</a></p>"
        "</body></html>\n"
    )


def _html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _model_name() -> str:
    override = os.environ.get("STICKLLM_AGENT_MODEL", "").strip()
    if override:
        return override
    env_path = Path(os.environ.get("STICKLLM_MODEL_ENV", "/run/stickllm/model.env"))
    try:
        for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("STICKLLM_MODEL="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                name = Path(value).name
                if name:
                    return name
    except OSError:
        pass
    return "stickllm"


def preset_text(model_name: str) -> str:
    # device: cpu keeps the small MiniLM embedding off the GPU.
    # Chat and utility both use the llama-server already running on the host.
    name = json.dumps(model_name)
    return (
        "- name: Default\n"
        "  chat:\n"
        "    provider: llama_cpp\n"
        f"    name: {name}\n"
        f"    api_base: {LLAMA_BASE}\n"
        "    ctx_length: 32768\n"
        "    ctx_history: 0.7\n"
        "    vision: false\n"
        "    kwargs:\n"
        f"      api_base: {LLAMA_BASE}\n"
        "  utility:\n"
        "    provider: llama_cpp\n"
        f"    name: {name}\n"
        f"    api_base: {LLAMA_BASE}\n"
        "    ctx_length: 32768\n"
        "    ctx_input: 0.7\n"
        "    kwargs:\n"
        f"      api_base: {LLAMA_BASE}\n"
        "  embedding:\n"
        "    provider: huggingface\n"
        "    name: sentence-transformers/all-MiniLM-L6-v2\n"
        "    api_base: \"\"\n"
        "    kwargs:\n"
        "      device: cpu\n"
    )


_ENV_KEYS = (
    "API_KEY_LLAMA_CPP=dummy\n",
    "LLAMA_CPP_API_KEY=dummy\n",
    "API_KEY_HOSTED_VLLM=dummy\n",
    "HOSTED_VLLM_API_KEY=dummy\n",
)


def ensure_env_file(path: Path) -> None:
    """Create the portable env if needed. Never print its contents."""
    existing = ""
    if path.is_file():
        existing = path.read_text(encoding="utf-8", errors="replace")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    missing = []
    for line in _ENV_KEYS:
        key = line.split("=", 1)[0]
        if f"{key}=" not in existing:
            missing.append(line)
    if missing:
        with path.open("a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.writelines(missing)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def prepare_portable(model_name: str | None = None) -> None:
    """Write portable config only on the mounted settings partition."""
    if not settings_mounted():
        raise SystemExit("settings partition is not mounted")
    root = PORTABLE
    for sub in ("prompts", "instruments", "skills", "model-config"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    settings = root / "settings.json"
    if not settings.is_file() or settings.stat().st_size == 0:
        settings.write_text(
            json.dumps(
                {
                    "update_check_enabled": False,
                    "rfc_auto_docker": False,
                    "a2a_server_enabled": False,
                    "mcp_server_enabled": False,
                    "workdir_path": "/a0/usr/workdir",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.chmod(settings, 0o600)
    ensure_env_file(root / ".env")
    preset = root / "model-config" / "presets.yaml"
    preset.write_text(preset_text(model_name or _model_name()), encoding="utf-8")
    os.chmod(preset, 0o600)


def prepare_vault_dirs() -> None:
    if not docker_may_start():
        raise SystemExit("vault locked")
    for sub in ("state", "work", "memory", "logs"):
        (ADDON / sub).mkdir(parents=True, exist_ok=True)
    (VAULT_MNT / "docker").mkdir(parents=True, exist_ok=True)


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "docker-may-start":
        if docker_may_start():
            return 0
        print("vault locked: docker not started", file=sys.stderr)
        return 2
    if cmd == "settings-mounted":
        return 0 if settings_mounted() else 3
    if cmd == "pull-allowed":
        free = vault_free_bytes()
        if pull_allowed(free):
            print(free if free is not None else 0)
            return 0
        print(free if free is not None else -1)
        return 3
    if cmd == "image-ref":
        print(image_ref())
        return 0
    if cmd == "prepare-vault":
        prepare_vault_dirs()
        return 0
    if cmd == "prepare-portable":
        prepare_portable()
        return 0
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
