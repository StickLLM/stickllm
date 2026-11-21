"""Experimental tab: classify GPUs and gate engine offers (no network)."""
import importlib.util
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


def test_snapshot_master_off():
    m = _load()
    snap = m.experimental_snapshot(
        [{"vendor": "nvidia", "pci_id": "10de:2204", "bus": "0000:21:00.0", "memory_total_mib": 24576, "name": "RTX 3090"}],
        os_release='VERSION_ID="13"\n',
        master_unlocks_enabled=False,
    )
    assert snap["ninfer_linux_ok"] is True
    assert snap["auto_install"] is False
    assert any("master toggle off" in r for r in snap["reports"])
    assert "3 November" in snap["nov3_context"]
