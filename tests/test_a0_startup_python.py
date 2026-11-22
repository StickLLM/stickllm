"""Agent Zero first-start: prefer venv python; seed +x must cover python."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "overlay/usr/local/lib/stickllm_agent.py"
ENTRY = ROOT / "overlay/usr/local/bin/stickllm-agent-entrypoint"
AGENT_SH = ROOT / "overlay/usr/local/bin/stickllm-agent"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_entrypoint_prefers_venv_python_over_bare_python3():
    src = ENTRY.read_text(encoding="utf-8")
    assert "a0_python()" in src
    assert "/opt/venv-a0/bin/python" in src
    assert '"$A0_PY"' in src
    # Must not hard-fail on the first bare python3 before A0_PY is chosen.
    assert "python3 - <<'PY'" not in src
    assert "Permission denied" in src  # documents the observed crash loop


def test_agent_health_wait_surfaces_a0_init_progress():
    src = AGENT_SH.read_text(encoding="utf-8")
    assert "first start can take a few minutes" in src
    assert "a0-init.log" in src
    assert "Updating framework" in src
    assert "Local TTS" in src


def test_seed_layers_executable_requires_python_when_present(tmp_path, monkeypatch):
    # Windows chmod cannot model Unix +x; drive the helper directly.
    a = _load(AGENT, "stickllm_agent_seed_py")
    seed = tmp_path / "seed"
    layer = seed / "overlay2" / "layer1"
    bindir = layer / "diff" / "usr" / "bin"
    bindir.mkdir(parents=True)
    bash = bindir / "bash"
    bash.write_bytes(b"#!/bin/sh\n")
    py = bindir / "python3.13"
    py.write_bytes(b"\x7fELF")
    exec_map = {bash: True, py: False}

    def fake_exec(path: Path) -> bool:
        return bool(exec_map.get(path, False))

    monkeypatch.setattr(a, "_layer_file_executable", fake_exec)
    assert a.seed_layers_executable(seed) is False
    exec_map[py] = True
    assert a.seed_layers_executable(seed) is True


def test_seed_layers_executable_ok_when_only_bash(tmp_path, monkeypatch):
    a = _load(AGENT, "stickllm_agent_seed_bash_only")
    seed = tmp_path / "seed"
    layer = seed / "overlay2" / "layer1"
    bindir = layer / "diff" / "usr" / "bin"
    bindir.mkdir(parents=True)
    bash = bindir / "bash"
    bash.write_bytes(b"#!/bin/sh\n")
    exec_map = {bash: True}

    def fake_exec(path: Path) -> bool:
        return bool(exec_map.get(path, False))

    monkeypatch.setattr(a, "_layer_file_executable", fake_exec)
    assert a.seed_layers_executable(seed) is True
    exec_map[bash] = False
    assert a.seed_layers_executable(seed) is False
