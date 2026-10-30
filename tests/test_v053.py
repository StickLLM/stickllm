"""v0.5.3: bug list (A1-A6), blocked catalog apps (B) and hash pinning (C)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "overlay/usr/local/lib"
BIN = ROOT / "overlay/usr/local/bin"
MANIFEST = ROOT / "overlay/usr/local/share/stickllm/verified.json"
WARNING = "Not verified by StickLLM: this hasn't been checked and may be unsafe"


def _load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _verify(tmp_path, monkeypatch):
    monkeypatch.setenv("STICKLLM_VERIFIED", str(MANIFEST))
    monkeypatch.setenv("STICKLLM_RUN", str(tmp_path / "run"))
    return _load(LIB / "stickllm_verify.py", "stickllm_verify_t")


# ------------------------------------------------------------------ A: bug list
def test_a1_kiosk_uses_swiftshader_not_disable_gpu():
    kiosk = (BIN / "stickllm-kiosk").read_text()
    assert "--use-gl=angle --use-angle=swiftshader" in kiosk
    kiosk = "\n".join(l for l in kiosk.splitlines() if not l.lstrip().startswith("#"))
    for bad in ("--no-sandbox", "--ignore-certificate-errors", "--disable-web-security", "--test-type",
                "--allow-insecure-localhost"):
        assert bad not in kiosk, bad


def test_a2_office_rename_keeps_internal_ids():
    apps = _load(LIB / "stickllm_apps.py", "apps_t")
    office = next(a for a in apps.CATALOG if a["id"] == "onlyoffice")
    assert office["name"] == "ONLYOFFICE" and office["tile"] == "Office"  # v0.5.4 naming
    html = (ROOT / "ui/index.html").read_text()
    assert 'data-app="onlyoffice"' in html and "Office" in html


def test_a3_one_reused_named_tab_per_app():
    js = (ROOT / "ui/app.js").read_text()
    named = js[js.index("function openNamedTab("):js.index("const AGENT_TAB")]
    assert 'window.open("", target)' in named and "w.opener = null" in named
    assert "showAppInPage" not in js and "stickllm-embed-" not in js
    html = (ROOT / "ui/index.html").read_text()
    listing = html.split('id="appsList"', 1)[1].split('id="settings"', 1)[0]
    assert 'target="_blank"' not in listing and "noopener" not in listing
    gw = _load(BIN / "stickllm-gateway", "gw_v053_coop")
    assert not gw.addon_response_header_ok("Cross-Origin-Opener-Policy", "same-origin")
    assert not gw.addon_response_header_ok("cross-origin-opener-policy-report-only", "same-origin")
    assert gw.addon_response_header_ok("Content-Type", "text/html")


def test_a4_version_name_and_iso():
    assert json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())["version"] == "0.5.5"
    html = (ROOT / "ui/index.html").read_text()
    assert 'id="aboutVer">StickLLM v0.5.5<' in html
    about = html.split('id="aboutVer"', 1)[0][-2000:]
    assert "Agent Zero v" not in about


def test_a5_publisher():
    assert '--iso-publisher "Nink Inc."' in (ROOT / "scripts/lib/docker-build-live.sh").read_text()


def test_a6_bridge_status_codes():
    agent = _load(LIB / "stickllm_agent.py", "agent_v053")
    assert agent.bridge_status({"ok": True}) == 200
    assert agent.bridge_status({"ok": False, "error": "bad_id"}) == 400
    assert agent.bridge_status({"ok": False, "error": "vault_locked"}) == 423
    assert agent.bridge_status({"ok": False, "error": "unverified"}) == 428
    r = {"ok": False, "error": "x", "_http_status": 503}
    assert agent.bridge_status(r) == 503 and "_http_status" not in r
    assert agent.bridge_status({"ok": False, "error": "something"}) == 409


def test_a6_entrypoint_mutes_tunnel_api_on_both_paths():
    src = (BIN / "stickllm-agent-entrypoint").read_text()
    assert '"run_tunnel_api"' in src and "/per/" in src and "eventlistener" in src


def test_a6_print_blob_is_quiet():
    vault = (BIN / "stickllm-vault").read_text()
    assert 'print-blob 2>/dev/null)" || rc=$?' in vault


# ------------------------------------------------------------------ B: catalog
def test_b_unworkable_apps_are_blocked_with_reasons():
    apps = _load(LIB / "stickllm_apps.py", "apps_t2")
    blocked = json.loads(MANIFEST.read_text(encoding="utf-8"))["blocked_apps"]
    for app_id in ("paperless-ngx", "snappymail", "immich", "searxng", "matrix", "simplex", "jitsi",
                   "onionshare", "postiz", "opentimestamps", "code-server-jupyter", "n8n"):
        assert len(blocked.get(app_id, "")) > 20, app_id
        assert apps.is_blocked(app_id)
    doc = apps.catalog_document()
    listed = {r["id"] for r in doc.get("apps", [])}
    assert not listed & set(blocked)
    assert "hidden" not in doc
    html = (ROOT / "ui/index.html").read_text()
    for app_id in blocked:
        assert f'data-app="{app_id}"' not in html
    text = (ROOT / "docs/APPS.md").read_text()
    assert "Blocked in v0.5.3" in text and all(f"`{i}`" in text for i in blocked)
    assert "comfyui" not in blocked and not apps.is_blocked("comfyui")  # v0.5.4 ships ComfyUI


# ------------------------------------------------------------------ C: pins
def test_c_pins_verify_passes():
    out = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/pins.py"), "verify"],
                         capture_output=True, text=True, timeout=60, cwd=ROOT)
    assert out.returncode == 0, out.stdout + out.stderr


def test_c_manifest_covers_apps_plugins_models():
    doc = json.loads(MANIFEST.read_text())
    for key in ("onlyoffice", "tasks-md", "paisa", "trilium", "node-red", "comfyui", "agent-zero"):
        pin = doc["apps"][key]
        assert pin["manifest_digest"].startswith("sha256:") and pin["amd64_digest"].startswith("sha256:")
    assert doc["plugins"] == {}  # v0.5.4: no third-party Agent Zero plugins
    assert doc["models"] and all(len(s) == 64 for s in doc["models"].values())


def test_c_app_status_verified_changed_unverified(tmp_path, monkeypatch):
    v = _verify(tmp_path, monkeypatch)
    pin = v.load_manifest()["apps"]["trilium"]
    same = v.app_status("trilium", check_upstream=True, fetch=lambda i, t: pin["manifest_digest"])
    assert same["status"] == "verified" and same["confirm_required"] is False
    (tmp_path / "run" / "upstream-digests.json").unlink()
    moved = v.app_status("trilium", check_upstream=True, fetch=lambda i, t: "sha256:" + "1" * 64)
    assert moved["status"] == "changed" and moved["offer"] == "verified_version"
    assert "blocked" in moved["message"]
    # Cached: the Apps page (no upstream call) shows the same answer.
    assert v.app_status("trilium")["status"] == "changed"
    # Offline: the pinned digest is still what gets pulled, so verified.
    (tmp_path / "run" / "upstream-digests.json").unlink()
    assert v.app_status("trilium", check_upstream=True, fetch=lambda i, t: None)["status"] == "verified"
    un = v.app_status("not-on-the-list")
    assert un["status"] == "unverified" and un["confirm_required"] and WARNING in un["message"]
    assert v.UNVERIFIED_WARNING == WARNING
    assert v.app_status("docs")["id"] == "docs" and v.app_pin("docs") == v.app_pin("onlyoffice")


def test_c_plugin_and_model_status(tmp_path, monkeypatch):
    v = _verify(tmp_path, monkeypatch)
    doc = v.load_manifest()
    assert doc["plugins"] == {}
    assert v.plugin_status("clock_24h")["status"] != "verified"  # removed in v0.5.4
    assert v.plugin_status("someone-elses-plugin")["status"] == "unverified"
    key, sha = next(iter(doc["models"].items()))
    repo, file = "/".join(key.split("/")[:2]), "/".join(key.split("/")[2:])
    assert v.model_status(repo, file, sha)["status"] == "verified"
    assert v.model_status(repo, file, "f" * 64)["status"] == "blocked"
    assert v.model_status("x/y", "z.gguf", "a" * 64)["status"] == "unverified"
    s = v.summary()
    assert s["apps"] and not s["plugins"] and s["warning"] == WARNING


def _gateway_server(tmp_path, monkeypatch, upstream):
    import threading
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html></html>", encoding="utf-8")
    (ui / "stickllm.json").write_text(json.dumps({"version": "0.5.3"}), encoding="utf-8")
    monkeypatch.setenv("STICKLLM_UI", str(ui))
    monkeypatch.setenv("STICKLLM_RUN", str(tmp_path / "run"))
    monkeypatch.setenv("STICKLLM_VERIFIED", str(MANIFEST))
    gw = _load(BIN / "stickllm-gateway", "gw_v053_gate")
    gw.AUTH_PATH = tmp_path / "no-auth.json"
    gw.vault_unlocked = lambda: True
    gw.vault_configured = lambda: True
    monkeypatch.setattr(gw.verify_lib(), "registry_digest", lambda *a, **k: upstream)
    addons = gw.addons_lib()
    monkeypatch.setattr(addons, "vault_open", lambda: True)
    monkeypatch.setattr(addons, "is_installed", lambda app_id: False)
    monkeypatch.setattr(addons, "write_status", lambda *a, **k: {})
    started = []

    class Done:
        returncode = 0
        stdout = stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda cmd, *a, **k: started.append(list(cmd)) or Done())
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
    return gw, srv, started


def _post(srv, path, body):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", data=json.dumps(body).encode(),
                                 method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def _get(srv, path):
    import urllib.request
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.server_address[1]}{path}", timeout=10) as r:
        return json.loads(r.read())


def test_c_gateway_blocks_changed_upstream_until_verified_version(tmp_path, monkeypatch):
    gw, srv, started = _gateway_server(tmp_path, monkeypatch, "sha256:" + "2" * 64)
    try:
        status, doc = _post(srv, "/api/apps/install", {"id": "trilium"})
        assert status == 409 and doc["error"] == "blocked" and doc["verification"]["status"] == "changed"
        assert not started
        status, doc = _post(srv, "/api/apps/install", {"id": "trilium", "verified_version": True})
        assert status == 200 and started
        cat = _get(srv, "/api/apps")
        row = next(r for r in cat["apps"] if r["id"] == "trilium")
        assert row["verification"]["status"] == "changed"
        assert cat["unverified_warning"] == WARNING
        ver = _get(srv, "/api/verified")
        assert ver["warning"] == WARNING and not ver["plugins"]
    finally:
        srv.shutdown()


def test_c_gateway_unverified_needs_confirm(tmp_path, monkeypatch):
    doc = json.loads(MANIFEST.read_text())
    del doc["apps"]["paisa"]
    alt = tmp_path / "verified.json"
    alt.write_text(json.dumps(doc))
    gw, srv, started = _gateway_server(tmp_path, monkeypatch, None)
    monkeypatch.setattr(gw.verify_lib(), "MANIFEST", alt)
    try:
        status, body = _post(srv, "/api/apps/install", {"id": "paisa"})
        assert status == 428 and body["error"] == "unverified" and WARNING in body["message"]
        assert not started
        status, body = _post(srv, "/api/apps/install", {"id": "paisa", "accept_unverified": True})
        assert status == 200 and started
        # Pinned and offline: installs at once (the pinned digest is pulled).
        started.clear()
        status, body = _post(srv, "/api/apps/install", {"id": "node-red"})
        assert status == 200 and started
    finally:
        srv.shutdown()


def test_c_control_model_download_gate(tmp_path, monkeypatch):
    ctl = _load(BIN / "stickllm-control", "ctl_v053")
    pinned = "c" * 64
    monkeypatch.setattr(ctl, "parse_catalog", lambda: [
        {"id": "m", "hf_repo": "org/model", "hf_files": ["m.gguf"], "sha256": [pinned], "approx_size_gb": 1}])
    monkeypatch.setattr(ctl, "get_preferred_models_dir", lambda: tmp_path)
    base = {"repo": "org/model", "file": "m.gguf", "bytes": 10}
    ok = ctl._build_download_job(dict(base))
    assert ok["ok"] and ok["verified"] is True and ok["sha256"] == pinned
    bad = ctl._build_download_job(dict(base, sha256="d" * 64))
    assert bad["error"] == "blocked"
    other = {"repo": "someone/else", "file": "x.gguf", "bytes": 10, "sha256": "e" * 64}
    gate = ctl._build_download_job(dict(other))
    assert gate["error"] == "unverified" and WARNING in gate["message"]
    yes = ctl._build_download_job(dict(other, accept_unverified=True))
    assert yes["ok"] and yes["verified"] is False and yes["sha256"] == "e" * 64


def test_c_ui_badges_and_confirms():
    js = (ROOT / "ui/app.js").read_text()
    assert f'"{WARNING}"' in js
    for needle in ("function paintVerifyBadge", "function verifyGate", "Install verified version",
                   "accept_unverified: true", "verified_version: true",
                   "Download anyway"):
        assert needle in js, needle
    gate = js[js.index("function verifyGate"):]
    gate = gate[:gate.index("\n}\n")]
    assert "confirmBox" in gate and "confirm(" not in gate.replace("confirmBox(", "")
    css = (ROOT / "ui/style.css").read_text()
    assert ".vbadge" in css and ".pill.bad" in css


def test_c_agent_zero_is_told_and_cannot_bypass():
    agent = _load(LIB / "stickllm_agent.py", "agent_v053b")
    prompt = agent.install_app_tool_prompt()
    assert "hash pinned" in prompt and "never try to get around the warning" in prompt
    gw = (BIN / "stickllm-gateway").read_text()
    req = gw[gw.index("def _agent_install_request"):]
    req = req[:req.index("\n    def ", 10)]
    assert "verification" in req and "accept_unverified" not in req and "verified_version" not in req


def test_c_docs():
    text = (ROOT / "docs/VERIFIED.md").read_text()
    assert WARNING in text and "pins.py upstream" in text and "pins.py manifest" in text


def test_a3_isolated_apps_keep_shared_array_buffer():
    # Actual Budget needs crossOriginIsolated; dropping COOP alone broke it.
    gw = _load(BIN / "stickllm-gateway", "gw_v053_dip")
    actual = [("Cross-Origin-Opener-Policy", "same-origin"), ("Cross-Origin-Embedder-Policy", "require-corp"), ("Content-Type", "text/html")]
    chrome = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
    got = dict((k.lower(), v) for k, v in gw.addon_response_headers(actual, chrome))
    assert got.get("document-isolation-policy") == "isolate-and-require-corp"
    assert "cross-origin-opener-policy" not in got and "cross-origin-embedder-policy" not in got
    firefox = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"
    got = dict((k.lower(), v) for k, v in gw.addon_response_headers(actual, firefox))
    assert got.get("cross-origin-opener-policy") == "same-origin" and "document-isolation-policy" not in got
    plain = [("Cross-Origin-Opener-Policy", "same-origin"), ("Content-Type", "text/html")]
    got = dict((k.lower(), v) for k, v in gw.addon_response_headers(plain, firefox))
    assert "cross-origin-opener-policy" not in got


def test_a3_kiosk_opens_addons_through_gateway_relay():
    # The console browser must get the same header handling as LAN (tab reuse).
    import importlib.util
    spec = importlib.util.spec_from_file_location("addons_v053_kiosk", ROOT / "overlay/usr/local/lib/stickllm_addons.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    ports = set()
    for app_id in mod.ORDER:
        app = mod.APPS[app_id]
        assert app["kiosk_port"] not in (app["local_port"], app["tls_port"])
        ports.add(app["kiosk_port"])
    assert len(ports) == len(mod.ORDER)
    src = (BIN / "stickllm-gateway").read_text()
    assert '_ReuseHTTPServer(("127.0.0.1", port), Handler)' in src
    assert "spec.get('kiosk_port') or spec['local_port']" in src
    assert "    start_addon_kiosk_servers()\n" in src