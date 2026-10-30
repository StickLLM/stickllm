"""StickLLM 0.5.4: plugins gone, no-model reply, hardware warnings, Trilium setup, unlock polish."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import socket
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "overlay" / "usr" / "local" / "lib"
BIN = ROOT / "overlay" / "usr" / "local" / "bin"
SHARE = ROOT / "overlay" / "usr" / "local" / "share" / "stickllm"
BUILD = ROOT / "scripts" / "lib" / "docker-build-live.sh"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def _load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# --- Agent Zero plugins: none on any path ---------------------------------

def test_plugin_allowlist_is_empty_and_build_enforces_it():
    allow = _text(SHARE / "agent-zero-plugins.allow")
    entries = [ln for ln in allow.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert entries == []
    build = _text(BUILD)
    assert "agent-zero-plugins.allow must be empty" in build
    assert 'test ! -s "$A0_PLUGINS_OUT/MANIFEST"' in build


def test_runtime_gate_and_entrypoint_remove_plugin_manager():
    agent = _text(LIB / "stickllm_agent.py")
    assert "THIRD_PARTY_PLUGINS = False" in agent
    assert "if not THIRD_PARTY_PLUGINS:\n        return {}" in agent
    entry = _text(BIN / "stickllm-agent-entrypoint")
    assert "for plug in _plugin_installer _plugin_scan _plugin_validator; do" in entry
    assert 'rm -rf "/git/agent-zero/plugins/${plug}" "/a0/plugins/${plug}"' in entry
    ui = _text(ROOT / "ui" / "app.js") + _text(ROOT / "ui" / "index.html")
    assert "refreshPluginBadges" not in ui and "agentPlugins" not in ui


def test_verified_manifest_lists_no_plugins():
    doc = json.loads(_text(SHARE / "verified.json"))
    assert not doc.get("plugins")


# --- friendly reply when no model is loaded --------------------------------

@pytest.fixture(scope="module")
def agent():
    return _load(LIB / "stickllm_agent.py", "stickllm_agent_v054")


def _req(path: str, body: dict) -> bytes:
    raw = json.dumps(body).encode()
    return (f"POST {path} HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(raw)}\r\n\r\n").encode() + raw


def test_no_model_reply_plain_and_stream(agent):
    out = agent.no_model_reply(_req("/v1/chat/completions", {"model": "m", "messages": []}))
    head, _, body = out.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 200")
    doc = json.loads(body)
    tool = json.loads(doc["choices"][0]["message"]["content"])
    assert tool["tool_name"] == "response" and "No AI model is loaded" in tool["tool_args"]["text"]
    out = agent.no_model_reply(_req("/v1/chat/completions", {"model": "m", "stream": True}))
    head, _, body = out.partition(b"\r\n\r\n")
    assert b"text/event-stream" in head and body.endswith(b"data: [DONE]\n\n")
    first = json.loads(body.split(b"\n\n")[0][len(b"data: "):])
    assert "No AI model is loaded" in first["choices"][0]["delta"]["content"]
    out = agent.no_model_reply(_req("/v1/embeddings", {"input": "x"}))
    assert out.startswith(b"HTTP/1.1 503") and b"no_model_loaded" in out


def test_relay_answers_when_llama_is_down(agent):
    dead = socket.socket()
    dead.bind(("127.0.0.1", 0))
    dead_port = dead.getsockname()[1]
    dead.close()  # nothing listens here: connect is refused
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    threading.Thread(target=agent.run_tcp_relay, args=("127.0.0.1", port, "127.0.0.1", dead_port),
                     daemon=True).start()
    import time
    for _ in range(50):
        try:
            c = socket.create_connection(("127.0.0.1", port), timeout=2)
            break
        except OSError:
            time.sleep(0.05)
    c.sendall(_req("/v1/chat/completions", {"model": "m"}))
    data = b""
    c.settimeout(10)
    while True:
        got = c.recv(65536)
        if not got:
            break
        data += got
    c.close()
    assert data.startswith(b"HTTP/1.1 200") and b"No AI model is loaded" in data


def test_gateway_chat_says_no_model_loaded():
    gw = _text(BIN / "stickllm-gateway")
    assert "No AI model is loaded yet (or it is still loading)" in gw


# --- hardware warnings: warn, never fail -----------------------------------

def test_hardware_warnings():
    sysmod = _load(LIB / "stickllm_system.py", "stickllm_system_v054")
    noavx = "processor : 0\nflags : fpu sse sse2 ssse3\n"
    w = sysmod.hardware_warnings(noavx, None, 0)
    assert any("no AVX" in x for x in w) and any("No NVIDIA GPU" in x for x in w)
    w = sysmod.hardware_warnings("flags : avx sse\n", 4.0, 1)
    assert any("not AVX2" in x for x in w) and any("4.0 GB" in x for x in w)
    assert sysmod.hardware_warnings("flags : avx avx2\n", 24.0, 1) == []
    assert sysmod.hardware_warnings("", None, None) == []
    ctl = _text(BIN / "stickllm-control")
    assert '"hw_warnings"' in ctl
    js = _text(ROOT / "ui" / "app.js")
    assert "hw_warnings" in js and 'id="hwWarn"' in _text(ROOT / "ui" / "index.html")


# --- Trilium: no login, automatic first-boot setup --------------------------

def test_trilium_no_auth_and_setup(monkeypatch):
    addons = _load(LIB / "stickllm_addons.py", "stickllm_addons_v054")
    spec = addons.app("trilium")
    assert ("TRILIUM_GENERAL_NOAUTHENTICATION", "true") in tuple(spec["env"])
    assert spec["post_start"] == "trilium-setup"
    calls = []
    state = {"init": False}

    def fake_http(method, port, path, timeout=10.0):
        calls.append((method, path))
        if path == "/api/setup/status":
            return 200, json.dumps({"isInitialized": state["init"]}).encode()
        if method == "POST" and path == "/api/setup/new-document?skipDemoDb=true":
            state["init"] = True
            return 200, b"{}"
        return 404, b""

    monkeypatch.setattr(addons, "_http", fake_http)
    monkeypatch.setattr(addons.time, "sleep", lambda s: None)
    out = addons.post_start("trilium", wait=5)
    assert out["ok"] and out["created"] and out["hook"] == "trilium-setup"
    calls.clear()
    out = addons.post_start("trilium", wait=5)
    assert out["ok"] and not out["created"]
    assert ("POST", "/api/setup/new-document?skipDemoDb=true") not in calls
    assert addons.post_start("tasks-md")["hook"] == ""


def test_comfyui_unblocked_and_gpu_optional():
    addons = _load(LIB / "stickllm_addons.py", "stickllm_addons_v054c")
    assert "comfyui" in addons.ORDER
    assert not hasattr(addons, "PARKED_APPS") or not addons.PARKED_APPS
    verify = _load(LIB / "stickllm_verify.py", "stickllm_verify_v054")
    assert "comfyui" not in verify.BLOCKED_APPS
    assert "comfyui" not in _text(SHARE / "blocked-apps.list").split("#", 1)[0]
    assert (SHARE / "addons" / "comfyui.pin").is_file()


# --- vault unlock polish ------------------------------------------------------

def test_unlock_no_flash_and_hidden_form_error():
    js = _text(ROOT / "ui" / "app.js")
    assert 'if (usb === "present-locked" || usb === "unlocked") return false;' in js
    assert "if (vaultUnlocking) return false;" in js
    assert "async function focusVaultUnlock()" in js
    assert "The unlock form is not available." in js
    assert 'unlockMessage("Unlock failed: " + err.message);' in js
    html = _text(ROOT / "ui" / "index.html")
    assert '<small class="unlockMsg" id="unlockMsg" role="alert" hidden></small>' in html
    assert "No vault set up" not in html


def test_vault_mode_switch_treats_present_locked_as_locked():
    """Switching to Vault mode before the first unlock must ask for the passcode,
    not say "No vault yet" (status reads "absent" with usb_settings present-locked)."""
    js = _text(ROOT / "ui" / "app.js")
    body = js[js.index("async function setSessionMode(m)"):]
    body = body[: body.index("\n}\n")]
    assert "vaultIsAbsent(vault)" in body
    assert 'st === "absent" || !st' not in body
    assert body.index("vaultIsAbsent(vault)") < body.index("await focusVaultUnlock();")


# --- rc2: mode tabs follow the vault; lock clears the screen -----------------

def test_lock_clear_node_unit():
    import shutil, subprocess
    if not shutil.which("node"):
        pytest.skip("node not installed")
    out = subprocess.run(["node", str(Path(__file__).with_name("lock_clear.test.js"))],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "lock clear ok" in out.stdout


def test_health_mode_needs_open_vault():
    """refreshStatus highlights Vault only when health says the vault is open."""
    js = _text(ROOT / "ui" / "app.js")
    assert 'applyModeUi(j.session_mode === "vault" ? "vault" : "ephemeral")' not in js
    assert 'applyModeUi(j.session_mode === "vault" && vOpen ? "vault" : "ephemeral")' in js


def test_gateway_health_reports_ephemeral_when_locked():
    gw = _text(ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway")
    i = gw.index("session_mode = get_session_mode()\n            vault_doc = vault_health()")
    block = gw[i:i + 600]
    assert 'if session_mode == "vault" and not vault_doc.get("mounted"):' in block
    assert '"vault": vault_doc,' in gw


def test_every_lock_path_clears_screen():
    js = _text(ROOT / "ui" / "app.js")
    lock = js[js.index("async function lockVault("):]
    lock = lock[: lock.index("\n}\n")]
    assert lock.index("clearOnLock();") < lock.index('control("vault_lock")')
    # Ctrl+Shift+L and both lock buttons go through lockVault.
    assert '$("#lockBtn").onclick = () => lockVault();' in js
    assert '$("#lockBtn2").onclick = () => lockVault();' in js
    assert 'if (e.ctrlKey && e.shiftKey && k === "l") { e.preventDefault(); lockVault(); }' in js
    # Any open->locked change (kiosk combo, other browser) clears via setVaultChrome.
    chrome = js[js.index("function setVaultChrome("):]
    chrome = chrome[: chrome.index("\n}\n")]
    assert "clearOnLock()" in chrome
    assert 'applyModeUi("ephemeral")' in chrome


def test_ui_cache_bust_v055():
    html = _text(ROOT / "ui" / "index.html")
    assert "app.js?v=v055" in html and "style.css?v=v055" in html
    assert "v054a" not in html and "v054b" not in html
