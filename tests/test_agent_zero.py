"""Agent Zero gates: unlock does not install, and unpaired :5443 is refused."""
from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
AGENT = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_agent.py"
SCRIPT = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-agent"
ENTRY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-agent-entrypoint"
LLAMA = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-llama-start"
PIN = ROOT / "overlay" / "usr" / "local" / "share" / "stickllm" / "agent-zero.pin"
PACKAGES = ROOT / "live-build" / "package-lists" / "stickllm.list.chroot"


def _load(path: Path, name: str, env: dict | None = None):
    if env:
        os.environ.update(env)
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_pin_is_a_real_digest():
    agent = _load(AGENT, "stickllm_agent_pin")
    pin = agent.load_pin(PIN)
    assert pin["image"] == "agent0ai/agent-zero"
    assert pin["version"] == "v2.14"
    assert pin["amd64_digest"] == (
        "sha256:307a2ceffc8501ba05a1e7253e8b6e4d656d2e1c3b97f0eb943c18b9c40a30fd"
    )
    assert agent.image_ref(pin).endswith("@" + pin["amd64_digest"])


def test_locked_vault_does_not_allow_docker():
    agent = _load(AGENT, "stickllm_agent_gate")
    assert agent.docker_may_start(False) is False
    assert agent.docker_may_start(True) is True
    assert agent.MIN_FREE_BYTES == 12 * 1024 * 1024 * 1024
    assert agent.pull_allowed(agent.MIN_FREE_BYTES - 1) is False
    assert agent.pull_allowed(agent.MIN_FREE_BYTES) is True
    assert agent.pull_allowed(15_000_000_000) is True
    assert agent.pull_allowed(None) is False
    # A large vault does not satisfy a small SSD folder.
    assert agent.pull_allowed(1024) is False


def test_docker_dir_is_beside_models_and_missing_ssd_is_visible(tmp_path):
    host = tmp_path / "host" / "nvme0n1p3"
    models = host / "home" / "someone" / "models"
    models.mkdir(parents=True)
    mounts_file = tmp_path / "mounts"
    mounts_file.write_text(f"ext4 {host} ext4 rw 0 0\n", encoding="utf-8")
    models_file = tmp_path / "models-dir.json"
    models_file.write_text(json.dumps({"path": str(models)}), encoding="utf-8")
    agent = _load(
        AGENT,
        "stickllm_agent_dockerdir",
        {
            "STICKLLM_VAULT_MNT": str(tmp_path / "vault"),
            "STICKLLM_HOST_MNT": str(tmp_path / "host"),
            "STICKLLM_MOUNTS_FILE": str(mounts_file),
            "STICKLLM_MODELS_DIR_FILE": str(models_file),
            "STICKLLM_DOCKER_DIR": "",
        },
    )
    (tmp_path / "vault").mkdir()
    root = agent.docker_data_root(use_env=False)
    assert root == models.parent / "stickllm-docker"
    assert "vault" not in root.parts
    assert root.name == "stickllm-docker"
    explicit = agent.docker_data_root(
        models=models,
        mounts=[str(host)],
        use_env=False,
    )
    assert explicit == models.parent / "stickllm-docker"
    assert agent.docker_data_root(mounts=[], use_env=False) is None
    missing = agent.status_document(
        vault_open=True,
        settings_open=True,
        upstream_up=False,
        saved={},
        mounts=[],
    )
    assert missing["message"] == "Mount a drive for Agent Zero"
    assert missing["state"] == "no_ssd"
    assert missing["needs_install"] is False
    ready = agent.status_document(
        vault_open=True,
        settings_open=True,
        upstream_up=False,
        saved={"image_present": False},
        mounts=[str(host)],
    )
    assert ready["needs_install"] is True
    assert ready["message"] == "Agent Zero is not installed yet"
    assert "vault" not in agent.LOW_SPACE_MESSAGE.lower()
    assert "12 GB" in agent.LOW_SPACE_MESSAGE
    inside = agent.docker_data_root(override=str(tmp_path / "vault" / "docker"), use_env=False)
    assert inside is None


def test_run_does_not_install_and_checks_the_ssd_folder():
    text = _script()
    run = text.split("cmd_run()", 1)[1].split("\ncmd_stop()", 1)[0]
    assert "cmd_install" not in run
    assert "docker_cli pull" not in run
    assert "Unlock starts a container that is already installed" in run
    install = text.split("cmd_install()", 1)[1].split("\nstop_container()", 1)[0]
    assert "docker_cli pull" in install
    assert "pull-allowed" in install
    assert "Mount a drive for Agent Zero" in text
    assert "host SSD has under 12 GB free" in text
    assert "vault free space" not in text
    assert "15 GB" not in text
    assert '${VAULT}/docker' not in text
    assert "--data-root \"${DOCKER_DIR}\"" in text
    assert 'SOCK="/run/stickllm/agent-docker.sock"' in text
    assert "apparmor=unconfined" not in text
    assert "no-new-privileges=true" in text
    assert "no-new-privileges:true" not in text
    assert "--network host" not in text
    assert "-p 127.0.0.1:5099:5099" in text
    assert "nft-apply" in text
    assert "nft-delete" in text
    assert "ALLOWED_ORIGINS" in text
    assert "--iptables=false" in text
    assert "0.0.0.0:8080" not in text
    assert "kitten" not in text.lower()
    assert "whisper-server" not in text
    body = text.split("cmd_run_container()", 1)[1].split("\ncmd_run()", 1)[0]
    assert "docker-may-start" in body
    assert body.index("docker-may-start") < body.index("ensure_dockerd")
    daemon = text.split("ensure_dockerd()", 1)[1].split("\nimage_present()", 1)[0]
    assert daemon.index("docker-may-start") < daemon.index("\n  dockerd")


def test_agent_page_is_not_rewritten_under_agent():
    agent = _load(AGENT, "stickllm_agent_norewrite")
    assert not hasattr(agent, "rewrite_text")
    assert not hasattr(agent, "upstream_path")
    assert not hasattr(agent, "rewrite_location")
    preset = agent.preset_text("qwen.gguf")
    assert agent.LLAMA_BASE in preset
    assert "172.30.0.1:8080/v1" in preset
    assert "device: cpu" in preset
    assert "llama_cpp" in preset
    rules = agent.nft_ruleset()
    assert rules.index("172.30.0.0/24") < rules.index("192.168.0.0/16")
    assert rules.index("172.30.0.0/24") < rules.index("10.0.0.0/8")
    assert rules.index("172.30.0.0/24") < rules.index("172.16.0.0/12")
    assert "drop" in rules
    gateway = GATEWAY.read_text(encoding="utf-8")
    assert "rewrite_text" not in gateway
    assert "rewrite_bytes" not in gateway
    assert 'path == "/agent"' not in gateway
    assert "stickllm_agent_gateway" in gateway
    assert "5443" in gateway
    entry = ENTRY.read_text(encoding="utf-8")
    assert "--host=127.0.0.1" not in entry
    assert "--port=5099" in entry
    llama = LLAMA.read_text(encoding="utf-8")
    assert "--jinja" in llama
    assert 'HOST="${STICKLLM_LLAMA_HOST:-127.0.0.1}"' in llama
    assert "--host 0.0.0.0" not in llama
    packages = PACKAGES.read_text(encoding="utf-8")
    assert "\napparmor\n" in packages
    assert "\nnftables\n" in packages
    origins = agent.allowed_origins(["192.168.72.70"])
    assert origins.startswith("https://192.168.72.70:5443")
    assert "https://127.0.0.1:5443" in origins


def test_llama_relay_forwards_on_loopback_only():
    agent = _load(AGENT, "stickllm_agent_relay")
    assert agent.LLAMA_BRIDGE_HOST != "0.0.0.0"
    try:
        agent.run_tcp_relay("0.0.0.0", 9, "127.0.0.1", 9)
        raise AssertionError("relay accepted 0.0.0.0")
    except SystemExit:
        pass
    target = socket.socket()
    target.bind(("127.0.0.1", 0))
    target.listen(1)
    tport = target.getsockname()[1]

    def accept_one() -> None:
        conn, _addr = target.accept()
        data = conn.recv(100)
        conn.sendall(b"ok:" + data)
        conn.close()

    threading.Thread(target=accept_one, daemon=True).start()
    listen = socket.socket()
    listen.bind(("127.0.0.1", 0))
    lport = listen.getsockname()[1]
    listen.close()
    threading.Thread(
        target=agent.run_tcp_relay,
        args=("127.0.0.1", lport, "127.0.0.1", tport),
        daemon=True,
    ).start()
    client = socket.socket()
    last = None
    for _ in range(30):
        try:
            client.connect(("127.0.0.1", lport))
            break
        except OSError as exc:
            last = exc
            time.sleep(0.05)
    else:
        raise AssertionError(f"relay did not listen: {last}")
    client.sendall(b"ping")
    client.shutdown(socket.SHUT_WR)
    data = b""
    client.settimeout(2)
    while True:
        try:
            chunk = client.recv(100)
        except OSError:
            break
        if not chunk:
            break
        data += chunk
    client.close()
    target.close()
    assert data == b"ok:ping"


def test_unpaired_agent_port_is_refused(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html></html>", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    token = "paired-token"
    auth = {
        "require_pair": True,
        "paired": True,
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
    }
    (run / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    env = {
        "STICKLLM_UI": str(ui),
        "STICKLLM_RUN": str(run),
        "STICKLLM_VAULT_MNT": str(tmp_path / "vault"),
        "STICKLLM_SETTINGS_MNT": str(tmp_path / "settings"),
        "STICKLLM_AGENT_STATUS": str(run / "agent-status.json"),
        "STICKLLM_AGENT_PIN": str(PIN),
        "STICKLLM_MOUNTS_FILE": str(tmp_path / "empty-mounts"),
        "STICKLLM_AGENT_TLS_PORT": "5443",
    }
    (tmp_path / "empty-mounts").write_text("", encoding="utf-8")
    (tmp_path / "vault").mkdir()
    gateway = _load(GATEWAY, "stickllm_gateway_agent", env)
    assert gateway.AGENT_TLS_PORT == 5443

    class LanHandler(gateway.Handler):
        def _is_loopback(self) -> bool:
            return False

    httpd = gateway.ThreadingHTTPServer(("127.0.0.1", 0), LanHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    agent_httpd = gateway.ThreadingHTTPServer(("127.0.0.1", 0), LanHandler)
    agent_httpd.stickllm_agent_gateway = True
    agent_port = agent_httpd.server_address[1]
    agent_thread = threading.Thread(target=agent_httpd.serve_forever, daemon=True)
    agent_thread.start()
    try:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{agent_port}/", timeout=5)
            raise AssertionError("unpaired agent port was allowed")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode()
            assert exc.code == 401
            assert "pair_required" in body

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{agent_port}/ui/index", timeout=5)
            raise AssertionError("unpaired agent asset was allowed")
        except urllib.error.HTTPError as exc:
            assert exc.code == 401

        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/agent", timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("main gateway still served /agent")

        status_req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/agent/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(status_req, timeout=5) as resp:
            doc = json.loads(resp.read().decode())
        assert doc["vault_unlocked"] is False
        assert doc["message"] == "Unlock vault to use Agent"
        assert doc["gateway_port"] == 5443
        assert doc["agent_url"].endswith(":5443/")

        page_req = urllib.request.Request(
            f"http://127.0.0.1:{agent_port}/ui/asset-bundle",
            headers={"Cookie": f"stickllm_pair={token}"},
        )
        with urllib.request.urlopen(page_req, timeout=5) as resp:
            html = resp.read().decode()
        assert "Unlock vault to use Agent" in html
        assert 'href="https://127.0.0.1/"' in html
        assert "Back to StickLLM" in html
        assert ":5443" not in html
        assert 'href="/"' not in html
        assert "/agent/" not in html

        lan_req = urllib.request.Request(
            f"http://127.0.0.1:{agent_port}/",
            headers={"Cookie": f"stickllm_pair={token}", "Host": "192.168.72.70:5443"},
        )
        with urllib.request.urlopen(lan_req, timeout=5) as resp:
            lan_html = resp.read().decode()
        assert 'href="https://192.168.72.70/"' in lan_html
        assert ":5443" not in lan_html
        assert 'href="/"' not in lan_html
    finally:
        httpd.shutdown()
        agent_httpd.shutdown()


def test_interstitial_links_home_not_agent_port():
    agent = _load(AGENT, "stickllm_agent_home_link")
    assert agent.stickllm_home_url("192.168.72.70:5443") == "https://192.168.72.70/"
    assert agent.stickllm_home_url("[2001:db8::1]:5443") == "https://[2001:db8::1]/"
    assert ":5443" not in agent.stickllm_home_url("192.168.72.70:5443")
    locked = {"state": "locked", "message": "Unlock vault to use Agent"}
    html = agent.status_html(locked, home="https://192.168.72.70/")
    assert "Unlock vault to use Agent" in html
    assert html.count('href="https://192.168.72.70/"') >= 2
    assert "Back to StickLLM" in html
    assert ":5443" not in html
    assert 'href="/"' not in html
    rejected = agent.status_html(locked, home="https://192.168.72.70:5443/")
    assert ":5443" not in rejected
    assert 'href="https://127.0.0.1/"' in rejected
    missing = {
        "state": "needs_install",
        "message": "Agent Zero is not installed yet",
        "needs_install": True,
    }
    page = agent.status_html(missing, home="https://192.168.72.70/")
    assert "Agent Zero is not installed yet" in page
    assert 'href="https://192.168.72.70/"' in page
    assert 'action="/install"' in page
    assert ":5443" not in page


def test_agent_sidebar_opens_a_new_tab():
    html = (ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    side = html.split('<aside class="sidebar"', 1)[1].split("</aside>", 1)[0]
    assert 'id="agentLink"' in side
    tag_at = side.index('id="agentLink"')
    tag = side[side.rfind("<", 0, tag_at) : side.index(">", tag_at) + 1]
    assert tag.rstrip(">").split()[-1] == "hidden"
    assert 'target="_blank"' in side
    assert "noopener" in side
    assert ":5443" in side
    assert 'id="appsLink"' in side
    assert "comfyLink" not in side
    assert "writerLink" not in side
    assert "Comfy" not in side
    assert "Word processor" not in side
    apps_at = side.index('id="appsLink"')
    apps_tag = side[side.rfind("<", 0, apps_at) : side.index(">", apps_at) + 1]
    assert apps_tag.startswith("<button")
    assert "target=" not in apps_tag
    assert ":5443" not in apps_tag
    js = (ROOT / "ui" / "app.js").read_text(encoding="utf-8")
    assert 'link.target = "_blank"' in js
    assert "noopener" in js
    assert 'label.textContent = "Agent"' in js
    assert "function agentIsInstalled" in js
    assert "link.hidden = !installed" in js
    assert "agentDeskIcon" in js
    assert "agent-zero.png" in js
    assert 's.state === "starting"' in js
    logo = ROOT / "ui" / "agent-zero.png"
    raw = logo.read_bytes()
    assert raw.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(raw) > 10000


def test_console_browser_keeps_a_tab_strip():
    text = (ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-kiosk").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        assert "--kiosk" not in line
        assert "--app=" not in line
        assert " --app " not in f" {line} "
        assert "--no-sandbox" not in line
        assert "userChrome" not in line
    assert 'KIOSK_USER="${STICKLLM_KIOSK_USER:-stickllm}"' in text
    assert "--hide-crash-restore-bubble" in text
    assert "clear_restore_prompt" in text
    assert "FullscreenAllowed" in text
    assert "ensure_browser_tabs" in text
    policy = json.loads(
        (
            ROOT / "overlay" / "etc" / "chromium" / "policies" / "managed" / "stickllm-tabs.json"
        ).read_text(encoding="utf-8")
    )
    assert policy["FullscreenAllowed"] is False
