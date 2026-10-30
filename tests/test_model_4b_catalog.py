"""Baked app-agent Qwen3.5-4B is a first-class catalog row in the Models page."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-control"
CATALOG = ROOT / "config" / "models" / "catalog.toml"
BUILD = ROOT / "scripts" / "lib" / "docker-build-live.sh"
PROBE = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-model-probe"
FILE = "Qwen3.5-4B-Q4_K_M.gguf"
HF_ID = "hf:unsloth__Qwen3.5-4B-GGUF:" + FILE


def _load(monkeypatch):
    monkeypatch.setenv("STICKLLM_CATALOG", str(CATALOG))
    loader = importlib.machinery.SourceFileLoader("stickllm_control_4b", str(CTL))
    spec = importlib.util.spec_from_loader("stickllm_control_4b", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _stub(ctl, monkeypatch, tmp_path, active: str = "", healthy: bool = False):
    baked = tmp_path / "opt" / "appagent" / FILE
    baked.parent.mkdir(parents=True)
    baked.write_bytes(b"GGUF" + b"\0" * 16)
    monkeypatch.setattr(ctl, "BAKED_4B", baked)
    monkeypatch.setattr(ctl, "BAKED_3B", tmp_path / "missing-3b.gguf")
    monkeypatch.setattr(ctl, "BAKED_7B", tmp_path / "missing-7b.gguf")
    monkeypatch.setattr(ctl, "find_file", lambda name: baked if name == FILE else None)
    monkeypatch.setattr(ctl, "gguf_weight_bytes", lambda p: int(2.6 * 1024**3))
    monkeypatch.setattr(ctl, "discover_local_ggufs", lambda: [])
    monkeypatch.setattr(ctl, "detect_vram_gb", lambda: 0.0)
    monkeypatch.setattr(ctl, "detect_ram_gb", lambda: 16.0)
    monkeypatch.setattr(ctl, "has_nvidia", lambda: False)
    monkeypatch.setattr(ctl, "active_model_path", lambda: active)
    monkeypatch.setattr(ctl, "llama_health_ok", lambda: (healthy, "ok" if healthy else "down"))
    monkeypatch.setattr(ctl, "active_ctx_size", lambda: None)
    monkeypatch.setattr(ctl, "read_gguf_meta", lambda p: {})
    monkeypatch.setattr(ctl, "find_mmproj", lambda p: "")
    return baked


def test_catalog_entry_pins_baked_hash(monkeypatch):
    ctl = _load(monkeypatch)
    rows = {m["id"]: m for m in ctl.parse_catalog()}
    m = rows["qwen35-4b-q4km"]
    assert m["hf_repo"] == "unsloth/Qwen3.5-4B-GGUF" and m["hf_files"] == [FILE]
    sha = re.search(r'AA_SHA="([0-9a-f]{64})"', BUILD.read_text()).group(1)
    assert m["sha256"] == [sha], "catalog hash must match the baked app-agent file"
    assert 2.0 <= m["approx_size_gb"] <= 3.5 and 4 <= m["min_vram_gb"] <= 6
    # 3B stays default/recommended; 4B never outranks it.
    assert "qwen25-3b-q4km" in rows
    assert m["quality_rank"] < rows["qwen25-3b-q4km"]["quality_rank"]
    text = CATALOG.read_text()
    assert 'base_model_id = "qwen25-3b-q4km"' in text
    assert "qwen35-4b-q4km" not in text.split("[[model]]")[0], "not in any tier"
    # Multi-line sha arrays parse too (7B has two).
    assert len(rows["qwen25-7b-q5km"]["sha256"]) == 2


def test_probe_never_recommends_4b(tmp_path):
    """Run the probe's embedded selection: 3B (not 4B) wins at 5-7 GB VRAM."""
    src = PROBE.read_text()
    py = src.split("<<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    script = tmp_path / "sel.py"
    script.write_text(py)
    for vram in ("0", "6", "7"):
        out = tmp_path / f"p{vram}.json"
        r = subprocess.run(
            ["python3", str(script), str(CATALOG), vram, "50", "/x", str(out)],
            capture_output=True, text=True, check=True,
        )
        assert '"recommend_id": "qwen25-3b-q4km"' in out.read_text(), r.stdout


def test_baked_4b_installed_protected_and_running(monkeypatch, tmp_path):
    ctl = _load(monkeypatch)
    baked = _stub(ctl, monkeypatch, tmp_path, active="", healthy=False)
    m = next(x for x in ctl.enrich_models() if x["id"] == "qwen35-4b-q4km")
    assert m["installed"] and m["runnable"] and m["path"] == str(baked)
    assert m["deletable"] is False and not m["running"]
    ctl2 = _load(monkeypatch)
    baked2 = _stub(ctl2, monkeypatch, tmp_path / "b", active=str(tmp_path / "b" / "opt" / "appagent" / FILE), healthy=True)
    rows = ctl2.enrich_models()
    m = next(x for x in rows if x["id"] == "qwen35-4b-q4km")
    assert m["active"] and m["running"] and m["path"] == str(baked2)
    assert sum(1 for x in rows if x.get("running")) == 1


def test_delete_blocked(monkeypatch, tmp_path):
    ctl = _load(monkeypatch)
    _stub(ctl, monkeypatch, tmp_path)
    r = ctl.delete_model("qwen35-4b-q4km")
    assert r["ok"] is False


def test_hf_id_load_reuses_catalog_row(monkeypatch, tmp_path):
    ctl = _load(monkeypatch)
    baked = _stub(ctl, monkeypatch, tmp_path)
    row = ctl._hf_local_row(HF_ID)
    assert row["local_path"] == str(baked)
    models = ctl.enrich_models()
    hit = next(x for x in models if x.get("installed") and x.get("path") == row["local_path"])
    assert hit["id"] == "qwen35-4b-q4km"


def test_active_unknown_file_gets_running_row(monkeypatch, tmp_path):
    ctl = _load(monkeypatch)
    _stub(ctl, monkeypatch, tmp_path)
    other = tmp_path / "opt" / "extra" / "Some-Model-Q4_K_M.gguf"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"GGUF" + b"\0" * 16)
    monkeypatch.setattr(ctl, "active_model_path", lambda: str(other))
    monkeypatch.setattr(ctl, "llama_health_ok", lambda: (True, "ok"))
    rows = ctl.enrich_models()
    run = [x for x in rows if x.get("running")]
    assert len(run) == 1 and run[0]["path"] == str(other) and run[0]["installed"]


def test_hf_search_maps_to_catalog_row(monkeypatch, tmp_path):
    ctl = _load(monkeypatch)
    baked = _stub(ctl, monkeypatch, tmp_path)
    monkeypatch.setattr(ctl, "model_dirs", lambda: [baked.parent])
    monkeypatch.setattr(ctl, "gguf_index", lambda roots=None: {baked.parent: [baked]})
    listing = [{"id": "unsloth/Qwen3.5-4B-GGUF", "downloads": 10},
               {"id": "lmstudio-community/Qwen3.5-4B-GGUF", "downloads": 5},
               {"id": "other/Qwen3.5-9B-GGUF", "downloads": 99}]
    trees = {
        "unsloth/Qwen3.5-4B-GGUF": [{"type": "file", "path": FILE, "size": 2_700_000_000}],
        "lmstudio-community/Qwen3.5-4B-GGUF": [{"type": "file", "path": FILE, "size": 2_700_000_000}],
        "other/Qwen3.5-9B-GGUF": [{"type": "file", "path": "Qwen3.5-9B-Q4_K_M.gguf", "size": 5_000_000_000}],
    }

    def fake(url, timeout=12):
        if "/tree/main" in url:
            for repo, t in trees.items():
                if repo in url:
                    return t
            return []
        return listing

    monkeypatch.setattr(ctl, "_hf_get_json", fake)
    res = ctl.hf_search("Qwen3.5")
    ids = [m["id"] for m in res["models"]]
    assert ids.count("qwen35-4b-q4km") == 1, ids
    hit = next(m for m in res["models"] if m["id"] == "qwen35-4b-q4km")
    assert hit["installed"] and hit["verified"] and hit["hf_id"].startswith("hf:unsloth__")
    assert not any(i.startswith("hf:") and FILE in i for i in ids)


def _js():
    return (ROOT / "ui" / "app.js").read_text(encoding="utf-8")


def test_ui_search_installed_first_and_merges_catalog():
    js = _js()
    i = js.index("function renderModelsList")
    body = js[i : js.index("function syncModelActions")]
    assert "const have = (m) => (searching ? Number(!m.installed) : 0);" in body
    assert "if (have(a) !== have(b)) return have(a) - have(b);" in body
    assert "return searchRows();" in js and "function searchRows()" in js


def test_ui_search_sort_behaviour(tmp_path):
    """Run the merge + sort logic in node with a tiny harness."""
    js = _js()
    a = js.index("function searchRows()")
    b = js.index("function browseSource()")
    harness = (
        "let hfHits=[{id:'x',name:'Qwen3.5-9B',installed:false},{id:'qwen35-4b-q4km',hf_id:'hf:u:f',catalog_id:'qwen35-4b-q4km',installed:true,sha256:'ab'}];"
        "let lastCatalog=[{id:'qwen35-4b-q4km',name:'Qwen3.5-4B Q4_K_M',installed:true,running:true,deletable:false,sha256:['ab']}];"
        + js[a:b]
        + "const r=searchRows();const searching=true;const have=(m)=>(searching?Number(!m.installed):0);"
        "r.sort((p,q)=>have(p)-have(q));"
        "if(r[0].id!=='qwen35-4b-q4km'||!r[0].running||r[0].deletable!==false||r[0].sha256!=='ab'||r.length!==2)throw new Error(JSON.stringify(r));"
    )
    f = tmp_path / "h.js"
    f.write_text(harness)
    subprocess.run(["node", str(f)], check=True)


def test_probe_survives_nvidia_smi_without_gpu(tmp_path):
    """nvidia-smi installed but no driver/GPU exits 9; pipefail used to kill the probe (UI showed "Recommended —")."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "nvidia-smi").write_text("#!/bin/sh\nexit 9\n")
    (fake / "nvidia-smi").chmod(0o755)
    import os
    env = {**os.environ, "PATH": f"{fake}:{os.environ['PATH']}", "STICKLLM_CATALOG": str(CATALOG),
           "STICKLLM_RUN": str(tmp_path / "run"), "STICKLLM_DATA_MNT": str(tmp_path / "nomnt")}
    r = subprocess.run(["bash", str(PROBE)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    import json
    doc = json.loads((tmp_path / "run" / "model-probe.json").read_text())
    assert doc["recommend_id"] == "qwen25-3b-q4km"
