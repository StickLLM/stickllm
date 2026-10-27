"""/api/health reports the release version from stickllm.json and the vault state."""
from __future__ import annotations

import http.server
import importlib.machinery
import importlib.util
import json
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
UI_JSON = ROOT / "overlay" / "opt" / "stickllm" / "ui" / "stickllm.json"


def _load(name: str, ui: Path, tmp_path: Path):
    import os
    os.environ["STICKLLM_UI"] = str(ui)
    os.environ.setdefault("STICKLLM_RUN", str(tmp_path / "run"))
    loader = importlib.machinery.SourceFileLoader(name, str(GATEWAY))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_version_comes_from_stickllm_json(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "stickllm.json").write_text(json.dumps({"version": "9.8.7"}), encoding="utf-8")
    gw = _load("gw_health_ver", ui, tmp_path)
    assert gw.stickllm_version() == "9.8.7"
    (ui / "stickllm.json").write_text("{not json", encoding="utf-8")
    assert gw.stickllm_version() == "unknown"
    (ui / "stickllm.json").write_text(json.dumps({"version": "<script>"}), encoding="utf-8")
    assert gw.stickllm_version() == "unknown"
    # The shipped file is the single source of truth.
    shipped = json.loads(UI_JSON.read_text(encoding="utf-8"))["version"]
    gw.UI_ROOT = UI_JSON.parent
    assert gw.stickllm_version() == shipped


def test_no_hardcoded_health_version():
    text = GATEWAY.read_text(encoding="utf-8")
    assert '"version": "0.3.2"' not in text
    assert '"version": stickllm_version()' in text


def test_health_live_version_and_vault(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html></html>", encoding="utf-8")
    (ui / "stickllm.json").write_text(json.dumps({"version": "0.5.1"}), encoding="utf-8")
    gw = _load("gw_health_live", ui, tmp_path)

    def down(*a, **k):
        raise OSError("down")

    gw.http_json = down
    gw.uplink_ok = lambda *a, **k: False
    gw.detect_backend = lambda *a, **k: "cpu"
    gw.get_session_mode = lambda *a, **k: "ephemeral"
    gw.connect_info = lambda *a, **k: {}
    gw.llama_load_info = lambda *a, **k: {}
    gw.llama_unit_state = lambda *a, **k: "inactive"
    state = {"open": False}
    gw.vault_unlocked = lambda: state["open"]

    class H(gw.Handler):
        def _client_ip(self):
            return "127.0.0.1"

        def _is_loopback(self):
            return True

        def log_message(self, *a):
            pass

    srv = gw.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            doc = json.loads(r.read())
        assert doc["version"] == "0.5.1"
        assert doc["vault"] == "locked"
        state["open"] = True
        with urllib.request.urlopen(url, timeout=10) as r:
            doc = json.loads(r.read())
        assert doc["vault"] == "unlocked"
    finally:
        srv.shutdown()