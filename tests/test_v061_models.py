"""0.6.1 model fixes (items 16-20)."""
import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "ui/app.js"
CTL = ROOT / "overlay/usr/local/bin/stickllm-control"
CATALOG = ROOT / "config/models/catalog.toml"


def _js_presets(expr: str):
    if not shutil.which("node"):
        pytest.skip("node missing")
    s = APP.read_text()
    a = s.index("const KV_MUL")
    b = s.index("function preloadFit")
    b = s.index("\n}\n", b) + 3
    code = ("let HW = {vram: 48, vramEach: 24, backend: 'cuda'};\n"
            "function hardwarePool(){return HW;}\n"
            "function modelGb(m){return m.gb;}\n"
            "const TUNE_PRESETS = {};\nconst document = {querySelector(){return null;}};\n"
            + s[a:b] + f"\nconsole.log(JSON.stringify({expr}));")
    out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_presets_big_gpu_long64k_balanced32k():
    d = _js_presets("dynamicPresets({gb: 8, ctx_max: 131072}, 48)")
    assert d["long"]["ctx"] == 65536 and d["balanced"]["ctx"] == 32768


def test_presets_scale_down_on_small_gpu():
    d = _js_presets("dynamicPresets({gb: 9, ctx_max: 131072}, 12)")
    assert d["long"]["ctx"] < 65536 and d["balanced"]["ctx"] <= 32768
    assert d["long"]["ctx"] >= 2048


def test_preload_fit_offers_kv_or_smaller_ctx():
    ok = _js_presets("preloadFit({gb: 8}, 8192, 'f16', 48)")
    assert ok["ok"] is True
    r = _js_presets("preloadFit({gb: 17}, 131072, 'f16', 48)")
    assert r["ok"] is False and (r["kv"] in ("q8", "q4"))
    r2 = _js_presets("preloadFit({gb: 40}, 131072, 'f16', 48)")
    assert r2["ok"] is False and r2["ctx"] < 131072


def _ctl(monkeypatch):
    monkeypatch.setenv("STICKLLM_CATALOG", str(CATALOG))
    loader = importlib.machinery.SourceFileLoader("stickllm_control_v061m", str(CTL))
    spec = importlib.util.spec_from_loader("stickllm_control_v061m", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_place_cards_one_if_fits_else_split(monkeypatch):
    ctl = _ctl(monkeypatch)
    monkeypatch.setattr(ctl, "_model_env_kv", lambda: {})
    cards = [{"index": 0, "free_mib": 24000, "total_mib": 24576},
             {"index": 1, "free_mib": 24000, "total_mib": 24576}]
    gib = 1024 ** 3
    assert len(ctl.place_cards(cards, 10 * gib)) == 1
    assert len(ctl.place_cards(cards, 30 * gib)) == 2
    # Within 10% of a card: split rather than risk an OOM.
    assert len(ctl.place_cards(cards, 22 * gib)) == 2


def test_place_cards_pin_does_not_block_split(monkeypatch):
    ctl = _ctl(monkeypatch)
    monkeypatch.setattr(ctl, "_model_env_kv", lambda: {"STICKLLM_GPU_PIN": "1"})
    cards = [{"index": 0, "free_mib": 24000, "total_mib": 24576},
             {"index": 1, "free_mib": 24000, "total_mib": 24576}]
    gib = 1024 ** 3
    one = ctl.place_cards(cards, 8 * gib)
    assert [g["index"] for g in one] == [1]
    both = ctl.place_cards(cards, 40 * gib)
    assert sorted(g["index"] for g in both) == [0, 1] and both[0]["index"] == 1


def test_usb_models_bottom_and_red_label_and_autorefresh():
    s = APP.read_text()
    assert "Slow USB load" in s and "slowUsb(a) - slowUsb(b)" in s
    assert "pill.slowUsb" in (ROOT / "ui/style.css").read_text()
    assert "if (vaultChanged) setTimeout(" in s and "refreshModels().catch" in s
    assert "refreshModels().catch(() => {});  // 0.6.1 (item 20)" in s
