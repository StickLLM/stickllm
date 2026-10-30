"""Load from a Hugging Face search hit whose GGUF is already on disk (e.g. baked app-agent 4B)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-control"


def _load():
    loader = importlib.machinery.SourceFileLoader("stickllm_control_hfload", str(CTL))
    spec = importlib.util.spec_from_loader("stickllm_control_hfload", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _stub(ctl, monkeypatch, tmp_path, gguf: Path | None):
    monkeypatch.setattr(ctl, "find_file", lambda name: gguf if gguf and gguf.name == name else None)
    monkeypatch.setattr(ctl, "gguf_weight_bytes", lambda p: 2 * 1024**3)
    monkeypatch.setattr(ctl, "parse_catalog", lambda: [])
    monkeypatch.setattr(ctl, "discover_local_ggufs", lambda: [])
    monkeypatch.setattr(ctl, "detect_vram_gb", lambda: 0.0)
    monkeypatch.setattr(ctl, "detect_ram_gb", lambda: 8.0)
    monkeypatch.setattr(ctl, "has_nvidia", lambda: False)
    monkeypatch.setattr(ctl, "active_model_path", lambda: "")
    monkeypatch.setattr(ctl, "llama_health_ok", lambda: (False, "down"))
    monkeypatch.setattr(ctl, "active_ctx_size", lambda: None)
    monkeypatch.setattr(ctl, "read_gguf_meta", lambda p: {})
    monkeypatch.setattr(ctl, "find_mmproj", lambda p: "")


def test_hf_id_maps_to_baked_file(monkeypatch, tmp_path):
    ctl = _load()
    f = tmp_path / "appagent" / "Qwen3.5-4B-Q4_K_M.gguf"
    f.parent.mkdir()
    f.write_bytes(b"GGUF" + b"\0" * 16)
    _stub(ctl, monkeypatch, tmp_path, f)
    mid = "hf:unsloth__Qwen3.5-4B-GGUF:Qwen3.5-4B-Q4_K_M.gguf"
    row = ctl._hf_local_row(mid)
    assert row and row["id"] == mid and row["local_path"] == str(f)
    m = next(x for x in ctl.enrich_models(extra=[row]) if x["id"] == mid)
    assert m["installed"] and m["runnable"] and m["path"] == str(f)


def test_missing_ids_get_clear_error(monkeypatch, tmp_path):
    ctl = _load()
    _stub(ctl, monkeypatch, tmp_path, None)
    for mid in ("local-some-model-q4-k-m", "hf:a__b:c.gguf"):
        r = ctl.activate_model(mid)
        assert r["ok"] is False and r.get("stale") is True
        assert "unknown model" not in r["error"] and "Unlock the vault" in r["error"]
    r = ctl.activate_model("nope")
    assert r["error"].startswith("unknown model: nope")


def test_ui_refreshes_list_after_failed_load():
    js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    i = js.index('$("#activate").onclick')
    assert "refreshModels().then(() => renderModelsList())" in js[i : i + 4000]
