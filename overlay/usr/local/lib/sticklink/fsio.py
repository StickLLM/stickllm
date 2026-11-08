"""Atomic file I/O and locking for /mnt/stickllm-settings/sticklink (§3).

Write: temp `.<target>.tmp.<8 hex>` in the target's own directory, O_CREAT|O_EXCL,
0600, write, fsync, rename over the target, fsync the directory.
Delete: unlink, fsync the directory.
Lock: exclusive flock on sticklink/.lock for writers, shared for readers.
"""
from __future__ import annotations

import errno
import os
import re
import secrets
import stat
import sys
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows host lab unit tests
    fcntl = None  # type: ignore

TEMP_RE = re.compile(r"^\..+\.tmp\.[0-9a-f]{8}$")
LOCK_NAME = ".lock"
# Host-side Windows has no flock / O_NOFOLLOW / O_DIRECTORY. Allow a reduced
# path only under STICKLINK_TESTING (lab/VM host runners). Shipping images are Linux.
def _win_lab() -> bool:
    return sys.platform == "win32" and os.environ.get("STICKLINK_TESTING") == "1"


class FaultInjected(Exception):
    """Raised by fault points in tests (simulated crash)."""


# Fault injection. Only active when STICKLINK_TESTING=1. A test sets
# STICKLINK_FAULT=<point> (crash = os._exit(97), for subprocess tests) or
# installs a python hook (raises FaultInjected, for in-process tests).
_fault_hook = None


def fault(point: str) -> None:
    if os.environ.get("STICKLINK_TESTING") != "1":
        return
    if _fault_hook is not None:
        _fault_hook(point)
    want = os.environ.get("STICKLINK_FAULT", "")
    if want and want == point:
        os._exit(97)


def set_fault_hook(fn) -> None:
    global _fault_hook
    _fault_hook = fn


def _owner():
    """uid/gid for sticklink files: the sticklinkd user if it exists, else none."""
    try:
        import pwd
        pw = pwd.getpwnam(os.environ.get("STICKLINK_USER", "sticklinkd"))
        return pw.pw_uid, pw.pw_gid
    except (KeyError, ImportError):
        return None


def _chown(path_or_fd, own) -> None:
    if own is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return
    if isinstance(path_or_fd, int):
        os.fchown(path_or_fd, own[0], own[1])
    else:
        os.chown(path_or_fd, own[0], own[1], follow_symlinks=False)


def ensure_dir(path: Path, mode: int = 0o700) -> Path:
    path = Path(path)
    try:
        os.mkdir(path, mode)
    except FileExistsError:
        pass
    st = os.lstat(path)
    if not stat.S_ISDIR(st.st_mode):
        raise RuntimeError(f"{path} is not a directory")
    os.chmod(path, mode)
    _chown(str(path), _owner())
    return path


def fsync_dir(path: Path) -> None:
    if _win_lab():
        return
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def temp_name(target: Path) -> Path:
    return target.parent / f".{target.name}.tmp.{secrets.token_hex(4)}"


def atomic_write(target: Path, data: bytes, fault_tag: str = "") -> None:
    target = Path(target)
    tmp = temp_name(target)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):  # Windows: prevent CRLF corruption of sealed blobs
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW") and not _win_lab():
        flags |= os.O_NOFOLLOW
    fd = os.open(str(tmp), flags, 0o600)
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        _chown(fd, _owner())
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            view = view[n:]
        os.fsync(fd)
    finally:
        os.close(fd)
    fault(f"{fault_tag}:tmp-written" if fault_tag else "tmp-written")
    os.replace(tmp, target) if _win_lab() else os.rename(tmp, target)
    fault(f"{fault_tag}:renamed" if fault_tag else "renamed")
    fsync_dir(target.parent)


def atomic_delete(target: Path) -> bool:
    target = Path(target)
    try:
        os.unlink(target)
    except FileNotFoundError:
        return False
    fsync_dir(target.parent)
    return True


def read_exact(path: Path, max_len: int = 1 << 20) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW") and not _win_lab():
        flags |= os.O_NOFOLLOW
    fd = os.open(str(path), flags)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"{path}: not a regular file")
        if st.st_size > max_len:
            raise ValueError(f"{path}: too large")
        chunks = []
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            chunks.append(b)
        return b"".join(chunks)
    finally:
        os.close(fd)


def cleanup_temps(*dirs: Path) -> list[str]:
    """R5 step 1: delete leftover .<target>.tmp.<hex> files. Returns names removed."""
    removed = []
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        hit = False
        for name in os.listdir(d):
            if TEMP_RE.match(name):
                p = d / name
                if p.is_symlink() or p.is_file():
                    os.unlink(p)
                    removed.append(name)
                    hit = True
        if hit:
            fsync_dir(d)
    return removed


class Lock:
    """flock on sticklink/.lock. Exclusive for writers, shared for readers."""

    def __init__(self, root: Path, exclusive: bool = True, blocking: bool = True):
        self.path = Path(root) / LOCK_NAME
        self.exclusive = exclusive
        self.blocking = blocking
        self.fd = -1

    def __enter__(self):
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW") and not _win_lab():
            flags |= os.O_NOFOLLOW
        self.fd = os.open(str(self.path), flags, 0o600)
        if fcntl is None:
            if not _win_lab():
                os.close(self.fd)
                self.fd = -1
                raise RuntimeError("fcntl.flock required outside Windows STICKLINK_TESTING lab")
            return self
        op = fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH
        if not self.blocking:
            op |= fcntl.LOCK_NB
        try:
            fcntl.flock(self.fd, op)
        except OSError as e:
            os.close(self.fd)
            self.fd = -1
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN):
                raise TimeoutError("sticklink lock is held") from e
            raise
        return self

    def __exit__(self, *exc):
        if self.fd >= 0:
            if fcntl is not None:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = -1
        return False
