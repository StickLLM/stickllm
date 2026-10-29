"""ONLYOFFICE Docs: documents are only ever saved in the vault."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay" / "usr" / "local" / "bin"
LIB = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_docs.py"
GATEWAY = BIN / "stickllm-gateway"
SCRIPT = BIN / "stickllm-docs"
ENTRY = BIN / "stickllm-docs-entrypoint"
VAULT_SCRIPT = BIN / "stickllm-vault"
PIN = ROOT / "overlay" / "usr" / "local" / "share" / "stickllm" / "onlyoffice.pin"
UNITS = ROOT / "overlay" / "etc" / "systemd" / "system"
BUILD = ROOT / "scripts" / "lib" / "docker-build-live.sh"
HOOK = ROOT / "live-build" / "hooks" / "normal" / "0100-stickllm-setup.hook.chroot"

POSIX = pytest.mark.skipif(sys.platform == "win32", reason="Linux-only file APIs (dir_fd, symlinks)")
SECRET = "a" * 64


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


def _env(tmp_path: Path, *, vault: bool = True, settings: bool = True) -> dict:
    v = tmp_path / "vault"
    s = tmp_path / "settings"
    run = tmp_path / "run"
    for p in (v, s, run):
        p.mkdir(exist_ok=True)
    mounts = []
    if vault:
        mounts.append(f"/dev/mapper/v {v} ext4 rw 0 0")
    if settings:
        mounts.append(f"/dev/mapper/s {s} ext4 rw 0 0")
    (tmp_path / "mounts").write_text("\n".join(mounts) + "\n", encoding="utf-8")
    return {
        "STICKLLM_VAULT_MNT": str(v),
        "STICKLLM_SETTINGS_MNT": str(s),
        "STICKLLM_RUN": str(run),
        "STICKLLM_MOUNTS_FILE": str(tmp_path / "mounts"),
        "STICKLLM_DOCS_PIN": str(PIN),
    }


def _docs(tmp_path: Path, name: str, **kw):
    return _load(LIB, name, _env(tmp_path, **kw))


def _lock(tmp_path: Path) -> None:
    (tmp_path / "mounts").write_text("", encoding="utf-8")


# ------------------------------------------------------------------ pin


def test_pin_file_matches_embedded_default_and_build_check():
    docs = _load(LIB, "stickllm_docs_pin")
    pin = docs.load_pin(PIN)
    assert pin == {k: pin[k] for k in pin} and pin["image"] == "onlyoffice/documentserver"
    for key in ("image", "version", "manifest_digest", "amd64_digest"):
        assert pin[key] == docs.DEFAULT_PIN[key]
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", pin["amd64_digest"])
    assert docs.image_ref(pin) == "onlyoffice/documentserver@" + pin["amd64_digest"]
    assert docs.prepared_ref(pin) == "stickllm-docs:" + pin["amd64_digest"][7:23]
    build = _text(BUILD)
    assert pin["amd64_digest"][7:] in build or pin["amd64_digest"][7:15] in build
    assert "onlyoffice.pin" in build
    with pytest.raises(ValueError):
        docs.parse_pin("image=x\nversion=1\namd64_digest=latest\n")


# ------------------------------------------------------------------ locked vault


@POSIX
def test_locked_vault_refuses_every_read_and_write(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_locked", vault=False)
    for call in (
        lambda: docs.list_documents(),
        lambda: docs.read_doc("a.docx"),
        lambda: docs.upload_document("a.docx", b"x"),
        lambda: docs.create_document("a", "docx"),
        lambda: docs.atomic_write("a.docx", b"x", overwrite=True),
        lambda: docs.prepare_vault(),
        lambda: docs.addon_dir(),
    ):
        with pytest.raises(docs.DocsError) as exc:
            call()
        assert exc.value.status == 423
        assert "vault" in exc.value.message.lower()
    assert docs.handle_callback("x.y", b"{}", "")["error"] == 1
    assert not (tmp_path / "vault" / "Documents").exists()
    st = docs.status_document(upstream_up=True)
    assert st["state"] == "locked" and st["running"] is False


@POSIX
def test_vault_locked_between_temp_and_rename_leaves_nothing(tmp_path, monkeypatch):
    docs = _docs(tmp_path, "stickllm_docs_race")
    docs.prepare_vault()
    real = docs.require_vault
    calls = {"n": 0}

    def flip():
        calls["n"] += 1
        if calls["n"] >= 3:  # docs_root (resolve), docs_root (fd check), then pre-rename
            _lock(tmp_path)
        real()

    monkeypatch.setattr(docs, "require_vault", flip)
    with pytest.raises(docs.DocsError) as exc:
        docs.atomic_write("a.docx", b"data", overwrite=True)
    assert exc.value.status == 423
    assert os.listdir(tmp_path / "vault" / "Documents") == []


# ------------------------------------------------------------------ path guards


@POSIX
@pytest.mark.parametrize(
    "rel",
    [
        "../x.docx",
        "a/../../x.docx",
        "a\\..\\..\\x.docx",
        "/etc/passwd.docx",
        "C:/x.docx",
        ".hidden.docx",
        "a/.git/x.docx",
        "a\x00b.docx",
        "a\nb.docx",
        "x.sh",
        "",
    ],
)
def test_path_guard_refuses(tmp_path, rel):
    docs = _docs(tmp_path, "stickllm_docs_guard")
    docs.prepare_vault()
    with pytest.raises(docs.DocsError):
        docs.resolve_doc(rel)
    with pytest.raises(docs.DocsError):
        docs.atomic_write(rel, b"x", overwrite=True)


@POSIX
def test_symlink_escape_is_refused(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_symlink")
    docs.prepare_vault()
    outside = tmp_path / "ssd"
    outside.mkdir()
    (outside / "victim.docx").write_bytes(b"old")
    root = tmp_path / "vault" / "Documents"
    os.symlink(outside, root / "linkdir")
    os.symlink(outside / "victim.docx", root / "victim.docx")
    for rel in ("linkdir/new.docx", "victim.docx"):
        with pytest.raises(docs.DocsError):
            docs.atomic_write(rel, b"new", overwrite=True)
        with pytest.raises(docs.DocsError):
            docs.read_doc(rel)
    with pytest.raises(docs.DocsError):
        docs.upload_document("new.docx", b"new", folder="linkdir")
    assert sorted(os.listdir(outside)) == ["victim.docx"]
    assert (outside / "victim.docx").read_bytes() == b"old"
    # Symlinks are never listed.
    assert docs.list_documents()["documents"] == []


@POSIX
def test_documents_folder_symlink_is_refused(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_rootlink")
    outside = tmp_path / "ssd"
    outside.mkdir()
    os.symlink(outside, tmp_path / "vault" / "Documents")
    with pytest.raises(docs.DocsError) as exc:
        docs.upload_document("a.docx", b"x")
    assert exc.value.code == "bad_root"
    with pytest.raises(docs.DocsError):
        docs.prepare_vault()
    assert os.listdir(outside) == []


@POSIX
def test_addon_dir_symlink_is_refused(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_addonlink")
    outside = tmp_path / "ssd"
    outside.mkdir()
    (tmp_path / "vault" / "addons").mkdir()
    os.symlink(outside, tmp_path / "vault" / "addons" / "onlyoffice")
    with pytest.raises(docs.DocsError):
        docs.prepare_vault()
    assert os.listdir(outside) == []


@POSIX
def test_cross_device_write_is_refused(tmp_path, monkeypatch):
    docs = _docs(tmp_path, "stickllm_docs_dev")
    docs.prepare_vault()
    monkeypatch.setattr(docs, "_vault_dev", lambda: -1)
    with pytest.raises(docs.DocsError) as exc:
        docs.atomic_write("a.docx", b"x", overwrite=True)
    assert exc.value.code == "bad_root"
    assert os.listdir(tmp_path / "vault" / "Documents") == []


@POSIX
def test_atomic_write_upload_create_and_list(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_write")
    docs.prepare_vault()
    root = tmp_path / "vault" / "Documents"
    assert docs.upload_document("Report.docx", b"one") == "Report.docx"
    assert docs.upload_document("Report.docx", b"two") == "Report (2).docx"
    (root / "Work").mkdir()
    assert docs.upload_document("a/b:c.xlsx", b"three", folder="Work") == "Work/a b c.xlsx"
    with pytest.raises(docs.DocsError):
        docs.upload_document("evil.exe", b"x")
    with pytest.raises(docs.DocsError) as exc:
        docs.create_document("New", "docx")
    assert exc.value.status == 409  # templates are seeded by install
    (tmp_path / "vault" / "addons" / "onlyoffice" / "templates" / "new.docx").write_bytes(b"tpl")
    assert docs.create_document("New", "docx") == "New.docx"
    assert (root / "New.docx").read_bytes() == b"tpl"
    assert docs.atomic_write("Report.docx", b"edited", overwrite=True) == "Report.docx"
    assert (root / "Report.docx").read_bytes() == b"edited"
    assert oct((root / "Report.docx").stat().st_mode & 0o777) == oct(0o640)
    names = sorted(p.name for p in root.rglob("*"))
    assert not [n for n in names if n.startswith(".~stickllm")]
    listed = {d["path"] for d in docs.list_documents()["documents"]}
    assert listed == {"Report.docx", "Report (2).docx", "Work/a b c.xlsx", "New.docx"}
    for name in docs.ADDON_DIRS:
        assert (tmp_path / "vault" / "addons" / "onlyoffice" / name).is_dir()


# ------------------------------------------------------------------ tokens


def test_jwt_sign_verify_tamper_alg_and_expiry():
    docs = _load(LIB, "stickllm_docs_jwt")
    tok = docs.jwt_sign({"status": 2, "exp": 1000}, SECRET)
    assert docs.jwt_verify(tok, SECRET, now=900)["status"] == 2
    with pytest.raises(docs.DocsError):
        docs.jwt_verify(tok, SECRET, now=2000)
    with pytest.raises(docs.DocsError):
        docs.jwt_verify(tok, "b" * 64, now=900)
    head, body, sig = tok.split(".")
    forged = docs._b64(json.dumps({"status": 2, "url": "http://evil/"}).encode())
    with pytest.raises(docs.DocsError):
        docs.jwt_verify(f"{head}.{forged}.{sig}", SECRET, now=900)
    none_head = docs._b64(json.dumps({"alg": "none"}).encode())
    with pytest.raises(docs.DocsError):
        docs.jwt_verify(f"{none_head}.{body}.", SECRET, now=900)
    with pytest.raises(docs.DocsError):
        docs.jwt_verify(tok, "short", now=900)


def test_link_token_expiry_and_callback_ignores_it():
    docs = _load(LIB, "stickllm_docs_link")
    tok = docs.link_token("Work/a.docx", SECRET, ttl=10, now=1000)
    assert docs.link_verify(tok, SECRET, now=1005) == "Work/a.docx"
    with pytest.raises(docs.DocsError):
        docs.link_verify(tok, SECRET, now=2000)
    assert docs.link_verify(tok, SECRET, now=2000, check_expiry=False) == "Work/a.docx"
    with pytest.raises(docs.DocsError):
        docs.link_verify(tok[:-2] + "AA", SECRET, now=1005)
    with pytest.raises(docs.DocsError):
        docs.link_verify(docs.link_token("../x.docx", SECRET, now=1000), SECRET, now=1005)
    assert "check_expiry=False" in _text(LIB).split("def handle_callback", 1)[1].split("def ", 1)[0]


def test_callback_url_is_pinned_to_loopback_docs():
    docs = _load(LIB, "stickllm_docs_ssrf")
    assert (
        docs.ds_fetch_url("http://172.30.1.2/cache/files/data/abc/output.docx/output.docx?md5=x&expires=1")
        == "http://127.0.0.1:8083/cache/files/data/abc/output.docx/output.docx?md5=x&expires=1"
    )
    assert docs.ds_fetch_url("https://evil.example/x/cache/files/a/b").startswith("http://127.0.0.1:8083/cache/files/")
    for bad in (
        "http://evil.example/etc/passwd",
        "file:///etc/passwd",
        "http://127.0.0.1:8083/cache/files/../../etc",
        "http://127.0.0.1:8083/cache/files/%2e%2e/x",
        "",
    ):
        with pytest.raises(docs.DocsError):
            docs.ds_fetch_url(bad)
    with pytest.raises(docs.DocsError):
        docs._fetch("http://10.0.0.1/cache/files/x")
    assert docs.ds_client_ok("172.30.1.2") and docs.ds_client_ok("127.0.0.1")
    assert not docs.ds_client_ok("192.168.1.5") and not docs.ds_client_ok("172.30.10.2")


@POSIX
def test_callback_saves_only_signed_edits_into_documents(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_callback")
    docs.prepare_vault()
    (tmp_path / "run" / "docs-jwt").write_text(SECRET, encoding="utf-8")
    root = tmp_path / "vault" / "Documents"
    (root / "a.docx").write_bytes(b"old")
    link = docs.link_token("a.docx", SECRET)
    fetched = []

    def fetch(url):
        fetched.append(url)
        return b"new"

    url = "http://172.30.1.2/cache/files/data/k/output.docx/output.docx"
    # Editing (status 1): nothing written.
    body = json.dumps({"token": docs.jwt_sign({"status": 1}, SECRET)}).encode()
    assert docs.handle_callback(link, body, "", fetch=fetch) == {"error": 0}
    assert (root / "a.docx").read_bytes() == b"old" and not fetched
    # Unsigned or wrongly signed: refused.
    for bad in (json.dumps({"status": 2, "url": url}).encode(),
                json.dumps({"token": docs.jwt_sign({"status": 2, "url": url}, "b" * 64)}).encode()):
        with pytest.raises(docs.DocsError):
            docs.handle_callback(link, bad, "", fetch=fetch)
    # Wrong type: refused.
    body = json.dumps({"token": docs.jwt_sign({"status": 2, "url": url, "filetype": "xlsx"}, SECRET)}).encode()
    with pytest.raises(docs.DocsError):
        docs.handle_callback(link, body, "", fetch=fetch)
    assert (root / "a.docx").read_bytes() == b"old"
    # Signed save (status 2, then forcesave 6 via the header form).
    body = json.dumps({"token": docs.jwt_sign({"status": 2, "url": url, "filetype": "docx"}, SECRET)}).encode()
    assert docs.handle_callback(link, body, "", fetch=fetch) == {"error": 0}
    assert (root / "a.docx").read_bytes() == b"new"
    assert fetched == ["http://127.0.0.1:8083/cache/files/data/k/output.docx/output.docx"]
    header = "Bearer " + docs.jwt_sign({"payload": {"status": 6, "url": url}}, SECRET)
    assert docs.handle_callback(link, b"{}", header, fetch=lambda u: b"forced") == {"error": 0}
    assert (root / "a.docx").read_bytes() == b"forced"
    # Vault locked: ONLYOFFICE is told to retry; nothing written anywhere.
    _lock(tmp_path)
    assert docs.handle_callback(link, body, "", fetch=fetch)["error"] == 1
    assert (root / "a.docx").read_bytes() == b"forced"


@POSIX
def test_editor_config_points_at_gateway_and_is_signed(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_config")
    docs.prepare_vault()
    (tmp_path / "vault" / "Documents" / "a.xlsx").write_bytes(b"x")
    doc = docs.editor_config("a.xlsx", SECRET)
    cfg = doc["config"]
    assert cfg["documentType"] == "cell"
    assert cfg["document"]["url"].startswith("http://172.30.1.1:80/api/docs/storage/")
    assert cfg["editorConfig"]["callbackUrl"].startswith("http://172.30.1.1:80/api/docs/callback/")
    claims = docs.jwt_verify(cfg["token"], SECRET)
    assert claims["document"]["key"] == cfg["document"]["key"]
    assert cfg["editorConfig"]["customization"]["plugins"] is False


# ------------------------------------------------------------------ secret


@POSIX
def test_secret_is_on_settings_0600_and_runtime_copy_is_ram(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_secret")
    path = docs.ensure_settings_secret()
    assert path == tmp_path / "settings" / "onlyoffice" / "jwt.secret"
    assert path.stat().st_mode & 0o777 == 0o600
    assert (path.parent.stat().st_mode & 0o777) == 0o700
    rt = docs.install_runtime_secret()
    assert rt.parent == tmp_path / "run" and rt.stat().st_mode & 0o777 == 0o600
    assert len(docs.runtime_secret()) >= 32
    docs.drop_runtime_secret()
    with pytest.raises(docs.DocsError) as exc:
        docs.runtime_secret()
    assert exc.value.status == 503
    docs2 = _docs(tmp_path, "stickllm_docs_secret2", settings=False)
    with pytest.raises(docs2.DocsError):
        docs2.ensure_settings_secret()


def test_entrypoint_reads_secret_file_not_env():
    text = _text(ENTRY)
    assert "/run/stickllm-secret/jwt.secret" in text
    assert "export JWT_SECRET" in text
    assert "exec /app/ds/run-document-server.sh" in text
    assert "-lt 32" in text or "< 32" in text or "32" in text


# ------------------------------------------------------------------ container


def test_container_flags_are_vault_or_tmpfs_only():
    text = _text(SCRIPT)
    body = text.split("container_args() {", 1)[1].split("\n}\n", 1)[0]
    for flag in ("--read-only", "--log-driver none", "--cap-drop ALL", "no-new-privileges=true",
                 "-p 127.0.0.1:8083:80", "--rm"):
        assert flag in body, flag
    assert "JWT_SECRET" not in body
    assert "PLUGINS_ENABLED=false" in body and "NGINX_ACCESS_LOG=false" in body
    binds = re.findall(r'-v "([^"]+)"', body)
    assert len(binds) == 6
    for b in binds:
        src = b.split(":", 1)[0]
        assert src.startswith("${dir}/") or src in ("${secret}", "${ENTRY}"), b
    assert '"${secret}:/run/stickllm-secret/jwt.secret:ro"' in body
    assert '"${ENTRY}:/usr/local/bin/stickllm-docs-entrypoint:ro"' in body
    assert "Documents" not in body  # gateway alone touches vault/Documents
    for vol in ("/var/lib/onlyoffice", "/var/log/onlyoffice", "/var/www/onlyoffice/Data", "/etc/onlyoffice"):
        assert ":" + vol + '"' in body
    for tmpfs in ("/tmp", "/run", "/var/lib/nginx", "/var/log/nginx", "/var/log/supervisor"):
        assert f"--tmpfs {tmpfs}:" in body
    prep = text.split("prepare_image() {", 1)[1].split("\n}\n", 1)[0]
    assert "--network none" in prep and "--log-driver none" in prep
    for vol in ("/var/log/onlyoffice", "/var/lib/onlyoffice", "/var/www/onlyoffice/Data"):
        assert f"--tmpfs {vol}" in prep
    assert "rm -f -v" in prep
    stop = text.split("stop_container() {", 1)[1].split("\n}\n", 1)[0]
    assert stop.index("prepare4shutdown") < stop.index(" stop ")
    run = text.split("cmd_run() {", 1)[1].split("\n}\n", 1)[0]
    assert run.index("gate ||") < run.index("ensure docs")
    assert run.rindex("gate ||") < run.index("docker_cli run")
    assert run.rindex("prepare-vault") < run.index("docker_cli run")


def _have_bash() -> bool:
    return sys.platform != "win32" and shutil.which("bash") is not None


def _run_script(tmp_path: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    fake = tmp_path / "fakebin"
    fake.mkdir(exist_ok=True)
    for tool in ("docker", "nft", "systemctl", "nsenter"):
        (fake / tool).write_text(f'#!/bin/sh\necho "{tool} $*" >>"{tmp_path}/calls"\nexit 1\n', encoding="utf-8")
        (fake / tool).chmod(0o755)
    full = dict(os.environ)
    full.update(env)
    full.update({
        "PATH": f"{fake}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "STICKLLM_DOCS_LIB": str(LIB),
        "STICKLLM_DOCKERD": str(fake / "docker"),
        "STICKLLM_AGENT_HOST_NS": "1",
        "STICKLLM_AGENT_NO_SYSTEMD": "1",
    })
    return subprocess.run(["bash", str(SCRIPT), *args], env=full, capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(not _have_bash(), reason="needs bash")
def test_script_never_touches_docker_with_vault_locked(tmp_path):
    env = _env(tmp_path, vault=False)
    for cmd in ("run", "start", "install", "docker-args"):
        proc = _run_script(tmp_path, env, cmd)
        assert proc.returncode in (0, 2), (cmd, proc.stderr)
    assert not (tmp_path / "calls").exists()
    st = json.loads((tmp_path / "run" / "docs-status.json").read_text())
    assert st["state"] == "locked"


@pytest.mark.skipif(not _have_bash(), reason="needs bash")
def test_real_docker_args_bind_only_vault_settings_and_entrypoint(tmp_path):
    env = _env(tmp_path)
    proc = _run_script(tmp_path, env, "docker-args")
    assert proc.returncode == 0, proc.stderr
    args = proc.stdout.splitlines()
    vault = str(tmp_path / "vault")
    settings = str(tmp_path / "settings")
    assert "--read-only" in args and args[args.index("--log-driver") + 1] == "none"
    assert not any(a.startswith("JWT_SECRET") for a in args)
    vols = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    assert vols
    for v in vols:
        src = v.split(":", 1)[0]
        assert (src.startswith(vault + "/addons/onlyoffice/")
                or src == settings + "/onlyoffice/jwt.secret"
                or src == "/usr/local/bin/stickllm-docs-entrypoint"), v
        if not src.startswith(vault):
            assert v.endswith(":ro"), v
    secret = Path(settings) / "onlyoffice" / "jwt.secret"
    assert secret.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "calls").exists()


def test_units_are_not_enabled_and_require_the_mounts():
    docs_unit = _text(UNITS / "stickllm-docs.service")
    install_unit = _text(UNITS / "stickllm-docs-install.service")
    for unit in (docs_unit, install_unit):
        assert "[Install]" not in unit
        assert "ConditionPathIsMountPoint=/var/lib/stickllm/vault" in unit
        assert "ConditionPathIsMountPoint=/mnt/stickllm-settings" in unit
    assert "RequiresMountsFor=/var/lib/stickllm/vault" in docs_unit
    assert "stickllm-ui.service" in docs_unit.split("[Service]")[0]
    assert "ExecStop=/usr/local/bin/stickllm-docs stop" in docs_unit
    hook = _text(HOOK)
    for name in ("stickllm-docs", "stickllm-docs-entrypoint", "stickllm-dockerd"):
        assert name in hook
    assert "enable stickllm-docs" not in hook


def test_nft_allows_only_the_gateway_port():
    docs = _load(LIB, "stickllm_docs_nft")
    rules = docs.nft_ruleset()
    assert 'iifname "stickllm-d0" drop' in rules
    assert "ip daddr 172.30.1.1 tcp dport 80 accept" in rules
    assert rules.count("accept\n") == 3


# ------------------------------------------------------------------ lock order


def test_lock_stops_docs_before_agent_dockerd_and_umount():
    text = _text(VAULT_SCRIPT)
    stop = text.split("stop_vault_addons() {", 1)[1].split("\n}\n", 1)[0]
    assert stop.index("stickllm-docs stop") < stop.index("stickllm-agent stop") < stop.index("stickllm-dockerd halt")
    lock = text.split("cmd_lock() {", 1)[1].split("\n}\n", 1)[0]
    assert lock.index("stop_vault_addons") < lock.index("close >/dev/null") < lock.index('umount "$MNT_POINT"')


@pytest.mark.skipif(not _have_bash(), reason="needs bash")
def test_lock_order_real_run(tmp_path):
    text = _text(VAULT_SCRIPT)
    func = "stop_vault_addons() {" + text.split("stop_vault_addons() {", 1)[1].split("\n}\n", 1)[0] + "\n}\n"
    fake = tmp_path / "bin"
    fake.mkdir()
    log = tmp_path / "order"
    for name in ("stickllm-docs", "stickllm-agent", "stickllm-dockerd"):
        p = fake / name
        # Docs must still see the vault mounted when it is stopped.
        p.write_text(f'#!/bin/sh\necho "{name} $1 vault=$(cat {tmp_path}/mounted)" >>"{log}"\nexit 1\n')
        p.chmod(0o755)
    (tmp_path / "mounted").write_text("yes")
    (tmp_path / "logs").mkdir()
    func = func.replace("/usr/local/bin/", f"{fake}/").replace("/run/stickllm/", f"{tmp_path}/logs/")
    script = func + f'stop_vault_addons\necho no > "{tmp_path}/mounted"\necho umount >>"{log}"\n'
    subprocess.run(["bash", "-c", script], check=True, timeout=30)
    assert log.read_text().splitlines() == [
        "stickllm-docs stop vault=yes",
        "stickllm-agent stop vault=yes",
        "stickllm-dockerd halt vault=yes",
        "umount",
    ]


# ------------------------------------------------------------------ gateway


def test_gateway_proxy_headers_drop_credentials():
    gw = _load(GATEWAY, "stickllm_gateway_docs_headers")
    out = gw.docs_proxy_headers(
        {"Cookie": "stickllm_apps=x; stickllm_pair=y", "Authorization": "Bearer pair", "Accept": "*/*",
         "X-Forwarded-Host": "evil", "Connection": "keep-alive"},
        "192.168.1.9", "https", "192.168.1.20",
    )
    assert "Cookie" not in out and "Authorization" not in out
    assert out["X-Forwarded-Host"] == "192.168.1.9/docs-server"
    assert out["X-Forwarded-Proto"] == "https"
    assert out["Host"] == "127.0.0.1:8083" and out["Accept"] == "*/*"
    ws = gw.docs_proxy_headers({}, 'x"\r\nInjected: 1', "http", "1.2.3.4", websocket=True)
    assert "\r" not in ws["X-Forwarded-Host"] and "\n" not in ws["X-Forwarded-Host"]
    assert ws["Upgrade"] == "websocket"
    assert gw.docs_container_ip("172.30.1.2") and not gw.docs_container_ip("127.0.0.1")
    assert gw.docs_container_route_ok("GET", "/api/docs/storage/abc")
    assert gw.docs_container_route_ok("POST", "/api/docs/callback/abc")
    assert not gw.docs_container_route_ok("GET", "/api/chats")
    assert not gw.docs_container_route_ok("GET", "/docs-server/")
    assert not gw.docs_container_route_ok("POST", "/api/docs/upload")


@POSIX
def test_gateway_docs_routes_live(tmp_path, monkeypatch):
    env = _env(tmp_path)
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html></html>")
    env.update({"STICKLLM_UI": str(ui)})
    gw = _load(GATEWAY, "stickllm_gateway_docs_live", env)
    mod = gw.docs_lib()
    mod.VAULT_MNT = Path(env["STICKLLM_VAULT_MNT"])
    mod.SETTINGS_MNT = Path(env["STICKLLM_SETTINGS_MNT"])
    mod.RUN_DIR = Path(env["STICKLLM_RUN"])
    mod.MOUNTS_FILE = env["STICKLLM_MOUNTS_FILE"]
    mod.prepare_vault()
    (mod.RUN_DIR / "docs-jwt").write_text(SECRET)
    (mod.VAULT_MNT / "Documents" / "a.docx").write_bytes(b"old")
    ip = {"v": "127.0.0.1"}

    class H(gw.Handler):
        def _client_ip(self):
            return ip["v"]

        def _desktop_allowed(self):
            return True

    httpd = gw.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def call(method, path, body=None, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=body, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    try:
        link = mod.link_token("a.docx", SECRET)
        # Container: storage and callback only.
        ip["v"] = "172.30.1.2"
        assert call("GET", f"/api/docs/storage/{link}") == (200, b"old")
        assert call("GET", "/api/docs/list")[0] == 403
        assert call("GET", "/api/chats")[0] == 403
        assert call("GET", "/")[0] == 403
        assert call("POST", "/api/docs/upload?name=x.docx", b"x")[0] == 403
        monkeypatch.setattr(mod, "_fetch", lambda url: b"saved")
        url = "http://172.30.1.2/cache/files/data/k/output.docx/output.docx"
        cb = json.dumps({"token": mod.jwt_sign({"status": 2, "url": url}, SECRET)}).encode()
        status, out = call("POST", f"/api/docs/callback/{link}", cb, {"Content-Type": "application/json"})
        assert status == 200 and json.loads(out) == {"error": 0}
        assert (mod.VAULT_MNT / "Documents" / "a.docx").read_bytes() == b"saved"
        bad = json.dumps({"status": 2, "url": url}).encode()
        assert json.loads(call("POST", f"/api/docs/callback/{link}", bad)[1]) == {"error": 1}
        # LAN client never reaches the container routes.
        ip["v"] = "192.168.1.20"
        assert call("GET", f"/api/docs/storage/{link}")[0] == 403
        # UI routes.
        ip["v"] = "127.0.0.1"
        status, out = call("GET", "/api/docs/list")
        assert status == 200 and [d["path"] for d in json.loads(out)["documents"]] == ["a.docx"]
        status, out = call("POST", "/api/docs/upload?name=b.pptx", b"deck",
                           {"X-StickLLM-Client": "ui", "Content-Type": "application/octet-stream"})
        assert status == 200 and json.loads(out)["path"] == "b.pptx"
        status, out = call("POST", "/api/docs/upload?name=..%2F..%2Fx.docx&folder=..", b"x",
                           {"X-StickLLM-Client": "ui"})
        assert status == 400
        status, out = call("GET", "/api/docs/config?path=a.docx")
        assert status == 200 and json.loads(out)["server"] == "/docs-server/"
        status, out = call("GET", "/api/docs/download?path=a.docx")
        assert status == 200 and out == b"saved"
        # Locked: 423 with a clear message, and the proxy is closed.
        _lock(tmp_path)
        status, out = call("GET", "/api/docs/list")
        assert status == 423 and "vault" in json.loads(out)["message"].lower()
        status, out = call("POST", "/api/docs/upload?name=c.docx", b"x", {"X-StickLLM-Client": "ui"})
        assert status == 423
        assert call("GET", "/docs-server/web-apps/apps/api/documents/api.js")[0] == 423
        status, out = call("GET", "/api/docs/status")
        assert status == 200 and json.loads(out)["state"] == "locked"
        assert not (mod.VAULT_MNT / "Documents" / "c.docx").exists()
    finally:
        httpd.shutdown()


def test_gateway_wires_onlyoffice_into_apps():
    text = _text(GATEWAY)
    assert 'if app_id == "onlyoffice":' in text
    assert "stickllm-docs-install.service" in text
    assert '"/usr/local/bin/stickllm-docs", "uninstall"' in text
    js = _text(ROOT / "ui" / "app.js")
    assert "j.started === true" in js
    apps = _load(ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_apps.py", "stickllm_apps_docs")
    row = [a for a in apps.CATALOG if a["id"] == "onlyoffice"][0]
    assert row.get("installer") is None


def test_docs_page_uses_gateway_api_and_external_script():
    html = _text(ROOT / "ui" / "apps" / "docs" / "index.html")
    js = _text(ROOT / "ui" / "apps" / "docs" / "docs.js")
    assert re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html) is None
    assert '<script src="docs.js' in html
    assert "/docs-server/web-apps/apps/api/documents/api.js" in js
    assert '"X-StickLLM-Client": "ui"' in js
    for route in ("/api/docs/status", "/api/docs/list", "/api/docs/config", "/api/docs/create", "/api/docs/upload"):
        assert route in js
    assert "http://" not in js and "https://" not in js


# ------------------------------------------- 0.5.4: rename, copy, save as, downloads


@POSIX
def test_rename_keeps_extension_refuses_clobber_and_follows_open_editor(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_rename")
    docs.prepare_vault()
    (tmp_path / "run" / "docs-jwt").write_text(SECRET, encoding="utf-8")
    root = tmp_path / "vault" / "Documents"
    (root / "a.docx").write_bytes(b"old")
    (root / "taken.docx").write_bytes(b"t")
    link = docs.link_token("a.docx", SECRET)  # editor opened before the rename
    assert docs.rename_document("a.docx", "Report") == "Report.docx"
    assert docs.rename_document("Report.docx", "Report.docx") == "Report.docx"
    assert (root / "Report.docx").read_bytes() == b"old" and not (root / "a.docx").exists()
    with pytest.raises(docs.DocsError) as exc:
        docs.rename_document("Report.docx", "taken")
    assert exc.value.status == 409 and (root / "taken.docx").read_bytes() == b"t"
    # Path tricks are cleaned into a plain name in the same folder.
    assert docs.rename_document("Report.docx", "../x") == "x.docx"
    assert docs.rename_document("x.docx", ".hidden") == "hidden.docx"
    assert docs.rename_document("hidden.docx", "Report") == "Report.docx"
    assert not (tmp_path / "vault" / "x.docx").exists()
    assert docs.rename_document("Report.docx", "Final.xlsx") == "Final.xlsx.docx"
    # The old editor's save lands in the renamed file, not a resurrected a.docx.
    url = "http://172.30.1.2/cache/files/data/k/output.docx/output.docx"
    body = json.dumps({"token": docs.jwt_sign({"status": 2, "url": url, "filetype": "docx"}, SECRET)}).encode()
    assert docs.handle_callback(link, body, "", fetch=lambda u: b"new") == {"error": 0}
    assert not (root / "a.docx").exists()
    assert (root / "Final.xlsx.docx").read_bytes() == b"new"
    assert docs.follow_renames("a.docx") == "Final.xlsx.docx"
    assert all(d["name"] != ".stickllm-renames.json" for d in docs.list_documents()["documents"])


@POSIX
def test_copy_and_editor_save_as_never_overwrite(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_copy")
    docs.prepare_vault()
    root = tmp_path / "vault" / "Documents"
    (root / "sub").mkdir()
    (root / "sub" / "a.xlsx").write_bytes(b"orig")
    assert docs.copy_document("sub/a.xlsx") == "sub/a copy.xlsx"
    assert docs.copy_document("sub/a.xlsx") == "sub/a copy (2).xlsx"
    assert docs.copy_document("sub/a.xlsx", "Budget") == "sub/Budget.xlsx"
    assert (root / "sub" / "Budget.xlsx").read_bytes() == b"orig"
    seen = []
    url = "http://172.30.1.2/cache/files/data/k/output.pdf/output.pdf"
    rel = docs.save_as_from_editor("sub/a.xlsx", "Export", "pdf", url, fetch=lambda u: seen.append(u) or b"%PDF")
    assert rel == "sub/Export.pdf" and (root / "sub" / "Export.pdf").read_bytes() == b"%PDF"
    assert seen == ["http://127.0.0.1:8083/cache/files/data/k/output.pdf/output.pdf"]
    with pytest.raises(docs.DocsError):
        docs.save_as_from_editor("sub/a.xlsx", "x", "exe", url, fetch=lambda u: b"x")
    with pytest.raises(docs.DocsError):
        docs.save_as_from_editor("sub/a.xlsx", "x", "pdf", "http://evil.example/a.pdf", fetch=lambda u: b"x")
    assert (root / "sub" / "a.xlsx").read_bytes() == b"orig"


@POSIX
def test_downloads_list_and_import_copy_only(tmp_path):
    docs = _docs(tmp_path, "stickllm_docs_downloads")
    docs.prepare_vault()
    assert docs.list_downloads()["downloads"] == []
    dl = tmp_path / "vault" / "Downloads"
    dl.mkdir()
    (dl / "notes.docx").write_bytes(b"d")
    (dl / "movie.mp4").write_bytes(b"m")
    (dl / "half.pdf.crdownload").write_bytes(b"h")
    (dl / ".hidden.docx").write_bytes(b"h")
    os.symlink("/etc/passwd", dl / "link.txt")
    names = {d["name"]: d["office"] for d in docs.list_downloads()["downloads"]}
    assert names == {"notes.docx": True, "movie.mp4": False}
    assert docs.import_download("notes.docx") == "notes.docx"
    assert (dl / "notes.docx").exists()  # copied, never moved
    assert (tmp_path / "vault" / "Documents" / "notes.docx").read_bytes() == b"d"
    for bad in ("movie.mp4", "../Documents/notes.docx", "link.txt", ".hidden.docx", "gone.docx"):
        with pytest.raises(docs.DocsError):
            docs.import_download(bad)


def test_office_ui_has_name_dialog_rename_copy_and_downloads():
    html = _text(ROOT / "ui" / "apps" / "docs" / "index.html")
    js = _text(ROOT / "ui" / "apps" / "docs" / "docs.js")
    assert '<dialog id="nameDlg">' in html and 'id="downloads"' in html
    assert "onRequestSaveAs" in js and "onRequestRename" in js
    assert '"/api/docs/rename"' in js and '"/api/docs/copy"' in js and '"/api/docs/save-as"' in js
    assert '"/api/docs/downloads"' in js and '"/api/docs/import-download"' in js
    assert 'KIND_LABEL = { docx: "Document", xlsx: "Spreadsheet", pptx: "Presentation" }' in js
    gw = _text(GATEWAY)
    for route in ("/api/docs/rename", "/api/docs/copy", "/api/docs/save-as", "/api/docs/downloads",
                  "/api/docs/import-download"):
        assert route in gw


def test_office_default_new_names_are_dated():
    if not shutil.which("node"):
        pytest.skip("node not installed")
    js = ROOT / "ui" / "apps" / "docs" / "docs.js"
    script = (
        "const fs=require('fs');const el={addEventListener(){},querySelectorAll(){return[]},textContent:''};"
        "global.document={querySelector(){return el},querySelectorAll(){return[]},body:{classList:{add(){},remove(){}}}};"
        "global.window={};global.location={search:''};global.fetch=()=>new Promise(()=>{});"
        f"eval(fs.readFileSync({json.dumps(str(js))},'utf8'));"
        "const d=window.__stickDocs;const t=d.today();"
        "console.log(JSON.stringify([t,d.defaultName('docx'),d.defaultName('xlsx'),d.defaultName('pptx')]));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, check=True).stdout
    t, doc, xls, ppt = json.loads(out)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", t)
    assert doc == f"Document {t}.docx" and xls == f"Spreadsheet {t}.xlsx" and ppt == f"Presentation {t}.pptx"
