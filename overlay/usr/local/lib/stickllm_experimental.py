"""Experimental tab: GPU classify + engine offer rules (no downloads, no unlocks).

Safety: never fetch NVIDIA firmware, never patch drivers, never auto-install.
Callers must require Cancel/Continue before any privileged action.
"""
from __future__ import annotations

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

NOV3_CONTEXT = (
    "On 3 November 2026 these unlocks and alternative engines were left as "
    "community add-ons. That decision is reversed: StickLLM ships detection and "
    "opt-in installers only. Nothing runs until you press Continue."
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
        if vendor and vendor not in ("nvidia", "10de") and not pid.startswith("10de:"):
            continue
        if not pid and not str(row.get("name") or "").lower().startswith("nvidia"):
            # Still try if name looks NVIDIA from smi without pci_id.
            name_l = str(row.get("name") or "").lower()
            if "nvidia" not in name_l and "geforce" not in name_l and "cmp" not in name_l:
                continue
        out.append(
            classify_nvidia_card(
                pid,
                subsystem_id=str(row.get("subsystem_id") or row.get("subsystem") or ""),
                memory_total_mib=row.get("memory_total_mib") or row.get("total_mib"),
                bus=str(row.get("bus") or ""),
                name=str(row.get("name") or ""),
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
    """Return download *offers* only — never URLs that auto-fetch.

    Rules (handoff §4): offer Strata / NInfer-all for RTX 3090; for CMP only
    when likely unlocked (or UI shows separate unlock-first warning).
    NInfer Linux requires Debian 13.
    """
    offers: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(engine: str, card: dict[str, Any], note: str = "", blocked: str = "") -> None:
        key = (engine, card.get("bus") or card.get("pci_id") or card.get("label") or "")
        if key in seen:
            return
        seen.add(key)
        offers.append(
            {
                "engine": engine,
                "card_label": card.get("label") or "",
                "card_bus": card.get("bus") or "",
                "card_pci_id": card.get("pci_id") or "",
                "platform": platform,
                "note": note,
                "blocked": blocked,
                "auto_install": False,
            }
        )

    for card in cards:
        kind = card.get("kind")
        unlocked = bool(card.get("likely_unlocked"))
        if kind == "rtx_3090":
            add("strata", card, note="Linux AppImage + matching CUDA engine (Confirm before download)")
            if platform == "linux" and debian_major_version != 13:
                add(
                    "ninfer-all",
                    card,
                    blocked="NInfer-all Linux builds require Debian 13",
                )
            else:
                add("ninfer-all", card, note="Debian 13 / Windows community builds (Confirm before download)")
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
            add("strata", card, note="Community evidence on unlocked CMP (sm_80); Confirm before download")
            if platform == "linux" and debian_major_version != 13:
                add("ninfer-all", card, blocked="NInfer-all Linux builds require Debian 13")
            else:
                add("ninfer-all", card, note="Prefer official NInfer-all sm_80; Confirm before download")

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


def experimental_snapshot(
    rows: list[dict] | None,
    *,
    os_release: str = "",
    master_unlocks_enabled: bool = False,
    platform: str = "linux",
) -> dict[str, Any]:
    """Full Experimental tab payload (detect + offers only)."""
    cards = classify_inventory(rows)
    maj = debian_major(os_release)
    offers = engine_offers(cards, debian_major_version=maj, platform=platform)
    reports = []
    for c in cards:
        if not c.get("unlock_in_scope"):
            reason = c.get("skip_reason") or "not in unlock scope"
            reports.append(unlock_report_line(c, "skipped", reason))
        elif not master_unlocks_enabled:
            reports.append(unlock_report_line(c, "skipped", "master toggle off"))
        else:
            reports.append(unlock_report_line(c, "skipped", "off by default; not confirmed"))
    return {
        "ok": True,
        "nov3_context": NOV3_CONTEXT,
        "master_unlocks_enabled": bool(master_unlocks_enabled),
        "debian_major": maj,
        "ninfer_linux_ok": maj == 13,
        "cards": cards,
        "offers": offers,
        "reports": reports,
        "actions_require_confirm": True,
        "auto_install": False,
        "stub": {
            "download": "not wired — Confirm/Continue will be required",
            "unlock_apply": "not wired — CMP=cmpunlocker, 3090=gpu-unlock 2.0",
            "unlock_disable": "not wired — restores stock / drops gpu_unlock.targets",
        },
    }
