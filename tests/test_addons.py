"""Starter add-ons (Tasks.md, Paisa, Trilium, Node-RED, ComfyUI).

Same rules as ONLYOFFICE Docs: pinned by digest, data only in
vault/addons/<id>, read-only non-root containers with no logs, no GPU, no
network, reached only through the paired gateway on the app's own TLS port.
ComfyUI is the one add-on that may get NVIDIA device nodes.
"""
from __future__ import annotations

import http.server
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay" / "usr" / "local" / "bin"
LIB = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_addons.py"
SHARE = ROOT / "overlay" / "usr" / "local" / "share" / "stickllm" / "addons"
GATEWAY = BIN / "stickllm-gateway"
SCRIPT = BIN / "stickllm-addon"
VAULT_SCRIPT = BIN / "stickllm-vault"
UNITS = ROOT / "overlay" / "etc" / "systemd" / "system"
BUILD = ROOT / "scripts" / "lib" / "docker-build-live.sh"
HOOK = ROOT / "live-build" / "hooks" / "normal" / "0100-stickllm-setup.hook.chroot"
HTML = ROOT / "ui" / "index.html"
APP_JS = ROOT / "ui" / "app.js"

IDS = ("tasks-md", "paisa", "trilium", "node-red", "comfyui")
# Apps lib.app() accepts today (ComfyUI stays refused while it is on the blocklist).
OPEN_IDS = ("tasks-md", "paisa", "trilium", "node-red")
POSIX = pytest.mark.skipif(sys.platform == "win32", reason="Linux-only file APIs (symlinks, modes)")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _load(path: Path, name: str, env: dict | None = None):
    if env:
        os.environ.update(env)
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _env(tmp_path: Path, *, vault: bool = True) -> dict:
    v = tmp_path / "vault"
    run = tmp_path / "run"
    for p in (v, run):
        p.mkdir(exist_ok=True)
    (tmp_path / "mounts").write_text((f"/dev/mapper/v {v} ext4 rw 0 0\n" if vault else ""), encoding="utf-8")
    return {
        "STICKLLM_VAULT_MNT": str(v),
        "STICKLLM_RUN": str(run),
        "STICKLLM_MOUNTS_FILE": str(tmp_path / "mounts"),
        "STICKLLM_ADDONS_SHARE": str(SHARE),
        "STICKLLM_DEV_DIR": str(tmp_path / "dev"),
    }


def _lib(tmp_path: Path, name: str, **kw):
    return _load(LIB, name, _env(tmp_path, **kw))


def _lock(tmp_path: Path) -> None:
    (tmp_path / "mounts").write_text("", encoding="utf-8")


def _opt(args: list[str], flag: str) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args) if a == flag]


# ------------------------------------------------------------------ one test per app


def _check_common(lib, app_id: str, tmp_path: Path) -> list[str]:
    spec = lib.app(app_id)
    pin = lib.parse_pin(_text(SHARE / f"{app_id}.pin"))
    assert pin == lib.load_pin(app_id) == spec["pin"]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", pin["amd64_digest"])
    assert lib.base_ref(app_id) == f"{pin['image']}@{pin['amd64_digest']}"
    if lib.has_build(app_id):
        assert lib.image_ref(app_id).startswith("stickllm-local/")
        assert pin["amd64_digest"][7:19] in lib.image_ref(app_id)
    else:
        assert lib.image_ref(app_id) == lib.base_ref(app_id)
    lib.prepare_vault(app_id)
    args = lib.docker_args(app_id)
    assert args[args.index("--log-driver") + 1] == "none"
    for flag in ("--read-only", "--rm"):
        assert flag in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert "no-new-privileges=true" in _opt(args, "--security-opt")
    user = args[args.index("--user") + 1]
    assert not user.startswith("0") and user.split(":")[0] != "root"
    for bad in ("--gpus", "--privileged", "--cap-add", "--network=host", "--pid", "--ipc"):
        assert bad not in args, bad
    assert "--device" not in args          # no GPU in the test env (STICKLLM_DEV_DIR is empty)
    assert not any("docker.sock" in a for a in args)
    publish = _opt(args, "-p")
    assert publish == [f"127.0.0.1:{spec['local_port']}:{spec['port']}"]
    net = lib.network(app_id)
    assert args[args.index("--network") + 1] == net["name"]
    assert args[args.index("--ip") + 1] == net["ip"]
    assert args[-1 - len(spec["command"])] == lib.image_ref(app_id)
    base = str(tmp_path / "vault" / "addons" / app_id)
    targets = []
    for vol in _opt(args, "-v"):
        src, target = vol.split(":")[0], vol.split(":")[1]
        targets.append(target)
        if src.startswith(str(SHARE) + "/") or src == str(SHARE):
            assert vol.endswith(":ro"), vol
        else:
            assert src == base or src.startswith(base + "/"), vol
            assert Path(src).is_dir()
    for volume in spec["volumes"]:
        assert any(volume == t or volume.startswith(t.rstrip("/") + "/") for t in targets), volume
    for tmpfs in _opt(args, "--tmpfs"):
        assert "nosuid" in tmpfs and "nodev" in tmpfs and "size=" in tmpfs
    # Locked: no args, status locked, nothing installed.
    _lock(tmp_path)
    with pytest.raises(lib.AddonError):
        lib.docker_args(app_id)
    st = lib.status_document(app_id, upstream_up=True)
    assert st["state"] == "locked" and st["running"] is False and st["installed"] is False
    return args


@POSIX
def test_tasks_md(tmp_path):
    lib = _lib(tmp_path, "addons_tasks_md")
    args = _check_common(lib, "tasks-md", tmp_path)
    vols = _opt(args, "-v")
    assert any(v.endswith(":/config") for v in vols) and any(v.endswith(":/tasks") for v in vols)
    assert lib.load_pin("tasks-md")["image"] == "baldissaramatheus/tasks.md"
    # The upstream entrypoint chowns and builds as root at every start; the
    # wrapper does that once at install, offline, and runs as uid 1000.
    build = lib.build_spec("tasks-md")
    assert "npm run build" in build["script"] and "exec node /api/server.js" in build["script"]
    assert "USER 1000:1000" in build["changes"]
    assert not any(c.startswith("USER 0") or "root" in c for c in build["changes"])
    script = _text(SCRIPT)
    inst = script.split("build_local() {", 1)[1].split("\n}\n", 1)[0]
    assert "--network none" in inst and "--log-driver none" in inst and "commit" in inst
    run_line = inst.split("docker_cli run", 1)[1].split("\n", 2)
    run_line = " ".join(run_line[:2])
    assert " -v " not in run_line and "--volume" not in run_line and "--mount" not in run_line  # no vault data


@POSIX
def test_paisa(tmp_path):
    lib = _lib(tmp_path, "addons_paisa")
    args = _check_common(lib, "paisa", tmp_path)
    assert any(v.endswith(":/data") for v in _opt(args, "-v"))
    assert args[-3:] == ["serve", "--port", "7500"]
    cfg = tmp_path / "vault" / "addons" / "paisa" / "data" / "paisa.yaml"
    first = cfg.read_text(encoding="utf-8")
    assert "journal_path: /data/main.ledger" in first and "db_path: /data/paisa.db" in first
    assert "user_accounts: []" in first        # the vault unlock is the only login
    # Written once: the user's edits survive restarts.
    cfg.write_text(first + "# edited\n", encoding="utf-8")
    (tmp_path / "mounts").write_text(f"/dev/mapper/v {tmp_path / 'vault'} ext4 rw 0 0\n")
    lib.prepare_vault("paisa")
    assert cfg.read_text(encoding="utf-8").endswith("# edited\n")
    assert (tmp_path / "vault" / "addons" / "paisa" / "data" / "main.ledger").is_file()


def test_old_addons_are_gone():
    lib = _load(LIB, "addons_gone")
    for old in ("radicale", "vikunja", "actual"):
        assert old not in lib.APPS
        assert not (SHARE / f"{old}.pin").exists()
        with pytest.raises(lib.AddonError):
            lib.app(old)
    assert not (SHARE / "radicale").exists()
    html = _text(HTML)
    for old in ("radicale", "vikunja", "actual"):
        assert f'data-app="{old}"' not in html


def test_comfyui_spec(tmp_path):
    lib = _load(LIB, "addons_comfy_spec")
    spec = lib.APPS["comfyui"]
    assert spec["gpu"] and spec["vram_gb"] > 0
    assert "--disable-all-custom-nodes" in " ".join(spec["command"])
    assert "--listen" in " ".join(spec["command"])
    pin = lib.parse_pin(_text(SHARE / "comfyui.pin"))
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", pin["amd64_digest"])


@POSIX
def test_trilium(tmp_path):
    lib = _lib(tmp_path, "addons_trilium")
    args = _check_common(lib, "trilium", tmp_path)
    # Non-root without the image's root entrypoint (it would chown and su).
    assert args[-2:] == ["node", "./main.mjs"]
    assert any(v.endswith(":/home/node/trilium-data") for v in _opt(args, "-v"))
    assert lib.app("trilium")["websocket"] is True


@POSIX
def test_node_red(tmp_path):
    lib = _lib(tmp_path, "addons_node_red")
    args = _check_common(lib, "node-red", tmp_path)
    assert f"{SHARE}/node-red-settings.js:/data/settings.js:ro" in _opt(args, "-v")
    settings = _text(SHARE / "node-red-settings.js")
    for needle in ("allowInstall: false", "allowUpload: false", "autoInstall: false",
                   "functionExternalModules: false", "enabled: false"):
        assert needle in settings, needle
    assert "adminAuth" not in settings     # the gateway pairing is the login
    docs = _text(ROOT / "docs" / "APPS.md")
    assert "Node-RED" in docs and "arbitrary code" in docs


# ------------------------------------------------------------------ shared


def test_ports_networks_and_ids_are_unique():
    lib = _load(LIB, "addons_unique")
    assert lib.ORDER == IDS
    for key in ("local_port", "tls_port", "octet"):
        values = [lib.APPS[i][key] for i in IDS]
        assert len(set(values)) == len(values), key
    subnets = [lib.network(i)["subnet"] for i in IDS]
    assert len(set(subnets)) == len(subnets) and "172.30.1.0/24" not in subnets  # Docs owns .1
    gw = _text(GATEWAY)
    for port in (lib.APPS[i]["tls_port"] for i in IDS):
        assert str(port) not in ("5443", "5444")
    assert "start_addon_tls_servers()" in gw.split("def main() -> int:", 1)[1]
    with pytest.raises(lib.AddonError):
        lib.app("../x")
    with pytest.raises(lib.AddonError):
        lib.app("immich")


def test_nft_drops_every_packet_the_containers_start():
    lib = _load(LIB, "addons_nft")
    rules = lib.nft_ruleset()
    bridges = [lib.network(i)["bridge"] for i in IDS]
    for b in bridges:
        assert f'"{b}"' in rules
    fwd = rules.split("chain forward", 1)[1].split("chain input", 1)[0]
    inp = rules.split("chain input", 1)[1]
    assert re.search(r"iifname \{[^}]+\} drop", fwd)
    assert re.search(r"iifname \{[^}]+\} drop", inp)
    assert "dport" not in rules and rules.count("accept\n") == 2


@POSIX
def test_vault_dirs_refuse_symlinks(tmp_path):
    lib = _lib(tmp_path, "addons_symlink")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "vault" / "addons").mkdir()
    (tmp_path / "vault" / "addons" / "paisa").symlink_to(outside)
    with pytest.raises(lib.AddonError):
        lib.prepare_vault("paisa")
    with pytest.raises(lib.AddonError):
        lib.docker_args("paisa")
    assert list(outside.iterdir()) == []


def test_units_build_and_lock_order():
    run = _text(UNITS / "stickllm-addon@.service")
    install = _text(UNITS / "stickllm-addon-install@.service")
    for unit in (run, install):
        assert "[Install]" not in unit
        assert "ConditionPathIsMountPoint=/var/lib/stickllm/vault" in unit
    assert "ExecStart=/usr/local/bin/stickllm-addon %i run" in run
    assert "ExecStop=/usr/local/bin/stickllm-addon %i stop" in run
    assert "RequiresMountsFor=/var/lib/stickllm/vault" in run
    hook = _text(HOOK)
    assert "/usr/local/bin/stickllm-addon" in hook and "/usr/local/share/stickllm/addons" in hook
    assert "enable stickllm-addon" not in hook
    build = _text(BUILD)
    for name in ("stickllm-addon", "stickllm_addons.py", "tasks-md paisa trilium node-red comfyui", "node-red-settings.js"):
        assert name in build
    vault = _text(VAULT_SCRIPT)
    stop = vault.split("stop_vault_addons() {", 1)[1].split("\n}\n", 1)[0]
    assert stop.index("stickllm-docs stop") < stop.index("stickllm-addon stop-all") < stop.index("stickllm-agent stop")
    assert stop.index("stickllm-addon stop-all") < stop.index("stickllm-dockerd halt")
    script = _text(SCRIPT)
    assert "docker_cli pull" in script and "image-ref" in script
    assert ":latest" not in script


def _have_bash() -> bool:
    return sys.platform != "win32" and shutil.which("bash") is not None


@pytest.mark.skipif(not _have_bash(), reason="needs bash")
def test_script_never_touches_docker_with_vault_locked(tmp_path):
    env = _env(tmp_path, vault=False)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    for tool in ("docker", "nft", "systemctl", "nsenter", "dockerd"):
        (fake / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >>"{tmp_path}/calls"\nexit 1\n', encoding="utf-8")
        (fake / tool).chmod(0o755)
    full = dict(os.environ)
    full.update(env)
    full.update({
        "PATH": f"{fake}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "STICKLLM_ADDONS_LIB": str(LIB),
        "STICKLLM_DOCKERD": str(fake / "dockerd"),
        "STICKLLM_AGENT_HOST_NS": "1",
        "STICKLLM_AGENT_NO_SYSTEMD": "1",
    })
    for cmd in ("run", "start", "install", "docker-args"):
        proc = subprocess.run(["bash", str(SCRIPT), "tasks-md", cmd], env=full, capture_output=True,
                              text=True, timeout=60)
        assert proc.returncode in (0, 2), (cmd, proc.stderr)
    assert not (tmp_path / "calls").exists()
    st = json.loads((tmp_path / "run" / "addon-tasks-md-status.json").read_text())
    assert st["state"] == "locked"


def test_ui_has_install_open_remove_in_named_tabs():
    html = _text(HTML)
    for app_id in IDS + ("onlyoffice",):
        row = html.split(f'data-app="{app_id}"', 1)[1].split("</div>", 1)[0]
        assert f'data-actions-for="{app_id}"' in row
        assert 'data-app-act="install"' in row and 'data-app-act="uninstall"' in row
        # v0.5.3: no rel="noopener" so window.open("", name) finds and reuses the tab.
        assert f'target="stickllm-{app_id}"' in row and "noopener" not in row
        assert 'target="_blank"' not in row
    js = _text(APP_JS)
    assert '"/api/apps/" + action' in js and "/api/apps/open-link" not in js.split("function paintAppActions", 1)[0]
    assert 'window.open("", target)' in js and "function openNamedTab" in js
    assert "w.opener = null" in js
    assert "confirm(" not in js.split("function appsActFor", 1)[1].split("async function appsAct(", 1)[0]


# ------------------------------------------------------------------ gateway


def test_gateway_headers_strip_stickllm_cookies_and_set_cookie():
    gw = _load(GATEWAY, "gw_addon_headers")
    out = gw.addon_proxy_headers(
        {"Cookie": "stickllm_pair=p; stickllm_addon_paisa=s; StickLLM_apps=a; app=1; other=2",
         "Authorization": "Basic dTpw", "Host": "192.168.1.9:5453", "X-Forwarded-For": "evil",
         "X-Real-IP": "evil", "Forwarded": "evil", "Proxy-Authorization": "x", "Connection": "keep-alive"},
        "192.168.1.9:5453", "192.168.1.20",
    )
    assert out["Cookie"] == "app=1; other=2"
    assert out["Authorization"] == "Basic dTpw"           # Radicale/Vikunja own logins
    assert out["X-Forwarded-For"] == "192.168.1.20" and out["X-Forwarded-Proto"] == "https"
    assert "X-Real-IP" not in out and "Forwarded" not in out and "Proxy-Authorization" not in out
    assert out["Connection"] == "close"
    ws = gw.addon_proxy_headers({"Host": 'x"\r\nInjected: 1'}, 'x"\r\nInjected: 1', "1.2.3.4", websocket=True)
    assert all("\r" not in v and "\n" not in v for v in ws.values())
    assert ws["Upgrade"] == "websocket"
    assert not gw.addon_response_header_ok("Set-Cookie", "stickllm_pair=x; Path=/")
    assert not gw.addon_response_header_ok("Set-Cookie", "stickllm_addon_trilium=x")
    assert gw.addon_response_header_ok("Set-Cookie", "trilium.sid=x; Path=/")
    assert not gw.addon_response_header_ok("Transfer-Encoding", "chunked")


def test_gateway_handoff_is_one_time_and_per_app():
    gw = _load(GATEWAY, "gw_addon_handoff")
    doc = {"paired": True, "require_pair": True, "token_hash": "b" * 64}
    t = gw.mint_addon_handoff(doc, "tasks-md", now=1000)
    assert t and not gw.addon_handoff_redeem(t, doc, "paisa", now=1001)   # bound to one app
    assert gw.addon_handoff_redeem(t, doc, "tasks-md", now=1001)
    assert not gw.addon_handoff_redeem(t, doc, "tasks-md", now=1002)        # one time
    late = gw.mint_addon_handoff(doc, "tasks-md", now=1000)
    assert not gw.addon_handoff_redeem(late, doc, "tasks-md", now=1000 + 3600)
    a = gw.addon_session_value(doc, "tasks-md")
    assert len(a) == 64 and a != gw.addon_session_value(doc, "paisa")
    assert a != gw.agent_session_value(doc)
    assert gw.addon_session_ok(a, doc, "tasks-md") and not gw.addon_session_ok(a, doc, "paisa")
    assert gw.mint_addon_handoff({"paired": False}, "tasks-md") == ""


@POSIX
def test_gateway_addon_proxy_live(tmp_path):
    env = _env(tmp_path)
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html></html>")
    env["STICKLLM_UI"] = str(ui)
    gw = _load(GATEWAY, "gw_addon_live", env)
    mod = gw.addons_lib()
    mod.VAULT_MNT = Path(env["STICKLLM_VAULT_MNT"])
    mod.RUN_DIR = Path(env["STICKLLM_RUN"])
    mod.MOUNTS_FILE = env["STICKLLM_MOUNTS_FILE"]
    pair = "p" * 43
    import hashlib
    doc = {"paired": True, "require_pair": True, "token_hash": hashlib.sha256(pair.encode()).hexdigest()}
    gw.AUTH_PATH = tmp_path / "run" / "auth.json"
    gw.AUTH_PATH.write_text(json.dumps(doc))

    seen = {}

    class Up(http.server.BaseHTTPRequestHandler):
        def _reply(self):
            n = int(self.headers.get("Content-Length") or 0)
            seen["body"] = self.rfile.read(n) if n else b""
            seen["cookie"] = self.headers.get("Cookie")
            seen["method"] = self.command
            seen["path"] = self.path
            body = b"hello from app"
            self.send_response(207 if self.command == "PROPFIND" else 200)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Set-Cookie", "stickllm_pair=evil; Path=/")
            self.send_header("Set-Cookie", "app=1; Path=/")
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = do_PROPFIND = _reply

        def log_message(self, *a):
            pass

    up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Up)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    mod.APPS["tasks-md"]["local_port"] = up.server_address[1]
    mod.prepare_vault("tasks-md")
    mod.mark_installed("tasks-md")
    ip = {"v": "192.168.1.20"}

    class H(gw.Handler):
        def _client_ip(self):
            return ip["v"]

        def _is_loopback(self):
            return ip["v"] == "127.0.0.1"

        def log_message(self, *a):
            pass

    httpd = gw.ThreadingHTTPServer(("127.0.0.1", 0), H)
    httpd.stickllm_addon = "tasks-md"
    main = gw.ThreadingHTTPServer(("127.0.0.1", 0), H)
    for srv in (httpd, main):
        threading.Thread(target=srv.serve_forever, daemon=True).start()

    def call(srv, method, path, body=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", data=body,
                                     method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    try:
        # Unpaired LAN browser: nothing reaches the app.
        status, body, _ = call(httpd, "GET", "/", headers={"Accept": "text/html"})
        assert status == 401 and b"hello" not in body and "path" not in seen
        # The StickLLM tab asks for a link (UI marker + pair token).
        status, body, _ = call(main, "POST", "/api/apps/open-link", json.dumps({"id": "tasks-md"}).encode(),
                               {"X-StickLLM-Client": "ui", "Authorization": "Bearer " + pair,
                                "Host": "192.168.1.9", "Content-Type": "application/json"})
        link = json.loads(body)
        assert status == 200 and link["url"].startswith("https://192.168.1.9:5452/__stickllm/handoff?t=")
        assert call(main, "POST", "/api/apps/open-link", json.dumps({"id": "tasks-md"}).encode(),
                    {"X-StickLLM-Client": "ui"})[0] == 401
        assert call(main, "POST", "/api/apps/open-link", json.dumps({"id": "immich"}).encode(),
                    {"X-StickLLM-Client": "ui", "Authorization": "Bearer " + pair})[0] == 404
        path = "/" + link["url"].split("/", 3)[3]
        status, body, headers = call(httpd, "GET", path)
        cookie = headers.get("Set-Cookie")
        assert status == 200 and cookie.startswith("stickllm_addon_tasks_md=")
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Strict" in cookie
        assert call(httpd, "GET", path)[0] == 401                     # one time
        jar = cookie.split(";", 1)[0]
        status, body, headers = call(httpd, "POST", "/api/v1/x?y=1", b"payload",
                                     {"Cookie": f"{jar}; stickllm_pair={pair}; app=1"})
        assert status == 200 and body == b"hello from app"
        assert seen["body"] == b"payload" and seen["path"] == "/api/v1/x?y=1"
        assert seen["cookie"] == "app=1"                               # StickLLM cookies stripped
        assert headers.get_all("Set-Cookie") == ["app=1; Path=/"]
        status, body, _ = call(httpd, "PROPFIND", "/", b"<x/>", {"Cookie": jar, "Depth": "0"})
        assert status == 207 and seen["method"] == "PROPFIND"
        # The tasks-md cookie does not open another app's port.
        other = gw.ThreadingHTTPServer(("127.0.0.1", 0), H)
        other.stickllm_addon = "paisa"
        threading.Thread(target=other.serve_forever, daemon=True).start()
        assert call(other, "GET", "/", headers={"Cookie": jar})[0] == 401
        other.shutdown()
        # WebDAV verbs are refused on the main StickLLM port.
        assert call(main, "PROPFIND", "/")[0] == 405
        # Too large / chunked bodies never reach the app.
        seen.clear()
        req_headers = {"Cookie": jar, "Content-Length": str(gw.ADDON_MAX_BODY + 1)}
        assert call(httpd, "POST", "/", b"", req_headers)[0] in (413, 400)
        assert "path" not in seen
        # Catalog: the add-on rows are live.
        ip["v"] = "127.0.0.1"
        status, body, _ = call(main, "GET", "/api/apps")
        catalog = json.loads(body)
        rows = {r["id"]: r for r in catalog["apps"]}
        assert rows["tasks-md"]["installer"] == "stickllm-addon" and rows["tasks-md"]["installed"] is True
        # installed_count is recounted after the add-on rows are overridden.
        assert catalog["installed_count"] == sum(1 for r in catalog["apps"] if r["installed"]) >= 1
        assert rows["tasks-md"]["not_installed"] is False
        # v0.5.3: the console opens the gateway loopback relay, not the container publish.
        assert rows["tasks-md"]["open_url"] == f"http://127.0.0.1:{mod.APPS['tasks-md']['kiosk_port']}/"
        assert rows["node-red"]["installed"] is False and rows["node-red"]["state"] == "not_installed"
        assert "immich" not in rows  # hidden in v0.5.3 (needs four containers + GPU)
        # Locked vault: 423, the app is never contacted.
        ip["v"] = "192.168.1.20"
        _lock(tmp_path)
        seen.clear()
        status, body, _ = call(httpd, "GET", "/", headers={"Cookie": jar, "Accept": "text/html"})
        assert status in (401, 423) and "path" not in seen
        ip["v"] = "127.0.0.1"
        assert call(httpd, "GET", "/")[0] == 423 and "path" not in seen
        # Open link refuses while locked (loopback and paired LAN tab alike).
        status, body, _ = call(main, "POST", "/api/apps/open-link", json.dumps({"id": "tasks-md"}).encode(),
                               {"X-StickLLM-Client": "ui"})
        assert status == 423 and json.loads(body)["error"] == "vault_locked" and "url" not in json.loads(body)
        ip["v"] = "192.168.1.20"
        status, body, _ = call(main, "POST", "/api/apps/open-link", json.dumps({"id": "tasks-md"}).encode(),
                               {"X-StickLLM-Client": "ui", "Authorization": "Bearer " + pair})
        assert status == 423 and "url" not in json.loads(body)
        assert call(main, "POST", "/api/apps/open-link", json.dumps({"id": "tasks-md"}).encode(),
                    {"X-StickLLM-Client": "ui"})[0] == 401
        ip["v"] = "127.0.0.1"
        status, body, _ = call(main, "POST", "/api/apps/install", json.dumps({"id": "node-red"}).encode(),
                               {"X-StickLLM-Client": "ui", "Content-Type": "application/json"})
        assert status == 423
    finally:
        httpd.shutdown()
        main.shutdown()
        up.shutdown()


def _bash_func(name: str) -> str:
    text = _text(SCRIPT)
    start = text.index(f"{name}() {{")
    end = text.index("\n}\n", start) + 3
    return text[start:end]


@POSIX
def test_free_stale_subnet_only_drops_empty_stickllm_networks(tmp_path):
    """0.5.4: a leftover stickllm-vikunja bridge on 172.30.12.0/24 blocked tasks-md
    ("Pool overlaps"). Only empty stickllm-* networks on that subnet are removed."""
    import subprocess

    log = tmp_path / "rm.log"
    stub = f"""
docker_cli() {{
  case "$1 $2" in
    "network ls") printf '%s\\n' bridge stickllm-vikunja stickllm-busy stickllm-tasks-md other-12 stickllm-paisa ;;
    "network inspect")
      case "$4" in
        *Subnet*) case "$5" in stickllm-paisa) echo 172.30.13.0/24 ;; *) echo 172.30.12.0/24 ;; esac ;;
        *Containers*) case "$5" in stickllm-busy) echo 2 ;; *) echo 0 ;; esac ;;
      esac ;;
    "network rm") echo "$3" >> {log} ;;
  esac
}}
"""
    script = stub + _bash_func("free_stale_subnet") + "free_stale_subnet stickllm-tasks-md 172.30.12.0/24\n"
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    assert log.read_text().split() == ["stickllm-vikunja"]
    assert "removed unused network stickllm-vikunja" in r.stderr


def test_ensure_network_retries_after_freeing_stale_subnet():
    body = _bash_func("ensure_network")
    assert body.index("create_network") < body.index("free_stale_subnet") < body.rindex("create_network")
