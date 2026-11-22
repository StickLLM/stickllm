"""MoE offload must use -ngl 99 + --n-cpu-moe (never dense full_ngl)."""
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay" / "usr" / "local" / "bin"
GiB = 1024**3


def _load(tmp_path, monkeypatch):
    # stickllm-control imports fcntl (Linux-only); stub on Windows hosts.
    if "fcntl" not in sys.modules:
        sys.modules["fcntl"] = types.ModuleType("fcntl")
    monkeypatch.setenv("STICKLLM_RUN", str(tmp_path / "run"))
    (tmp_path / "run").mkdir(parents=True, exist_ok=True)
    loader = importlib.machinery.SourceFileLoader("stickllm_control_moe", str(BIN / "stickllm-control"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _meta_inkling():
    a = "inkling2_loop"
    return {
        "general.architecture": a,
        f"{a}.block_count": 24,
        f"{a}.context_length": 1048576,
        f"{a}.embedding_length": 2304,
        f"{a}.attention.key_length": 128,
        f"{a}.expert_count": 128,
        f"{a}.expert_used_count": 8,
    }


def test_moe_always_ngl_99_even_when_file_fits(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    rows = [{"index": 0, "total_mib": 24576, "free_mib": 24100}]
    # 18 GiB MoE "fits" a 24GB card by file size — old bug used ngl=25, no n_cpu_moe.
    plan = c.plan_gpu_fit(
        file_bytes=int(18 * GiB),
        ctx=26624,
        meta=_meta_inkling(),
        gpus=rows,
    )
    assert plan["moe"] is True
    assert plan["n_gpu_layers"] == 99  # never dense full_ngl (=25)
    assert plan["n_cpu_moe"] >= 0
    assert plan["fit"] in ("moe", "full")


def test_large_moe_ctx_suggested_32k(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    b = c.estimate_context_budget(
        vram_gb=24.0,
        ram_gb=64.0,
        approx_size_gb=18.0,
        backend="cuda",
        model_max_ctx=1048576,
    )
    assert b["ctx_suggested"] == 32768
    assert b["ctx_min"] == 32768
    assert b["ctx_fits_floor"] is True


def test_large_moe_32k_spills_experts_not_ctx(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    rows = [{"index": 0, "total_mib": 24576, "free_mib": 24000}]
    plan = c.plan_gpu_fit(
        file_bytes=int(18 * GiB),
        ctx=32768,
        meta=_meta_inkling(),
        gpus=rows,
        kv_type="q8_0",
    )
    assert plan["ok"] is True
    assert plan["ctx"] >= 32768
    assert plan["n_gpu_layers"] == 99
    assert plan.get("ctx_unfit") is not True


def test_refuse_when_32k_cannot_fit(tmp_path, monkeypatch):
    c = _load(tmp_path, monkeypatch)
    # Tiny card: even MoE spill cannot hold 32K KV + non-expert weights.
    rows = [{"index": 0, "total_mib": 4096, "free_mib": 3900}]
    plan = c.plan_gpu_fit(
        file_bytes=int(18 * GiB),
        ctx=32768,
        meta=_meta_inkling(),
        gpus=rows,
        kv_type="q8_0",
    )
    assert plan["ok"] is False
    assert plan.get("ctx_unfit") is True
    assert plan["fit"] == "unfit"
