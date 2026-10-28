#!/usr/bin/env python3
"""ONLYOFFICE Docs for StickLLM: vault-only documents.

Rules this module enforces (the gateway and stickllm-docs both use it):

* User documents live in ``<vault>/Documents``. ONLYOFFICE's own cache,
  logs, config and keys live in ``<vault>/addons/onlyoffice``. The host SSD
  holds only the pinned public image (plus a font/cache layer generated
  from that image alone).
* Nothing is read or written while the vault is locked (HTTP 423).
* Every write is re-checked: vault mounted, path inside Documents, no
  ``..``, no symlink anywhere on the path, same filesystem as the vault,
  temp file in the same directory, fsync, rename.
* The JWT secret is on the encrypted settings partition (0600). A RAM copy in
  /run/stickllm lets the gateway sign editor configs and verify callbacks.

Never print document text or the secret.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

VAULT_MNT = Path(os.environ.get("STICKLLM_VAULT_MNT", "/var/lib/stickllm/vault"))
SETTINGS_MNT = Path(os.environ.get("STICKLLM_SETTINGS_MNT", "/mnt/stickllm-settings"))
RUN_DIR = Path(os.environ.get("STICKLLM_RUN", "/run/stickllm"))
MOUNTS_FILE = os.environ.get("STICKLLM_MOUNTS_FILE", "")
PIN_PATH = Path(
    os.environ.get(
        "STICKLLM_DOCS_PIN",
        str(Path(__file__).resolve().parent.parent / "share" / "stickllm" / "onlyoffice.pin"),
    )
)

DOCS_DIR_NAME = "Documents"
ADDON_REL = ("addons", "onlyoffice")
# Bind mounts into the container. Every image VOLUME is covered, so Docker
# never creates an anonymous volume on the host SSD data-root.
ADDON_DIRS = ("lib", "logs", "data", "etc", "templates")
CONTAINER = "stickllm-docs"
NETWORK = "stickllm-docs"
BRIDGE = "stickllm-d0"
SUBNET = "172.30.1.0/24"
GATEWAY_IP = "172.30.1.1"
CONTAINER_IP = "172.30.1.2"
DS_PORT = 8083
DS_BASE = f"http://127.0.0.1:{DS_PORT}"
GATEWAY_PORT = 80
NFT_TABLE = "stickllm_docs"
SECRET_REL = ("onlyoffice", "jwt.secret")
RUNTIME_SECRET_NAME = "docs-jwt"
STATUS_NAME = "docs-status.json"
SERVER_PREFIX = "/docs-server"

MAX_UPLOAD = 100 * 1024 * 1024
MAX_SAVE = 200 * 1024 * 1024
LINK_TTL = 24 * 3600
LIST_LIMIT = 1000
LIST_DEPTH = 4

# Documents the editor opens. Kinds map to ONLYOFFICE documentType.
KINDS = {
    "docx": "word", "doc": "word", "odt": "word", "rtf": "word", "txt": "word",
    "xlsx": "cell", "xls": "cell", "ods": "cell", "csv": "cell",
    "pptx": "slide", "ppt": "slide", "odp": "slide",
    "pdf": "pdf",
}
# Formats ONLYOFFICE saves back in the same format.
EDITABLE = frozenset({"docx", "xlsx", "pptx", "odt", "ods", "odp", "txt", "csv", "rtf", "pdf"})
CREATE_KINDS = ("docx", "xlsx", "pptx")

VAULT_LOCKED_MESSAGE = (
    "Unlock the vault to use Docs. Documents are only ever saved in the vault."
)
SETTINGS_MISSING_MESSAGE = "USB settings partition is not mounted: Docs not started."

# Embedded copy of the pin file, so a hotfix of this module alone still has
# the digest. Tests assert both agree.
DEFAULT_PIN = {
    "image": "onlyoffice/documentserver",
    "version": "10.0.0.1",
    "manifest_digest": "sha256:ca17889f10b11141cc6441836aebdd2835cf3e1b49681b2fd6e155c94b7850b3",
    "amd64_digest": "sha256:bff1a9fd46f2b79ada776fd0447c3fccf66cbf44c1996ec9316efa8ac4ee3fd5",
}

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_KEY_RE = re.compile(r"[0-9A-Za-z._=-]{1,128}")


class DocsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status

    def document(self) -> dict:
        return {"ok": False, "error": self.code, "message": self.message}


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


def load_pin(path: Path | None = None) -> dict:
    try:
        return parse_pin(Path(path or PIN_PATH).read_text(encoding="utf-8"))
    except OSError:
        return dict(DEFAULT_PIN)


def image_ref(pin: dict | None = None) -> str:
    pin = pin or load_pin()
    return f"{pin['image']}@{pin['amd64_digest']}"


def prepared_ref(pin: dict | None = None) -> str:
    """Local tag of the image after fonts and api.js were generated from it."""
    pin = pin or load_pin()
    return "stickllm-docs:" + pin["amd64_digest"].split(":", 1)[1][:16]


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


def settings_open() -> bool:
    return is_mounted(SETTINGS_MNT)


def require_vault() -> None:
    if not vault_open():
        raise DocsError("vault_locked", VAULT_LOCKED_MESSAGE, 423)


# ---------------------------------------------------------------- paths


def _no_symlink_walk(base: Path, parts: list[str]) -> Path:
    """Walk ``parts`` below ``base`` with lstat. Any symlink is refused."""
    current = base
    for part in parts:
        current = current / part
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode):
            raise DocsError("bad_path", "Symlinks are not followed in Documents.")
    return current


def _vault_dev() -> int:
    return os.stat(VAULT_MNT).st_dev


def _clean_parts(rel: str) -> list[str]:
    text = str(rel or "")
    if "\x00" in text:
        raise DocsError("bad_path", "That path is not allowed.")
    text = text.replace("\\", "/").strip()
    if text.startswith("/") or (len(text) >= 2 and text[1] == ":"):
        raise DocsError("bad_path", "That path is outside Documents.")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    for part in parts:
        if part == ".." or part.startswith(".") or len(part) > 200:
            raise DocsError("bad_path", "That path is outside Documents.")
        if any(ord(ch) < 32 for ch in part):
            raise DocsError("bad_path", "That path is not allowed.")
    return parts


def addon_dir() -> Path:
    require_vault()
    path = _no_symlink_walk(VAULT_MNT, list(ADDON_REL))
    return path


def docs_root(create: bool = True) -> Path:
    """``<vault>/Documents``. Locked vault: 423. Symlinked or foreign fs: refused."""
    require_vault()
    if os.path.islink(VAULT_MNT):
        raise DocsError("bad_root", "The vault path is a symlink.", 500)
    root = VAULT_MNT / DOCS_DIR_NAME
    if os.path.islink(root):
        raise DocsError("bad_root", "Documents is a symlink and is not used.", 500)
    if not root.exists():
        if not create:
            raise DocsError("not_found", "Documents does not exist yet.", 404)
        os.mkdir(root, 0o750)
        _match_owner(root, VAULT_MNT)
    real = Path(os.path.realpath(root))
    vault_real = Path(os.path.realpath(VAULT_MNT))
    if real.parent != vault_real:
        raise DocsError("bad_root", "Documents is outside the vault.", 500)
    if os.stat(root).st_dev != _vault_dev():
        raise DocsError("bad_root", "Documents is not on the vault filesystem.", 500)
    return root


def _match_owner(path: Path, like: Path) -> None:
    if os.geteuid() != 0:
        return
    try:
        st = os.stat(like)
        os.chown(path, st.st_uid, st.st_gid, follow_symlinks=False)
    except OSError:
        pass


def resolve_doc(rel: str, *, want_file: bool = True) -> Path:
    """A path inside Documents. Rejects NUL, absolute, ``..``, dot names, symlinks."""
    root = docs_root()
    parts = _clean_parts(rel)
    if want_file and not parts:
        raise DocsError("bad_path", "Pick a document.")
    path = _no_symlink_walk(root, parts)
    real = os.path.realpath(path)
    root_real = os.path.realpath(root)
    if real != root_real and not real.startswith(root_real + os.sep):
        raise DocsError("bad_path", "That path is outside Documents.")
    if want_file and extension(path.name) not in KINDS:
        raise DocsError("bad_type", "Docs opens Word, Excel, PowerPoint, OpenDocument, text and PDF files.")
    return path


def extension(name: str) -> str:
    _, dot, ext = str(name).rpartition(".")
    return ext.lower() if dot else ""


def rel_of(path: Path) -> str:
    return path.relative_to(docs_root()).as_posix()


def clean_name(name: str, ext: str | None = None) -> str:
    text = str(name or "").strip()
    text = re.sub(r"[\x00-\x1f/\\:*?\"<>|]+", " ", text).strip().strip(".")
    text = re.sub(r"\s+", " ", text)[:120] or "Untitled"
    if ext:
        if extension(text) != ext:
            text = f"{text}.{ext}"
    return text


def _unique(parent: Path, name: str) -> str:
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    candidate = name
    n = 1
    while os.path.lexists(parent / candidate):
        n += 1
        candidate = f"{stem} ({n}).{ext}" if ext else f"{stem} ({n})"
        if n > 999:
            raise DocsError("exists", "Too many files with that name.", 409)
    return candidate


def atomic_write(rel: str, data: bytes, *, overwrite: bool) -> str:
    """Write bytes into Documents only. Returns the relative path written."""
    if not isinstance(data, (bytes, bytearray)):
        raise DocsError("bad_body", "No file data.")
    target = resolve_doc(rel)
    parent = target.parent
    name = target.name
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        dfd = os.open(parent, flags)
    except FileNotFoundError as exc:
        raise DocsError("not_found", "That folder does not exist.", 404) from exc
    except OSError as exc:
        raise DocsError("bad_path", "That folder cannot be used.") from exc
    tmp = ""
    try:
        if os.fstat(dfd).st_dev != _vault_dev():
            raise DocsError("bad_root", "Refusing to write outside the vault filesystem.", 500)
        real_parent = os.path.realpath(f"/proc/self/fd/{dfd}") if os.path.exists("/proc/self/fd") else os.path.realpath(parent)
        root_real = os.path.realpath(docs_root())
        if real_parent != root_real and not real_parent.startswith(root_real + os.sep):
            raise DocsError("bad_path", "That path is outside Documents.")
        if not overwrite:
            name = _unique(parent, name)
        else:
            try:
                st = os.lstat(name, dir_fd=dfd)
                if not stat.S_ISREG(st.st_mode):
                    raise DocsError("bad_path", "Only regular files are replaced.")
            except FileNotFoundError:
                pass
        tmp = f".~stickllm-{secrets.token_hex(8)}.part"
        fd = os.open(
            tmp,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o640,
            dir_fd=dfd,
        )
        try:
            view = memoryview(bytes(data))
            while view:
                n = os.write(fd, view)
                view = view[n:]
            os.fsync(fd)
            if os.geteuid() == 0:
                st = os.fstat(dfd)
                try:
                    os.fchown(fd, st.st_uid, st.st_gid)
                except OSError:
                    pass
        finally:
            os.close(fd)
        # The vault is checked again right before the file appears.
        require_vault()
        if os.fstat(dfd).st_dev != _vault_dev():
            raise DocsError("bad_root", "Refusing to write outside the vault filesystem.", 500)
        os.replace(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
        tmp = ""
        os.fsync(dfd)
    finally:
        if tmp:
            try:
                os.unlink(tmp, dir_fd=dfd)
            except OSError:
                pass
        os.close(dfd)
    return (Path(rel_of(parent)) / name).as_posix() if rel_of(parent) != "." else name


def read_doc(rel: str) -> tuple[Path, bytes]:
    path = resolve_doc(rel)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError as exc:
        raise DocsError("not_found", "That document does not exist.", 404) from exc
    except OSError as exc:
        raise DocsError("bad_path", "That document cannot be read.") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise DocsError("bad_path", "That is not a file.")
        if st.st_size > MAX_SAVE:
            raise DocsError("too_large", "That document is too large.", 413)
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(fd)
    return path, b"".join(chunks)


def list_documents() -> dict:
    root = docs_root()
    out: list[dict] = []

    def walk(folder: Path, depth: int) -> None:
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
        except OSError:
            return
        for entry in entries:
            if len(out) >= LIST_LIMIT:
                return
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                if depth < LIST_DEPTH:
                    walk(Path(entry.path), depth + 1)
                continue
            ext = extension(entry.name)
            if ext not in KINDS or not entry.is_file(follow_symlinks=False):
                continue
            st = entry.stat(follow_symlinks=False)
            out.append(
                {
                    "path": Path(entry.path).relative_to(root).as_posix(),
                    "name": entry.name,
                    "type": ext,
                    "kind": KINDS[ext],
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "editable": ext in EDITABLE,
                }
            )

    walk(root, 0)
    out.sort(key=lambda d: -d["mtime"])
    return {"ok": True, "root": "vault/Documents", "documents": out, "truncated": len(out) >= LIST_LIMIT}


def template_path(kind: str) -> Path:
    if kind not in CREATE_KINDS:
        raise DocsError("bad_type", "New documents are docx, xlsx or pptx.")
    path = _no_symlink_walk(addon_dir(), ["templates", f"new.{kind}"])
    if not path.is_file():
        raise DocsError("not_installed", "Install ONLYOFFICE Docs from Apps first.", 409)
    return path


def create_document(name: str, kind: str, folder: str = "") -> str:
    tpl = template_path(kind)
    data = tpl.read_bytes()
    rel = "/".join(_clean_parts(folder) + [clean_name(name, kind)])
    return atomic_write(rel, data, overwrite=False)


# ------------------------------------------------- agent-made documents
# Agent Zero's create_spreadsheet / create_document tools (0.5.2). Plain
# stdlib OOXML so the host needs no office libraries; ONLYOFFICE opens them.
AGENT_MAX_CELLS = 20000
AGENT_MAX_TEXT = 200_000


def _xml_text(value: object) -> str:
    text = str(value)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _col_name(idx: int) -> str:
    out = ""
    idx += 1
    while idx:
        idx, rem = divmod(idx - 1, 26)
        out = chr(65 + rem) + out
    return out


def _zip_bytes(files: dict[str, str]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in files.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, text.encode("utf-8"))
    return buf.getvalue()


def build_xlsx(rows: object, sheet: str = "Sheet1") -> bytes:
    """rows: list of rows, each a list of numbers/strings/None. Numbers stay numbers."""
    if not isinstance(rows, list):
        raise DocsError("bad_rows", "rows must be a list of rows, for example [[1],[2],[3]].")
    cells = 0
    out_rows = []
    for r_i, row in enumerate(rows):
        if not isinstance(row, list):
            row = [row]
        parts = []
        for c_i, val in enumerate(row):
            cells += 1
            if cells > AGENT_MAX_CELLS:
                raise DocsError("too_large", f"At most {AGENT_MAX_CELLS} cells.", 413)
            ref = f"{_col_name(c_i)}{r_i + 1}"
            if val is None or val == "":
                continue
            if isinstance(val, bool):
                parts.append(f'<c r="{ref}" t="b"><v>{int(val)}</v></c>')
            elif isinstance(val, (int, float)) and val == val and val not in (float("inf"), float("-inf")):
                parts.append(f'<c r="{ref}"><v>{val!r}</v></c>')
            elif isinstance(val, str) and val.startswith("="):
                parts.append(f'<c r="{ref}"><f>{_xml_text(val[1:])}</f></c>')
            else:
                parts.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_xml_text(val)}</t></is></c>')
        out_rows.append(f'<row r="{r_i + 1}">' + "".join(parts) + "</row>")
    name = _xml_text(re.sub(r"[\\/?*\[\]:]", " ", str(sheet or "Sheet1"))[:31] or "Sheet1")
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel_ns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    return _zip_bytes({
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            "</Relationships>"
        ),
        "xl/workbook.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook {ns} {rel_ns}>'
            f'<sheets><sheet name="{name}" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "xl/worksheets/sheet1.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet {ns}><sheetData>'
            + "".join(out_rows)
            + "</sheetData></worksheet>"
        ),
    })


def build_docx(text: object, title: str = "") -> bytes:
    """Plain paragraphs (blank line or newline separated). A title becomes a bold first line."""
    body = str(text or "")
    if len(body) > AGENT_MAX_TEXT:
        raise DocsError("too_large", "That text is too long for one document.", 413)
    paras = []
    if title:
        paras.append(f'<w:p><w:r><w:rPr><w:b/><w:sz w:val="32"/></w:rPr><w:t xml:space="preserve">{_xml_text(title)}</w:t></w:r></w:p>')
    for line in body.split("\n"):
        paras.append(f'<w:p><w:r><w:t xml:space="preserve">{_xml_text(line)}</w:t></w:r></w:p>')
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    return _zip_bytes({
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>"
        ),
        "_rels/.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>"
        ),
        "word/document.xml": (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {w}><w:body>'
            + "".join(paras)
            + "<w:sectPr/></w:body></w:document>"
        ),
    })


def agent_create(kind: str, name: str, *, rows: object = None, text: object = None, title: str = "") -> str:
    """Write an agent-made xlsx/docx into vault/Documents (never overwrites). Returns its path."""
    require_vault()
    if kind == "xlsx":
        data = build_xlsx(rows if rows is not None else [])
    elif kind == "docx":
        data = build_docx(text, title=title)
    else:
        raise DocsError("bad_type", "The agent creates docx or xlsx files.")
    docs_root()
    base = re.sub(r"^[\s.]+", "", str(name or ""))
    return atomic_write(clean_name(base or "Untitled", kind), data, overwrite=False)


def upload_document(name: str, data: bytes, folder: str = "") -> str:
    if len(data) > MAX_UPLOAD:
        raise DocsError("too_large", "That file is over the 100 MB limit.", 413)
    fname = clean_name(name)
    if extension(fname) not in KINDS:
        raise DocsError("bad_type", "Docs opens Word, Excel, PowerPoint, OpenDocument, text and PDF files.")
    rel = "/".join(_clean_parts(folder) + [fname])
    return atomic_write(rel, data, overwrite=False)


# ---------------------------------------------------------------- secrets


def settings_secret_path() -> Path:
    return SETTINGS_MNT.joinpath(*SECRET_REL)


def runtime_secret_path() -> Path:
    return RUN_DIR / RUNTIME_SECRET_NAME


def ensure_settings_secret() -> Path:
    """Create the JWT secret on the settings partition (0600) if missing."""
    if not settings_open():
        raise DocsError("settings_missing", SETTINGS_MISSING_MESSAGE, 423)
    path = settings_secret_path()
    if os.path.islink(path.parent) or os.path.islink(path):
        raise DocsError("bad_path", "The Docs secret path is a symlink.", 500)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if not path.exists() or len(_read_secret(path)) < 32:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            os.write(fd, (secrets.token_hex(32) + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)
    os.chmod(path, 0o600)
    return path


def _read_secret(path: Path) -> str:
    try:
        raw = path.read_text(encoding="ascii", errors="ignore")
    except OSError:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", raw)


def install_runtime_secret() -> Path:
    src = ensure_settings_secret()
    value = _read_secret(src)
    dest = runtime_secret_path()
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        os.write(fd, value.encode())
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)
    return dest


def drop_runtime_secret() -> None:
    try:
        runtime_secret_path().unlink()
    except FileNotFoundError:
        pass


def runtime_secret() -> str:
    value = _read_secret(runtime_secret_path())
    if len(value) < 32:
        raise DocsError("not_running", "ONLYOFFICE Docs is not running.", 503)
    return value


# ---------------------------------------------------------------- JWT (HS256)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    text = str(text)
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def jwt_sign(payload: dict, secret: str) -> str:
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(sig)}"


def jwt_verify(token: str, secret: str, now: float | None = None) -> dict:
    if not secret or len(secret) < 32:
        raise DocsError("bad_token", "No signing secret.", 403)
    parts = str(token or "").split(".")
    if len(parts) != 3:
        raise DocsError("bad_token", "Token is malformed.", 403)
    try:
        header = json.loads(_unb64(parts[0]))
        payload = json.loads(_unb64(parts[1]))
        sig = _unb64(parts[2])
    except Exception as exc:
        raise DocsError("bad_token", "Token is malformed.", 403) from exc
    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise DocsError("bad_token", "Only HS256 tokens are accepted.", 403)
    want = hmac.new(secret.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
    if not hmac.compare_digest(want, sig):
        raise DocsError("bad_token", "Token signature does not match.", 403)
    if not isinstance(payload, dict):
        raise DocsError("bad_token", "Token payload is not an object.", 403)
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and (now or time.time()) > exp + 60:
        raise DocsError("bad_token", "Token expired.", 403)
    return payload


# ---------------------------------------------------------------- links


def link_token(rel: str, secret: str, ttl: int = LINK_TTL, now: float | None = None) -> str:
    body = _b64(json.dumps({"p": rel, "e": int((now or time.time()) + ttl)}, separators=(",", ":")).encode())
    sig = hmac.new(("link:" + secret).encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def link_verify(token: str, secret: str, now: float | None = None, *, check_expiry: bool = True) -> str:
    body, dot, sig = str(token or "").partition(".")
    if not dot or not body or not sig or len(token) > 2048:
        raise DocsError("bad_link", "Link is malformed.", 403)
    want = hmac.new(("link:" + secret).encode(), body.encode(), hashlib.sha256).digest()
    try:
        got = _unb64(sig)
    except Exception as exc:
        raise DocsError("bad_link", "Link is malformed.", 403) from exc
    if not hmac.compare_digest(want, got):
        raise DocsError("bad_link", "Link signature does not match.", 403)
    try:
        doc = json.loads(_unb64(body))
    except Exception as exc:
        raise DocsError("bad_link", "Link is malformed.", 403) from exc
    if not isinstance(doc, dict):
        raise DocsError("bad_link", "Link is malformed.", 403)
    if check_expiry and (now or time.time()) > float(doc.get("e") or 0):
        raise DocsError("bad_link", "Link expired. Reopen the document.", 403)
    rel = str(doc.get("p") or "")
    _clean_parts(rel)
    return rel


def ds_client_ok(ip: str) -> bool:
    """Storage and callback routes answer the Docs container (or loopback) only."""
    ip = str(ip or "")
    if ip in ("127.0.0.1", "::1"):
        return True
    if ip.startswith("::ffff:"):
        ip = ip[7:]
    return ip.startswith("172.30.1.") and ip.split(".")[-1].isdigit()


# ---------------------------------------------------------------- editor


def document_key(path: Path, rel: str) -> str:
    st = os.stat(path, follow_symlinks=False)
    raw = f"{rel}\x00{st.st_mtime_ns}\x00{st.st_size}".encode()
    return hashlib.sha256(raw).hexdigest()[:32]


def editor_config(rel: str, secret: str, *, user_name: str = "StickLLM", lang: str = "en") -> dict:
    path = resolve_doc(rel)
    if not path.is_file():
        raise DocsError("not_found", "That document does not exist.", 404)
    rel = rel_of(path)
    ext = extension(path.name)
    token = link_token(rel, secret)
    base = f"http://{GATEWAY_IP}:{GATEWAY_PORT}/api/docs"
    editable = ext in EDITABLE
    config = {
        "document": {
            "fileType": ext,
            "key": document_key(path, rel),
            "title": path.name,
            "url": f"{base}/storage/{token}",
            "permissions": {"edit": editable, "download": True, "print": True},
        },
        "documentType": KINDS[ext],
        "editorConfig": {
            "callbackUrl": f"{base}/callback/{token}",
            "lang": lang if re.fullmatch(r"[a-z]{2}(-[A-Z]{2})?", lang or "") else "en",
            "mode": "edit" if editable else "view",
            "user": {"id": "stickllm", "name": str(user_name)[:60] or "StickLLM"},
            "customization": {
                "autosave": True,
                "forcesave": True,
                "plugins": False,
                "uiTheme": "theme-classic-light",
            },
        },
    }
    config["token"] = jwt_sign(config, secret)
    return {"ok": True, "path": rel, "config": config}


def ds_fetch_url(url: str) -> str:
    """The callback's download URL, re-pointed at the loopback Docs server.

    Only ONLYOFFICE's own ``/cache/files/`` output is fetched, so a forged
    callback cannot make the gateway fetch another host (SSRF).
    """
    parsed = urllib.parse.urlsplit(str(url or ""))
    if parsed.scheme not in ("http", "https"):
        raise DocsError("bad_url", "Callback URL is not http.", 400)
    path = parsed.path
    at = path.find("/cache/files/")
    if at < 0:
        raise DocsError("bad_url", "Callback URL is not an ONLYOFFICE cache file.", 400)
    tail = path[at:]
    if ".." in tail.split("/") or "\\" in tail or "%2e" in tail.lower() or "%2f" in tail.lower():
        raise DocsError("bad_url", "Callback URL is not allowed.", 400)
    query = ("?" + parsed.query) if parsed.query else ""
    return DS_BASE + tail + query


def _fetch(url: str, limit: int = MAX_SAVE) -> bytes:
    if not url.startswith(DS_BASE + "/"):
        raise DocsError("bad_url", "Only the local Docs server is fetched.", 400)
    req = urllib.request.Request(url, headers={"User-Agent": "StickLLM-Docs"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=120) as resp:
        chunks = []
        total = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise DocsError("too_large", "Saved document is too large.", 413)
            chunks.append(chunk)
    return b"".join(chunks)


def callback_claims(body: bytes, auth_header: str, secret: str) -> dict:
    """The callback body as signed by ONLYOFFICE. Unsigned callbacks are refused."""
    try:
        doc = json.loads(body.decode("utf-8") or "{}")
    except Exception as exc:
        raise DocsError("bad_json", "Callback body is not JSON.", 400) from exc
    if not isinstance(doc, dict):
        raise DocsError("bad_json", "Callback body is not an object.", 400)
    if doc.get("token"):
        return jwt_verify(str(doc["token"]), secret)
    auth = str(auth_header or "")
    if auth.lower().startswith("bearer "):
        claims = jwt_verify(auth[7:].strip(), secret)
        inner = claims.get("payload")
        return inner if isinstance(inner, dict) else claims
    raise DocsError("bad_token", "Callback is not signed.", 403)


def handle_callback(token: str, body: bytes, auth_header: str, *, fetch=None) -> dict:
    """Save edited bytes from ONLYOFFICE into Documents. Returns ``{"error": 0|1}``."""
    if not vault_open():
        # ONLYOFFICE keeps the edit in its (vault) cache and retries.
        return {"error": 1, "message": VAULT_LOCKED_MESSAGE}
    secret = runtime_secret()
    # The link may be older than LINK_TTL when an editor stayed open for a
    # day; the body is still verified with the JWT secret below.
    rel = link_verify(token, secret, check_expiry=False)
    claims = callback_claims(body, auth_header, secret)
    status = int(claims.get("status") or 0)
    if status not in (2, 6):
        return {"error": 0}
    target = resolve_doc(rel)
    want = extension(target.name)
    got = str(claims.get("filetype") or want).lower()
    if got != want:
        raise DocsError("bad_type", "Saved file type does not match the document.", 400)
    data = (fetch or _fetch)(ds_fetch_url(str(claims.get("url") or "")))
    atomic_write(rel, data, overwrite=True)
    return {"error": 0}


# ---------------------------------------------------------------- vault dirs


def prepare_vault() -> dict:
    """Create the addon folders and Documents. Refuses symlinks."""
    require_vault()
    base = VAULT_MNT
    for part in ADDON_REL:
        base = base / part
        if os.path.islink(base):
            raise DocsError("bad_path", f"{base} is a symlink.", 500)
        if not base.exists():
            os.mkdir(base, 0o750)
    for name in ADDON_DIRS:
        path = base / name
        if os.path.islink(path):
            raise DocsError("bad_path", f"{path} is a symlink.", 500)
        if not path.exists():
            os.mkdir(path, 0o750)
        if os.stat(path).st_dev != _vault_dev():
            raise DocsError("bad_root", f"{path} is not on the vault filesystem.", 500)
    root = docs_root()
    return {"ok": True, "addon": str(base), "documents": str(root)}


# ---------------------------------------------------------------- nft


def nft_ruleset() -> str:
    """No internet and no LAN for the Docs container.

    Forwarded traffic from or to the Docs bridge is dropped unless it answers
    a connection the host made (the loopback publish). From the bridge, the
    host accepts only the gateway on 172.30.1.1:80 (document download and
    save callback, both signed).
    """
    return (
        f"table inet {NFT_TABLE} {{\n"
        "  chain forward {\n"
        "    type filter hook forward priority 0; policy accept;\n"
        f'    iifname "{BRIDGE}" drop\n'
        f'    oifname "{BRIDGE}" ct state established,related accept\n'
        f'    oifname "{BRIDGE}" drop\n'
        "  }\n"
        "  chain input {\n"
        "    type filter hook input priority 0; policy accept;\n"
        f'    iifname "{BRIDGE}" ct state established,related accept\n'
        f'    iifname "{BRIDGE}" ip daddr {GATEWAY_IP} tcp dport {GATEWAY_PORT} accept\n'
        f'    iifname "{BRIDGE}" drop\n'
        "  }\n"
        "}\n"
    )


def nft_apply_text() -> str:
    return f"add table inet {NFT_TABLE}\ndelete table inet {NFT_TABLE}\n" + nft_ruleset()


def nft_delete() -> int:
    proc = subprocess.run(["nft", "delete", "table", "inet", NFT_TABLE], capture_output=True, text=True, check=False)
    return 0 if proc.returncode in (0, 1) else proc.returncode


def nft_apply() -> int:
    nft_delete()
    proc = subprocess.run(["nft", "-f", "-"], input=nft_apply_text(), text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        print((proc.stderr or proc.stdout or "nft failed").strip(), file=sys.stderr)
    return proc.returncode


# ---------------------------------------------------------------- status


def status_path() -> Path:
    return RUN_DIR / STATUS_NAME


def read_status() -> dict:
    try:
        doc = json.loads(status_path().read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def write_status(state: str, **extra: object) -> dict:
    doc = {"state": state, "updated": int(time.time())}
    for key, value in extra.items():
        if value is not None:
            doc[key] = value
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        tmp = status_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(doc) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o644)
        os.replace(tmp, status_path())
    except OSError:
        pass
    return doc


def installed_marker() -> Path:
    return VAULT_MNT.joinpath(*ADDON_REL, "installed.json")


def is_installed() -> bool:
    if not vault_open():
        return False
    try:
        doc = json.loads(installed_marker().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(doc, dict) and doc.get("amd64_digest") == load_pin()["amd64_digest"]


def mark_installed() -> None:
    pin = load_pin()
    installed_marker().write_text(
        json.dumps({"image": pin["image"], "version": pin["version"], "amd64_digest": pin["amd64_digest"],
                    "prepared": prepared_ref(pin), "installed": int(time.time())}) + "\n",
        encoding="utf-8",
    )


def port_open(port: int = DS_PORT, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def status_document(*, upstream_up: bool | None = None) -> dict:
    vault = vault_open()
    settings = settings_open()
    saved = read_status()
    installed = is_installed() if vault else False
    up = port_open() if upstream_up is None else bool(upstream_up)
    state = saved.get("state") or ("stopped" if installed else "not_installed")
    if not vault:
        state, message = "locked", VAULT_LOCKED_MESSAGE
    elif not settings:
        state, message = "settings_missing", SETTINGS_MISSING_MESSAGE
    elif state == "installing":
        message = "Installing ONLYOFFICE Docs. The image is pulled onto the host drive."
    elif not installed:
        state, message = "not_installed", "ONLYOFFICE Docs is not installed yet."
    elif up and state in ("running", "starting", "stopped"):
        state, message = "running", "ONLYOFFICE Docs is running."
    elif state == "error":
        message = str(saved.get("message") or "ONLYOFFICE Docs failed to start.")[:300]
    else:
        message = "ONLYOFFICE Docs is starting."
    return {
        "ok": True,
        "state": state,
        "message": message,
        "vault_open": vault,
        "settings_open": settings,
        "installed": installed,
        "running": bool(vault and settings and installed and up),
        "documents": "vault/Documents",
        "version": load_pin()["version"],
    }


# ---------------------------------------------------------------- CLI


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    try:
        if cmd == "vault-open":
            return 0 if vault_open() else 2
        if cmd == "settings-open":
            return 0 if settings_open() else 2
        if cmd == "image-ref":
            print(image_ref())
            return 0
        if cmd == "prepared-ref":
            print(prepared_ref())
            return 0
        if cmd == "digest":
            print(load_pin()["amd64_digest"])
            return 0
        if cmd == "addon-dir":
            print(VAULT_MNT.joinpath(*ADDON_REL))
            return 0
        if cmd == "prepare-vault":
            prepare_vault()
            return 0
        if cmd == "secret-path":
            print(ensure_settings_secret())
            return 0
        if cmd == "runtime-secret":
            install_runtime_secret()
            return 0
        if cmd == "drop-runtime-secret":
            drop_runtime_secret()
            return 0
        if cmd == "nft-apply":
            return nft_apply()
        if cmd == "nft-delete":
            return nft_delete()
        if cmd == "nft-text":
            print(nft_apply_text(), end="")
            return 0
        if cmd == "installed":
            return 0 if is_installed() else 1
        if cmd == "mark-installed":
            mark_installed()
            return 0
        if cmd == "write-status":
            args = argv[2:]
            state = "unknown"
            extra: dict = {}
            i = 0
            while i < len(args):
                if args[i] == "--state" and i + 1 < len(args):
                    state = args[i + 1]
                    i += 2
                elif args[i] == "--message" and i + 1 < len(args):
                    extra["message"] = args[i + 1][:300]
                    i += 2
                else:
                    i += 1
            write_status(state, **extra)
            return 0
        if cmd == "status":
            print(json.dumps(status_document()))
            return 0
    except DocsError as exc:
        print(f"stickllm-docs: {exc.message}", file=sys.stderr)
        return 2 if exc.status == 423 else 1
    print("usage: stickllm_docs.py {vault-open|settings-open|image-ref|prepared-ref|digest|addon-dir|"
          "prepare-vault|secret-path|runtime-secret|drop-runtime-secret|nft-apply|nft-delete|nft-text|"
          "installed|mark-installed|write-status|status}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
