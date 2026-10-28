"""0.5.2 fix 4: presets follow the knobs, KV type reaches llama-server,
sampling reaches the chat upstream."""
import importlib.machinery
import importlib.util
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay" / "usr" / "local" / "bin"
APP = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
HTML = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")


def _load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _run_llama_start(tmp_path, kv):
    model = tmp_path / "m.gguf"
    model.write_bytes(b"GGUF")
    fake = tmp_path / "fake-llama"
    out = tmp_path / "args.txt"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {out}\n', encoding="utf-8")
    fake.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("STICKLLM_")}
    env.update({
        "STICKLLM_MODEL": str(model), "STICKLLM_BACKEND": "cpu", "STICKLLM_RUN": str(tmp_path / "run"),
        "STICKLLM_LLAMA_CPU": str(fake), "STICKLLM_LLAMA_CUDA": str(fake), "STICKLLM_LLAMA_VULKAN": str(fake),
        "STICKLLM_LIB_CPU": str(tmp_path / "nolib"), "STICKLLM_CTX_SIZE": "8192",
    })
    if kv is not None:
        env["STICKLLM_KV_TYPE"] = kv
    subprocess.run(["bash", str(BIN / "stickllm-llama-start")], env=env, check=True, timeout=60,
                   capture_output=True)
    return out.read_text(encoding="utf-8").split("\n")


def test_llama_start_kv_flags(tmp_path):
    a = _run_llama_start(tmp_path, "q8_0")
    assert a[a.index("--cache-type-k") + 1] == "q8_0"
    assert a[a.index("--cache-type-v") + 1] == "q8_0"
    assert a[a.index("--flash-attn") + 1] == "on"
    assert a[a.index("--ctx-size") + 1] == "32768"  # floor kept (Agent Zero)
    for kv in (None, "f16", "bogus"):
        a = _run_llama_start(tmp_path, kv)
        assert "--cache-type-k" not in a and "--flash-attn" not in a


def test_llama_start_kv_on_all_backends():
    s = (BIN / "stickllm-llama-start").read_text(encoding="utf-8")
    assert s.count('"${kv_extra[@]}"') == 3


def test_activate_writes_kv_type(tmp_path, monkeypatch):
    monkeypatch.setenv("STICKLLM_RUN", str(tmp_path / "run"))
    c = _load(BIN / "stickllm-control", "stickllm_control_tune")
    g = tmp_path / "x.gguf"
    g.write_bytes(b"GGUF")
    m = {"id": "x", "installed": True, "fits": True, "path": str(g), "ctx_max": 32768, "backend": "cpu"}
    monkeypatch.setattr(c, "enrich_models", lambda: [m])
    monkeypatch.setattr(c, "sh", lambda *a, **k: {"code": 0})
    monkeypatch.setattr(c, "llama_health_ok", lambda: (False, "loading"))
    monkeypatch.setattr(c, "write_offload_plan", lambda p: {})
    monkeypatch.setattr(c, "build_offload_plan", lambda: {})
    monkeypatch.setattr(c, "llama_service_snapshot", lambda **k: {})
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    r = c.handle("model_activate", {"id": "x", "ctx_size": 8192, "kv_type": "q4_0"})
    assert r["kv_type"] == "q4_0" and r["ctx_size"] == 32768 and r["ctx_requested"] == 8192
    env = (tmp_path / "run" / "model.env").read_text(encoding="utf-8")
    assert "STICKLLM_KV_TYPE=q4_0" in env
    assert c.active_kv_type() == "q4_0"
    assert c.active_ctx_size() == 32768
    assert c.activate_model("x", 8192, "q2")["ok"] is False
    r = c.activate_model("x", 8192, None)
    assert r["kv_type"] == "f16"


def test_gateway_sampling_passthrough():
    gw = (BIN / "stickllm-gateway").read_text(encoding="utf-8")
    assert '_sampling_num(req.get("temperature"), 0.7, 0.0, 2.0)' in gw
    for key in ("top_p", "top_k", "repeat_penalty"):
        assert f'("{key}",' in gw
    mod_src = gw[gw.index("def _sampling_num"):gw.index("class _AgentClients")]
    ns: dict = {}
    exec(mod_src, ns)
    f = ns["_sampling_num"]
    assert f("1.5", 0.7, 0, 2) == 1.5 and f(9, 0.7, 0, 2) == 2 and f("x", 0.7, 0, 2) == 0.7
    assert f(float("nan"), None, 0, 1) is None


def test_ui_presets_follow_knobs():
    assert "function syncPresetHighlight()" in APP
    assert re.search(r'\$\("#ctx"\)\.addEventListener\("input", \(\) => \{ paintCtxVal\(\); syncPresetHighlight\(\)', APP)
    assert 'kv_type: { f16: "f16", q8: "q8_0", q4: "q4_0" }[state.kv]' in APP
    assert "temperature: 0.7," not in APP
    assert "base.top_p = t.top_p" in APP and "base.repeat_penalty" in APP
    assert 'id="ctxNote"' in HTML and 'id="tuneApplies"' in HTML and 'id="presetCustom"' in HTML
    assert "greyed" not in APP
