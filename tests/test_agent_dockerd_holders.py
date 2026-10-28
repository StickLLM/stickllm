"""Agent Zero install keeps its own hold on the shared dockerd.

v0.5.0: unlock started stickllm-agent.service with no image; it exited
(needs_install), ExecStop released the "agent" holder and stopped dockerd in
the middle of the Apps-page install, which then reported pull_failed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-agent"
AGENT = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_agent.py"
UNIT = ROOT / "overlay" / "etc" / "systemd" / "system" / "stickllm-agent.service"
DIGEST = "sha256:" + "a" * 64

BASH = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("bash") or not shutil.which("flock"),
    reason="bash/flock not available",
)

STUB_LIB = r'''
import os, sys
cmd = sys.argv[1] if len(sys.argv) > 1 else ""
log = os.environ["STUB_LOG"]
def note(line):
    with open(log, "a") as fh:
        fh.write(line + "\n")
if cmd == "write-status":
    note("status " + " ".join(sys.argv[2:]))
    sys.exit(0)
if cmd == "docker-dir":
    print(os.environ["STUB_DOCKER_DIR"])
    sys.exit(0)
if cmd == "image-ref":
    print("agent0ai/agent-zero@" + "sha256:" + "a" * 64)
    sys.exit(0)
if cmd == "image-on-disk":
    sys.exit(int(os.environ.get("STUB_IMAGE", "1")))
sys.exit(0)
'''


def _setup(tmp_path: Path, image: int = 1) -> tuple[dict, Path, Path, Path]:
    lib = tmp_path / "stub_lib.py"
    lib.write_text(STUB_LIB, encoding="utf-8")
    calls = tmp_path / "dockerd.log"
    fake_dockerd = tmp_path / "fake-dockerd"
    fake_dockerd.write_text(f'#!/bin/bash\necho "$*" >>"{calls}"\n', encoding="utf-8")
    fake_dockerd.chmod(0o755)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text("#!/bin/bash\necho \"fake docker: $*\" >&2\nexit 1\n", encoding="utf-8")
    docker.chmod(0o755)
    run = tmp_path / "run"
    run.mkdir()
    status = tmp_path / "status.log"
    env = dict(os.environ)
    env.update({
        "STICKLLM_AGENT_LIB": str(lib),
        "STICKLLM_AGENT_RUN": str(run),
        "STICKLLM_DOCKERD": str(fake_dockerd),
        "STICKLLM_DOCKERD_RUN": str(run),
        "STICKLLM_AGENT_NO_SYSTEMD": "1",
        "STICKLLM_AGENT_HOST_NS": "1",
        "STICKLLM_VAULT_MNT": str(tmp_path / "vault"),
        "STUB_LOG": str(status),
        "STUB_DOCKER_DIR": str(tmp_path / "docker"),
        "STUB_IMAGE": str(image),
        "PATH": f"{bindir}:{env.get('PATH', '')}",
    })
    return env, calls, status, run / "agent-install.lock"


def _run(env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _hold(lock: Path):
    import fcntl
    fh = open(lock, "w")
    fcntl.flock(fh, fcntl.LOCK_EX)
    return fh


@BASH
def test_stop_never_releases_dockerd_during_install(tmp_path):
    env, calls, status, lock = _setup(tmp_path)
    fh = _hold(lock)
    try:
        r = _run(env, "stop")
    finally:
        fh.close()
    assert r.returncode == 0, r.stderr
    assert "install running" in r.stderr
    assert not any(line.startswith("release") for line in _lines(calls))
    assert not any("stopped" in line for line in _lines(status))
    # No install: stop releases only its own holder.
    r = _run(env, "stop")
    assert r.returncode == 0, r.stderr
    assert _lines(calls) == ["release agent"]
    assert any("--state stopped" in line for line in _lines(status))


@BASH
def test_install_uses_its_own_holder_and_releases_it_on_failure(tmp_path):
    env, calls, status, _lock = _setup(tmp_path)
    r = _run(env, "install")
    assert r.returncode == 1, r.stderr
    assert "pull failed" in r.stderr
    assert _lines(calls) == ["ensure agent-install", "release agent-install"]
    assert any("--state pull_failed" in line for line in _lines(status))


@BASH
def test_start_without_image_does_not_touch_dockerd(tmp_path):
    env, calls, status, lock = _setup(tmp_path, image=1)
    r = _run(env, "start")
    assert r.returncode == 0, r.stderr
    assert _lines(calls) == []
    assert any("--state needs_install" in line for line in _lines(status))
    # The service path (ExecStart=run) behaves the same.
    status.unlink()
    r = _run(env, "run")
    assert r.returncode == 0, r.stderr
    assert _lines(calls) == []
    # During an install the "installing" status is not overwritten.
    status.unlink()
    fh = _hold(lock)
    try:
        assert _run(env, "start").returncode == 0
    finally:
        fh.close()
    assert _lines(status) == []
    assert _lines(calls) == []


@BASH
@pytest.mark.parametrize("state,expected", [(0, 0), (1, 1), (2, 0)])
def test_image_ready_exec_condition(tmp_path, state, expected):
    env, calls, _status, _lock = _setup(tmp_path, image=state)
    assert _run(env, "image-ready").returncode == expected
    assert _lines(calls) == []


def test_unit_is_skipped_without_image():
    text = UNIT.read_text(encoding="utf-8")
    assert "ExecCondition=/usr/local/bin/stickllm-agent image-ready" in text
    assert text.index("ExecCondition=") < text.index("ExecStart=")


def _lib():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("stickllm_agent_ondisk", str(AGENT))
    spec = importlib.util.spec_from_loader("stickllm_agent_ondisk", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_image_on_disk_reads_repositories_json(tmp_path):
    mod = _lib()
    ref = "agent0ai/agent-zero@" + DIGEST
    root = tmp_path / "stickllm-docker"
    assert mod.image_on_disk(root, ref) is False             # dockerd never ran here
    (root / "image" / "overlay2").mkdir(parents=True)
    assert mod.image_on_disk(root, ref) is None              # unknown layout: ask dockerd
    repos = root / "image" / "overlay2" / "repositories.json"
    repos.write_text(json.dumps({"Repositories": {"agent0ai/agent-zero": {
        "agent0ai/agent-zero@sha256:" + "b" * 64: "sha256:" + "c" * 64}}}), encoding="utf-8")
    assert mod.image_on_disk(root, ref) is False             # other digest
    repos.write_text(json.dumps({"Repositories": {
        "agent0ai/agent-zero": {"agent0ai/agent-zero@" + DIGEST: "sha256:" + "c" * 64},
        "stickllm-agent-zero": {"stickllm-agent-zero:rollback": "sha256:" + "d" * 64},
    }}), encoding="utf-8")
    assert mod.image_on_disk(root, ref) is True
    assert mod.image_on_disk(root, "docker.io/agent0ai/agent-zero@" + DIGEST) is True
    repos.write_text("{broken", encoding="utf-8")
    assert mod.image_on_disk(root, ref) is None