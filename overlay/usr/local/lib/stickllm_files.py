#!/usr/bin/env python3
"""Desktop file roots for StickLLM.

The file manager, notepad, and media player may touch only three places:

- ``/home/stickllm``
- the unlocked vault mount (``/var/lib/stickllm/vault``)
- the host SSD apps folder beside the models directory the product already
  recorded (``<models>/../apps``), and only while that SSD is mounted

A locked vault or an unmounted SSD is absent. Those roots are never replaced
with ``/``, ``/mnt``, or another disk. Symlinks that resolve outside a root
are refused. This module does not log file contents.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

HOME_ROOT = Path(os.environ.get("STICKLLM_HOME", "/home/stickllm"))
VAULT_MNT = Path(os.environ.get("STICKLLM_VAULT_MNT", "/var/lib/stickllm/vault"))
HOST_MNT = Path(os.environ.get("STICKLLM_HOST_MNT", "/mnt/stickllm-host"))
MODELS_FILE = Path(os.environ.get("STICKLLM_MODELS_DIR_FILE", "/run/stickllm/models-dir.json"))
MOUNTS_FILE = Path(os.environ.get("STICKLLM_MOUNTS_FILE", "/proc/mounts"))
MAX_BYTES = 32 * 1024 * 1024
TEXT_MAX = 1024 * 1024

# Notepad may save only under these ids. The SSD apps folder is for the
# file manager and the media player, not for notepad's save button.
NOTEPAD_ROOTS = frozenset({"home", "vault"})

INLINE_TYPES = {
    ".txt": "text/plain; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".ogv": "video/ogg",
}


class FilesError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _read_mounts(text: str | None = None) -> str:
    if text is not None:
        return text
    try:
        return MOUNTS_FILE.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _host_mounts(mounts_text: str | None = None) -> list[str]:
    root = str(HOST_MNT)
    found: list[str] = []
    for line in _read_mounts(mounts_text).splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        mp = parts[1].replace("\\040", " ")
        if mp == root or mp.startswith(root + "/"):
            if mp not in found:
                found.append(mp)
    return found


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return False
    return True


def vault_is_open(mounts_text: str | None = None) -> bool:
    """True only when the vault path is an actual mount. A plain directory is locked."""
    target = str(VAULT_MNT)
    if os.path.ismount(target):
        return True
    for line in _read_mounts(mounts_text).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].replace("\\040", " ") == target:
            return True
    return False


def _recorded_models() -> list[Path]:
    out: list[Path] = []
    env = os.environ.get("STICKLLM_MODELS_DIR", "").strip()
    if env:
        out.append(Path(env))
    try:
        doc = json.loads(MODELS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = None
    if isinstance(doc, dict) and doc.get("path"):
        out.append(Path(str(doc["path"])))
    return out


def ssd_apps_dir(mounts_text: str | None = None) -> Path | None:
    """The apps directory beside a recorded models folder, on the host SSD only.

    Missing SSD, missing models record, or a path that is the disk itself:
    the root is absent. This function does not create the directory.
    """
    override = os.environ.get("STICKLLM_SSD_APPS", "").strip()
    if override:
        path = Path(override)
        if path.is_symlink() or not path.is_dir():
            return None
        if str(path) in {"/", "/mnt", "/etc", "/home", "/var", "/root"}:
            return None
        if _under(path, VAULT_MNT):
            return None
        return path
    mounts = _host_mounts(mounts_text)
    if not mounts:
        return None
    for models in _recorded_models():
        try:
            if models.is_symlink() or not models.is_dir():
                continue
        except OSError:
            continue
        if _under(models, VAULT_MNT):
            continue
        on_host = False
        for mp in mounts:
            if _under(models, Path(mp)):
                on_host = True
                break
        if not on_host:
            continue
        apps = models.parent / "apps"
        if apps.name != "apps" or apps.is_symlink():
            continue
        if any(apps == Path(mp) for mp in mounts):
            continue
        if str(apps) in {"/", "/mnt", "/etc", "/home", "/var"}:
            continue
        parent_on_host = any(_under(models.parent, Path(mp)) for mp in mounts)
        if not parent_on_host:
            continue
        if _under(apps, VAULT_MNT):
            continue
        return apps
    return None


def root_map(mounts_text: str | None = None) -> dict[str, Path | None]:
    home = HOME_ROOT if HOME_ROOT.is_dir() and not HOME_ROOT.is_symlink() else None
    vault = VAULT_MNT if vault_is_open(mounts_text) and not VAULT_MNT.is_symlink() else None
    ssd = ssd_apps_dir(mounts_text)
    if ssd is not None and ssd.is_symlink():
        ssd = None
    return {"home": home, "vault": vault, "ssd": ssd}


def roots_document(mounts_text: str | None = None) -> dict:
    found = root_map(mounts_text)
    rows = []
    labels = {
        "home": "Home",
        "vault": "Vault",
        "ssd": "SSD apps",
    }
    for key in ("home", "vault", "ssd"):
        path = found[key]
        rows.append(
            {
                "id": key,
                "label": labels[key],
                "available": path is not None,
                "exists": bool(path is not None and path.is_dir()),
            }
        )
    return {"ok": True, "roots": rows}


def _root_path(root_id: str, mounts_text: str | None = None) -> Path:
    found = root_map(mounts_text)
    if root_id not in found:
        raise FilesError("bad_root", "That folder is not one of the three allowed roots.")
    path = found[root_id]
    if path is None:
        raise FilesError(
            "root_absent",
            "That folder is not available. A locked vault or an unmounted drive is left out.",
            404,
        )
    return path


def resolve_inside(root: Path, rel: str) -> Path:
    """Resolve ``rel`` and require the result to stay inside ``root``.

    ``..``, absolute paths, NUL bytes, and symlinks that leave the root fail.
    """
    if root.is_symlink():
        raise FilesError("bad_root", "The root is a symlink and is not used.")
    text = str(rel or "")
    if "\x00" in text:
        raise FilesError("bad_path", "That path is not allowed.")
    text = text.replace("\\", "/").strip()
    if text.startswith("/") or (len(text) >= 2 and text[1] == ":"):
        raise FilesError("bad_path", "That path is outside the allowed folders.")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        raise FilesError("bad_path", "That path is outside the allowed folders.")
    try:
        root_real = root.resolve()
    except OSError as exc:
        raise FilesError("bad_root", "That folder is not available.", 404) from exc
    candidate = root_real.joinpath(*parts) if parts else root_real
    # Walk so a symlink in the middle cannot escape before the final check.
    current = root_real
    for part in parts:
        nxt = current / part
        if nxt.is_symlink():
            try:
                landed = nxt.resolve()
            except OSError as exc:
                raise FilesError("bad_path", "That path is outside the allowed folders.") from exc
            if landed != root_real and root_real not in landed.parents:
                raise FilesError("bad_path", "That path is outside the allowed folders.")
            current = landed
        else:
            current = nxt
    try:
        resolved = current.resolve() if current.exists() else current
    except OSError as exc:
        raise FilesError("bad_path", "That path is outside the allowed folders.") from exc
    if resolved != root_real and root_real not in resolved.parents and resolved != candidate:
        raise FilesError("bad_path", "That path is outside the allowed folders.")
    if resolved != root_real:
        try:
            resolved.relative_to(root_real)
        except ValueError as exc:
            raise FilesError("bad_path", "That path is outside the allowed folders.") from exc
    return resolved


def list_dir(root_id: str, rel: str = "", mounts_text: str | None = None) -> dict:
    root = _root_path(root_id, mounts_text)
    target = resolve_inside(root, rel)
    if not target.exists():
        if rel.strip() in ("", "."):
            return {"ok": True, "root": root_id, "path": "", "entries": [], "exists": False}
        raise FilesError("not_found", "That folder is not there.", 404)
    if not target.is_dir() or target.is_symlink():
        raise FilesError("not_a_dir", "That path is not a folder.")
    entries = []
    try:
        def _sort_key(child: Path):
            try:
                folder = child.is_dir() and not child.is_symlink()
            except OSError:
                folder = False
            return (not folder, child.name.lower())

        children = sorted(target.iterdir(), key=_sort_key)
    except OSError as exc:
        raise FilesError("unavailable", "That folder cannot be read.", 403) from exc
    for child in children:
        link = child.is_symlink()
        try:
            if link:
                landed = child.resolve()
                root_real = root.resolve()
                outside = landed != root_real and root_real not in landed.parents
                entries.append(
                    {
                        "name": child.name,
                        "dir": False,
                        "symlink": True,
                        "outside": outside,
                        "size": 0,
                    }
                )
                continue
            entries.append(
                {
                    "name": child.name,
                    "dir": child.is_dir(),
                    "symlink": False,
                    "outside": False,
                    "size": child.stat().st_size if child.is_file() else 0,
                }
            )
        except OSError:
            continue
    shown = "" if target == root.resolve() else str(target.relative_to(root.resolve())).replace("\\", "/")
    return {"ok": True, "root": root_id, "path": shown, "entries": entries, "exists": True}


def read_file(root_id: str, rel: str, mounts_text: str | None = None) -> tuple[Path, str, bool]:
    """Return ``(path, content_type, inline)``. Does not read the bytes."""
    root = _root_path(root_id, mounts_text)
    target = resolve_inside(root, rel)
    if target.is_symlink() or not target.is_file():
        raise FilesError("not_found", "That file is not there.", 404)
    suffix = target.suffix.lower()
    if suffix in INLINE_TYPES:
        return target, INLINE_TYPES[suffix], True
    return target, "application/octet-stream", False


def write_text(root_id: str, rel: str, text: str, mounts_text: str | None = None) -> dict:
    """Notepad save. Plain UTF-8 ``.txt`` under home or the unlocked vault only."""
    if root_id not in NOTEPAD_ROOTS:
        raise FilesError("bad_root", "Notepad saves only in Home or the unlocked vault.")
    if not isinstance(text, str):
        raise FilesError("bad_text", "Notepad saves plain text only.")
    if len(text.encode("utf-8")) > TEXT_MAX:
        raise FilesError("too_large", "That note is over the 1 MB limit.", 413)
    if "\x00" in text:
        raise FilesError("bad_text", "Notepad saves plain text only.")
    root = _root_path(root_id, mounts_text)
    name = str(rel or "").replace("\\", "/").split("/")[-1]
    if not name.lower().endswith(".txt") or name in {".txt", "."}:
        raise FilesError("bad_name", "Notepad saves .txt files only.")
    target = resolve_inside(root, rel)
    if target == root.resolve():
        raise FilesError("bad_path", "That path is outside the allowed folders.")
    if target.exists() and (target.is_symlink() or not target.is_file()):
        raise FilesError("bad_path", "That name is already a folder.")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Re-check the parent stayed inside the root after mkdir.
    resolve_inside(root, str(target.parent.relative_to(root.resolve())).replace("\\", "/") if target.parent != root.resolve() else "")
    target.write_text(text, encoding="utf-8")
    shown = str(target.relative_to(root.resolve())).replace("\\", "/")
    return {"ok": True, "root": root_id, "path": shown, "bytes": target.stat().st_size}


def _ensure_root_dir(root: Path) -> None:
    """Create the apps directory itself when a user writes into it.

    Listing does not create anything. The parent must already exist, and the
    new directory's name stays ``apps``.
    """
    if root.is_dir() and not root.is_symlink():
        return
    if root.exists():
        raise FilesError("bad_root", "That folder is not available.", 404)
    parent = root.parent
    if parent.is_symlink() or not parent.is_dir() or root.name != "apps":
        raise FilesError("root_absent", "That folder is not available.", 404)
    root.mkdir(mode=0o750)


def write_bytes(root_id: str, rel: str, data: bytes, mounts_text: str | None = None) -> dict:
    if not isinstance(data, (bytes, bytearray)):
        raise FilesError("bad_body", "Nothing was written.")
    if len(data) > MAX_BYTES:
        raise FilesError("too_large", "That file is over the 32 MB limit.", 413)
    root = _root_path(root_id, mounts_text)
    _ensure_root_dir(root)
    target = resolve_inside(root, rel)
    if target == root.resolve():
        raise FilesError("bad_path", "Choose a file name inside the folder.")
    if target.exists() and (target.is_symlink() or target.is_dir()):
        raise FilesError("bad_path", "That name is a folder.")
    if not target.parent.exists():
        raise FilesError("not_found", "That folder is not there.", 404)
    resolve_inside(root, "" if target.parent == root.resolve() else str(target.parent.relative_to(root.resolve())).replace("\\", "/"))
    target.write_bytes(bytes(data))
    shown = str(target.relative_to(root.resolve())).replace("\\", "/")
    return {"ok": True, "root": root_id, "path": shown, "bytes": len(data)}


def make_dir(root_id: str, rel: str, mounts_text: str | None = None) -> dict:
    root = _root_path(root_id, mounts_text)
    _ensure_root_dir(root)
    target = resolve_inside(root, rel)
    if target == root.resolve():
        raise FilesError("bad_path", "That folder is the root itself.")
    if target.exists():
        raise FilesError("exists", "That name is already there.")
    if target.parent.is_symlink():
        raise FilesError("bad_path", "That path is outside the allowed folders.")
    target.mkdir(parents=False)
    shown = str(target.relative_to(root.resolve())).replace("\\", "/")
    return {"ok": True, "root": root_id, "path": shown}


def remove_path(root_id: str, rel: str, mounts_text: str | None = None) -> dict:
    root = _root_path(root_id, mounts_text)
    target = resolve_inside(root, rel)
    if target == root.resolve() or not str(rel or "").strip():
        raise FilesError("bad_path", "The folder root is not deleted.")
    if target.is_symlink():
        target.unlink()
    elif target.is_file():
        target.unlink()
    elif target.is_dir():
        if any(target.iterdir()):
            raise FilesError("not_empty", "That folder is not empty.")
        target.rmdir()
    else:
        raise FilesError("not_found", "That file is not there.", 404)
    return {"ok": True, "root": root_id, "deleted": str(rel).replace("\\", "/")}


def grant_vault_to_user(user: str = "stickllm") -> dict:
    """Let the files helper read the unlocked vault. Refuses every other path.

    Runs as root from the service start hook. It changes ownership of the
    vault mount directory and its immediate real subdirectories only.
    """
    import pwd

    try:
        ent = pwd.getpwnam(user)
    except KeyError as exc:
        raise FilesError("no_user", "The stickllm user is not on this system.", 500) from exc
    if VAULT_MNT.is_symlink():
        return {"ok": True, "changed": False, "reason": "symlink"}
    if not vault_is_open():
        return {"ok": True, "changed": False, "reason": "locked"}
    try:
        real = VAULT_MNT.resolve()
    except OSError as exc:
        raise FilesError("bad_root", "The vault path is not usable.", 500) from exc
    if real != VAULT_MNT or str(real) in {"/", "/mnt", "/etc", "/home", "/var"}:
        return {"ok": False, "changed": False, "reason": "refused"}
    os.chown(real, ent.pw_uid, ent.pw_gid)
    os.chmod(real, 0o750)
    changed = [str(real)]
    try:
        children = list(real.iterdir())
    except OSError:
        children = []
    for child in children:
        if child.is_symlink() or not child.is_dir():
            continue
        try:
            landed = child.resolve()
        except OSError:
            continue
        if landed != real and real not in landed.parents:
            continue
        os.chown(child, ent.pw_uid, ent.pw_gid)
        os.chmod(child, 0o750)
        changed.append(str(child))
    return {"ok": True, "changed": True, "paths": changed}
