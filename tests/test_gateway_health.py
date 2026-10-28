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
        # Object shape, same as control vault_status: ui/app.js reads .status/.mounted.
        assert doc["vault"] == {"status": "locked", "mounted": False}
        state["open"] = True
        with urllib.request.urlopen(url, timeout=10) as r:
            doc = json.loads(r.read())
        assert doc["vault"] == {"status": "unlocked", "mounted": True}
    finally:
        srv.shutdown()

def test_apps_install_vault_gate_matches_health(tmp_path, monkeypatch):
    """Apps install refuses with vault_locked only while health says locked."""
    import subprocess
    import urllib.error

    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html></html>", encoding="utf-8")
    (ui / "stickllm.json").write_text(json.dumps({"version": "0.5.1"}), encoding="utf-8")
    gw = _load("gw_health_apps", ui, tmp_path)
    gw.AUTH_PATH = tmp_path / "no-auth.json"
    state = {"open": False}
    gw.vault_unlocked = lambda: state["open"]
    addons = gw.addons_lib()
    monkeypatch.setattr(addons, "vault_open", lambda: state["open"])
    monkeypatch.setattr(addons, "is_installed", lambda app_id: False)
    monkeypatch.setattr(addons, "write_status", lambda *a, **k: {})
    started = []

    class Done:
        returncode = 0
        stdout = stderr = ""

    def fake_run(cmd, *a, **k):
        started.append(list(cmd))
        return Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, *a, **k: started.append(list(cmd)))

    class H(gw.Handler):
        def _client_ip(self):
            return "127.0.0.1"

        def _is_loopback(self):
            return True

        def log_message(self, *a):
            pass

    srv = gw.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def install(app_id):
        req = urllib.request.Request(base + "/api/apps/install", data=json.dumps({"id": app_id}).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def health():
        with urllib.request.urlopen(base + "/api/health", timeout=10) as r:
            return json.loads(r.read())["vault"]

    gw.http_json = lambda *a, **k: (_ for _ in ()).throw(OSError("down"))
    gw.uplink_ok = lambda *a, **k: False
    gw.detect_backend = lambda *a, **k: "cpu"
    gw.get_session_mode = lambda *a, **k: "vault"
    gw.connect_info = lambda *a, **k: {}
    gw.llama_load_info = lambda *a, **k: {}
    gw.llama_unit_state = lambda *a, **k: "inactive"
    try:
        assert health()["status"] == "locked"
        status, doc = install("radicale")
        assert status == 423 and doc["error"] == "vault_locked" and not started
        state["open"] = True
        assert health() == {"status": "unlocked", "mounted": True}
        status, doc = install("radicale")
        assert status == 200 and doc.get("error") != "vault_locked"
        assert doc["started"] is True and doc["state"] == "installing"
        assert started and "stickllm-addon-install@radicale.service" in started[0]
    finally:
        srv.shutdown()


def test_ui_reads_both_vault_shapes_and_ignores_key_repeat():
    js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    assert "function vaultIsOpen(v)" in js
    assert 'if (typeof v === "string") return v.toLowerCase() === "unlocked";' in js
    assert "setVaultChrome(vaultIsOpen(j.vault))" in js
    assert "const open = vaultIsOpen(v);" in js
    # Old inline check that broke on a string vault field is gone.
    assert 'String(j.vault.status || "")' not in js
    hot = js.split('if (e.key !== "F9" && e.key !== "F10") return;', 1)[1].split("}, true);", 1)[0]
    assert "if (e.repeat) return;" in hot
    assert hot.index("if (e.repeat) return;") < hot.index("issueSshHotkey()")
