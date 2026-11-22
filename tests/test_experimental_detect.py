"""Experimental tab: classify GPUs, gate offers, plan downloads, unlock preflight."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_experimental.py"


def _load():
    spec = importlib.util.spec_from_file_location("stickllm_experimental", MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_classify_cmp_8gb_10gb_and_3090():
    m = _load()
    cmp = m.classify_nvidia_card("10de:20c2", memory_total_mib=8192, bus="0000:81:00.0")
    assert cmp["kind"] == "cmp_170hx"
    assert cmp["unlock_path"] == "cmpunlocker"
    assert cmp["unlock_in_scope"] is True
    assert cmp["likely_unlocked"] is False
    cmp10 = m.classify_nvidia_card("10de:2082", memory_total_mib=10240, bus="0000:82:00.0")
    assert cmp10["kind"] == "cmp_170hx"
    assert cmp10["pci_id"] == "10de:2082"
    assert cmp10["unlock_in_scope"] is True
    rtx = m.classify_nvidia_card("10de:2204", memory_total_mib=24576, bus="0000:21:00.0")
    assert rtx["kind"] == "rtx_3090"
    assert rtx["unlock_path"] == "gpu_unlock"


def test_skip_cmp_32gb_subsystem_and_3090_ti():
    m = _load()
    bad = m.classify_nvidia_card("10de:20c2", subsystem_id="10de:1586")
    assert bad["unlock_in_scope"] is False
    assert "1586" in bad["skip_reason"]
    ti = m.classify_nvidia_card("10de:2203")
    assert ti["unlock_in_scope"] is False


def test_offers_3090_ninfer_needs_debian_13():
    m = _load()
    cards = [m.classify_nvidia_card("10de:2204", bus="0000:21:00.0")]
    blocked = m.engine_offers(cards, debian_major_version=12, platform="linux")
    ninfer = [o for o in blocked if o["engine"] == "ninfer-all"]
    assert ninfer and ninfer[0]["blocked"]
    ok = m.engine_offers(cards, debian_major_version=13, platform="linux")
    ninfer13 = [o for o in ok if o["engine"] == "ninfer-all"]
    assert ninfer13 and not ninfer13[0]["blocked"]
    strata = [o for o in ok if o["engine"] == "strata"]
    assert strata and not strata[0]["blocked"]


def test_offers_windows_builds_catalogued():
    m = _load()
    cards = [m.classify_nvidia_card("10de:2204", bus="0000:21:00.0")]
    win = m.engine_offers(cards, debian_major_version=13, platform="windows")
    assert any(o["engine"] == "strata" and not o["blocked"] for o in win)
    assert any(o["engine"] == "ninfer-all" and not o["blocked"] for o in win)


def test_locked_cmp_blocks_engines():
    m = _load()
    cards = [m.classify_nvidia_card("10de:20c2", memory_total_mib=8192)]
    offers = m.engine_offers(cards, debian_major_version=13)
    assert offers
    assert all(o["blocked"] for o in offers)


def test_unlocked_cmp_offers_engines():
    m = _load()
    cards = [m.classify_nvidia_card("10de:20c2", memory_total_mib=65536)]
    assert cards[0]["likely_unlocked"] is True
    offers = m.engine_offers(cards, debian_major_version=13)
    assert any(o["engine"] == "strata" and not o["blocked"] for o in offers)


def test_report_line_and_driver_gate():
    m = _load()
    c = m.classify_nvidia_card("10de:20c2", bus="0000:81:00.0")
    line = m.unlock_report_line(c, "skipped", "off by default; not confirmed")
    assert "CMP 170HX" in line and "skipped" in line
    ok, _ = m.cmp_driver_ok("615.71.09")
    assert ok is True
    bad, reason = m.cmp_driver_ok("615.78.08")
    assert bad is False and "615.78.08" in reason


def test_unlock_preflight_cmp_needs_open_and_allowlist():
    m = _load()
    c = m.classify_nvidia_card("10de:20c2", bus="0000:81:00.0")
    gate = m.unlock_preflight(c, driver_version="615.71.09", secure_boot=False, nvidia_open=False)
    assert gate["ok"] is False and "nvidia-open" in gate["reason"]
    gate2 = m.unlock_preflight(c, driver_version="615.71.09", secure_boot=False, nvidia_open=True)
    assert gate2["ok"] is True
    gate3 = m.unlock_preflight(c, driver_version="615.78.08", secure_boot=False, nvidia_open=True)
    assert gate3["ok"] is False
    gate4 = m.unlock_preflight(c, driver_version="615.71.09", secure_boot=True, nvidia_open=True)
    assert gate4["ok"] is False and "Secure Boot" in gate4["reason"]


def test_unlock_preflight_3090():
    m = _load()
    c = m.classify_nvidia_card("10de:2204", bus="0000:21:00.0")
    gate = m.unlock_preflight(c, secure_boot=False)
    assert gate["ok"] is True
    assert "gpu_unlock" in (gate.get("path") or "")


def test_snapshot_per_card_intent_no_master_toggle():
    m = _load()
    rows = [{"vendor": "nvidia", "pci_id": "10de:2204", "bus": "0000:21:00.0", "memory_total_mib": 24576, "name": "RTX 3090"}]
    snap = m.experimental_snapshot(rows, os_release='VERSION_ID="13"\n', card_unlock_intent={})
    assert snap["ninfer_linux_ok"] is True
    assert snap["auto_install"] is False
    assert "master_unlocks_enabled" not in snap
    assert snap["wired"]["download"] is True
    assert any("off by default" in r for r in snap["reports"])
    on = m.experimental_snapshot(
        rows,
        os_release='VERSION_ID="13"\n',
        card_unlock_intent={"0000:21:00.0": True},
    )
    assert any("intent on" in r for r in on["reports"])
    assert "3 November" in snap["nov3_context"]


def test_name_fallback_3090():
    m = _load()
    cards = m.classify_inventory(
        [{"vendor": "nvidia", "name": "NVIDIA GeForce RTX 3090", "bus": "0000:10:00.0", "memory_total_mib": 24576}]
    )
    assert cards and cards[0]["kind"] == "rtx_3090" and cards[0]["unlock_in_scope"] is True


def test_plan_strata_and_ninfer_from_fixture():
    m = _load()
    strata_release = {
        "tag_name": "v0.2.18",
        "html_url": "https://github.com/Niko1221/Strata/releases/tag/v0.2.18",
        "assets": [
            {
                "name": "Strata-0.2.18-linux-x86_64.AppImage",
                "browser_download_url": "https://example.test/AppImage",
                "size": 100,
            },
            {
                "name": "strata-engine-0.1.64-linux-x86_64-cuda-cuda13.tar.gz",
                "browser_download_url": "https://example.test/engine",
                "size": 200,
            },
            {
                "name": "Strata-0.2.18-windows-x64-setup.exe",
                "browser_download_url": "https://example.test/setup.exe",
                "size": 50,
            },
            {
                "name": "strata-engine-0.1.64-windows-x86_64-cuda-cuda13.tar.gz",
                "browser_download_url": "https://example.test/win-engine",
                "size": 60,
            },
            {
                "name": "SHA256SUMS.txt",
                "browser_download_url": "https://example.test/SHA256SUMS.txt",
                "size": 10,
            },
        ],
    }
    linux = m.plan_engine_download("strata", strata_release, platform="linux", cuda="cuda13")
    assert not linux["blocked"]
    names = [a["name"] for a in linux["assets"]]
    assert any(n.endswith(".AppImage") for n in names)
    assert any("cuda13" in n and "linux" in n for n in names)
    assert any("SHA256" in n for n in names)
    win = m.plan_engine_download("strata", strata_release, platform="windows", cuda="cuda13")
    assert not win["blocked"]
    assert any("setup.exe" in a["name"] for a in win["assets"])

    ninfer_release = {
        "tag_name": "2026-11-21.4",
        "html_url": "https://github.com/iamwavecut/ninfer-all/releases/tag/2026-11-21.4",
        "assets": [
            {
                "name": "ninfer-linux-x64-cuda12.9-sm70-75-80-86-89-bd8195f42e87.tar.gz.001",
                "browser_download_url": "https://example.test/n1",
                "size": 10,
            },
            {
                "name": "ninfer-linux-x64-cuda12.9-sm70-75-80-86-89-bd8195f42e87.tar.gz.002",
                "browser_download_url": "https://example.test/n2",
                "size": 10,
            },
            {
                "name": "SHA256SUMS-ninfer-linux-x64-cuda12.9-sm70-75-80-86-89-bd8195f42e87.txt",
                "browser_download_url": "https://example.test/nsha",
                "size": 5,
            },
            {
                "name": "ninfer-windows-x64-cuda12.9-sm70-75-80-86-89-bd8195f42e87.7z.001",
                "browser_download_url": "https://example.test/w1",
                "size": 10,
            },
            {
                "name": "SHA256SUMS-ninfer-windows-x64-cuda12.9-sm70-75-80-86-89-bd8195f42e87.txt",
                "browser_download_url": "https://example.test/wsha",
                "size": 5,
            },
        ],
    }
    blocked = m.plan_engine_download(
        "ninfer-all", ninfer_release, platform="linux", cuda="cuda12.9", debian_major_version=12
    )
    assert blocked["blocked"]
    ok = m.plan_engine_download(
        "ninfer-all", ninfer_release, platform="linux", cuda="cuda12.9", debian_major_version=13
    )
    assert not ok["blocked"]
    assert len([a for a in ok["assets"] if a.get("role") == "payload"]) == 2
    win_n = m.plan_engine_download(
        "ninfer-all", ninfer_release, platform="windows", cuda="cuda12.9", debian_major_version=13
    )
    assert not win_n["blocked"]
    assert any(".7z." in a["name"] for a in win_n["assets"])


def test_parse_sha256sums():
    m = _load()
    text = "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899  foo.bin\n"
    got = m.parse_sha256sums(text)
    assert got["foo.bin"] == "aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899"
