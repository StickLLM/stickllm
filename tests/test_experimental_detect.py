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
    assert snap["wired"]["set_default"] is True
    assert snap["wired"]["use"] is True
    assert snap["active_engine"] == "llama.cpp"
    assert any("off by default" in r for r in snap["reports"])
    on = m.experimental_snapshot(
        rows,
        os_release='VERSION_ID="13"\n',
        card_unlock_intent={"0000:21:00.0": True},
    )
    assert any("intent on" in r for r in on["reports"])
    assert "3 November" not in snap["nov3_context"]
    assert "Continue" in snap["nov3_context"]
    assert "Debian 13" not in snap["nov3_context"]


def test_strata_cuda_for_driver():
    m = _load()
    assert m.strata_cuda_for_driver("550.163.01") == "cuda12"
    assert m.strata_cuda_for_driver("580.65.00") == "cuda13"
    assert m.strata_cuda_for_driver("580.64.00") == "cuda12"
    assert m.strata_cuda_for_driver("") == "cuda12"


def test_ensure_ninfer_extracted(tmp_path):
    m = _load()
    dest = tmp_path / "ninfer-all" / "tag1"
    dest.mkdir(parents=True)
    import io
    import tarfile

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="ninfer-serve")
        payload = b"#!/bin/sh\n"
        info.size = len(payload)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(payload))
        info2 = tarfile.TarInfo(name="run.sh")
        payload2 = b"#!/bin/sh\n"
        info2.size = len(payload2)
        info2.mode = 0o755
        tf.addfile(info2, io.BytesIO(payload2))
    raw = buf.getvalue()
    part1 = dest / "ninfer-linux-x64-cuda12.9-sm70.tar.gz.001"
    part2 = dest / "ninfer-linux-x64-cuda12.9-sm70.tar.gz.002"
    mid = max(1, len(raw) // 2)
    part1.write_bytes(raw[:mid])
    part2.write_bytes(raw[mid:])
    ready = m.ensure_ninfer_extracted(dest)
    assert ready.get("ok") is True, ready
    root = Path(ready["root"])
    assert (root / "ninfer-serve").is_file()
    assert (root / ".ok").is_file()
    again = m.ensure_ninfer_extracted(dest)
    assert again.get("already") is True


def test_scan_installed_engines_from_marker(tmp_path):
    m = _load()
    dest = tmp_path / "ninfer-all" / "2026-11-22.1"
    dest.mkdir(parents=True)
    part = dest / "ninfer-linux-x64-cuda12.9-sm70.tar.gz.001"
    part.write_bytes(b"x" * (2 * 1024 * 1024))
    marker = {
        "ok": True,
        "state": "done",
        "engine": "ninfer-all",
        "tag": "2026-11-22.1",
        "dest": dest.as_posix(),
        "bytes_done": 2 * 1024 * 1024,
    }
    (dest / "stickllm-download.json").write_text(json.dumps(marker) + "\n", encoding="utf-8")
    found = m.scan_installed_engines(tmp_path)
    assert "ninfer-all" in found
    assert found["ninfer-all"]["installed"] is True
    assert found["ninfer-all"]["tag"] == "2026-11-22.1"
    rows = [{"vendor": "nvidia", "pci_id": "10de:2204", "bus": "0000:21:00.0", "memory_total_mib": 24576}]
    snap = m.experimental_snapshot(rows, os_release='VERSION_ID="13"\n', engines_root=tmp_path)
    ninfer = [o for o in snap["offers"] if o["engine"] == "ninfer-all"][0]
    assert ninfer["installed"] is True
    assert "Installed" in ninfer["note"]
    assert snap["engines"]["ninfer-all"]["dest"]


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


def test_github_archive_urls_and_family_stem():
    m = _load()
    urls = m.github_archive_urls("https://github.com/Zagitta/gpu-unlock.git")
    assert urls[0].endswith("/main.tar.gz")
    assert urls[1].endswith("/master.tar.gz")
    assert m.archive_family_stem("ninfer-linux-x64-cuda12.9-sm70.tar.gz.001").endswith("sm70")
    assert "tar.gz" not in m.archive_family_stem("pkg.tar.gz.002")


def test_ninfer_sha_matches_payload_family_not_dual_pack():
    m = _load()
    release = {
        "tag_name": "2026-11-22.1",
        "assets": [
            {
                "name": "ninfer-linux-x64-cuda12.9-sm70-75-80-86-89-c14e46605b97.tar.gz.001",
                "browser_download_url": "https://example.test/1",
                "size": 10,
            },
            {
                "name": "ninfer-linux-x64-cuda12.9-sm70-75-80-86-89-c14e46605b97.tar.gz.002",
                "browser_download_url": "https://example.test/2",
                "size": 10,
            },
            {
                "name": "SHA256SUMS-ninfer-linux-x64-cuda12.9-13.4-c14e46605b97.txt",
                "browser_download_url": "https://example.test/dual-sha",
                "size": 5,
            },
            {
                "name": "SHA256SUMS-ninfer-linux-x64-cuda12.9-sm70-75-80-86-89-c14e46605b97.txt",
                "browser_download_url": "https://example.test/sm-sha",
                "size": 5,
            },
        ],
    }
    plan = m.plan_engine_download(
        "ninfer-all", release, platform="linux", cuda="cuda12.9", debian_major_version=13
    )
    assert not plan["blocked"]
    sha = [a for a in plan["assets"] if a.get("role") == "checksums"]
    assert sha and "sm70" in sha[0]["name"]
    assert "12.9-13.4" not in sha[0]["name"]


def test_ninfer_catalog_rows_and_artifact_lookup(tmp_path):
    m = _load()
    art = tmp_path / "qwen3_8_27b.ninfer"
    art.write_bytes(b"x" * 64)
    rows = m.ninfer_catalog_rows(tmp_path, active_key="qwen38-27b")
    ids = {r["id"] for r in rows}
    assert "qwen38-27b" in ids
    hit = next(r for r in rows if r["id"] == "qwen38-27b")
    assert hit["installed"] is True
    assert hit["active"] is True
    assert hit["path"].endswith("qwen3_8_27b.ninfer")
    assert m.find_ninfer_artifact("qwen38-27b", tmp_path) == art


def test_active_engine_env_id_does_not_override_json_path(tmp_path, monkeypatch):
    """systemd EnvironmentFile sets STICKLLM_ACTIVE_ENGINE=ninfer-all (engine id).

    That must not be treated as the path to active-engine.json (ISS / lab: serve
    then always fell back to llama.cpp and exited).
    """
    import importlib.util

    json_path = tmp_path / "active-engine.json"
    json_path.write_text(
        json.dumps(
            {
                "engine": "ninfer-all",
                "tag": "t",
                "dest": "/x",
                "root": "/x/extracted",
                "model_dir": "/m",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("STICKLLM_ACTIVE_ENGINE", "ninfer-all")
    monkeypatch.setenv("STICKLLM_ACTIVE_ENGINE_FILE", str(json_path))
    spec = importlib.util.spec_from_file_location("stickllm_experimental_env", MOD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    doc = mod.read_active_engine()
    assert doc["engine"] == "ninfer-all"
    # Without FILE override, STICKLLM_ACTIVE_ENGINE must still not become the path.
    monkeypatch.delenv("STICKLLM_ACTIVE_ENGINE_FILE", raising=False)
    monkeypatch.setenv("STICKLLM_ACTIVE_ENGINE", "ninfer-all")
    spec2 = importlib.util.spec_from_file_location("stickllm_experimental_env2", MOD)
    mod2 = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(mod2)
    assert Path(mod2.ACTIVE_ENGINE_PATH).as_posix() == "/var/lib/stickllm/experimental/active-engine.json"
