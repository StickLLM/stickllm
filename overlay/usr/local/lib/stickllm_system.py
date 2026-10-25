#!/usr/bin/env python3
"""Read-only system snapshot for the desktop monitor.

GPU numbers come only from nvidia-smi. If that command is missing or fails,
the GPU block says stats are unavailable. This module never starts or stops
the model, and it does not read secrets.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

RUN_DIR = Path(os.environ.get("STICKLLM_RUN", "/run/stickllm"))
_LAST_CPU: tuple[int, int] | None = None


def _kv(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def cpu_block(stat_text: str | None = None, load_text: str | None = None) -> dict:
    """CPU load, and a percent once two samples exist. Missing files stay unavailable."""
    global _LAST_CPU
    if stat_text is None:
        stat_text = _read(Path("/proc/stat"))
    if load_text is None:
        load_text = _read(Path("/proc/loadavg"))
    if not stat_text.strip() and not load_text.strip():
        return {"available": False, "message": "CPU stats are unavailable"}
    load = None
    bits = load_text.split()
    if len(bits) >= 3:
        try:
            load = [float(bits[0]), float(bits[1]), float(bits[2])]
        except ValueError:
            load = None
    percent = None
    line = ""
    for row in stat_text.splitlines():
        if row.startswith("cpu "):
            line = row
            break
    if line:
        nums = []
        for part in line.split()[1:]:
            try:
                nums.append(int(part))
            except ValueError:
                nums = []
                break
        if len(nums) >= 4:
            idle = nums[3] + (nums[4] if len(nums) > 4 else 0)
            total = sum(nums)
            prev = _LAST_CPU
            _LAST_CPU = (total, idle)
            if prev is not None:
                dt = total - prev[0]
                di = idle - prev[1]
                if dt > 0:
                    percent = round(100.0 * (dt - di) / dt, 1)
    if percent is None and load is None:
        return {"available": False, "message": "CPU stats are unavailable"}
    return {"available": True, "percent": percent, "load": load}


def memory_block(meminfo: str | None = None) -> dict:
    if meminfo is None:
        meminfo = _read(Path("/proc/meminfo"))
    if not meminfo.strip():
        return {"available": False, "message": "Memory stats are unavailable"}
    vals: dict[str, int] = {}
    for line in meminfo.splitlines():
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            vals[key] = int(parts[0]) * 1024
        except ValueError:
            continue
    total = vals.get("MemTotal")
    avail = vals.get("MemAvailable")
    if total is None or avail is None:
        return {"available": False, "message": "Memory stats are unavailable"}
    used = max(0, total - avail)
    return {"available": True, "total": total, "used": used, "free": avail}


def gpu_block(runner=None) -> dict:
    """Query nvidia-smi. A missing command is unavailable, never a made-up reading."""
    if runner is None:
        if shutil.which("nvidia-smi") is None:
            return {"available": False, "message": "GPU stats are unavailable"}

        def runner(argv: list[str]) -> subprocess.CompletedProcess:
            return subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )

    try:
        proc = runner(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ]
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "message": "GPU stats are unavailable"}
    stdout = getattr(proc, "stdout", "") or ""
    code = getattr(proc, "returncode", 1)
    if code != 0 or not stdout.strip():
        return {"available": False, "message": "GPU stats are unavailable"}
    gpus = []
    for line in stdout.splitlines():
        cells = [cell.strip() for cell in line.split(",")]
        if len(cells) < 4:
            continue
        try:
            used = int(float(cells[1]))
            total = int(float(cells[2]))
            temp = int(float(cells[3]))
        except ValueError:
            continue
        gpus.append(
            {
                "name": cells[0],
                "memory_used_mib": used,
                "memory_total_mib": total,
                "temperature_c": temp,
            }
        )
    if not gpus:
        return {"available": False, "message": "GPU stats are unavailable"}
    return {"available": True, "gpus": gpus}


def disk_block(paths: list[tuple[str, str]] | None = None) -> dict:
    if paths is None:
        paths = [("System", "/"), ("Home", "/home/stickllm")]
        vault = os.environ.get("STICKLLM_VAULT_MNT", "/var/lib/stickllm/vault")
        if os.path.ismount(vault):
            paths.append(("Vault", vault))
    rows = []
    for label, raw in paths:
        path = Path(raw)
        if not path.exists():
            continue
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            rows.append({"label": label, "available": False, "message": "Disk stats are unavailable"})
            continue
        rows.append(
            {
                "label": label,
                "available": True,
                "total": usage.total,
                "used": usage.used,
                "free": usage.free,
            }
        )
    if not rows:
        return {"available": False, "message": "Disk stats are unavailable", "volumes": []}
    return {"available": True, "volumes": rows}


def model_block(run_dir: Path | None = None) -> dict:
    run = RUN_DIR if run_dir is None else Path(run_dir)
    env = _kv(_read(run / "model.env"))
    runtime = _kv(_read(run / "llama-runtime.env"))
    name = env.get("STICKLLM_MODEL_NAME") or ""
    path = env.get("STICKLLM_MODEL") or runtime.get("model") or runtime.get("STICKLLM_MODEL") or ""
    if not name and path:
        name = Path(path).name
    active = ""
    sub = ""
    try:
        proc = subprocess.run(
            ["systemctl", "show", "stickllm-llama.service", "-p", "ActiveState", "-p", "SubState", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        for line in (proc.stdout or "").splitlines():
            if line.startswith("ActiveState="):
                active = line.split("=", 1)[1].strip()
            elif line.startswith("SubState="):
                sub = line.split("=", 1)[1].strip()
    except (OSError, subprocess.SubprocessError):
        active = ""
    llama_up = False
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=1) as resp:
            doc = json.loads(resp.read().decode() or "{}")
        llama_up = str(doc.get("status") or "").lower() in {"ok", "healthy"}
    except Exception:
        llama_up = False
    if not name and not path and not active:
        return {"available": False, "message": "No model is loaded"}
    return {
        "available": True,
        "name": name,
        "path": path,
        "service": active or "unknown",
        "sub_state": sub,
        "llama_up": llama_up,
    }


def snapshot(
    *,
    stat_text: str | None = None,
    load_text: str | None = None,
    meminfo: str | None = None,
    gpu_runner=None,
    disks: list[tuple[str, str]] | None = None,
    run_dir: Path | None = None,
    include_gpu: bool = True,
    include_model: bool = True,
) -> dict:
    gpu = gpu_block(gpu_runner) if include_gpu else {"available": False, "message": "GPU stats are unavailable"}
    model = model_block(run_dir) if include_model else {"available": False, "message": "No model is loaded"}
    return {
        "ok": True,
        "cpu": cpu_block(stat_text, load_text),
        "memory": memory_block(meminfo),
        "gpu": gpu,
        "disk": disk_block(disks),
        "model": model,
    }
