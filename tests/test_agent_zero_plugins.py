"""Agent Zero plugin lockdown: allowlist bake, read-only assembly, gateway deny."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_agent.py"
A0P = ROOT / "scripts" / "lib" / "a0_plugins.py"
ALLOW = ROOT / "overlay" / "usr" / "local" / "share" / "stickllm" / "agent-zero-plugins.allow"
RUN = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-agent"
ENTRY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-agent-entrypoint"
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
BUILD = ROOT / "scripts" / "lib" / "docker-build-live.sh"
REVIEWS = ROOT / "docs" / "PLUGIN-REVIEWS.md"


def _load(path: Path, name: str, env: dict | None = None):
    old = {}
    for key, value in (env or {}).items():
        old[key] = os.environ.get(key)
        os.environ[key] = value
    try:
        loader = importlib.machinery.SourceFileLoader(name, str(path))
        spec = importlib.util.spec_from_loader(name, loader)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        loader.exec_module(mod)
        return mod
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _load_agent(monkeypatch, name: str, env: dict):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return _load(AGENT, name, None)


def _write_plugin(root: Path, name: str, js: str = "console.log(1)\n") -> None:
    (root / "extensions" / "webui" / "initFw_end").mkdir(parents=True, exist_ok=True)
    (root / "plugin.yaml").write_text(f"name: {name}\ntitle: {name}\n", encoding="utf-8")
    (root / "extensions" / "webui" / "initFw_end" / "x.js").write_text(js, encoding="utf-8")


def _agent_env(tmp_path: Path, allow: Path, baked: Path) -> tuple:
    vault = tmp_path / "vault"
    settings = tmp_path / "settings"
    vault.mkdir()
    settings.mkdir()
    mounts = tmp_path / "mounts"
    mounts.write_text(f"dev {vault} ext4 rw 0 0\ndev {settings} ext4 rw 0 0\n", encoding="utf-8")
    env = {
        "STICKLLM_VAULT_MNT": str(vault),
        "STICKLLM_SETTINGS_MNT": str(settings),
        "STICKLLM_MOUNTS_FILE": str(mounts),
        "STICKLLM_A0_PLUGIN_ALLOW": str(allow),
        "STICKLLM_A0_BAKED_PLUGINS": str(baked),
    }
    return vault, settings, env


def _bake_fixture(tmp_path: Path, a0p, names=("good_plugin",)) -> tuple[Path, Path]:
    """A baked dir + allowlist exactly as the ISO build writes them (no network)."""
    srcs = tmp_path / "srcs"
    lines = []
    for name in names:
        _write_plugin(srcs / name, name)
        tree = a0p.tree_hash(srcs / name)
        lines.append(f"{name} https://github.com/example/{name} {'a' * 40} MIT {tree}\n")
    allow = tmp_path / "plugins.allow"
    allow.write_text("# test\n" + "".join(lines), encoding="utf-8")

    def fake_fetch(entry, dest):
        shutil.copytree(srcs / entry["name"], dest)

    baked = tmp_path / "baked"
    a0p.bake(allow, baked, fetcher=fake_fetch)
    return allow, baked


# --- allowlist + bake ------------------------------------------------------

def test_repo_allowlist_is_pinned_and_licensed():
    a0p = _load(A0P, "a0_plugins_t1")
    entries = a0p.parse_allowlist(ALLOW.read_text(encoding="utf-8"))
    names = [e["name"] for e in entries]
    assert names == ["clock_24h", "chat_status_marklet"]
    for e in entries:
        assert re.fullmatch(r"[0-9a-f]{40}", e["commit"])
        assert re.fullmatch(r"[0-9a-f]{64}", e["tree_sha256"])
        assert e["license"] == "MIT"
        assert e["repo"].startswith("https://github.com/")
        assert e["name"] in REVIEWS.read_text(encoding="utf-8")
        assert e["commit"] in REVIEWS.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "line",
    [
        "bad-Name https://github.com/a/b " + "a" * 40 + " MIT " + "b" * 64,
        "_core https://github.com/a/b " + "a" * 40 + " MIT " + "b" * 64,
        "stickllm_apps https://github.com/a/b " + "a" * 40 + " MIT " + "b" * 64,
        "p http://github.com/a/b " + "a" * 40 + " MIT " + "b" * 64,
        "p https://evil.example/a/b " + "a" * 40 + " MIT " + "b" * 64,
        "p https://github.com/a/b main MIT " + "b" * 64,
        "p https://github.com/a/b " + "a" * 40 + " GPL-3.0 " + "b" * 64,
        "p https://github.com/a/b " + "a" * 40 + " MIT short",
        "p https://github.com/a/b " + "a" * 40 + " MIT",
    ],
)
def test_parse_rejects_bad_lines(line):
    a0p = _load(A0P, "a0_plugins_t2")
    with pytest.raises(a0p.AllowlistError):
        a0p.parse_allowlist(line + "\n")


def test_parse_rejects_duplicates():
    a0p = _load(A0P, "a0_plugins_t3")
    line = "p https://github.com/a/b " + "a" * 40 + " MIT " + "b" * 64 + "\n"
    with pytest.raises(a0p.AllowlistError):
        a0p.parse_allowlist(line + line)


def test_bake_ok_writes_manifest(tmp_path):
    a0p = _load(A0P, "a0_plugins_t4")
    allow, baked = _bake_fixture(tmp_path, a0p)
    entry = a0p.parse_allowlist(allow.read_text(encoding="utf-8"))[0]
    manifest = (baked / "MANIFEST").read_text(encoding="utf-8")
    assert manifest == f"good_plugin {entry['commit']} {entry['tree_sha256']}\n"
    assert (baked / "good_plugin" / "plugin.yaml").is_file()
    assert not (baked / "good_plugin" / ".git").exists()


def test_bake_fails_on_hash_mismatch(tmp_path):
    a0p = _load(A0P, "a0_plugins_t5")
    src = tmp_path / "src"
    _write_plugin(src, "p")
    allow = tmp_path / "a.allow"
    allow.write_text(f"p https://github.com/a/p {'a' * 40} MIT {'0' * 64}\n", encoding="utf-8")
    with pytest.raises(a0p.AllowlistError, match="tree sha256"):
        a0p.bake(allow, tmp_path / "out", fetcher=lambda e, d: shutil.copytree(src, d))
    assert not (tmp_path / "out" / "MANIFEST").exists()


def test_bake_fails_on_changed_file(tmp_path):
    a0p = _load(A0P, "a0_plugins_t6")
    src = tmp_path / "src"
    _write_plugin(src, "p")
    tree = a0p.tree_hash(src)
    allow = tmp_path / "a.allow"
    allow.write_text(f"p https://github.com/a/p {'a' * 40} MIT {tree}\n", encoding="utf-8")

    def tampered(entry, dest):
        shutil.copytree(src, dest)
        (dest / "extensions" / "webui" / "initFw_end" / "x.js").write_text("fetch('//x')\n", encoding="utf-8")

    with pytest.raises(a0p.AllowlistError):
        a0p.bake(allow, tmp_path / "out", fetcher=tampered)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_bake_fails_on_commit_pin_mismatch(tmp_path):
    a0p = _load(A0P, "a0_plugins_t7")
    src = tmp_path / "src"
    _write_plugin(src, "p")
    tree = a0p.tree_hash(src)
    allow = tmp_path / "a.allow"
    allow.write_text(f"p https://github.com/a/p {'a' * 40} MIT {tree}\n", encoding="utf-8")

    def git_fetch(entry, dest):
        shutil.copytree(src, dest)
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                   GIT_COMMITTER_EMAIL="t@t")
        for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "x"]):
            subprocess.run(["git", *args], cwd=dest, env=env, check=True, capture_output=True)

    with pytest.raises(a0p.AllowlistError, match="pinned"):
        a0p.bake(allow, tmp_path / "out", fetcher=git_fetch)


def test_bake_cli_exit_code_on_mismatch(tmp_path):
    allow = tmp_path / "a.allow"
    allow.write_text("p https://github.com/a/p main MIT x\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(A0P), "bake", str(allow), str(tmp_path / "o")],
                          capture_output=True, text=True)
    assert proc.returncode == 1
    assert "a0-plugins: FAIL" in proc.stderr


def test_iso_build_bakes_plugins_and_fails_hard():
    text = BUILD.read_text(encoding="utf-8")
    assert "a0_plugins.py bake" in text
    assert "agent-zero-plugins.allow" in text
    assert "set -e" in text or "set -euo" in text


def test_runtime_hash_matches_build_hash(tmp_path, monkeypatch):
    a0p = _load(A0P, "a0_plugins_t8")
    _, _, env = _agent_env(tmp_path, tmp_path / "none", tmp_path / "none2")
    agent = _load_agent(monkeypatch, "stickllm_agent_hash", env)
    _write_plugin(tmp_path / "p", "p")
    for i in range(12):
        (tmp_path / "p" / "webui" / f"d{i % 3}").mkdir(parents=True, exist_ok=True)
        (tmp_path / "p" / "webui" / f"d{i % 3}" / f"f{i}.js").write_text(f"x{i}\n", encoding="utf-8")
    (tmp_path / "p" / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (tmp_path / "p" / "README.md").write_text("r\n", encoding="utf-8")
    assert agent.plugin_tree_hash(tmp_path / "p") == a0p.tree_hash(tmp_path / "p")


# --- runtime assembly ------------------------------------------------------

def test_unlisted_plugins_are_quarantined_not_loaded(tmp_path, monkeypatch):
    a0p = _load(A0P, "a0_plugins_t9")
    allow, baked = _bake_fixture(tmp_path, a0p)
    vault, settings, env = _agent_env(tmp_path, allow, baked)
    # A plugin baked into the ISO dir but NOT on the allowlist is ignored too.
    _write_plugin(baked / "sneaky_baked", "sneaky_baked")
    agent = _load_agent(monkeypatch, "stickllm_agent_assemble", env)
    addon = vault / "addons" / "agent-zero"
    old = addon / "state" / "plugins"
    _write_plugin(old / "evil_plugin", "evil_plugin")
    _write_plugin(old / "good_plugin", "good_plugin", js="tampered()\n")  # user copy of an allowed name
    (old / "_model_config").mkdir(parents=True)
    (old / "_browser").mkdir()
    (old / "_browser" / "config.json").write_text("{}", encoding="utf-8")
    (old / "_browser" / "plugin.yaml").write_text("name: _browser\n", encoding="utf-8")  # shadow attempt
    (old / "_goal" / "goals").mkdir(parents=True)
    (old / "_goal" / "goals" / "g1.json").write_text("{}", encoding="utf-8")
    (addon / "state" / "api").mkdir(parents=True)
    (addon / "state" / "api" / "backdoor.py").write_text("x", encoding="utf-8")
    (addon / "state" / "extensions").mkdir(parents=True)
    (addon / "state" / "extensions" / "hook").mkdir()
    mc = settings / "agent-zero" / "model-config"
    mc.mkdir(parents=True)
    (mc / "presets.yaml").write_text("a: 1\n", encoding="utf-8")
    (mc / "plugin.yaml").write_text("name: _model_config\n", encoding="utf-8")

    agent.assemble_plugins()

    plugins = addon / "plugins"
    assert agent.assembled_plugin_names() == ["good_plugin", "stickllm_apps"]
    assert not (plugins / "evil_plugin").exists()
    assert not (plugins / "sneaky_baked").exists()
    # Allowed plugin comes from the baked ISO copy, not the user's tampered copy.
    js = (plugins / "good_plugin" / "extensions" / "webui" / "initFw_end" / "x.js").read_text(encoding="utf-8")
    assert js == "console.log(1)\n"
    # Built-in data carried over; code files not.
    assert (plugins / "_browser" / "config.json").is_file()
    assert not (plugins / "_browser" / "plugin.yaml").exists()
    assert (addon / "plugin-data" / "_goal" / "goals" / "g1.json").is_file()
    assert (plugins / "_goal" / "goals").is_dir()
    assert (plugins / "_orchestrator" / "data").is_dir()
    assert (plugins / "_model_config").is_dir()
    assert (plugins / ".gitkeep").is_file()
    assert (plugins / "_plugin_scan" / ".toggle-0").is_file()
    # Old dirs emptied; nothing deleted, all moved to quarantine.
    assert list(old.iterdir()) == []
    assert list((addon / "state" / "api").iterdir()) == []
    assert list((addon / "state" / "extensions").iterdir()) == []
    q = addon / "quarantine"
    log = (q / "quarantine.log").read_text(encoding="utf-8")
    for name in ("plugins/evil_plugin", "plugins/good_plugin", "plugins/_browser", "api/backdoor.py",
                 "extensions/hook", "model-config/plugin.yaml"):
        assert name in log
    assert list(q.glob("*/plugins/evil_plugin/plugin.yaml"))
    assert list(q.glob("*/api/backdoor.py"))
    assert (mc / "presets.yaml").is_file()
    assert not (mc / "plugin.yaml").exists()
    # Second start is quiet and stable.
    before = log
    agent.assemble_plugins()
    assert (q / "quarantine.log").read_text(encoding="utf-8") == before
    assert agent.assembled_plugin_names() == ["good_plugin", "stickllm_apps"]


def test_baked_hash_mismatch_is_skipped_at_runtime(tmp_path, monkeypatch):
    a0p = _load(A0P, "a0_plugins_t10")
    allow, baked = _bake_fixture(tmp_path, a0p)
    (baked / "good_plugin" / "plugin.yaml").write_text("name: changed\n", encoding="utf-8")
    vault, _, env = _agent_env(tmp_path, allow, baked)
    agent = _load_agent(monkeypatch, "stickllm_agent_badbake", env)
    agent.assemble_plugins()
    assert agent.assembled_plugin_names() == ["stickllm_apps"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_assembled_dir_is_read_only_on_disk(tmp_path, monkeypatch):
    a0p = _load(A0P, "a0_plugins_t11")
    allow, baked = _bake_fixture(tmp_path, a0p)
    vault, _, env = _agent_env(tmp_path, allow, baked)
    agent = _load_agent(monkeypatch, "stickllm_agent_ro", env)
    plugins = agent.assemble_plugins()
    for path in [plugins, *plugins.rglob("*")]:
        mode = path.stat().st_mode & 0o777
        assert mode & 0o222 == 0, path


def test_container_mounts_plugins_read_only():
    text = RUN.read_text(encoding="utf-8")
    assert '-v "${ADDON}/plugins:/a0/usr/plugins:ro"' in text
    assert '-v "${ADDON}/empty-ro:/a0/usr/api:ro"' in text
    assert '-v "${ADDON}/empty-ro:/a0/usr/extensions:ro"' in text
    assert "--log-driver none" in text
    assert '"$PYBIN" "$LIB" assemble-plugins' in text
    # assemble runs before the container starts
    assert text.index("assemble-plugins") < text.index('docker_cli run --name "$CONTAINER"')
    # The ro plugins mount comes before the nested writable data mounts.
    ro = text.index("/a0/usr/plugins:ro")
    for nested in ("/a0/usr/plugins/_model_config", "/a0/usr/plugins/_goal/goals",
                   "/a0/usr/plugins/_orchestrator/data"):
        assert text.index(nested) > ro
    # The old writable state dir is still /a0/usr, but plugins no longer live there.
    assert "state/plugins" not in text


def test_plugin_skills_removed_in_container():
    text = ENTRY.read_text(encoding="utf-8")
    assert "a0-manage-plugin" in text and "a0-create-plugin" in text
    assert text.index("a0-manage-plugin") < text.index("exec /exe/initialize.sh")


# --- gateway deny ----------------------------------------------------------

@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/plugins/_plugin_installer/plugin_install", b'{"action":"install_git"}'),
        ("POST", "/api/plugins/_plugin_installer/plugin_install", b'{"action":"fetch_index"}'),
        ("POST", "//api/plugins//_plugin_installer/plugin_install", b"{}"),
        ("POST", "/api/plugins/%5Fplugin_installer/plugin_install", b"{}"),
        ("POST", "/api/plugins/x/../_plugin_installer/plugin_install", b"{}"),
        ("POST", "/api/plugins/_plugin_scan/plugin_scan_run", b"{}"),
        ("POST", "/api/plugins/_plugin_validator/plugin_validator_prepare_zip", b"{}"),
        ("POST", "/api/plugins", b'{"action":"delete_plugin","plugin_name":"x"}'),
        ("POST", "/api/plugins/", b'{"action":" Delete_Plugin "}'),
        ("POST", "/api/plugins", b'{"action":"run_execute_script","plugin_name":"x"}'),
        ("POST", "/api/plugins", b"action=delete_plugin"),
        ("GET", "/plugins/_plugin_installer/extensions/webui/plugins-list-header-buttons/install-buttons.html", None),
        ("GET", "/plugins/_plugin_installer/webui/install-index.html", None),
        ("GET", "/plugins/_plugin_installer/webui/main.html", None),
    ],
)
def test_gateway_denies_plugin_install(tmp_path, method, path, body, monkeypatch):
    _, _, env = _agent_env(tmp_path, tmp_path / "a", tmp_path / "b")
    agent = _load_agent(monkeypatch, "stickllm_agent_deny", env)
    assert agent.agent_request_denied(method, path, body) == "plugins_locked"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/plugins", b'{"action":"get_config","plugin_name":"_browser"}'),
        ("POST", "/api/plugins", b'{"action":"toggle_plugin","plugin_name":"clock_24h"}'),
        ("POST", "/api/message_async", b'{"text":"delete_plugin please"}'),
        ("GET", "/plugins/_plugin_installer/webui/pluginInstallStore.js", None),
        ("GET", "/plugins/_plugin_installer/webui/install-shared.css", None),
        ("GET", "/plugins/clock_24h/extensions/webui/initFw_end/clock-24h.js", None),
        ("GET", "/", None),
    ],
)
def test_gateway_allows_normal_agent_calls(tmp_path, method, path, body, monkeypatch):
    _, _, env = _agent_env(tmp_path, tmp_path / "a", tmp_path / "b")
    agent = _load_agent(monkeypatch, "stickllm_agent_allow", env)
    assert agent.agent_request_denied(method, path, body) == ""


def test_gateway_calls_deny_before_relay():
    text = GATEWAY.read_text(encoding="utf-8")
    relay = text[text.index("def _relay_http"):text.index("def _relay_websocket")]
    assert relay.index("agent_request_denied") < relay.index("conn.request(")
    assert '"plugins_locked"' in relay
    serve = text[text.index("def _serve_agent_gateway"):text.index("def _agent_html")]
    assert serve.index("agent_request_denied") < serve.index("self._relay_websocket(")
