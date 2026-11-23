"""Experimental tab: GPU classify, engine offers, download plans, unlock gates.

Safety: no NVIDIA firmware / .run / patched nvidia.ko in the public tree.
Downloads and unlocks run only after Cancel/Continue (confirmed=true).
No master unlock kill-switch — per-card intent only.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# PCI device IDs (vendor:device). Subsystem checks are separate.
PCI_CMP_170HX_8GB = "10de:20c2"
PCI_CMP_170HX_10GB = "10de:2082"
PCI_RTX_3090 = "10de:2204"
PCI_RTX_3090_TI = "10de:2203"  # out of unlock scope

# Uncommon 32 GB CMP — skip unlock until a tested recipe exists.
SUBSYS_CMP_32GB = "10de:1586"

# Indicative unlocked VRAM (MiB) for "already unlocked?" heuristics.
UNLOCKED_CMP_8GB_MIB = 65536
UNLOCKED_CMP_10GB_MIB = 40960
LOCKED_CMP_8GB_MIB = 8192
LOCKED_CMP_10GB_MIB = 10240

# cmpunlocker driver allowlist (handoff §5). Refuse known-bad 615.78.08.
CMP_DRIVER_ALLOWLIST = (
    "610.43.02",
    "610.43.03",
    "610.57.04",
    "615.71.09",
    "615.71.10",
)
CMP_DRIVER_PREFERRED = "615.71.09"
CMP_DRIVER_REFUSE = ("615.78.08",)

STRATA_REPO = "Niko1221/Strata"
STRATA_API = f"https://api.github.com/repos/{STRATA_REPO}/releases/latest"
NINFER_REPO = "iamwavecut/ninfer-all"
NINFER_API = f"https://api.github.com/repos/{NINFER_REPO}/releases/latest"
CMPUNLOCKER_GIT = "https://github.com/amoghmunikote/cmpunlocker.git"
GPU_UNLOCK_GIT = "https://github.com/Zagitta/gpu-unlock.git"

# stickllm-experimental-engine writes here: <root>/<engine>/<tag>/stickllm-download.json
ENGINES_ROOT = Path(
    os.environ.get(
        "STICKLLM_EXPERIMENTAL_ENGINES",
        "/var/lib/stickllm/experimental/engines",
    )
)
# Path to active-engine.json only. Do NOT use STICKLLM_ACTIVE_ENGINE here —
# that name is the engine *id* written into active-engine.env for systemd
# (ninfer-all / strata / llama.cpp). Colliding the two made EnvironmentFile=
# set the path to "ninfer-all", so serve fell back to llama.cpp and exited.
ACTIVE_ENGINE_PATH = Path(
    os.environ.get(
        "STICKLLM_ACTIVE_ENGINE_FILE",
        "/var/lib/stickllm/experimental/active-engine.json",
    )
)
# Fallback only when StickLLM models dir is unavailable. Prefer the same
# vault/DATA models folder as GGUF (set at Set default / download time).
NINFER_MODELS_DIR = Path(
    os.environ.get(
        "STICKLLM_NINFER_MODELS",
        "/mnt/stickllm-data/models",
    )
)
# Legacy lab path — still scanned so already-downloaded .ninfer files show up.
NINFER_MODELS_DIR_LEGACY = Path("/mnt/stickllm-data/experimental/ninfer-models")
# Official NInfer-all download-model.sh / run.sh profile ids (not GGUF).
NINFER_MODEL_CATALOG: list[dict[str, Any]] = [
    {
        "id": "qwen38-27b",
        "name": "Qwen3.8 27B (NInfer)",
        "approx_size_gb": 19.0,
        "note": "DFlash2 profile; ~19 GiB .ninfer",
    },
    {
        "id": "qwen36-27b",
        "name": "Qwen3.6 27B (NInfer)",
        "approx_size_gb": 16.0,
        "note": "NInfer profile; size varies by pack",
    },
    {
        "id": "qwen36-35b-a3b",
        "name": "Qwen3.6 35B-A3B (NInfer)",
        "approx_size_gb": 22.0,
        "note": "MoE profile; needs ample VRAM",
    },
]
STRATA_DATA_DIR = Path(
    os.environ.get(
        "STICKLLM_STRATA_DATA",
        "/mnt/stickllm-data/experimental/strata",
    )
)
# Strata CUDA 13 engine needs NVIDIA driver ≥ 580.65; older sticks use cuda12.
STRATA_CUDA13_MIN_DRIVER = (580, 65)
_PAYLOAD_SUFFIXES = (
    ".AppImage",
    ".tar.gz",
    ".tar.xz",
    ".7z",
    ".exe",
    ".zip",
)


def github_archive_urls(git_url: str) -> list[str]:
    """HTTPS tarball URLs for a github.com *.git repo (main then master).

    StickLLM live images ship curl/tar but not always git. Unlock helpers
    fall back to these archives when `git` is missing or clone fails.
    """
    url = (git_url or "").strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    if "github.com/" not in url:
        return []
    # Accept https://github.com/owner/repo[/...]
    try:
        path = url.split("github.com/", 1)[1]
    except IndexError:
        return []
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        return []
    owner, repo = parts[0], parts[1]
    base = f"https://github.com/{owner}/{repo}/archive/refs/heads"
    return [f"{base}/main.tar.gz", f"{base}/master.tar.gz"]

NOV3_CONTEXT = (
    "StickLLM detects cards and offers opt-in downloads/unlocks only. "
    "Nothing installs until you press Continue."
)

CMP_WARNING = (
    "CMP 170HX has no video outputs. Unlock only restores full compute and real "
    "HBM size via a patched NVIDIA open driver. NVIDIA does not support this. A "
    "driver or kernel update can break it. StickLLM will not flash VBIOS or burn "
    "fuses. Cancel leaves this card locked."
)

RTX3090_WARNING = (
    "RTX 3090 unlock (gpu-unlock 2.0) restores full FP16/BF16/TF32 tensor issue "
    "rate. It does not add VRAM. Effect is reapplied at boot via initramfs. "
    "Cancel leaves this card capped."
)


def _norm_pci(pid: str) -> str:
    return (pid or "").strip().lower().replace("0x", "")


def classify_nvidia_card(
    pci_id: str,
    *,
    subsystem_id: str = "",
    memory_total_mib: int | None = None,
    bus: str = "",
    name: str = "",
    index: int | None = None,
) -> dict[str, Any]:
    """Classify one NVIDIA function for Experimental offers / unlocks."""
    pid = _norm_pci(pci_id)
    sub = _norm_pci(subsystem_id)
    mem = int(memory_total_mib) if memory_total_mib is not None else None
    base: dict[str, Any] = {
        "bus": bus or "",
        "pci_id": pid,
        "subsystem_id": sub,
        "name": name or "",
        "index": index,
        "memory_total_mib": mem,
        "kind": "other_nvidia",
        "unlock_path": None,
        "unlock_in_scope": False,
        "likely_unlocked": False,
        "skip_reason": "",
        "label": name or pid or "NVIDIA GPU",
    }

    if pid == PCI_CMP_170HX_8GB:
        base.update(
            kind="cmp_170hx",
            sku="8gb",
            unlock_path="cmpunlocker",
            unlock_in_scope=True,
            label="CMP 170HX 8GB",
            expected_unlocked_mib=UNLOCKED_CMP_8GB_MIB,
        )
        if sub == SUBSYS_CMP_32GB:
            base["unlock_in_scope"] = False
            base["skip_reason"] = f"unsupported 32 GB subsystem {sub}"
            base["label"] = "CMP 170HX 32GB (unsupported)"
        elif mem is not None and mem >= UNLOCKED_CMP_8GB_MIB * 0.9:
            base["likely_unlocked"] = True
        return base

    if pid == PCI_CMP_170HX_10GB:
        base.update(
            kind="cmp_170hx",
            sku="10gb",
            unlock_path="cmpunlocker",
            unlock_in_scope=True,
            label="CMP 170HX 10GB",
            expected_unlocked_mib=UNLOCKED_CMP_10GB_MIB,
        )
        if mem is not None and mem >= UNLOCKED_CMP_10GB_MIB * 0.9:
            base["likely_unlocked"] = True
        return base

    if pid == PCI_RTX_3090:
        base.update(
            kind="rtx_3090",
            unlock_path="gpu_unlock",
            unlock_in_scope=True,
            label="RTX 3090",
        )
        return base

    if pid == PCI_RTX_3090_TI:
        base.update(
            kind="rtx_3090_ti",
            unlock_path="gpu_unlock",
            unlock_in_scope=False,
            skip_reason="RTX 3090 Ti (10de:2203) out of requested scope",
            label="RTX 3090 Ti",
        )
        return base

    return base


def classify_inventory(rows: list[dict] | None) -> list[dict[str, Any]]:
    """Classify nvidia_gpu_rows-style dicts (needs pci_id when possible)."""
    out: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        vendor = str(row.get("vendor") or "").lower()
        pid = _norm_pci(str(row.get("pci_id") or ""))
        name = str(row.get("name") or "")
        name_l = name.lower()
        if vendor and vendor not in ("nvidia", "10de") and not pid.startswith("10de:"):
            continue
        if not pid:
            # Name fallback when sysfs pci_id is missing (still NVIDIA-looking).
            if "3090 ti" in name_l:
                pid = PCI_RTX_3090_TI
            elif "rtx 3090" in name_l or "geforce rtx 3090" in name_l:
                pid = PCI_RTX_3090
            elif "cmp 170" in name_l or "cmp170" in name_l:
                mem = row.get("memory_total_mib") or row.get("total_mib")
                try:
                    mem_i = int(mem) if mem is not None else None
                except (TypeError, ValueError):
                    mem_i = None
                pid = PCI_CMP_170HX_10GB if mem_i and mem_i >= 9000 else PCI_CMP_170HX_8GB
            elif "nvidia" not in name_l and "geforce" not in name_l and "cmp" not in name_l:
                continue
        out.append(
            classify_nvidia_card(
                pid,
                subsystem_id=str(row.get("subsystem_id") or row.get("subsystem") or ""),
                memory_total_mib=row.get("memory_total_mib") or row.get("total_mib"),
                bus=str(row.get("bus") or ""),
                name=name,
                index=row.get("index"),
            )
        )
    return out


def unlock_report_line(card: dict[str, Any], status: str, reason: str = "") -> str:
    """One-line UI/log report per handoff §7."""
    label = card.get("label") or card.get("name") or "NVIDIA GPU"
    pid = card.get("pci_id") or ""
    bus = card.get("bus") or ""
    where = f" ({pid})" if pid else ""
    at = f" at {bus}" if bus else ""
    tail = f" ({reason})" if reason else ""
    return f"Found: {label}{where}{at} -> Unlock: {status}{tail}"


def debian_major(os_release: str = "") -> int | None:
    """Parse VERSION_ID major from /etc/os-release text, or None."""
    for line in (os_release or "").splitlines():
        if line.startswith("VERSION_ID="):
            raw = line.split("=", 1)[1].strip().strip('"').strip("'")
            try:
                return int(raw.split(".")[0])
            except ValueError:
                return None
    return None


def engine_offers(
    cards: list[dict[str, Any]],
    *,
    debian_major_version: int | None = None,
    platform: str = "linux",
) -> list[dict[str, Any]]:
    """Return download *offers* only — never auto-fetch.

    Rules (handoff §4): offer Strata / NInfer-all for RTX 3090; for CMP only
    when likely unlocked (or UI shows separate unlock-first warning).
    NInfer Linux is gated on debian_major_version == 13 (not shown as scare copy).
    Windows builds are catalogued for host use.
    """
    offers: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    plat = (platform or "linux").lower()

    def add(engine: str, card: dict[str, Any], note: str = "", blocked: str = "", **extra: Any) -> None:
        key = (engine, card.get("bus") or card.get("pci_id") or card.get("label") or "")
        if key in seen:
            return
        seen.add(key)
        row = {
            "engine": engine,
            "card_label": card.get("label") or "",
            "card_bus": card.get("bus") or "",
            "card_pci_id": card.get("pci_id") or "",
            "platform": plat,
            "note": note,
            "blocked": blocked,
            "auto_install": False,
        }
        row.update(extra)
        offers.append(row)

    for card in cards:
        kind = card.get("kind")
        unlocked = bool(card.get("likely_unlocked"))
        if kind == "rtx_3090":
            if plat == "windows":
                add(
                    "strata",
                    card,
                    note="Windows setup.exe + matching CUDA engine (Confirm before download)",
                    assets_hint="windows-x64-setup + windows cuda engine",
                )
                add(
                    "ninfer-all",
                    card,
                    note="Windows .7z community build (Confirm before download)",
                    assets_hint="windows-x64 cuda archive",
                )
            else:
                add(
                    "strata",
                    card,
                    note="Linux AppImage + matching CUDA engine (Confirm before download)",
                    assets_hint="linux AppImage + linux cuda engine",
                )
                if debian_major_version != 13:
                    add(
                        "ninfer-all",
                        card,
                        blocked="NInfer-all not available on this OS version",
                    )
                else:
                    add(
                        "ninfer-all",
                        card,
                        note="Linux x64 community build (Confirm before download)",
                        assets_hint="linux-x64 cuda archive + SHA256SUMS",
                    )
            continue

        if kind == "cmp_170hx":
            if not unlocked:
                add(
                    "strata",
                    card,
                    blocked="CMP still locked — unlock first (or community evidence is on unlocked 40/64 GB cards)",
                )
                add(
                    "ninfer-all",
                    card,
                    blocked="CMP still locked — do not offer as a 40/64 GB card",
                )
                continue
            if plat == "windows":
                add(
                    "strata",
                    card,
                    note="Community evidence on unlocked CMP (sm_80); Confirm before download",
                    assets_hint="windows-x64-setup + windows cuda engine",
                )
                add(
                    "ninfer-all",
                    card,
                    note="Windows build; prefer unlocked 40/64 GB CMP",
                    assets_hint="windows-x64 cuda archive",
                )
            else:
                add(
                    "strata",
                    card,
                    note="Community evidence on unlocked CMP (sm_80); Confirm before download",
                    assets_hint="linux AppImage + linux cuda engine",
                )
                if debian_major_version != 13:
                    add(
                        "ninfer-all",
                        card,
                        blocked="NInfer-all not available on this OS version",
                    )
                else:
                    add(
                        "ninfer-all",
                        card,
                        note="Prefer official NInfer-all sm_80; Confirm before download",
                        assets_hint="linux-x64 cuda archive + SHA256SUMS",
                    )

    return offers


def cmp_driver_ok(driver_version: str) -> tuple[bool, str]:
    ver = (driver_version or "").strip()
    if not ver:
        return False, "driver version unknown"
    if any(ver.startswith(bad) for bad in CMP_DRIVER_REFUSE):
        return False, f"refused driver {ver} (known-bad; do not use 615.78.08)"
    if any(ver.startswith(ok) for ok in CMP_DRIVER_ALLOWLIST):
        return True, ""
    return False, f"driver {ver} not on cmpunlocker allowlist (prefer {CMP_DRIVER_PREFERRED})"


def unlock_preflight(
    card: dict[str, Any],
    *,
    driver_version: str = "",
    secure_boot: bool | None = None,
    nvidia_open: bool | None = None,
    already_applied: bool = False,
) -> dict[str, Any]:
    """Gate unlock apply. Never patches — caller runs helper after Continue."""
    out: dict[str, Any] = {
        "ok": False,
        "path": card.get("unlock_path"),
        "card_bus": card.get("bus") or "",
        "card_label": card.get("label") or "",
        "reason": "",
        "already_applied": already_applied,
        "warning": "",
    }
    if not card.get("unlock_in_scope"):
        out["reason"] = card.get("skip_reason") or "not in unlock scope"
        return out
    if already_applied:
        out["ok"] = True
        out["reason"] = "already active"
        return out
    if secure_boot is True:
        out["reason"] = "Secure Boot enabled"
        return out
    path = card.get("unlock_path")
    if path == "cmpunlocker":
        out["warning"] = CMP_WARNING
        if nvidia_open is False:
            out["reason"] = "nvidia-open required (proprietary driver present)"
            return out
        ok, reason = cmp_driver_ok(driver_version)
        if not ok:
            out["reason"] = reason
            return out
        out["ok"] = True
        return out
    if path == "gpu_unlock":
        out["warning"] = RTX3090_WARNING
        out["ok"] = True
        return out
    out["reason"] = "no unlock path"
    return out


def _asset_map(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for a in release.get("assets") or []:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "")
        if not name:
            continue
        out[name] = {
            "name": name,
            "url": str(a.get("browser_download_url") or a.get("url") or ""),
            "size": int(a.get("size") or 0),
            "digest": str(a.get("digest") or ""),
        }
    return out


def _pick_named(assets: dict[str, dict[str, Any]], *needles: str) -> dict[str, Any] | None:
    """Pick first asset whose name contains all needles (case-insensitive)."""
    want = [n.lower() for n in needles if n]
    for name, meta in sorted(assets.items()):
        low = name.lower()
        if all(n in low for n in want):
            return dict(meta)
    return None


def _pick_sha_file(assets: dict[str, dict[str, Any]], prefix_hint: str = "") -> dict[str, Any] | None:
    """Pick a SHA256SUMS asset. Prefer the longest hint match (family stem over cuda token)."""
    hint = (prefix_hint or "").lower().strip()
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for name, meta in assets.items():
        low = name.lower()
        if "sha256" not in low:
            continue
        if hint and hint not in low:
            continue
        # Prefer exact family matches (longer hint overlap) over broad cuda12.9 hits
        # that also match the dual 12.9-13.4 checksum file.
        score = len(hint) if hint else 0
        if hint and "12.9-13.4" in low and "12.9-13.4" not in hint:
            score -= 100
        scored.append((score, name, meta))
    if scored:
        scored.sort(key=lambda t: (-t[0], t[1]))
        return dict(scored[0][2])
    # Fallback: any SHA256SUMS*
    for name, meta in sorted(assets.items()):
        if name.upper().startswith("SHA256") or "SHA256SUMS" in name.upper():
            return dict(meta)
    return None


def archive_family_stem(name: str) -> str:
    """Strip multipart suffix (.tar.gz.001 / .7z.002) for SHA family matching."""
    n = (name or "").strip()
    n = re.sub(r"\.(tar\.gz|7z)\.\d{3}$", "", n, flags=re.I)
    n = re.sub(r"\.(tar\.gz|7z)$", "", n, flags=re.I)
    return n


def select_strata_assets(
    release: dict[str, Any],
    *,
    platform: str = "linux",
    cuda: str = "cuda13",
) -> dict[str, Any]:
    """Choose Strata AppImage/setup + CUDA engine (+ SHA256SUMS) from a release JSON."""
    assets = _asset_map(release)
    plat = (platform or "linux").lower()
    cuda_key = "cuda13" if "13" in (cuda or "cuda13") else "cuda12"
    picked: list[dict[str, Any]] = []
    blocked = ""
    if plat == "windows":
        setup = _pick_named(assets, "windows", "setup.exe")
        engine = _pick_named(assets, "strata-engine", "windows", cuda_key)
        if setup:
            picked.append(setup)
        if engine:
            picked.append(engine)
        if not setup:
            blocked = "Strata Windows setup.exe not found in release"
    else:
        app = _pick_named(assets, "appimage")
        if not app:
            app = _pick_named(assets, "linux-x86_64.AppImage".lower())
        # Prefer exact AppImage name pattern
        for name, meta in assets.items():
            if name.endswith(".AppImage") and "linux" in name.lower() and "aarch64" not in name.lower():
                app = meta
                break
        engine = _pick_named(assets, "strata-engine", "linux-x86_64", cuda_key)
        if app:
            picked.append(app)
        if engine:
            picked.append(engine)
        if not app:
            blocked = "Strata Linux AppImage not found in release"
    sha = _pick_sha_file(assets)
    if sha:
        picked.append({**sha, "role": "checksums"})
    for p in picked:
        p.setdefault("role", "payload")
    return {
        "engine": "strata",
        "tag": release.get("tag_name") or release.get("name") or "",
        "platform": plat,
        "cuda": cuda_key,
        "assets": picked,
        "blocked": blocked,
        "repo": STRATA_REPO,
        "release_url": release.get("html_url") or "",
    }


def select_ninfer_assets(
    release: dict[str, Any],
    *,
    platform: str = "linux",
    cuda: str = "cuda12.9",
    debian_major_version: int | None = 13,
) -> dict[str, Any]:
    """Choose NInfer-all multi-part archive + SHA256SUMS for platform/CUDA."""
    assets = _asset_map(release)
    plat = (platform or "linux").lower()
    blocked = ""
    if plat == "linux" and debian_major_version is not None and debian_major_version != 13:
        return {
            "engine": "ninfer-all",
            "tag": release.get("tag_name") or "",
            "platform": plat,
            "cuda": cuda,
            "assets": [],
            "blocked": "NInfer-all not available on this OS version",
            "repo": NINFER_REPO,
            "release_url": release.get("html_url") or "",
        }

    # Prefer single-CUDA package (smaller) over dual 12.9-13.4 when possible.
    cuda_token = "cuda12.9" if "12" in (cuda or "cuda12.9") and "13.4" not in (cuda or "") else "cuda13.4"
    if cuda in ("cuda12.9", "12", "12.9"):
        cuda_token = "cuda12.9"
    elif cuda in ("cuda13.4", "13", "13.4", "cuda13"):
        cuda_token = "cuda13.4"
    else:
        cuda_token = "cuda12.9"

    os_token = "windows-x64" if plat == "windows" else "linux-x64"
    ext = ".7z." if plat == "windows" else ".tar.gz."
    parts: list[dict[str, Any]] = []
    # Prefer sm-inclusive single-cuda archives (not the dual 12.9-13.4 mega pack).
    candidates = []
    for name, meta in assets.items():
        low = name.lower()
        if os_token not in low:
            continue
        if cuda_token not in low:
            continue
        if "12.9-13.4" in low:
            continue
        if ext.strip(".") not in low and not any(low.endswith(f".{i:03d}") for i in range(1, 20)):
            # multipart: name.tar.gz.001
            if ext not in low:
                continue
        candidates.append(meta)
    if not candidates:
        # Fall back to dual pack
        for name, meta in assets.items():
            low = name.lower()
            if os_token in low and "12.9-13.4" in low:
                candidates.append(meta)
        if candidates:
            cuda_token = "cuda12.9-13.4"
    # Only multipart payload pieces (not SHA files)
    for meta in sorted(candidates, key=lambda m: m["name"]):
        n = meta["name"]
        if "SHA256" in n.upper():
            continue
        if re.search(r"\.(tar\.gz|7z)\.\d{3}$", n, re.I) or n.lower().endswith((".tar.gz", ".7z")):
            parts.append({**meta, "role": "payload"})
    if not parts:
        blocked = f"NInfer-all {os_token} {cuda_token} assets not found in release"
    # Match SHA256SUMS to the same archive family as the payload (sm70… vs dual 12.9-13.4).
    sha = None
    if parts:
        family = archive_family_stem(parts[0]["name"])
        if family:
            sha = _pick_sha_file(assets, prefix_hint=family)
    if not sha:
        sha = _pick_sha_file(assets, prefix_hint=f"ninfer-{os_token}-{cuda_token}")
    if not sha:
        sha = _pick_sha_file(assets, prefix_hint=f"ninfer-{os_token}")
    if sha:
        parts.append({**sha, "role": "checksums"})
    return {
        "engine": "ninfer-all",
        "tag": release.get("tag_name") or "",
        "platform": plat,
        "cuda": cuda_token,
        "assets": parts,
        "blocked": blocked,
        "repo": NINFER_REPO,
        "release_url": release.get("html_url") or "",
    }


def parse_driver_tuple(driver_version: str) -> tuple[int, ...] | None:
    """Parse '550.163.01' → (550, 163, 1)."""
    ver = (driver_version or "").strip().split()[0] if driver_version else ""
    if not ver:
        return None
    parts: list[int] = []
    for p in ver.split("."):
        if not p.isdigit():
            break
        parts.append(int(p))
    return tuple(parts) if parts else None


def strata_cuda_for_driver(driver_version: str = "") -> str:
    """Pick Strata CUDA engine pack for the installed NVIDIA driver."""
    tup = parse_driver_tuple(driver_version)
    if tup is None:
        return "cuda12"
    if tup >= STRATA_CUDA13_MIN_DRIVER:
        return "cuda13"
    return "cuda12"


def plan_engine_download(
    engine: str,
    release: dict[str, Any],
    *,
    platform: str = "linux",
    cuda: str = "",
    debian_major_version: int | None = 13,
    driver_version: str = "",
) -> dict[str, Any]:
    eng = (engine or "").strip().lower()
    if eng in ("strata",):
        return select_strata_assets(
            release,
            platform=platform,
            cuda=cuda or strata_cuda_for_driver(driver_version),
        )
    if eng in ("ninfer-all", "ninfer", "ninfer_all"):
        return select_ninfer_assets(
            release,
            platform=platform,
            cuda=cuda or "cuda12.9",
            debian_major_version=debian_major_version,
        )
    return {
        "engine": eng,
        "assets": [],
        "blocked": f"unknown engine {eng}",
        "tag": "",
        "platform": platform,
    }


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse `hash  filename` lines (GNU coreutils / GitHub release style)."""
    out: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", line)
        if not m:
            continue
        out[m.group(2).strip().lstrip("*").split("/")[-1]] = m.group(1).lower()
    return out


def file_sha256(path: str, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def fetch_github_latest(api_url: str, *, timeout: float = 45.0) -> dict[str, Any]:
    """Fetch GitHub releases/latest JSON. No assets downloaded."""
    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "StickLLM-Experimental/0.8.2",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("unexpected GitHub release payload")
    return data


def engine_api_for(engine: str) -> str:
    eng = (engine or "").strip().lower()
    if eng == "strata":
        return STRATA_API
    if eng in ("ninfer-all", "ninfer", "ninfer_all"):
        return NINFER_API
    raise ValueError(f"unknown engine {engine}")


def _looks_like_payload(name: str) -> bool:
    n = (name or "").lower()
    if n.endswith(".part") or n.endswith(".tmp"):
        return False
    if "sha256" in n or n.startswith("sha256sums"):
        return False
    if n == "stickllm-download.json":
        return False
    if any(n.endswith(suf.lower()) for suf in _PAYLOAD_SUFFIXES):
        return True
    # Multi-part archives: foo.tar.gz.001 / foo.7z.002
    if re.search(r"\.(tar\.gz|tar\.xz|7z|zip)\.\d{3}$", n):
        return True
    return False


def scan_installed_engines(root: str | Path | None = None) -> dict[str, Any]:
    """Detect engines already on disk under ENGINES_ROOT.

    A tag dir counts as installed when stickllm-download.json says done/ok, or
    when verified payload parts are present (so reboot without /run progress
    still shows Installed).
    """
    base = Path(root) if root else ENGINES_ROOT
    out: dict[str, Any] = {}
    if not base.is_dir():
        return out
    try:
        eng_dirs = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return out
    for eng_dir in eng_dirs:
        engine = eng_dir.name
        candidates: list[dict[str, Any]] = []
        try:
            tag_dirs = [p for p in eng_dir.iterdir() if p.is_dir()]
        except OSError:
            continue
        for tag_dir in tag_dirs:
            marker = tag_dir / "stickllm-download.json"
            meta: dict[str, Any] = {}
            if marker.is_file():
                try:
                    raw = json.loads(marker.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        meta = raw
                except (OSError, ValueError):
                    meta = {}
            payloads: list[dict[str, Any]] = []
            bytes_total = 0
            try:
                for f in tag_dir.iterdir():
                    if not f.is_file() or not _looks_like_payload(f.name):
                        continue
                    try:
                        sz = int(f.stat().st_size)
                    except OSError:
                        sz = 0
                    bytes_total += sz
                    payloads.append({"name": f.name, "path": str(f), "size": sz})
            except OSError:
                payloads = []
            marker_ok = bool(meta.get("ok")) or str(meta.get("state") or "") == "done"
            has_payload = bytes_total >= 1024 * 1024 and bool(payloads)
            if not (marker_ok or has_payload):
                continue
            try:
                mtime = int(tag_dir.stat().st_mtime)
            except OSError:
                mtime = 0
            candidates.append(
                {
                    "engine": engine,
                    "installed": True,
                    "tag": str(meta.get("tag") or tag_dir.name),
                    "dest": str(meta.get("dest") or tag_dir),
                    "bytes": int(meta.get("bytes_done") or meta.get("bytes_total") or bytes_total),
                    "files": payloads,
                    "marker": str(marker) if marker.is_file() else "",
                    "mtime": mtime,
                    "default": False,
                    "active": False,
                    "usable": False,
                    "note": (
                        "Downloaded and verified on disk — not StickLLM default "
                        "(chat still uses llama.cpp)."
                    ),
                }
            )
        if not candidates:
            continue
        candidates.sort(key=lambda r: (int(r.get("mtime") or 0), str(r.get("tag") or "")), reverse=True)
        out[engine] = candidates[0]
    return out


def normalize_engine_id(engine: str) -> str:
    eng = (engine or "").strip().lower()
    if eng in ("ninfer", "ninfer_all"):
        return "ninfer-all"
    if eng in ("llama", "llamacpp", "llama-cpp"):
        return "llama.cpp"
    return eng


def read_active_engine(path: str | Path | None = None) -> dict[str, Any]:
    """Persisted StickLLM default engine (llama.cpp | ninfer-all | strata)."""
    p = Path(path) if path else ACTIVE_ENGINE_PATH
    default = {
        "engine": "llama.cpp",
        "tag": "",
        "dest": "",
        "root": "",
        "updated": 0,
    }
    if not p.is_file():
        return dict(default)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(default)
    if not isinstance(raw, dict):
        return dict(default)
    eng = normalize_engine_id(str(raw.get("engine") or "llama.cpp"))
    if eng not in ("llama.cpp", "ninfer-all", "strata"):
        eng = "llama.cpp"
    return {
        "engine": eng,
        "tag": str(raw.get("tag") or ""),
        "dest": str(raw.get("dest") or ""),
        "root": str(raw.get("root") or ""),
        "model_dir": str(raw.get("model_dir") or ""),
        "model_key": str(raw.get("model_key") or ""),
        "note": str(raw.get("note") or ""),
        "updated": int(raw.get("updated") or 0),
    }


def ninfer_model_dirs(primary: str | Path | None = None) -> list[Path]:
    """Search order for .ninfer artifacts (shared models dir first)."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path | None) -> None:
        if p is None:
            return
        key = str(p)
        if key in seen:
            return
        seen.add(key)
        out.append(p)

    if primary:
        add(Path(primary))
    add(NINFER_MODELS_DIR)
    add(NINFER_MODELS_DIR_LEGACY)
    return out


def find_ninfer_artifact(model_id: str, model_dir: str | Path | None = None) -> Path | None:
    """Locate a downloaded .ninfer for a profile id (qwen38-27b, …)."""
    mid = (model_id or "").strip().lower()
    if not mid:
        return None
    # qwen38-27b → qwen3_8_27b / qwen38-27b style stems
    compact = mid.replace("-", "").replace("_", "")
    alts = {
        mid,
        mid.replace("-", "_"),
        mid.replace("_", "-"),
        # qwen38-27b ↔ qwen3_8_27b
        re.sub(r"qwen(\d)(\d+)", r"qwen\1_\2", mid.replace("-", "_")),
    }
    for root in ninfer_model_dirs(model_dir):
        if not root.is_dir():
            continue
        try:
            files = list(root.glob("*.ninfer"))
        except OSError:
            continue
        for f in files:
            stem = f.stem.lower()
            stem_c = stem.replace("-", "").replace("_", "")
            if stem in alts or stem_c == compact or mid in stem or compact in stem_c:
                return f
    return None


def ninfer_catalog_rows(
    model_dir: str | Path | None = None,
    active_key: str = "",
) -> list[dict[str, Any]]:
    """Models-page rows when active engine is NInfer (not GGUF)."""
    rows: list[dict[str, Any]] = []
    for entry in NINFER_MODEL_CATALOG:
        mid = str(entry.get("id") or "")
        art = find_ninfer_artifact(mid, model_dir)
        installed = art is not None
        size_gb = float(entry.get("approx_size_gb") or 0)
        if art is not None:
            try:
                size_gb = round(art.stat().st_size / (1024**3), 2) or size_gb
            except OSError:
                pass
        rows.append(
            {
                "id": mid,
                "name": entry.get("name") or mid,
                "approx_size_gb": size_gb,
                "size_gb": size_gb,
                "installed": installed,
                "path": str(art) if art else "",
                "engine": "ninfer-all",
                "format": "ninfer",
                "quant": "ninfer",
                "recommended": mid == "qwen38-27b",
                "deletable": installed,
                "runnable": installed,
                "running": bool(active_key and active_key == mid),
                "active": bool(active_key and active_key == mid),
                "fits": True,
                "trust": "verified",
                "note": entry.get("note") or "",
                "source": "ninfer",
            }
        )
    return rows


def write_active_engine(doc: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else ACTIVE_ENGINE_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    out = dict(doc or {})
    out["engine"] = normalize_engine_id(str(out.get("engine") or "llama.cpp"))
    out["updated"] = int(time.time())
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    tmp.replace(p)
    # Env file for systemd EnvironmentFile=
    env_path = p.with_suffix(".env")
    model_key = str(out.get("model_key") or "").strip()
    lines = [
        f"STICKLLM_ACTIVE_ENGINE={out.get('engine') or 'llama.cpp'}",
        f"STICKLLM_ENGINE_ROOT={out.get('root') or ''}",
        f"STICKLLM_ENGINE_DEST={out.get('dest') or ''}",
        f"STICKLLM_ENGINE_TAG={out.get('tag') or ''}",
        f"STICKLLM_NINFER_MODEL={model_key}",
        f"NINFER_MODEL_DIR={out.get('model_dir') or NINFER_MODELS_DIR}",
        f"NINFER_HOST=127.0.0.1",
        f"NINFER_PORT=8080",
        f"STICKLLM_LLAMA_HOST=127.0.0.1",
        f"STICKLLM_LLAMA_PORT=8080",
    ]
    env_tmp = env_path.with_suffix(".env.tmp")
    env_tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    env_tmp.replace(env_path)
    # Gate stickllm-exp-engine.service (ConditionPathExists).
    enabled = p.parent / "exp-engine.enabled"
    if out["engine"] in ("ninfer-all", "strata"):
        enabled.write_text(out["engine"] + "\n", encoding="utf-8")
    elif enabled.exists():
        try:
            enabled.unlink()
        except OSError:
            pass
    return out


def _multipart_stems(dest: Path) -> list[str]:
    stems: set[str] = set()
    try:
        for f in dest.iterdir():
            if not f.is_file():
                continue
            m = re.match(r"^(.+\.(?:tar\.gz|7z))\.\d{3}$", f.name, flags=re.I)
            if m:
                stems.add(m.group(1))
    except OSError:
        return []
    return sorted(stems)


def _flatten_single_child_dir(root: Path) -> None:
    try:
        kids = [p for p in root.iterdir() if p.name not in (".", "..")]
    except OSError:
        return
    dirs = [p for p in kids if p.is_dir()]
    files = [p for p in kids if p.is_file() and p.name != ".ok"]
    if len(dirs) == 1 and not files:
        only = dirs[0]
        for child in list(only.iterdir()):
            target = root / child.name
            if target.exists():
                continue
            try:
                child.rename(target)
            except OSError:
                shutil.move(str(child), str(target))
        try:
            only.rmdir()
        except OSError:
            pass


def _extract_tar_gz_stream(fileobj, out_dir: Path) -> None:
    """Extract a .tar.gz stream into out_dir (stdlib; works without GNU tar/cat)."""
    import tarfile

    out_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=fileobj, mode="r:gz") as tf:
        # filter='data' is Python 3.12+; older sticks may be 3.13 — still pass when available.
        try:
            tf.extractall(out_dir, filter="data")  # type: ignore[call-arg]
        except TypeError:
            tf.extractall(out_dir)


def ensure_ninfer_extracted(dest: str | Path) -> dict[str, Any]:
    """Concat multipart .tar.gz.00N and extract beside payloads → <dest>/extracted."""
    dest_p = Path(dest)
    out_dir = dest_p / "extracted"
    marker = out_dir / ".ok"
    serve = out_dir / "ninfer-serve"
    if marker.is_file() and serve.is_file():
        return {"ok": True, "root": str(out_dir), "engine": "ninfer-all", "already": True}
    stems = _multipart_stems(dest_p)
    sources: list[Path] = []
    if stems:
        stem = stems[0]
        parts = sorted(p for p in dest_p.glob(stem + ".*") if re.search(r"\.\d{3}$", p.name))
        if not parts:
            return {"ok": False, "error": f"missing multipart volumes for {stem}"}
        sources = parts
    else:
        tars = sorted(dest_p.glob("*.tar.gz"))
        if not tars:
            return {"ok": False, "error": "no NInfer archive parts found", "dest": str(dest_p)}
        sources = [tars[0]]

    out_dir.mkdir(parents=True, exist_ok=True)
    # Prefer GNU cat|tar on the stick (no 3 GiB temp). Stdlib fallback for Windows tests.
    try:
        if shutil.which("tar") and shutil.which("cat") and len(sources) >= 1:
            if len(sources) == 1:
                proc = subprocess.run(
                    ["tar", "-xzf", str(sources[0]), "-C", str(out_dir)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
            else:
                cat = subprocess.Popen(
                    ["cat", *[str(p) for p in sources]],
                    stdout=subprocess.PIPE,
                )
                assert cat.stdout is not None
                proc = subprocess.run(
                    ["tar", "-xz", "-C", str(out_dir)],
                    stdin=cat.stdout,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                cat.stdout.close()
                cat.wait()
            if proc.returncode != 0:
                return {
                    "ok": False,
                    "error": (proc.stderr or proc.stdout or "tar extract failed")[:400],
                }
        else:
            import tempfile

            if len(sources) == 1:
                with open(sources[0], "rb") as f:
                    _extract_tar_gz_stream(f, out_dir)
            else:
                with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                    for part in sources:
                        with open(part, "rb") as src:
                            shutil.copyfileobj(src, tmp, length=1024 * 1024)
                try:
                    with open(tmp_path, "rb") as f:
                        _extract_tar_gz_stream(f, out_dir)
                finally:
                    try:
                        tmp_path.unlink()
                    except OSError:
                        pass
    except Exception as exc:
        return {"ok": False, "error": f"extract failed: {exc}"[:400]}

    _flatten_single_child_dir(out_dir)
    serve = out_dir / "ninfer-serve"
    if not serve.is_file():
        return {"ok": False, "error": "ninfer-serve missing after extract", "root": str(out_dir)}
    try:
        serve.chmod(serve.stat().st_mode | 0o111)
    except OSError:
        pass
    for name in ("ninfer", "run.sh", "download-model.sh"):
        p = out_dir / name
        if p.is_file():
            try:
                p.chmod(p.stat().st_mode | 0o111)
            except OSError:
                pass
    marker.write_text("ok\n", encoding="utf-8")
    return {"ok": True, "root": str(out_dir), "engine": "ninfer-all", "already": False}


def ensure_strata_extracted(dest: str | Path) -> dict[str, Any]:
    """Prepare Strata AppImage (+ CUDA engine tarball) under <dest>/extracted."""
    dest_p = Path(dest)
    out_dir = dest_p / "extracted"
    marker = out_dir / ".ok"
    if marker.is_file() and (out_dir / "squashfs-root").is_dir():
        return {"ok": True, "root": str(out_dir), "engine": "strata", "already": True}
    apps = sorted(dest_p.glob("*.AppImage"))
    if not apps:
        return {"ok": False, "error": "Strata AppImage not found", "dest": str(dest_p)}
    app = apps[0]
    try:
        app.chmod(app.stat().st_mode | 0o111)
    except OSError:
        pass
    out_dir.mkdir(parents=True, exist_ok=True)
    # Extract without FUSE.
    proc = subprocess.run(
        [str(app), "--appimage-extract"],
        cwd=str(out_dir),
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "APPIMAGE_EXTRACT_AND_RUN": "1"},
    )
    if proc.returncode != 0 or not (out_dir / "squashfs-root").is_dir():
        return {
            "ok": False,
            "error": (proc.stderr or proc.stdout or "AppImage extract failed")[:400],
            "rc": proc.returncode,
        }
    for eng_tar in sorted(dest_p.glob("strata-engine*.tar.gz")):
        subprocess.run(
            ["tar", "-xzf", str(eng_tar), "-C", str(out_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
    marker.write_text("ok\n", encoding="utf-8")
    return {"ok": True, "root": str(out_dir), "engine": "strata", "already": False}


def ensure_engine_ready(engine: str, dest: str | Path) -> dict[str, Any]:
    eng = normalize_engine_id(engine)
    if eng == "ninfer-all":
        return ensure_ninfer_extracted(dest)
    if eng == "strata":
        return ensure_strata_extracted(dest)
    return {"ok": False, "error": f"cannot prepare engine {eng!r}"}


def find_gguf_for_strata(models_dirs: list[str | Path] | None = None) -> str:
    """Best-effort path to a GGUF Strata can try (--model-path)."""
    dirs: list[Path] = []
    for d in models_dirs or [
        "/mnt/stickllm-data/models",
        "/opt/stickllm/models",
        "/opt/stickllm/models/appagent",
    ]:
        dirs.append(Path(d))
    candidates: list[Path] = []
    for d in dirs:
        if not d.is_dir():
            continue
        try:
            for f in d.rglob("*.gguf"):
                if "mmproj" in f.name.lower():
                    continue
                try:
                    if f.stat().st_size < 50 * 1024 * 1024:
                        continue
                except OSError:
                    continue
                candidates.append(f)
        except OSError:
            continue
    if not candidates:
        return ""
    candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return str(candidates[0])


def experimental_snapshot(
    rows: list[dict] | None,
    *,
    os_release: str = "",
    card_unlock_intent: dict | None = None,
    platform: str = "linux",
    driver_version: str = "",
    secure_boot: bool | None = None,
    nvidia_open: bool | None = None,
    applied_unlocks: dict | None = None,
    engines_root: str | Path | None = None,
    active_engine: str | dict | None = None,
) -> dict[str, Any]:
    """Full Experimental tab payload (detect + offers + unlock gates).

    Per-card Cancel/Continue only — no master kill-switch.
    """
    cards = classify_inventory(rows)
    maj = debian_major(os_release)
    offers = engine_offers(cards, debian_major_version=maj, platform=platform)
    installed = scan_installed_engines(engines_root)
    if isinstance(active_engine, dict):
        active_doc = active_engine
    elif isinstance(active_engine, str) and active_engine.strip():
        active_doc = {"engine": normalize_engine_id(active_engine)}
    else:
        active_doc = read_active_engine()
    active_id = normalize_engine_id(str(active_doc.get("engine") or "llama.cpp"))
    for o in offers:
        eng = str(o.get("engine") or "")
        info = installed.get(eng)
        is_default = active_id == eng
        if info:
            o["installed"] = True
            o["tag"] = info.get("tag") or ""
            o["dest"] = info.get("dest") or ""
            o["bytes"] = info.get("bytes") or 0
            o["usable"] = True
            o["default"] = is_default
            o["active"] = is_default
            if is_default:
                o["note"] = (
                    f"Installed · tag {info.get('tag') or '?'} — StickLLM default "
                    f"(chat / health / Agent Zero use this engine on :8080)"
                )
            else:
                o["note"] = (
                    f"Installed · tag {info.get('tag') or '?'} — Use Set default to "
                    f"switch chat off llama.cpp onto this engine"
                )
            info["default"] = is_default
            info["active"] = is_default
            info["usable"] = True
            info["note"] = o["note"]
        else:
            o.setdefault("installed", False)
            o.setdefault("usable", False)
            o.setdefault("default", False)
            o.setdefault("active", False)
    intent = card_unlock_intent if isinstance(card_unlock_intent, dict) else {}
    applied = applied_unlocks if isinstance(applied_unlocks, dict) else {}
    reports = []
    unlock_gates = []
    for c in cards:
        key = str(c.get("bus") or c.get("pci_id") or "")
        already = bool(applied.get(key))
        if not c.get("unlock_in_scope"):
            reason = c.get("skip_reason") or "not in unlock scope"
            reports.append(unlock_report_line(c, "skipped", reason))
            continue
        gate = unlock_preflight(
            c,
            driver_version=driver_version,
            secure_boot=secure_boot,
            nvidia_open=nvidia_open,
            already_applied=already,
        )
        unlock_gates.append(gate)
        if already:
            reports.append(unlock_report_line(c, "applied", "already active"))
        elif intent.get(key):
            if gate.get("ok"):
                reports.append(
                    unlock_report_line(
                        c,
                        "intent on",
                        f"Continue recorded; ready for {c.get('unlock_path')} apply",
                    )
                )
            else:
                reports.append(
                    unlock_report_line(
                        c,
                        "intent on",
                        f"blocked: {gate.get('reason') or 'preflight failed'}",
                    )
                )
        else:
            reports.append(unlock_report_line(c, "skipped", "off by default; not confirmed"))
    if active_id != "llama.cpp":
        reports.append(f"active engine: {active_id} (Set default; switch back via llama.cpp)")
    else:
        reports.append("active engine: llama.cpp")
    return {
        "ok": True,
        "nov3_context": NOV3_CONTEXT,
        "cmp_warning": CMP_WARNING,
        "rtx3090_warning": RTX3090_WARNING,
        "debian_major": maj,
        "ninfer_linux_ok": maj == 13,
        "driver_version": driver_version or "",
        "strata_cuda": strata_cuda_for_driver(driver_version),
        "secure_boot": secure_boot,
        "nvidia_open": nvidia_open,
        "cards": cards,
        "offers": offers,
        "reports": reports,
        "unlock_gates": unlock_gates,
        "actions_require_confirm": True,
        "auto_install": False,
        "engines": installed,
        "engines_root": str(Path(engines_root) if engines_root else ENGINES_ROOT),
        "active_engine": active_id,
        "active_engine_detail": active_doc,
        "wired": {
            "download": True,
            "unlock_apply": True,
            "unlock_disable": True,
            "set_default": True,
            "use": True,
            "blobs_in_git": False,
        },
        "repos": {
            "strata": STRATA_REPO,
            "ninfer-all": NINFER_REPO,
            "cmpunlocker": CMPUNLOCKER_GIT,
            "gpu_unlock": GPU_UNLOCK_GIT,
        },
    }
