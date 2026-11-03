"""0.5.6 Models page fixes: per-card VRAM on Vulkan, AMD message, RAM check, sort, labels."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-control"
CATALOG = ROOT / "config" / "models" / "catalog.toml"
JS = ROOT / "ui" / "app.js"


def _load(monkeypatch):
    monkeypatch.setenv("STICKLLM_CATALOG", str(CATALOG))
    loader = importlib.machinery.SourceFileLoader("stickllm_control_v056m", str(CTL))
    spec = importlib.util.spec_from_loader("stickllm_control_v056m", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _two_rx570(tmp_path):
    env = tmp_path / "cuda.env"
    # Two 8 GB cards (sysfs VRAM). GTT is never part of this.
    env.write_text("STICKLLM_BACKEND=vulkan\nSTICKLLM_VULKAN_GPUS=0:8192:7900:16:8000,1:8192:8000:1:2500\n")
    return env


def test_vulkan_inventory_plans_one_card(monkeypatch, tmp_path):
    ctl = _load(monkeypatch)
    env = _two_rx570(tmp_path)
    monkeypatch.setattr(ctl, "nvidia_gpu_rows", lambda: [])
    real = ctl.vulkan_gpu_rows
    monkeypatch.setattr(ctl, "vulkan_gpu_rows", lambda env_path=None: real(env))
    monkeypatch.setattr(ctl, "_vulkan_label", lambda: "AMD GPU")
    inv = ctl.gpu_inventory()
    assert inv["backend"] == "vulkan" and inv["count"] == 2 and inv["plan_count"] == 1
    assert abs(inv["vram_gb"] - 8.0) < 0.01, inv  # one card, not 16 (sum) or 24 (sum + GTT)
    assert abs(inv["each_gb"] - 8.0) < 0.01 and inv["name"] == "AMD GPU"
    assert ctl.has_gpu() and not ctl.has_nvidia()


def test_status_and_warning_wiring():
    src = CTL.read_text()
    assert '"gpu_backend": inv.get("backend") or "cpu"' in src
    assert 'hardware_warnings(round(vram, 1), int(inv.get("count") or 0), inv.get("backend") or "")' in src
    assert '"ram_warning": ram_warning' in src


def test_ram_warning_on_big_model(monkeypatch, tmp_path):
    ctl = _load(monkeypatch)
    big = tmp_path / "Big-Q4_K_M.gguf"
    big.write_bytes(b"GGUF" + b"\0" * 16)
    monkeypatch.setattr(ctl, "BAKED_4B", tmp_path / "none.gguf")
    monkeypatch.setattr(ctl, "find_file", lambda name: None)
    monkeypatch.setattr(ctl, "discover_local_ggufs", lambda: [])
    monkeypatch.setattr(ctl, "detect_vram_gb", lambda: 8.0)
    monkeypatch.setattr(ctl, "detect_ram_gb", lambda: 6.0)
    monkeypatch.setattr(ctl, "has_gpu", lambda: True)
    monkeypatch.setattr(ctl, "has_nvidia", lambda: False)
    monkeypatch.setattr(ctl, "vulkan_gpu_rows", lambda env_path=None: [])
    monkeypatch.setattr(ctl, "active_model_path", lambda: "")
    monkeypatch.setattr(ctl, "llama_health_ok", lambda: (False, "down"))
    monkeypatch.setattr(ctl, "active_ctx_size", lambda: None)
    monkeypatch.setattr(ctl, "read_gguf_meta", lambda p: {})
    monkeypatch.setattr(ctl, "find_mmproj", lambda p: "")
    rows = {m["id"]: m for m in ctl.enrich_models()}
    assert "system RAM" in rows["qwen38-27b-q4km"]["ram_warning"]  # 16 GB model, 8 GB card, 6 GB RAM
    assert rows["qwen35-4b-q4km"]["ram_warning"] == ""
    assert rows["qwen35-4b-q4km"]["backend"] == "vulkan"


def _node(code: str):
    subprocess.run(["node", "-e", code], check=True)


def _fn(js: str, name: str) -> str:
    a = js.index(f"function {name}(")
    depth = 0
    i = js.index("{", a)
    for j in range(i, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                return js[a : j + 1]
    raise AssertionError(name)


def test_ui_fit_vulkan_one_card_and_ram():
    js = JS.read_text()
    code = (
        "const state={kv:'f16',mf:{ctx:8192,target:'auto'}};"
        + _fn(js, "fitGb") + _fn(js, "modelGb") + _fn(js, "hardwarePool") + _fn(js, "fitOf")
        + "let hwInfo={vram:8,vramEach:8,gpuCount:2,backend:'vulkan',ram:32};"
        "let f=fitOf({approx_size_gb:12});if(f.k==='gpu')throw new Error('12 GB on an 8 GB card: '+f.label);"
        "f=fitOf({approx_size_gb:2.6});if(f.k!=='gpu'||/2 GPUs/.test(f.label))throw new Error(f.label);"
        "hwInfo={vram:8,vramEach:8,gpuCount:1,backend:'vulkan',ram:4};"
        "f=fitOf({approx_size_gb:16});if(f.k!=='no'||!/RAM/.test(f.label))throw new Error(f.label);"
        "hwInfo={vram:0,vramEach:0,gpuCount:0,backend:'cpu',ram:16};"
        "f=fitOf({approx_size_gb:2.6});if(f.k!=='offload'||!/CPU/.test(f.label))throw new Error(f.label);"
    )
    _node(code)


def test_ui_no_24gb_default_and_labels():
    js = JS.read_text()
    assert "|| 24" not in js.split("async function refreshModelsNow", 1)[1].split("\n}\n", 1)[0]
    assert "let hwInfo = { vram: 0," in js
    assert "const have = (m) => Number(!m.installed);" in js
    assert "function modelWhere(m)" in js and 'if (p.startsWith("/opt/stickllm/")) return "stick";' in js
    assert "llamaStarting()" in js
    assert "AMD GPU found, using Vulkan" in (ROOT / "overlay/usr/local/lib/stickllm_system.py").read_text()
