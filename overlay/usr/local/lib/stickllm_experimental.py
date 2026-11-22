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
import urllib.error
import urllib.request
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

NOV3_CONTEXT = (
    "On 3 November 2026 these unlocks and alternative engines were left as "
    "community add-ons. That decision is reversed: StickLLM ships detection and "
    "opt-in installers only. Nothing runs until you press Continue."
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
    NInfer Linux requires Debian 13. Windows builds are catalogued for host use.
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
                        blocked="NInfer-all Linux builds require Debian 13",
                    )
                else:
                    add(
                        "ninfer-all",
                        card,
                        note="Debian 13 x64 community build (Confirm before download)",
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
                    add("ninfer-all", card, blocked="NInfer-all Linux builds require Debian 13")
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
    for name, meta in sorted(assets.items()):
        low = name.lower()
        if "sha256" not in low:
            continue
        if prefix_hint and prefix_hint.lower() not in low:
            continue
        return dict(meta)
    # Fallback: any SHA256SUMS*
    for name, meta in sorted(assets.items()):
        if name.upper().startswith("SHA256") or "SHA256SUMS" in name.upper():
            return dict(meta)
    return None


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
            "blocked": "NInfer-all Linux builds require Debian 13",
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


def plan_engine_download(
    engine: str,
    release: dict[str, Any],
    *,
    platform: str = "linux",
    cuda: str = "",
    debian_major_version: int | None = 13,
) -> dict[str, Any]:
    eng = (engine or "").strip().lower()
    if eng in ("strata",):
        return select_strata_assets(release, platform=platform, cuda=cuda or "cuda13")
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
            "User-Agent": "StickLLM-Experimental/0.8.1",
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
) -> dict[str, Any]:
    """Full Experimental tab payload (detect + offers + unlock gates).

    Per-card Cancel/Continue only — no master kill-switch.
    """
    cards = classify_inventory(rows)
    maj = debian_major(os_release)
    offers = engine_offers(cards, debian_major_version=maj, platform=platform)
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
    return {
        "ok": True,
        "nov3_context": NOV3_CONTEXT,
        "cmp_warning": CMP_WARNING,
        "rtx3090_warning": RTX3090_WARNING,
        "debian_major": maj,
        "ninfer_linux_ok": maj == 13,
        "driver_version": driver_version or "",
        "secure_boot": secure_boot,
        "nvidia_open": nvidia_open,
        "cards": cards,
        "offers": offers,
        "reports": reports,
        "unlock_gates": unlock_gates,
        "actions_require_confirm": True,
        "auto_install": False,
        "wired": {
            "download": True,
            "unlock_apply": True,
            "unlock_disable": True,
            "blobs_in_git": False,
        },
        "repos": {
            "strata": STRATA_REPO,
            "ninfer-all": NINFER_REPO,
            "cmpunlocker": CMPUNLOCKER_GIT,
            "gpu_unlock": GPU_UNLOCK_GIT,
        },
    }
