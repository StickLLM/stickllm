"""Stage large model files from slow USB into tmpfs RAM before Load / after Download.

First byte still comes off USB once (sequential copy). That avoids the engine
doing many small random reads against flash while loading into VRAM — which is
what makes USB Loads crawl in the high-90% range.

Staged copies live on a RAM-backed tmpfs (/tmp or /dev/shm — not tiny /run) and
are never mlock'd. They are deleted on Unload, when switching models, or when
MemAvailable gets tight so RAM stays available for KV / other work.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

RUN = Path(os.environ.get("STICKLLM_RUN", "/run/stickllm"))
MIN_STAGE_BYTES = int(float(os.environ.get("STICKLLM_STAGE_MIN_GB", "2")) * (1024**3))
# Keep headroom for OS + KV / activations after the copy / under pressure.
HEADROOM_BYTES = int(float(os.environ.get("STICKLLM_STAGE_HEADROOM_GB", "10")) * (1024**3))
PROGRESS = RUN / "stage-progress.json"


def _mem_available() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return 0


def _fs_free(path: Path) -> int:
    """Free bytes on the filesystem that would hold staged copies."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        st = os.statvfs(str(path))
        return int(st.f_bavail) * int(st.f_frsize)
    except OSError:
        try:
            st = os.statvfs(str(path.parent if path.name else path))
            return int(st.f_bavail) * int(st.f_frsize)
        except OSError:
            return 0


def stage_dir_for(need_bytes: int = 0) -> Path:
    """Pick a tmpfs big enough for this model. /run is often only ~6G — skip it."""
    env = os.environ.get("STICKLLM_MODEL_STAGE", "").strip()
    if env:
        return Path(env)
    need = max(int(need_bytes), MIN_STAGE_BYTES)
    candidates = (
        Path("/tmp/stickllm/model-stage"),
        Path("/dev/shm/stickllm-model-stage"),
        RUN / "model-stage",
    )
    best: Path | None = None
    best_free = -1
    for candidate in candidates:
        try:
            free = _fs_free(candidate)
        except OSError:
            free = 0
        if free >= need and free > best_free:
            best = candidate
            best_free = free
    if best is not None:
        return best
    # Last resort: largest free mount (caller may still refuse via should_stage).
    for candidate in candidates:
        free = _fs_free(candidate)
        if free > best_free:
            best = candidate
            best_free = free
    return best or Path("/tmp/stickllm/model-stage")


# Module default for free_stage / progress readers (updated when a stage starts).
STAGE_DIR = stage_dir_for(0)

def _write_progress(doc: dict) -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    payload = dict(doc)
    payload["updated"] = int(time.time())
    tmp = PROGRESS.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o666)
        except OSError:
            pass
        tmp.replace(PROGRESS)
        try:
            os.chmod(PROGRESS, 0o666)
        except OSError:
            pass
    except OSError:
        pass


def clear_progress() -> None:
    try:
        PROGRESS.unlink(missing_ok=True)
    except OSError:
        pass


def _all_stage_dirs() -> list[Path]:
    env = os.environ.get("STICKLLM_MODEL_STAGE", "").strip()
    out: list[Path] = []
    if env:
        out.append(Path(env))
    for p in (
        Path("/tmp/stickllm/model-stage"),
        Path("/dev/shm/stickllm-model-stage"),
        RUN / "model-stage",
        STAGE_DIR,
    ):
        if p not in out:
            out.append(p)
    return out


def stage_dir_bytes() -> int:
    total = 0
    for d in _all_stage_dirs():
        try:
            if not d.is_dir():
                continue
            for p in d.iterdir():
                try:
                    if p.is_file():
                        total += p.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass
    return total


def sibling_parts(path: Path) -> list[Path]:
    """GGUF split set (00001-of-N) or a single file."""
    import re

    name = path.name
    m = re.match(r"^(?P<stem>.+)-(?P<idx>\d{5})-of-(?P<total>\d{5})\.gguf$", name, re.I)
    if not m:
        return [path]
    total = int(m.group("total"))
    stem = m.group("stem")
    out: list[Path] = []
    for i in range(1, total + 1):
        p = path.parent / f"{stem}-{i:05d}-of-{total:05d}.gguf"
        if p.is_file():
            out.append(p)
    return out or [path]


def _path_is_staged(p: Path) -> bool:
    s = str(p)
    markers = ("/model-stage/", "/stickllm-model-stage/", "/stickllm/model-stage/")
    if any(m in s for m in markers):
        return True
    try:
        rp = p.resolve()
        for d in _all_stage_dirs():
            try:
                if d.resolve() == rp.parent.resolve() or d.resolve() in rp.parents:
                    return True
            except OSError:
                continue
    except OSError:
        pass
    return False


def active_stage_keep_names() -> set[str]:
    """Basenames currently referenced by model.env (do not free while loaded)."""
    keep: set[str] = set()
    env = RUN / "model.env"
    try:
        for line in env.read_text(encoding="utf-8").splitlines():
            if not line.startswith("STICKLLM_MODEL="):
                continue
            p = Path(line.split("=", 1)[1].strip())
            if _path_is_staged(p):
                keep.add(p.name)
                for sib in sibling_parts(p):
                    keep.add(sib.name)
    except OSError:
        pass
    return keep


def free_stage(*, keep: set[str] | None = None, reason: str = "reclaim") -> dict:
    """Delete staged tmpfs copies. Never mlock — this is how RAM is given back."""
    keep = keep or set()
    freed = 0
    removed: list[str] = []
    try:
        any_dir = False
        for d in _all_stage_dirs():
            if not d.is_dir():
                continue
            any_dir = True
            for p in list(d.iterdir()):
                if p.name in keep:
                    continue
                try:
                    if p.is_file():
                        sz = p.stat().st_size
                        p.unlink()
                        freed += sz
                        removed.append(p.name)
                except OSError:
                    pass
        left = stage_dir_bytes() > 0
        if not left:
            clear_progress()
        if not any_dir and not removed:
            clear_progress()
            return {"ok": True, "freed_bytes": 0, "removed": [], "reason": reason}
    except OSError as e:
        return {"ok": False, "error": str(e), "freed_bytes": freed, "removed": removed, "reason": reason}
    return {"ok": True, "freed_bytes": freed, "removed": removed, "reason": reason}


def reclaim_if_low_ram(*, need_extra: int = 0, force: bool = False) -> dict:
    """Free staged copies when MemAvailable is tight (or force=True).

    Keeps the currently loaded staged file while model.env still points at it,
    unless force=True (Unload / explicit clear).
    """
    avail = _mem_available()
    threshold = HEADROOM_BYTES + max(0, int(need_extra))
    if not force and avail >= threshold:
        return {
            "ok": True,
            "freed": False,
            "reason": "enough-ram",
            "avail": avail,
            "threshold": threshold,
            "staged_bytes": stage_dir_bytes(),
        }
    keep: set[str] = set() if force else active_stage_keep_names()
    # Under hard pressure, free even the active stage — engine must fall back
    # only after Unload; if still loaded, keep active names unless force.
    if not force and avail < HEADROOM_BYTES // 2:
        # Critical: free everything except we still keep active to avoid tearing
        # the running mmap out from under llama/ninfer mid-request.
        keep = active_stage_keep_names()
    out = free_stage(keep=keep, reason="pressure" if not force else "force")
    out.update(
        {
            "freed": bool(out.get("freed_bytes")),
            "avail_before": avail,
            "avail_after": _mem_available(),
            "threshold": threshold,
            "kept": sorted(keep),
        }
    )
    return out


def path_on_usb(path: Path) -> bool:
    """True when the file's block device reports TRAN=usb (or live DATA stick)."""
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    # Live StickLLM DATA / host USB mounts are almost always flash.
    s = str(resolved)
    if "/mnt/stickllm-data" in s or "/mnt/stickllm-host" in s or "/run/live/" in s:
        return True
    try:
        import subprocess

        r = subprocess.run(
            ["findmnt", "-n", "-o", "SOURCE", "-T", str(resolved)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        src = (r.stdout or "").strip()
        if not src:
            return False
        # SOURCE like /dev/sdc3 or /dev/mapper/...
        node = src.split("[", 1)[0].strip()
        if node.startswith("/dev/"):
            base = Path(node).name
            # strip partition digits: sdc3 → sdc
            while base and base[-1].isdigit():
                base = base[:-1]
            if not base:
                return False
            tran = Path(f"/sys/block/{base}/device/../../../").resolve()
            # Prefer lsblk
            r2 = subprocess.run(
                ["lsblk", "-no", "TRAN", f"/dev/{base}"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return "usb" in (r2.stdout or "").lower()
    except Exception:
        return False
    return False


def should_stage(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "missing"
    try:
        size = path.stat().st_size
    except OSError:
        return False, "stat-failed"
    parts = sibling_parts(path)
    total = 0
    for p in parts:
        try:
            total += p.stat().st_size
        except OSError:
            return False, "stat-failed"
    if total < MIN_STAGE_BYTES:
        return False, "small"
    if not path_on_usb(path):
        return False, "not-usb"
    avail = _mem_available()
    need = total + HEADROOM_BYTES
    if avail < need:
        return False, f"low-ram need={need} avail={avail}"
    # Pick a mount that can hold this file (/run is often only ~6G).
    global STAGE_DIR
    STAGE_DIR = stage_dir_for(total)
    fs_free = _fs_free(STAGE_DIR)
    if fs_free < total:
        return False, f"low-tmpfs need={total} free={fs_free} dir={STAGE_DIR}"
    return True, f"ok size={total} avail={avail} fs_free={fs_free} dir={STAGE_DIR}"


def find_existing_staged(parts: list[Path]) -> Path | None:
    """Return main staged path if a complete same-size copy already exists in ANY stage dir.

    Avoids a second USB→RAM copy when /dev/shm already has the file but
    stage_dir_for would prefer /tmp (more free space). Prefers the first
    complete hit; caller should drop duplicates in other mounts.
    """
    if not parts:
        return None
    main = parts[0]
    for d in _all_stage_dirs():
        try:
            if not d.is_dir():
                continue
            dest_main = d / main.name
            if not dest_main.is_file():
                continue
            if all(
                (d / p.name).is_file() and (d / p.name).stat().st_size == p.stat().st_size
                for p in parts
            ):
                return dest_main
        except OSError:
            continue
    return None


def _dedupe_staged(parts: list[Path], keep_dir: Path) -> None:
    """Delete complete duplicates of these names outside keep_dir (one RAM copy only)."""
    names = {p.name for p in parts}
    keep_dir = keep_dir.resolve() if keep_dir.exists() else keep_dir
    for d in _all_stage_dirs():
        try:
            if not d.is_dir():
                continue
            try:
                if d.resolve() == keep_dir:
                    continue
            except OSError:
                if d == keep_dir:
                    continue
            for p in list(d.iterdir()):
                if p.is_file() and (p.name in names or p.name in {n + ".partial" for n in names}):
                    try:
                        p.unlink()
                    except OSError:
                        pass
        except OSError:
            pass


def _drop_partials(parts: list[Path]) -> None:
    """Remove leftover *.partial for these names across stage dirs."""
    want = {p.name + ".partial" for p in parts}
    for d in _all_stage_dirs():
        try:
            if not d.is_dir():
                continue
            for p in list(d.iterdir()):
                if p.is_file() and p.name in want:
                    try:
                        p.unlink()
                    except OSError:
                        pass
        except OSError:
            pass


def stage_model_to_ram(path: str | Path) -> dict:
    """Copy USB model (and GGUF siblings) into tmpfs. Returns paths for Load.

    Never mlock. Other staged files are freed first so RAM is not piled up.
    """
    global STAGE_DIR
    src = Path(path)
    result: dict = {
        "ok": True,
        "staged": False,
        "path": str(src),
        "reason": "",
    }
    if not src.is_file():
        result["reason"] = "missing"
        return result
    parts = sibling_parts(src)
    try:
        total = sum(p.stat().st_size for p in parts)
    except OSError:
        result["reason"] = "stat-failed"
        return result

    # Prefer an already-complete RAM copy in any tmpfs (download stage or prior Load).
    existing = find_existing_staged(parts)
    if existing is not None:
        STAGE_DIR = existing.parent
        _dedupe_staged(parts, STAGE_DIR)
        _drop_partials(parts)
        free_stage(keep={p.name for p in parts}, reason="reuse-staged")
        _write_progress(
            {
                "state": "done",
                "phase": "staged",
                "percent": 100,
                "bytes_done": total,
                "bytes_total": total,
                "src": str(src),
                "dest": str(existing),
                "caption": "Already in RAM — loading…",
            }
        )
        result.update(
            {
                "staged": True,
                "path": str(existing),
                "reused": True,
                "reason": f"reused {existing}",
            }
        )
        return result

    ok, reason = should_stage(src)
    result["reason"] = reason
    if not ok:
        # Still reclaim leftovers if we're short on RAM.
        if "low-ram" in reason or "low-tmpfs" in reason:
            reclaim_if_low_ram(force=False)
        return result
    STAGE_DIR = stage_dir_for(total)
    # Make room: drop other staged models (keep only this set once copy starts).
    reclaim_if_low_ram(need_extra=total, force=False)
    free_stage(keep={p.name for p in parts}, reason="switch-model")
    _drop_partials(parts)
    # Re-check after reclaim — another path may have appeared, or RAM dropped.
    existing = find_existing_staged(parts)
    if existing is not None:
        STAGE_DIR = existing.parent
        _dedupe_staged(parts, STAGE_DIR)
        _write_progress(
            {
                "state": "done",
                "phase": "staged",
                "percent": 100,
                "bytes_done": total,
                "bytes_total": total,
                "src": str(src),
                "dest": str(existing),
                "caption": "Already in RAM — loading…",
            }
        )
        result.update(
            {
                "staged": True,
                "path": str(existing),
                "reused": True,
                "reason": f"reused {existing}",
            }
        )
        return result
    ok, reason = should_stage(src)
    if not ok:
        result["reason"] = reason
        return result
    STAGE_DIR = stage_dir_for(total)
    STAGE_DIR.mkdir(parents=True, exist_ok=True)

    dest_main = STAGE_DIR / src.name
    # Reuse if already staged same size in the chosen dir.
    try:
        if dest_main.is_file() and all(
            (STAGE_DIR / p.name).is_file() and (STAGE_DIR / p.name).stat().st_size == p.stat().st_size
            for p in parts
        ):
            _write_progress(
                {
                    "state": "done",
                    "phase": "staged",
                    "percent": 100,
                    "bytes_done": total,
                    "bytes_total": total,
                    "src": str(src),
                    "dest": str(dest_main),
                    "caption": "Already in RAM — loading…",
                }
            )
            result.update({"staged": True, "path": str(dest_main), "reused": True, "reason": "reused"})
            return result
    except OSError:
        pass

    done = 0
    _write_progress(
        {
            "state": "copying",
            "phase": "usb-to-ram",
            "percent": 0,
            "bytes_done": 0,
            "bytes_total": total,
            "src": str(src),
            "dest": str(dest_main),
            "caption": "Copying from USB to RAM…",
        }
    )
    chunk = 8 * 1024 * 1024
    try:
        for p in parts:
            dest = STAGE_DIR / p.name
            # Path.with_suffix(".ninfer.partial") replaces .ninfer — OK.
            # Prefer explicit name so multi-dot stems stay stable.
            tmp = dest.parent / (dest.name + ".partial")
            with p.open("rb") as inf, tmp.open("wb") as out:
                while True:
                    buf = inf.read(chunk)
                    if not buf:
                        break
                    out.write(buf)
                    done += len(buf)
                    pct = min(99.0, (done / total) * 100.0) if total else 0
                    _write_progress(
                        {
                            "state": "copying",
                            "phase": "usb-to-ram",
                            "percent": round(pct, 1),
                            "bytes_done": done,
                            "bytes_total": total,
                            "src": str(src),
                            "dest": str(dest_main),
                            "file": p.name,
                            "caption": "Copying from USB to RAM…",
                        }
                    )
            tmp.replace(dest)
    except OSError as e:
        clear_progress()
        result.update({"ok": False, "error": str(e), "path": str(src), "reason": f"copy-failed:{e}"})
        return result

    _write_progress(
        {
            "state": "done",
            "phase": "staged",
            "percent": 100,
            "bytes_done": total,
            "bytes_total": total,
            "src": str(src),
            "dest": str(dest_main),
            "caption": "Copied to RAM — loading into GPU…",
        }
    )
    result.update({"staged": True, "path": str(dest_main), "bytes": total, "reason": "copied"})
    return result


def read_stage_progress() -> dict:
    try:
        raw = json.loads(PROGRESS.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}
