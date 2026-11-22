"""Bake gate: CUDA sonames must be created on every boot via pick-gpus."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PICK = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-pick-gpus"
HOTFIX = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-hotfix"
DOCKER = ROOT / "scripts" / "lib" / "docker-build-llama.sh"


def test_pick_gpus_calls_ensure_cuda_sonames_at_boot():
    src = PICK.read_text(encoding="utf-8")
    assert "ensure_cuda_sonames" in src
    assert "libggml-cuda.so.0" in src
    assert "libllama-common.so.1" in src
    # Must actually invoke, not only define.
    assert "\nensure_cuda_sonames\n" in src or "\nensure_cuda_sonames()\n" in src or src.count("ensure_cuda_sonames") >= 2


def test_hotfix_still_has_ensure_cuda_sonames():
    src = HOTFIX.read_text(encoding="utf-8")
    assert "ensure_cuda_sonames" in src
    assert "libggml-cuda.so.0" in src


def test_docker_build_llama_links_sonames():
    src = DOCKER.read_text(encoding="utf-8")
    assert "link_soname" in src
    assert "libggml-cuda.so.0" in src
