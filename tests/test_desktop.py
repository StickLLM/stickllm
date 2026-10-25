"""Desktop starters, file-root bounds, and unpaired app routes."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "ui" / "index.html"
FILES = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_files.py"
SYSTEM = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_system.py"
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
APPS = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_apps.py"
UNIT = ROOT / "overlay" / "etc" / "systemd" / "system" / "stickllm-files.service"

STARTERS = ("files", "notepad", "minesweeper", "solitaire", "calculator", "media", "monitor")


def _load(path: Path, name: str, env: dict | None = None):
    if env:
        os.environ.update(env)
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_desktop_icons_are_the_starters_only():
    html = HTML.read_text(encoding="utf-8")
    desk = html.split('id="deskIcons"', 1)[1].split('id="appsMenu"', 1)[0]
    menu = html.split('id="appsMenu"', 1)[1].split('id="appsDetail"', 1)[0]
    found = [part.split('"', 1)[0] for part in desk.split('data-starter="')[1:]]
    assert found == list(STARTERS)
    assert "Agent Zero" not in desk
    assert "onlyoffice" not in desk
    assert "comfyui" not in desk
    assert 'target="_blank"' in desk
    for starter in STARTERS:
        assert f'href="/apps/{starter}/"' in desk
    assert "data-starter" not in menu
    assert "Agent Zero" not in menu
    for starter in STARTERS:
        assert f'data-app="{starter}"' not in menu
    assert "Not installed" in menu
    assert "Not available yet" in menu
    apps = _load(APPS, "stickllm_apps_desktop")
    catalog_ids = {app["id"] for app in apps.CATALOG}
    assert catalog_ids.isdisjoint(STARTERS)
    assert "agent-zero" not in catalog_ids
    assert all(app["installer"] is None for app in apps.CATALOG)


def test_games_are_original_and_offline():
    for name in ("minesweeper", "solitaire"):
        folder = ROOT / "ui" / "apps" / name
        page = (folder / "index.html").read_text(encoding="utf-8")
        license_text = (folder / "LICENSE").read_text(encoding="utf-8")
        assert "MIT License" in license_text
        assert "original StickLLM program" in license_text
        assert "http://" not in page
        assert "https://" not in page
        for path in folder.iterdir():
            if path.suffix.lower() not in {".html", ".js"}:
                continue
            text = path.read_text(encoding="utf-8")
            assert "http://" not in text
            assert "https://" not in text
    helper = (ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-files").read_text(encoding="utf-8")
    unit = UNIT.read_text(encoding="utf-8")
    assert 'HOST = "127.0.0.1"' in helper
    assert "must bind 127.0.0.1" in helper
    assert "must not run as root" in helper
    assert "User=stickllm" in unit
    assert "0.0.0.0" not in unit


def test_file_api_rejects_a_path_outside_the_three_roots(tmp_path, monkeypatch):
    home = tmp_path / "home"
    vault = tmp_path / "vault"
    host = tmp_path / "host"
    models = host / "disk" / "models"
    apps = host / "disk" / "apps"
    home.mkdir()
    vault.mkdir()
    models.mkdir(parents=True)
    secret = tmp_path / "secret.txt"
    secret.write_text("secret", encoding="utf-8")
    (home / "note.txt").write_text("hello", encoding="utf-8")
    mounts = tmp_path / "mounts"
    mounts.write_text(f"ext4 {vault} ext4 rw 0 0\next4 {host} ext4 rw 0 0\n", encoding="utf-8")
    models_file = tmp_path / "models-dir.json"
    models_file.write_text(json.dumps({"path": str(models)}), encoding="utf-8")
    monkeypatch.setenv("STICKLLM_HOME", str(home))
    monkeypatch.setenv("STICKLLM_VAULT_MNT", str(vault))
    monkeypatch.setenv("STICKLLM_HOST_MNT", str(host))
    monkeypatch.setenv("STICKLLM_MOUNTS_FILE", str(mounts))
    monkeypatch.setenv("STICKLLM_MODELS_DIR_FILE", str(models_file))
    monkeypatch.delenv("STICKLLM_SSD_APPS", raising=False)
    monkeypatch.delenv("STICKLLM_MODELS_DIR", raising=False)
    files = _load(FILES, "stickllm_files_bounds")
    mounts_text = mounts.read_text(encoding="utf-8")
    doc = files.roots_document(mounts_text)
    available = {row["id"]: row["available"] for row in doc["roots"]}
    assert available == {"home": True, "vault": True, "ssd": True}
    assert files.ssd_apps_dir(mounts_text) == apps
    assert files.list_dir("ssd", "", mounts_text)["exists"] is False
    assert not apps.exists()
    files.write_text("home", "saved.txt", "hi", mounts_text)
    assert (home / "saved.txt").read_text(encoding="utf-8") == "hi"

    for rel in ("../secret.txt", "../../secret.txt", "/etc/passwd", str(secret), "note/../../secret.txt"):
        try:
            files.read_file("home", rel, mounts_text)
        except files.FilesError as exc:
            assert exc.code == "bad_path"
        else:
            raise AssertionError(rel)
        assert secret.read_text(encoding="utf-8") == "secret"

    try:
        files.write_text("home", "../secret.txt", "nope", mounts_text)
    except files.FilesError:
        pass
    else:
        raise AssertionError("write escaped")
    assert secret.read_text(encoding="utf-8") == "secret"

    try:
        files.write_bytes("home", "../secret.txt", b"nope", mounts_text)
    except files.FilesError:
        pass
    else:
        raise AssertionError("upload escaped")
    assert secret.read_text(encoding="utf-8") == "secret"

    try:
        files.write_text("ssd", "note.txt", "nope", mounts_text)
    except files.FilesError as exc:
        assert exc.code == "bad_root"
    else:
        raise AssertionError("notepad wrote to the SSD")

    locked = files.roots_document("")
    assert {row["id"]: row["available"] for row in locked["roots"]}["vault"] is False
    assert {row["id"]: row["available"] for row in locked["roots"]}["ssd"] is False
    try:
        files.list_dir("vault", "", "")
    except files.FilesError as exc:
        assert exc.code == "root_absent"
    else:
        raise AssertionError("locked vault was opened")

    try:
        link = home / "out"
        link.symlink_to(secret)
    except OSError:
        return
    try:
        files.read_file("home", "out", mounts_text)
    except files.FilesError as exc:
        assert exc.code in {"bad_path", "not_found"}
    else:
        raise AssertionError("symlink was followed")
    assert secret.read_text(encoding="utf-8") == "secret"


def test_gpu_stats_are_absent_without_nvidia_smi():
    system = _load(SYSTEM, "stickllm_system_desktop")
    system._LAST_CPU = None

    class Missing:
        def __call__(self, argv):
            raise FileNotFoundError(argv[0])

    missing = system.gpu_block(Missing())
    assert missing["available"] is False
    assert "unavailable" in missing["message"].lower()
    assert "memory_used_mib" not in json.dumps(missing)

    class Failed:
        returncode = 1
        stdout = ""

        def __call__(self, argv):
            return self

    failed = system.gpu_block(Failed())
    assert failed["available"] is False
    assert "memory_used_mib" not in json.dumps(failed)

    class Ok:
        returncode = 0
        stdout = "RTX 3090, 1024, 24576, 42\n"

        def __call__(self, argv):
            return self

    found = system.gpu_block(Ok())
    assert found["available"] is True
    assert found["gpus"][0]["memory_used_mib"] == 1024
    assert found["gpus"][0]["temperature_c"] == 42

    first = system.cpu_block("cpu  10 0 0 10 0 0 0 0\n", "0.10 0.20 0.30 1/2 1\n")
    assert first["available"] is True
    assert first["percent"] is None
    second = system.cpu_block("cpu  20 0 0 10 0 0 0 0\n", "0.10 0.20 0.30 1/2 1\n")
    assert second["percent"] == 100.0
    empty = system.memory_block("")
    assert empty["available"] is False


def test_starter_pages_are_external_scripts(tmp_path):
    """Inline scripts never run: the gateway CSP is script-src 'self'."""
    ui = ROOT / "ui"
    run = tmp_path / "run"
    run.mkdir()
    env = {
        "STICKLLM_UI": str(ui),
        "STICKLLM_RUN": str(run),
        "STICKLLM_VAULT_MNT": str(tmp_path / "vault"),
        "STICKLLM_FILES_PORT": "9",
    }
    saved = {key: os.environ.get(key) for key in env}
    gateway = _load(GATEWAY, "stickllm_gateway_starters", env)
    httpd = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        app_js = (ui / "app.js").read_text(encoding="utf-8")
        assert "menu.contains(ev.target)" in app_js
        assert 'else if ($("#appsMenu") && !$("#appsMenu").hidden) toggleAppsMenu(false);' in app_js
        for name, src in (
            ("files", "files.js"),
            ("notepad", "notepad.js"),
            ("minesweeper", "game.js"),
            ("solitaire", "game.js"),
            ("calculator", "calc.js"),
            ("media", "media.js"),
            ("monitor", "monitor.js"),
        ):
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/apps/{name}/", timeout=5) as resp:
                body = resp.read().decode("utf-8")
                csp = resp.headers["Content-Security-Policy"]
                script_src = [part for part in csp.split(";") if "script-src" in part]
                assert script_src and "unsafe-inline" not in script_src[0]
                assert f'src="{src}' in body
                assert "<script>" not in body.lower()
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/apps/{name}/{src}", timeout=5) as resp:
                script = resp.read().decode("utf-8")
                assert resp.status == 200
                assert "javascript" in resp.headers["Content-Type"]
                assert len(script) > 200
    finally:
        httpd.shutdown()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_unpaired_app_routes_are_401(tmp_path):
    ui = tmp_path / "ui"
    page = ui / "apps" / "notepad"
    page.mkdir(parents=True)
    (page / "index.html").write_text("<!DOCTYPE html><title>Notepad</title>", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    token = "paired-token"
    (run / "auth.json").write_text(
        json.dumps(
            {
                "require_pair": True,
                "paired": True,
                "token_hash": __import__("hashlib").sha256(token.encode()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    env = {
        "STICKLLM_UI": str(ui),
        "STICKLLM_RUN": str(run),
        "STICKLLM_VAULT_MNT": str(tmp_path / "vault"),
        "STICKLLM_FILES_PORT": "9",
    }
    saved = {key: os.environ.get(key) for key in env}
    gateway = _load(GATEWAY, "stickllm_gateway_desktop", env)

    class LanHandler(gateway.Handler):
        def _is_loopback(self) -> bool:
            return False

    httpd = gateway.ThreadingHTTPServer(("127.0.0.1", 0), LanHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        for path in ("/apps/notepad/", "/api/files/roots", "/api/system"):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode()
                assert exc.code == 401, path
                assert "pair_required" in body
            else:
                raise AssertionError(path)

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/apps/notepad/",
            headers={"Cookie": f"stickllm_pair={token}"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            assert resp.status == 200
            assert b"Notepad" in resp.read()
    finally:
        httpd.shutdown()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
