"""0.6.3: Agent Zero preinstalled on USB + optional Move to SSD."""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "overlay/usr/local/lib/stickllm_agent.py"
AGENT_SH = ROOT / "overlay/usr/local/bin/stickllm-agent"
BUILD = ROOT / "scripts/lib/docker-build-live.sh"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_drive_pref_defaults_to_usb(tmp_path, monkeypatch):
    a = _load(AGENT, "stickllm_agent_pref")
    monkeypatch.setattr(a, "DOCKER_DRIVE_PREF", tmp_path / "missing-pref")
    assert a.docker_drive_pref() == "usb"


def test_seed_ready_and_ensure_seeded(tmp_path, monkeypatch):
    a = _load(AGENT, "stickllm_agent_seed")
    seed = tmp_path / "seed"
    (seed / "image").mkdir(parents=True)
    layer = seed / "overlay2" / "layer1"
    (layer / "diff").mkdir(parents=True)
    (layer / "diff" / "bulk").write_text("BIG", encoding="utf-8")
    (layer / "link").write_text("meta", encoding="utf-8")
    (seed / "overlay2" / "l").mkdir(parents=True)
    (seed / "stickllm-seed.json").write_text(json.dumps({
        "format": 1,
        "config_digest": "sha256:" + "a" * 64,
        "amd64_digest": "sha256:" + "b" * 64,
    }))
    monkeypatch.setattr(a, "SEED_DIR", seed)
    monkeypatch.setattr(a, "load_pin", lambda: {
        "config_digest": "sha256:" + "a" * 64,
        "amd64_digest": "sha256:" + "b" * 64,
    })
    assert a.seed_ready() is True
    assert a.seed_matches_pin() is True
    dest = tmp_path / "data" / "stickllm-docker"
    monkeypatch.setattr(a, "choose_docker_root", lambda **k: dest)
    binds = []

    def fake_bind(src, dst):
        binds.append((src, dst))
        dst.mkdir(parents=True, exist_ok=True)
        (dst / ".bind").write_text(str(src), encoding="utf-8")

    monkeypatch.setattr(a, "_bind_ro", fake_bind)
    res = a.ensure_seeded(dest)
    assert res["ok"] is True
    assert res["copied"] is False
    assert res.get("mounted") is True
    assert binds and binds[0][0] == layer / "diff"
    assert (dest / "image").is_dir()
    assert not (dest / "overlay2" / "layer1" / "diff" / "bulk").exists()
    res2 = a.ensure_seeded(dest)
    assert res2["ok"] is True
    assert res2["copied"] is False




def test_choose_docker_root_usb_default_with_seed(tmp_path, monkeypatch):
    a = _load(AGENT, "stickllm_agent_usb")
    monkeypatch.delenv("STICKLLM_DOCKER_DIR", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(a, "DATA_MNT", data)
    monkeypatch.setattr(a, "seed_ready", lambda: True)
    monkeypatch.setattr(a, "free_bytes", lambda p: 64 << 30)
    mounts = f"/dev/sdb3 {data} ext4 rw 0 0\n"
    ssd = tmp_path / "ssd" / "stickllm-docker"
    assert a.choose_docker_root(mounts_text=mounts, ssd_root=ssd, pref="auto") == data / "stickllm-docker"
    assert a.choose_docker_root(mounts_text=mounts, ssd_root=ssd, pref="usb") == data / "stickllm-docker"
    ssd.parent.mkdir(parents=True, exist_ok=True)
    assert a.choose_docker_root(mounts_text=mounts, ssd_root=ssd, pref="ssd") == ssd


def test_move_to_ssd_updates_pref(tmp_path, monkeypatch):
    a = _load(AGENT, "stickllm_agent_move")
    usb = tmp_path / "data" / "stickllm-docker"
    (usb / "image").mkdir(parents=True)
    (usb / "image" / "x").write_text("blob")
    ssd = tmp_path / "ssd" / "stickllm-docker"
    ssd.parent.mkdir(parents=True)
    monkeypatch.setattr(a, "DATA_MNT", tmp_path / "data")
    monkeypatch.setattr(a, "usb_data_mounted", lambda mounts_text=None: True)
    monkeypatch.setattr(a, "docker_data_root", lambda **k: ssd)
    monkeypatch.setattr(a, "DOCKER_DRIVE_PREF", tmp_path / "pref")
    monkeypatch.setattr(a, "MOVE_STATUS", tmp_path / "move.json")

    def fake_mat(root):
        root.mkdir(parents=True, exist_ok=True)
        (root / "image").mkdir(exist_ok=True)
        (root / "overlay2").mkdir(exist_ok=True)
        return {"ok": True, "copied": True, "root": str(root)}

    monkeypatch.setattr(a, "materialize_seed", fake_mat)
    monkeypatch.setattr(a, "ensure_seeded", lambda root=None: {
        "ok": True, "copied": False, "mounted": True, "root": str(root or usb),
    })
    res = a.move_agent_root("ssd")
    assert res["ok"] and res["pref"] == "ssd"
    assert a.docker_drive_pref() == "ssd"
    assert (ssd / "image").is_dir()
    res2 = a.move_agent_root("usb")
    assert res2["ok"] and res2["pref"] == "usb"
    assert a.docker_drive_pref() == "usb"



def test_agent_sh_seeds_before_start():
    sh = AGENT_SH.read_text(encoding="utf-8")
    assert "a0_ensure_seed" in sh
    assert "ensure-seeded" in sh
    start = sh[sh.index("cmd_start() {"): sh.index("cmd_sync_model() {")]
    assert "a0_ensure_seed" in start
    ready = sh[sh.index("cmd_image_ready() {"): sh.index("run_ref() {")]
    assert "a0_ensure_seed" in ready


def test_build_bakes_docker_seed():
    build = BUILD.read_text(encoding="utf-8")
    assert "a0_seed.sh" in build
    assert "/opt/stickllm/docker-seed" in build
    assert (ROOT / "scripts/lib/a0_seed.sh").is_file()


def test_gateway_has_docker_drive_api():
    gw = (ROOT / "overlay/usr/local/bin/stickllm-gateway").read_text(encoding="utf-8")
    assert "/api/agent/docker-drive" in gw
    assert "_agent_docker_drive" in gw

def test_a0_seed_forces_overlay2():
    src = Path('scripts/lib/a0_seed.sh').read_text(encoding='utf-8')
    assert '--storage-driver=overlay2' in src
    assert 'SEED_BYTES' in src
    assert 'expected overlay2' in src

def test_a0_seed_work_prefers_volume():
    src = Path("scripts/lib/a0_seed.sh").read_text(encoding="utf-8")
    assert "WORK=/work/stickllm-a0-seed-work" in src
    live = Path("scripts/lib/docker-build-live.sh").read_text(encoding="utf-8")
    assert "A0_SEED_WORK=/work/stickllm-a0-seed-work" in live

def test_a0_seed_keeps_image_layers():
    src = Path("scripts/lib/a0_seed.sh").read_text(encoding="utf-8")
    assert "system prune -af" not in src
    assert "seed too small" in src
    assert "overlay2 is empty" in src

