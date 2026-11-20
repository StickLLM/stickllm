#!/usr/bin/env python3
"""Read-only system snapshot for the desktop monitor.

NVIDIA numbers come from nvidia-smi, AMD numbers from amdgpu sysfs, names
from lspci (0.5.9). Missing sources say unavailable, never a made-up value. This module never starts or stops
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


# --- monitor cleanup: every physical drive with live MB/s ------------------
_LAST_IO: dict[str, tuple] = {}
_SKIP_BLOCK = ("loop", "ram", "dm-", "zram", "sr", "fd", "nbd", "md", "mmcblk0boot", "mtd")
LIVE_MEDIUM = os.environ.get("STICKLLM_LIVE_MEDIUM", "/run/live/medium")


def _unescape_mount(raw: str) -> str:
    return raw.replace("\\040", " ").replace("\\011", "\t").replace("\\134", "\\")


def _parent_disks(name: str, sys_block: Path) -> list[str]:
    """Physical disk(s) behind a kernel block name (partition, dm-N, md)."""
    if (sys_block / name).is_dir() and not name.startswith(("dm-", "md")):
        return [name]
    cls = sys_block.parent / "class" / "block" / name
    part = cls if cls.exists() else None
    if part is not None and (part / "partition").exists():
        try:
            return [os.path.basename(os.path.dirname(os.path.realpath(part)))]
        except OSError:
            return []
    slaves = (sys_block / name / "slaves")
    out: list[str] = []
    if slaves.is_dir():
        for s in sorted(slaves.iterdir()):
            for d in _parent_disks(s.name, sys_block):
                if d not in out:
                    out.append(d)
    return out


def _dev_name(dev: str) -> str:
    """'/dev/mapper/x' or '/dev/sda1' -> kernel name ('dm-0', 'sda1')."""
    try:
        return os.path.basename(os.path.realpath(dev))
    except OSError:
        return os.path.basename(dev)


def parse_diskstats(text: str) -> dict[str, tuple]:
    """name -> (sectors read, sectors written, io_ticks ms or None)."""
    out: dict[str, tuple] = {}
    for line in (text or "").splitlines():
        f = line.split()
        if len(f) >= 10:
            try:
                ticks = int(f[12]) if len(f) >= 13 else None
                out[f[2]] = (int(f[5]), int(f[9]), ticks)
            except ValueError:
                continue
    return out


def _models_path() -> str:
    env = os.environ.get("STICKLLM_MODELS_DIR", "").strip()
    if env:
        return env
    try:
        doc = json.loads(_read(Path(os.environ.get("STICKLLM_MODELS_DIR_FILE", str(RUN_DIR / "models-dir.json")))) or "{}")
        if isinstance(doc, dict) and doc.get("path"):
            return str(doc["path"])
    except ValueError:
        pass
    model = _kv(_read(RUN_DIR / "model.env")).get("STICKLLM_MODEL") or ""
    return os.path.dirname(model) if model else ""


def _mount_for(path: str, mounts: list[tuple[str, str]]) -> str:
    """Device of the longest mount point that contains path."""
    best, dev = "", ""
    if not path:
        return ""
    for d, mnt in mounts:
        if (path == mnt or path.startswith(mnt.rstrip("/") + "/")) and len(mnt) >= len(best):
            best, dev = mnt, d
    return dev


def drives_block(sys_block: Path | None = None, mounts_text: str | None = None,
                 diskstats_text: str | None = None, now: float | None = None,
                 usage=None, vault_mnt: str | None = None, models_path: str | None = None) -> list[dict]:
    """Every physical drive (USB stick, NVMe, SATA SSD/HDD): model, size,
    used/free of its mounted filesystems, live read/write MB/s, and which one is
    the boot stick and which holds the models or the vault."""
    import time
    sb = sys_block or Path("/sys/block")
    if mounts_text is None:
        mounts_text = _read(Path("/proc/mounts"))
    if diskstats_text is None:
        diskstats_text = _read(Path("/proc/diskstats"))
    now = time.monotonic() if now is None else now
    usage = usage or shutil.disk_usage
    vault_mnt = vault_mnt if vault_mnt is not None else os.environ.get("STICKLLM_VAULT_MNT", "/var/lib/stickllm/vault")
    models_path = _models_path() if models_path is None else models_path
    mounts: list[tuple[str, str]] = []
    for line in mounts_text.splitlines():
        f = line.split()
        if len(f) >= 2 and f[0].startswith("/dev/"):
            mounts.append((f[0], _unescape_mount(f[1])))
    stats = parse_diskstats(diskstats_text)
    try:
        names = sorted(p.name for p in sb.iterdir())
    except OSError:
        names = []
    disks: dict[str, dict] = {}
    for name in names:
        if name.startswith(_SKIP_BLOCK):
            continue
        base = sb / name
        sectors = _int(_read(base / "size").strip())
        if not sectors:
            continue
        model = " ".join((_read(base / "device" / "model") or "").split())
        vendor = " ".join((_read(base / "device" / "vendor") or "").split())
        if vendor and model and not model.lower().startswith(vendor.lower()) and vendor.upper() not in ("ATA", "NVME"):
            model = vendor + " " + model
        try:
            real = os.path.realpath(base)
        except OSError:
            real = ""
        rot = _read(base / "queue" / "rotational").strip() == "1"
        removable = _read(base / "removable").strip() == "1"
        if "/usb" in real:
            kind = "USB"
        elif name.startswith("nvme"):
            kind = "NVMe"
        elif name.startswith("mmcblk"):
            kind = "SD"
        else:
            kind = "HDD" if rot else "SSD"
        disks[name] = {"name": name, "model": model or name, "kind": kind, "removable": removable,
                       "size": sectors * 512, "mounts": [], "roles": [],
                       "read_mb_s": None, "write_mb_s": None, "busy_percent": None}
    seen_dev: set[str] = set()
    for dev, mnt in mounts:
        kname = _dev_name(dev)
        parents = [d for d in _parent_disks(kname, sb) if d in disks]
        for d in parents:
            if mnt == LIVE_MEDIUM and "boot" not in disks[d]["roles"]:
                disks[d]["roles"].append("boot")
        if not parents or kname in seen_dev:
            continue  # bind mounts of the same filesystem count once
        seen_dev.add(kname)
        try:
            u = usage(mnt)
            entry = {"mount": mnt, "total": u.total, "used": u.used, "free": u.free}
        except OSError:
            entry = {"mount": mnt}
        for d in parents:
            disks[d]["mounts"].append(entry)
    vault_dev = next((d for d, m in mounts if m == vault_mnt.rstrip("/")), "")
    for role, dev in (("models", _mount_for(models_path, mounts)), ("vault", vault_dev)):
        if not dev:
            continue
        for d in _parent_disks(_dev_name(dev), sb):
            if d in disks and role not in disks[d]["roles"]:
                disks[d]["roles"].append(role)
    for name, row in disks.items():
        if name in stats:
            rd, wr, ticks = stats[name]
            prev = _LAST_IO.get(name)
            _LAST_IO[name] = (now, rd, wr, ticks)
            if prev and now > prev[0]:
                dt = now - prev[0]
                row["read_mb_s"] = round(max(0, rd - prev[1]) * 512 / dt / 1e6, 1)
                row["write_mb_s"] = round(max(0, wr - prev[2]) * 512 / dt / 1e6, 1)
                # Utilisation: share of wall time the device had I/O in flight
                # (io_ticks ms delta over the sample interval), like iostat %util.
                if ticks is not None and len(prev) > 3 and prev[3] is not None:
                    row["busy_percent"] = round(min(100.0, max(0, ticks - prev[3]) / (dt * 1000.0) * 100.0), 1)
        tot = [m for m in row["mounts"] if "total" in m]
        if tot:
            row["fs_total"] = sum(m["total"] for m in tot)
            row["fs_used"] = sum(m["used"] for m in tot)
            row["fs_free"] = sum(m["free"] for m in tot)
    order = {"boot": 0, "models": 1, "vault": 2}
    return sorted(disks.values(), key=lambda r: (min([order[x] for x in r["roles"]] or [9]), r["name"]))


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


# Hardware warnings (v0.5.4): warn, never refuse. The production llama-server
# is built for AVX2 CPUs; without AVX it dies with SIGILL, so say so up front.
LOW_VRAM_GB = 6.0


def cpu_flags(cpuinfo: str | None = None) -> set[str]:
    if cpuinfo is None:
        cpuinfo = _read(Path("/proc/cpuinfo"))
    for line in cpuinfo.splitlines():
        if line.startswith("flags") and ":" in line:
            return set(line.split(":", 1)[1].split())
    return set()


def _amd_present(drm: Path | None = None) -> bool:
    """An AMD (0x1002) display device in sysfs."""
    root = drm or Path("/sys/class/drm")
    try:
        for v in root.glob("card[0-9]*/device/vendor"):
            if _read(v).strip().lower() == "0x1002":
                return True
    except OSError:
        pass
    return False


def hardware_warnings(cpuinfo: str | None = None, vram_gb: float | None = None,
                      gpu_count: int | None = None, backend: str = "") -> list[str]:
    """Plain-language warnings about this machine. Empty when all is well.

    cpuinfo None reads /proc/cpuinfo; an unreadable file gives no CPU warning.
    vram_gb None means unknown (no VRAM warning).
    """
    out: list[str] = []
    flags = cpu_flags(cpuinfo)
    if flags:
        if "avx" not in flags:
            out.append("This CPU has no AVX, so the local AI model cannot run here (chat will not answer). "
                       "Apps, files and the vault still work.")
        elif "avx2" not in flags:
            out.append("This CPU has AVX but not AVX2, so the local AI model may fail to start or run slowly.")
    if backend == "vulkan":
        # 0.5.6: an AMD/Intel card is a GPU, not "no NVIDIA GPU".
        if vram_gb is not None and 0 < vram_gb < LOW_VRAM_GB:
            out.append(f"AMD GPU found, using Vulkan. It has {vram_gb:.1f} GB of VRAM: pick a small model.")
        else:
            out.append("AMD GPU found, using Vulkan.")
    elif gpu_count is not None and gpu_count <= 0:
        if _amd_present():
            out.append("AMD GPU found, using Vulkan.")
        else:
            out.append("No GPU found: models run on the CPU and will be slow. Pick a small model.")
    elif vram_gb is not None and 0 < vram_gb < LOW_VRAM_GB:
        out.append(f"Only {vram_gb:.1f} GB of GPU memory: pick a small model; larger ones run partly on the CPU "
                   "and are slow.")
    return out


# --- 0.5.9 monitor: every GPU (NVIDIA, AMD, onboard), real PCI names, which
# card holds the model, CPU/uptime, and llama-server live numbers. Read-only.
_PCI_NAMES: dict[str, str] | None = None
_NV_FIELDS = ("index,pci.bus_id,name,memory.used,memory.total,temperature.gpu,utilization.gpu,"
              "power.draw,power.limit,fan.speed,clocks.sm,clocks.mem,"
              "pcie.link.gen.current,pcie.link.width.current")


def _run(argv: list[str], timeout: float = 4) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout or "" if p.returncode == 0 else ""


def _bdf(raw: str) -> str:
    """'00000000:81:00.0' or '0000:81:00.0' -> '0000:81:00.0' (lower case)."""
    raw = (raw or "").strip().lower()
    parts = raw.split(":")
    if len(parts) == 3:
        return parts[0][-4:].rjust(4, "0") + ":" + parts[1] + ":" + parts[2]
    if len(parts) == 2:
        return "0000:" + raw
    return raw


def pci_names() -> dict[str, str]:
    """BDF -> 'Vendor Device' from lspci -mm (display controllers only)."""
    global _PCI_NAMES
    if _PCI_NAMES is not None:
        return _PCI_NAMES
    import shlex
    out: dict[str, str] = {}
    for line in _run(["lspci", "-D", "-mm"], timeout=4).splitlines():
        try:
            cells = shlex.split(line)
        except ValueError:
            continue
        if len(cells) < 4:
            continue
        cls = cells[1].lower()
        if not ("vga" in cls or "3d" in cls or "display" in cls):
            continue
        vendor = cells[2]
        for long, short in (("NVIDIA Corporation", "NVIDIA"), ("Advanced Micro Devices, Inc. [AMD/ATI]", "AMD"),
                            ("ASPEED Technology, Inc.", "ASPEED"), ("Intel Corporation", "Intel"),
                            ("Matrox Electronics Systems Ltd.", "Matrox")):
            if vendor.startswith(long):
                vendor = short
        dev_name = cells[3]
        out[_bdf(cells[0])] = (dev_name if dev_name.split(" ")[0] == vendor else f"{vendor} {dev_name}").strip()
    _PCI_NAMES = out
    return out


# Small built-in table by PCI vendor:device for cards whose driver or pci.ids
# gives no useful name (nvidia-smi says "NVIDIA Graphics Device" for the CMP 170HX).
PCI_ID_NAMES = {
    "10de:20c2": "NVIDIA CMP 170HX",
    "10de:2204": "NVIDIA GeForce RTX 3090",
    "10de:2203": "NVIDIA GeForce RTX 3090 Ti",
    "10de:2208": "NVIDIA GeForce RTX 3080 Ti",
    "10de:2206": "NVIDIA GeForce RTX 3080",
    "10de:2684": "NVIDIA GeForce RTX 4090",
    "10de:20b0": "NVIDIA A100",
    "10de:1db4": "NVIDIA Tesla V100",
    "1002:67df": "AMD Radeon RX 470/480/570/580",
    "1002:73bf": "AMD Radeon RX 6800/6900",
    "1002:744c": "AMD Radeon RX 7900",
    "1a03:2000": "ASPEED Graphics",
}
_GENERIC_NAMES = {"", "graphics device", "nvidia graphics device", "nvidia gpu", "amd gpu",
                  "display adapter", "nvidia device", "amd device", "[n/a]", "n/a"}
PCI_SYSFS = Path(os.environ.get("STICKLLM_PCI_SYSFS", "/sys/bus/pci/devices"))


def _generic(name: str) -> bool:
    low = " ".join((name or "").lower().split())
    if low in _GENERIC_NAMES:
        return True
    # lspci without pci.ids: "NVIDIA Device 20c2"
    bits = low.split()
    return len(bits) >= 2 and bits[-2] == "device" and len(bits[-1]) == 4 and all(c in "0123456789abcdef" for c in bits[-1])


def pci_id(bdf: str, root: Path | None = None) -> str:
    """'10de:20c2' from sysfs, or ''."""
    base = (root or PCI_SYSFS) / bdf
    ven = _read(base / "vendor").strip().lower().replace("0x", "")
    dev = _read(base / "device").strip().lower().replace("0x", "")
    return f"{ven}:{dev}" if ven and dev else ""


def card_name(smi_name: str = "", pci_name: str = "", pid: str = "") -> str:
    """Best human name: a real nvidia-smi / amdgpu name, then the bracketed
    lspci text ('GA100 [CMP 170HX]' -> 'NVIDIA CMP 170HX'), then the lspci
    text, then the built-in table by PCI id."""
    if smi_name and not _generic(smi_name):
        return smi_name
    vendor_word = {"10de": "NVIDIA", "1002": "AMD", "1a03": "ASPEED", "8086": "Intel"}.get((pid or "").split(":")[0], "")
    if pci_name and not _generic(pci_name):
        if "[" in pci_name and "]" in pci_name:
            inner = pci_name[pci_name.rfind("[") + 1:pci_name.rfind("]")].strip()
            if inner and "/" not in inner.split()[0] and inner.upper() not in ("AMD/ATI",):
                head = pci_name.split()[0]
                head = head if head in ("NVIDIA", "AMD", "ASPEED", "Intel", "Matrox") else vendor_word
                return (head + " " + inner).strip() if not inner.startswith(head) else inner
            if inner:
                head = pci_name.split()[0]
                return (head + " " + inner).strip()
        return pci_name
    if pid and pid in PCI_ID_NAMES:
        return PCI_ID_NAMES[pid]
    return smi_name or pci_name or (vendor_word + " GPU" if vendor_word else "Display adapter")


def _num(raw: str):
    raw = (raw or "").strip()
    try:
        return float(raw)
    except ValueError:
        return None


def _int(raw):
    n = _num(str(raw)) if raw is not None else None
    return int(n) if n is not None else None


def parse_compute_apps(text: str, main_pid: int | None = None) -> dict[str, int]:
    """Bus id -> MiB used by llama-server, from
    nvidia-smi --query-compute-apps=pid,process_name,gpu_bus_id,used_memory."""
    out: dict[str, int] = {}
    for line in (text or "").splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < 3:
            continue
        pid = _int(cells[0])
        if not ((main_pid and pid == main_pid) or "llama" in cells[1].lower()):
            continue
        bus = _bdf(cells[2])
        mib = _int(cells[3].split()[0]) if len(cells) > 3 and cells[3] else None
        out[bus] = out.get(bus, 0) + (mib or 0)
    return out


def _llama_main_pid() -> int | None:
    for line in _run(["systemctl", "show", "stickllm-llama.service", "-p", "MainPID", "--no-pager"], timeout=3).splitlines():
        if line.startswith("MainPID="):
            pid = _int(line.split("=", 1)[1])
            return pid if pid else None
    return None


def _llama_bus_ids() -> dict[str, int]:
    """PCI ids of NVIDIA cards where llama-server holds memory right now (-> MiB)."""
    text = _run(["nvidia-smi", "--query-compute-apps=pid,process_name,gpu_bus_id,used_memory",
                 "--format=csv,noheader,nounits"])
    return parse_compute_apps(text, _llama_main_pid())


def _nvidia_rows(running: bool = True) -> list[dict]:
    if shutil.which("nvidia-smi") is None:
        return []
    names = pci_names()
    # 0.5.9 monitor cleanup: a stopped service never "holds the model".
    holders = _llama_bus_ids() if running else {}
    # No process list (permissions): fall back to the cards the plan used, only while running.
    plan_idx: set[int] = set()
    runtime = _kv(_read(RUN_DIR / "llama-runtime.env"))
    if running and not holders and runtime.get("backend") == "cuda":
        plan = _kv(_read(RUN_DIR / "llama-plan.env"))
        dev = plan.get("STICKLLM_PLAN_DEVICES") or ""
        if int(plan.get("STICKLLM_PLAN_GPU_COUNT") or 0) > 1:
            dev = _kv(_read(RUN_DIR / "cuda.env")).get("CUDA_VISIBLE_DEVICES") or dev
        plan_idx = {int(x) for x in dev.split(",") if x.strip().isdigit()}
    rows = []
    for line in _run(["nvidia-smi", "--query-gpu=" + _NV_FIELDS, "--format=csv,noheader,nounits"]).splitlines():
        c = [x.strip() for x in line.split(",")]
        if len(c) < 14:
            continue
        bdf = _bdf(c[1])
        used, total = _int(c[3]), _int(c[4])
        pid = pci_id(bdf)
        rows.append({
            "vendor": "nvidia", "index": _int(c[0]), "bus": bdf, "pci_id": pid,
            "name": card_name(c[2], names.get(bdf, ""), pid),
            "pci_name": names.get(bdf, ""),
            "model_mib": holders.get(bdf) or None,
            "memory_used_mib": used, "memory_total_mib": total,
            "temperature_c": _int(c[5]), "util_percent": _int(c[6]),
            "power_w": _num(c[7]), "power_limit_w": _num(c[8]), "fan_percent": _int(c[9]),
            "sm_mhz": _int(c[10]), "mem_mhz": _int(c[11]),
            "pcie_gen": _int(c[12]), "pcie_width": _int(c[13]),
            "holds_model": bdf in holders or (_int(c[0]) in plan_idx),
        })
    return rows


def _dpm_current(path: Path):
    for line in _read(path).splitlines():
        if line.strip().endswith("*"):
            bits = line.split()
            if len(bits) >= 2 and bits[1].lower().endswith("mhz"):
                return _int(bits[1][:-3])
    return None


def _sysfs_rows(drm: Path | None = None, skip_nvidia: bool = True) -> list[dict]:
    """AMD (amdgpu sysfs) and onboard cards (name only) from /sys/class/drm."""
    root = drm or Path("/sys/class/drm")
    names = pci_names() if drm is None else {}
    rows = []
    seen: set[str] = set()
    for card in sorted(root.glob("card[0-9]*")):
        if "-" in card.name:
            continue
        dev = card / "device"
        vendor = _read(dev / "vendor").strip().lower()
        if not vendor or (skip_nvidia and vendor == "0x10de"):
            continue
        try:
            bdf = _bdf(os.path.basename(os.path.realpath(dev)))
        except OSError:
            bdf = ""
        if bdf in seen:
            continue
        seen.add(bdf)
        pid = vendor.replace("0x", "") + ":" + _read(dev / "device").strip().lower().replace("0x", "")
        row: dict = {"vendor": {"0x1002": "amd", "0x8086": "intel", "0x1a03": "aspeed"}.get(vendor, vendor),
                     "index": None, "bus": bdf, "pci_id": pid,
                     "name": card_name(_read(dev / "product_name").strip(), names.get(bdf, ""), pid),
                     "pci_name": names.get(bdf, ""), "holds_model": False,
                     "onboard": _read(dev / "boot_vga").strip() == "1" and vendor not in ("0x1002",)}
        if vendor == "0x1002":
            used, total = _int(_read(dev / "mem_info_vram_used")), _int(_read(dev / "mem_info_vram_total"))
            row["memory_used_mib"] = used // 1048576 if used is not None else None
            row["memory_total_mib"] = total // 1048576 if total is not None else None
            row["util_percent"] = _int(_read(dev / "gpu_busy_percent"))
            hw = next(iter(sorted((dev / "hwmon").glob("hwmon*"))), None) if (dev / "hwmon").is_dir() else None
            if hw is not None:
                t = _int(_read(hw / "temp1_input"))
                row["temperature_c"] = t // 1000 if t is not None else None
                pw = _int(_read(hw / "power1_average")) or _int(_read(hw / "power1_input"))
                cap = _int(_read(hw / "power1_cap"))
                row["power_w"] = round(pw / 1e6, 1) if pw is not None else None
                row["power_limit_w"] = round(cap / 1e6, 1) if cap else None
                pwm, pmax = _int(_read(hw / "pwm1")), _int(_read(hw / "pwm1_max"))
                row["fan_percent"] = round(100 * pwm / pmax) if pwm is not None and pmax else None
            row["sm_mhz"] = _dpm_current(dev / "pp_dpm_sclk")
            row["mem_mhz"] = _dpm_current(dev / "pp_dpm_mclk")
            speed = _read(dev / "current_link_speed").strip()
            gen = {"2.5": 1, "5.0": 2, "8.0": 3, "16.0": 4, "32.0": 5}.get(speed.split(" ")[0] if speed else "", None)
            row["pcie_gen"] = gen
            row["pcie_width"] = _int(_read(dev / "current_link_width"))
        rows.append(row)
    return rows


def model_running(model: dict) -> bool:
    """The llama service is up (or loading) right now."""
    return bool(model.get("available")) and (bool(model.get("llama_up")) or model.get("service") in ("active", "activating"))


def gpus_block(running: bool = True) -> dict:
    rows = _nvidia_rows(running)
    rows += _sysfs_rows(skip_nvidia=bool(rows))
    # A Vulkan model has no per-process GPU list: mark the AMD card when it is
    # the only one and llama runs on Vulkan (only while the service runs).
    runtime = _kv(_read(RUN_DIR / "llama-runtime.env"))
    amd = [r for r in rows if r.get("vendor") == "amd"]
    if running and runtime.get("backend") == "vulkan" and len(amd) == 1:
        amd[0]["holds_model"] = True
    if not rows:
        return {"available": False, "message": "GPU stats are unavailable"}
    return {"available": True, "gpus": rows}


def cpu_info() -> dict:
    model = ""
    for line in _read(Path("/proc/cpuinfo")).splitlines():
        if line.startswith("model name") and ":" in line:
            model = " ".join(line.split(":", 1)[1].split())
            break
    up = _num(_read(Path("/proc/uptime")).split(" ")[0] if _read(Path("/proc/uptime")) else "")
    return {"model": model, "threads": os.cpu_count() or 0, "uptime_s": int(up) if up is not None else None}


def server_n_ctx(props, slots) -> int | None:
    """The running server's context size (--ctx-size), not the model's trained
    context: /props default_generation_settings.n_ctx, then the largest /slots
    n_ctx (with a unified KV cache every slot reports the full size, so a sum
    over parallel slots overstates it 4x), then a top-level /props n_ctx."""
    if isinstance(props, dict):
        dgs = props.get("default_generation_settings")
        if isinstance(dgs, dict):
            n = _int(dgs.get("n_ctx"))
            if n:
                return n
    if isinstance(slots, list):
        vals = [_int(s.get("n_ctx")) for s in slots if isinstance(s, dict)]
        vals = [v for v in vals if v]
        if vals:
            return max(vals)
    if isinstance(props, dict):
        n = _int(props.get("n_ctx"))
        if n:
            return n
    return None


def llama_live(port: int = 8080) -> dict:
    """Prompt / gen tok/s and context use from llama-server --metrics and /slots."""
    import urllib.request
    out: dict = {"available": False}
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=1) as resp:
            text = resp.read().decode("utf-8", "replace")
    except Exception:
        text = ""
    for line in text.splitlines():
        if line.startswith("#") or " " not in line:
            continue
        key, _, val = line.rpartition(" ")
        key = key.split("{", 1)[0]
        n = _num(val)
        if n is None:
            continue
        if key == "llamacpp:prompt_tokens_seconds":
            out["prompt_tok_s"] = round(n, 1)
        elif key == "llamacpp:predicted_tokens_seconds":
            out["gen_tok_s"] = round(n, 1)
        elif key == "llamacpp:requests_processing":
            out["busy"] = n > 0
        elif key == "llamacpp:kv_cache_usage_ratio":
            out["ctx_used_ratio"] = round(n, 3)
        out["available"] = True
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/slots", timeout=1) as resp:
            slots = json.loads(resp.read().decode() or "[]")
    except Exception:
        slots = None
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/props", timeout=1) as resp:
            props = json.loads(resp.read().decode() or "{}")
    except Exception:
        props = None
    n_ctx = server_n_ctx(props, slots)
    if n_ctx:
        out["available"] = True
        out["n_ctx"] = n_ctx
    if isinstance(slots, list) and slots:
        out["available"] = True
        used = 0
        known = False
        for s in slots:
            if not isinstance(s, dict):
                continue
            if s.get("is_processing"):
                out["busy"] = True
            n_past = s.get("n_past")
            if n_past is None:
                nt = s.get("next_token")
                nt = nt[0] if isinstance(nt, list) and nt else nt
                if isinstance(nt, dict) and nt.get("n_past") is not None:
                    n_past = nt.get("n_past")
            if isinstance(n_past, (int, float)):
                used += int(n_past)
                known = True
        if known:
            out["ctx_used"] = used
    return out


def status_line(model: dict, gpu: dict, live: dict) -> str:
    if not model.get("available"):
        state, name = "no model", ""
    elif not model.get("llama_up"):
        state, name = ("loading" if model.get("service") in ("active", "activating") else "stopped"), model.get("name") or ""
    else:
        state, name = ("generating" if live.get("busy") else "idle"), model.get("name") or ""
    bits = [state]
    if name:
        bits.append(name[:-5] if name.lower().endswith(".gguf") else name)
    hot = [g for g in (gpu.get("gpus") or []) if g.get("holds_model") and g.get("temperature_c") is not None]
    for g in hot[:2]:
        label = f"GPU{g['index']}" if g.get("index") is not None else "GPU"
        bits.append(f"{label} {g['temperature_c']}°")
    return " · ".join(bits)


def _disk_with_drives(disks) -> dict:
    out = disk_block(disks)
    if disks is None:
        try:
            out["drives"] = drives_block()
        except Exception:
            out["drives"] = []
        if out["drives"]:
            out["available"] = True
    return out


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
    cpuinfo: str | None = None,
) -> dict:
    model = model_block(run_dir) if include_model else {"available": False, "message": "No model is loaded"}
    if not include_gpu:
        gpu = {"available": False, "message": "GPU stats are unavailable"}
    elif gpu_runner is not None:
        gpu = gpu_block(gpu_runner)
    else:
        gpu = gpus_block(running=model_running(model))
    gpu_count = None
    vram_gb = None
    if include_gpu:
        gpus = gpu.get("gpus") or [] if gpu.get("available") else []
        gpus = [g for g in gpus if g.get("vendor", "nvidia") == "nvidia"]
        gpu_count = len(gpus)
        if gpus:
            vram_gb = sum(int(g.get("memory_total_mib") or 0) for g in gpus) / 1024
    live = llama_live() if include_model and model.get("llama_up") else {"available": False}
    return {
        "ok": True,
        "status_line": status_line(model, gpu, live),
        "host": cpu_info() if stat_text is None else {},
        "llama": live,
        "warnings": hardware_warnings(cpuinfo, vram_gb, gpu_count),
        "cpu": cpu_block(stat_text, load_text),
        "memory": memory_block(meminfo),
        "gpu": gpu,
        "disk": _disk_with_drives(disks),
        "model": model,
    }
