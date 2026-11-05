"""0.6.3: Agent Zero seed mounts at runnable root — no first-boot full copy."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_agent.py"


def _load():
    loader = importlib.machinery.SourceFileLoader("stickllm_agent_seedmount", str(AGENT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = mod
    loader.exec_module(mod)
    return mod


def test_ensure_seeded_source_has_no_full_seed_rsync():
    src = AGENT.read_text(encoding="utf-8")
    start = src.index("def ensure_seeded(")
    end = src.index("\ndef materialize_seed(")
    body = src[start:end]
    assert "rsync" not in body or "Never rsync" in body
    assert '["rsync"' not in body
    assert "str(SEED_DIR) + \"/\"" not in body
    assert "_bind_ro" in body
    assert "copied\": False" in body or "copied': False" in body or '"copied": False' in body


def test_materialize_seed_is_only_full_copy_path():
    src = AGENT.read_text(encoding="utf-8")
    start = src.index("def materialize_seed(")
    end = src.index("\ndef move_agent_root(")
    body = src[start:end]
    assert '["rsync"' in body
    assert "str(SEED_DIR)" in body


def test_ensure_seeded_binds_diffs_not_copy(tmp_path, monkeypatch):
    mod = _load()
    seed = tmp_path / "seed"
    root = tmp_path / "docker"
    # minimal seed layout
    (seed / "image" / "overlay2").mkdir(parents=True)
    (seed / "image" / "overlay2" / "repositories.json").write_text("{}", encoding="utf-8")
    layer = seed / "overlay2" / "abc123"
    (layer / "diff").mkdir(parents=True)
    (layer / "diff" / "file").write_text("bulk", encoding="utf-8")
    (layer / "link").write_text("meta", encoding="utf-8")
    (seed / "overlay2" / "l").mkdir(parents=True)
    (seed / "stickllm-seed.json").write_text(
        json.dumps({
            "format": 1,
            "kind": "docker-data-root",
            "config_digest": "sha256:dead",
            "amd64_digest": "sha256:beef",
            "version": "v2.15",
            "image": "agent0ai/agent-zero",
        }),
        encoding="utf-8",
    )
    binds = []

    def fake_bind(src, dst):
        binds.append((Path(src), Path(dst)))
        dst.mkdir(parents=True, exist_ok=True)
        # simulate mount by placing a marker (not copying bulk)
        (dst / ".bind").write_text(str(src), encoding="utf-8")

    monkeypatch.setattr(mod, "SEED_DIR", seed)
    monkeypatch.setattr(mod, "seed_ready", lambda: True)
    monkeypatch.setattr(mod, "seed_matches_pin", lambda: True)
    monkeypatch.setattr(mod, "choose_docker_root", lambda **k: root)
    monkeypatch.setattr(mod, "_bind_ro", fake_bind)

    res = mod.ensure_seeded(root)
    assert res["ok"] is True
    assert res["copied"] is False
    assert res.get("mounted") is True
    assert binds, "expected diff bind"
    assert binds[0][0] == layer / "diff"
    # bulk file must NOT exist as a real copy under root overlay2/abc123/diff/file
    # (bind stub only has .bind)
    assert not (root / "overlay2" / "abc123" / "diff" / "file").exists()
    assert (root / "overlay2" / "abc123" / "diff" / ".bind").is_file()
    assert (root / "image").is_dir()
    # DATA must not contain a full duplicate of seed overlay2 diff content
    assert (layer / "diff" / "file").read_text(encoding="utf-8") == "bulk"


def test_default_pref_is_usb():
    mod = _load()
    # missing pref file
    assert mod.docker_drive_pref() == "usb"


def test_move_ssd_uses_materialize(monkeypatch, tmp_path):
    mod = _load()
    calls = []

    def fake_mat(root):
        calls.append(root)
        root.mkdir(parents=True, exist_ok=True)
        (root / "image").mkdir()
        (root / "overlay2").mkdir()
        return {"ok": True, "copied": True, "root": str(root)}

    monkeypatch.setattr(mod, "materialize_seed", fake_mat)
    monkeypatch.setattr(mod, "docker_data_root", lambda use_env=False: tmp_path / "ssd" / "stickllm-docker")
    monkeypatch.setattr(mod, "usb_data_mounted", lambda *a, **k: False)
    monkeypatch.setattr(mod, "write_move_status", lambda doc: None)
    monkeypatch.setattr(mod, "set_docker_drive_pref", lambda v: None)
    monkeypatch.setattr(mod, "read_move_status", lambda: {})
    res = mod.move_agent_root("ssd")
    assert res["ok"] is True
    assert calls and calls[0].name == "stickllm-docker"
