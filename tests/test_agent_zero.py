"""Agent Zero gates: unlock does not install, and unpaired :5443 is refused."""
from __future__ import annotations

import base64
import fnmatch
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import socket
import subprocess
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
    assert "write-status --state error" in text
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
    assert "timeout: 90" in preset
    assert "api_key: dummy" in preset
    script = _script()
    assert "HF_HUB_OFFLINE" in script
    assert "embedding-cached" in script
    rules = agent.nft_ruleset()
    assert rules.index("172.30.0.0/24") < rules.index("192.168.0.0/16")
    assert rules.index("172.30.0.0/24") < rules.index("10.0.0.0/8")
    assert rules.index("172.30.0.0/24") < rules.index("172.16.0.0/12")
    assert "drop" in rules
    assert 'iifname "lo" accept' in rules
    gateway = GATEWAY.read_text(encoding="utf-8")
    assert "agent_proxy_headers" in gateway
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
    parts = origins.split(",")
    assert "https://192.168.72.70:5443" in parts
    assert "*://127.0.0.1:*" in parts
    assert "https://192.168.72.70" not in parts


def test_allowed_origins_include_lan_port_not_the_bare_host(tmp_path):
    """A browser on another PC sends Origin https://<lan-ip>:5443.

    Agent Zero's matcher is fnmatch. ``https://<ip>`` does not match that
    origin, so the generated list has to carry the gateway port itself.
    """
    agent = _load(AGENT, "stickllm_agent_origins_port")
    origins = agent.allowed_origins(["192.168.72.70", "127.0.0.1", "10.9.8.7"])
    parts = origins.split(",")
    browser = "https://192.168.72.70:5443"
    assert "https://192.168.72.70:5443" in parts
    assert "*://192.168.72.70:*" in parts
    assert "https://10.9.8.7:5443" in parts
    assert "*://10.9.8.7:*" in parts
    assert "https://192.168.72.70" not in parts
    assert "https://10.9.8.7" not in parts
    assert "https://127.0.0.1:5443" not in parts
    assert "*://localhost" in parts
    assert "*://localhost:*" in parts
    assert "*://127.0.0.1" in parts
    assert "*://127.0.0.1:*" in parts
    assert any(fnmatch.fnmatch(browser, item) for item in parts)
    assert not fnmatch.fnmatch(browser, "https://192.168.72.70")
    bare_only = [
        "*://localhost",
        "*://localhost:*",
        "*://127.0.0.1",
        "*://127.0.0.1:*",
        "*://0.0.0.0",
        "*://0.0.0.0:*",
        "https://192.168.72.70",
    ]
    assert not any(fnmatch.fnmatch(browser, item) for item in bare_only)
    assert any(fnmatch.fnmatch("http://127.0.0.1:5099", item) for item in parts)
    assert not any(":5099" in item and "192.168.72.70" in item for item in parts)
    assert "-p 127.0.0.1:5099:5099" in _script()
    env = tmp_path / ".env"
    env.write_text(
        "API_KEY_LLAMA_CPP=dummy\n"
        "ALLOWED_ORIGINS=*://localhost,*://127.0.0.1,https://192.168.72.70\n",
        encoding="utf-8",
    )
    agent.ensure_env_file(env, origins=origins)
    text = env.read_text(encoding="utf-8")
    assert "API_KEY_LLAMA_CPP=dummy" in text
    stored = next(
        line.split("=", 1)[1]
        for line in text.splitlines()
        if line.startswith("ALLOWED_ORIGINS=")
    )
    assert stored.split(",") == parts
    assert "https://192.168.72.70" not in stored.split(",")
    assert "https://192.168.72.70:5443" in stored.split(",")


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
    assert 's.state === "error"' in js
    assert "http://127.0.0.1:5099/" in js
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
        assert "--allow-insecure-localhost" not in line
        assert "--ignore-certificate-errors" not in line
        assert "--disable-web-security" not in line
        assert "--test-type" not in line
        assert "userChrome" not in line
    assert 'KIOSK_USER="${STICKLLM_KIOSK_USER:-stickllm}"' in text
    assert "--hide-crash-restore-bubble" in text
    assert "clear_restore_prompt" in text
    assert "FullscreenAllowed" in text
    assert "ensure_browser_tabs" in text
    assert "http://127.0.0.1:5099/" in text
    assert "chromium_trust_args" not in text
    assert "stick_cert_spki" not in text
    policy = json.loads(
        (
            ROOT / "overlay" / "etc" / "chromium" / "policies" / "managed" / "stickllm-tabs.json"
        ).read_text(encoding="utf-8")
    )
    assert policy["FullscreenAllowed"] is False
    assert "http://127.0.0.1" in policy["PopupsAllowedForUrls"]


def _nft_check(text: str) -> None:
    """Run ``nft -c -f -`` when nft or a bookworm container is available.

    Debian 12's nftables is 1.0.6. ``destroy table`` is rejected there, so the
    generated script must check cleanly on that version. When neither nft nor
    Docker is available, the caller still asserts the script text.
    """
    payload = text.replace("\r\n", "\n").encode()
    nft = shutil.which("nft")
    if nft:
        proc = subprocess.run(
            [nft, "-c", "-f", "-"],
            input=payload,
            capture_output=True,
            timeout=30,
            check=False,
        )
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace")
        assert proc.returncode == 0, err
        return
    docker = shutil.which("docker")
    if not docker:
        return
    # Bytes on a Windows pipe can still arrive as CRLF. Pass the ruleset as
    # base64 so nft 1.0.6 sees the real newlines.
    encoded = base64.b64encode(payload).decode("ascii")
    script = f"""
printf '%s' '{encoded}' | base64 -d >/tmp/ok.nft || exit 1
apt-get update -qq || exit 1
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nftables >/dev/null || exit 1
nft --version || exit 1
nft -c -f /tmp/ok.nft || exit 1
if nft --version | grep -q 'v1.0.6'; then
  if printf '%s\\n' 'destroy table inet stickllm_agent' | nft -c -f -; then
    echo DESTROY_ACCEPTED >&2
    exit 4
  fi
fi
"""
    try:
        proc = subprocess.run(
            [docker, "run", "--rm", "--cap-add", "NET_ADMIN", "debian:bookworm", "bash", "-lc", script],
            capture_output=True,
            timeout=240,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    combined = ((proc.stdout or b"") + (proc.stderr or b"")).decode("utf-8", "replace")
    lowered = combined.lower()
    if proc.returncode != 0 and "v1.0." not in combined and any(
        part in lowered for part in ("cannot connect", "error during connect", "daemon", "not found")
    ):
        return
    assert proc.returncode == 0, combined[-2500:]
    if "v1.0." in combined:
        assert "v1.0.6" in combined


def test_nft_apply_text_is_safe_on_debian12():
    agent = _load(AGENT, "stickllm_agent_nft")
    text = agent.nft_apply_text()
    assert text.startswith("add table inet stickllm_agent\n")
    assert "delete table inet stickllm_agent\n" in text
    assert agent.nft_ruleset().strip() in text
    for line in text.splitlines():
        assert line.strip() != "destroy table inet stickllm_agent"
        assert not line.strip().startswith("destroy table")
    assert "destroy table" not in text
    _nft_check(text)
    doc = agent.status_document(
        vault_open=True,
        settings_open=True,
        upstream_up=False,
        saved={
            "state": "error",
            "image_present": True,
            "message": "syntax error, unexpected destroy",
        },
        mounts=["/mnt/host"],
    )
    assert doc["state"] == "error"
    assert doc["message"] == "syntax error, unexpected destroy"
    assert doc["needs_install"] is False
    assert "starting" not in doc["message"].lower()
    page = agent.status_html(doc)
    assert "Agent failed to start" in page
    assert "unexpected destroy" in page
    assert "Agent is starting" not in page
    running = agent.status_document(
        vault_open=True,
        settings_open=True,
        upstream_up=True,
        saved={"state": "error", "image_present": True, "message": "old"},
        mounts=["/mnt/host"],
    )
    assert running["state"] == "running"


def test_loopback_agent_url_stays_on_the_stick(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "index.html").write_text("<html></html>", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
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
    token = "paired-token"
    (run / "auth.json").write_text(
        json.dumps(
            {
                "require_pair": True,
                "paired": True,
                "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    gateway = _load(GATEWAY, "stickllm_gateway_loop_agent", env)

    class LanHandler(gateway.Handler):
        def _is_loopback(self) -> bool:
            return False

    lan = gateway.ThreadingHTTPServer(("127.0.0.1", 0), LanHandler)
    local = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
    threads = [
        threading.Thread(target=lan.serve_forever, daemon=True),
        threading.Thread(target=local.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{local.server_address[1]}/api/agent/status", timeout=5) as resp:
            doc = json.loads(resp.read().decode())
        assert doc["agent_url"] == "http://127.0.0.1:5099/"
        assert ":5443" not in doc["agent_url"]
        unpaired = urllib.request.Request(
            f"http://127.0.0.1:{lan.server_address[1]}/api/agent/status",
            headers={"Host": "192.168.72.70"},
        )
        try:
            urllib.request.urlopen(unpaired, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
        else:
            raise AssertionError("unpaired LAN status was allowed")
        paired = urllib.request.Request(
            f"http://127.0.0.1:{lan.server_address[1]}/api/agent/status",
            headers={"Host": "192.168.72.70", "Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(paired, timeout=5) as resp:
            lan_doc = json.loads(resp.read().decode())
        assert lan_doc["agent_url"] == "https://192.168.72.70:5443/"
    finally:
        lan.shutdown()
        local.shutdown()
    run_text = _script()
    assert "-p 127.0.0.1:5099:5099" in run_text
    assert "-p 0.0.0.0:5099" not in run_text
    assert "-p 5099:5099" not in run_text


def test_model_settings_merge_keeps_user_fields_and_uses_the_relay(tmp_path):
    agent = _load(AGENT, "stickllm_agent_model_merge")
    model_id = "/models/Qwen3.6-35B-A3B-Q8_0.gguf"
    assert agent.model_id_from_list(
        {"data": [{"id": model_id}, {"id": "other"}]},
        "fallback.gguf",
    ) == model_id
    assert agent.model_id_from_list({}, "fallback.gguf") == "fallback.gguf"
    existing = {
        "auth_login": "kept",
        "secrets": {"token": "leave-me"},
        "chat_model_provider": "openrouter",
        "chat_model_name": "openai/gpt-5.6-terra",
        "workdir_path": "/a0/usr/workdir",
    }
    merged = agent.merge_model_settings(existing, model_id)
    assert merged["auth_login"] == "kept"
    assert merged["secrets"] == {"token": "leave-me"}
    assert merged["workdir_path"] == "/a0/usr/workdir"
    assert merged["chat_model_provider"] == "llama_cpp"
    assert merged["util_model_provider"] == "llama_cpp"
    assert merged["chat_model_name"] == model_id
    assert merged["util_model_name"] == model_id
    assert merged["chat_model_api_base"] == agent.LLAMA_BASE
    assert merged["util_model_api_base"] == agent.LLAMA_BASE
    assert merged["chat_model_ctx_length"] == 32768
    assert merged["chat_model_kwargs"]["api_key"] == "dummy"
    assert merged["chat_model_kwargs"]["timeout"] == 90
    headers = agent.agent_proxy_headers(
        {
            "Host": "192.168.72.70:5443",
            "Origin": "https://192.168.72.70:5443",
            "Content-Length": "4",
            "Connection": "keep-alive",
        }
    )
    assert headers["Host"] == "127.0.0.1:5099"
    assert headers["X-Forwarded-Host"] == "192.168.72.70:5443"
    assert headers["X-Forwarded-Proto"] == "https"
    assert headers["Origin"] == "https://192.168.72.70:5443"
    assert "Content-Length" not in headers
    assert "Connection" not in headers
    socket_headers = agent.agent_proxy_headers(
        {"Host": "192.168.72.70:5443", "Connection": "Upgrade", "Upgrade": "websocket"},
        websocket=True,
    )
    assert socket_headers["Connection"] == "Upgrade"
    assert socket_headers["X-Forwarded-Host"] == "192.168.72.70:5443"
    cache = tmp_path / "sentence-transformers" / "snapshots"
    cache.mkdir(parents=True)
    weights = cache / "model.safetensors"
    weights.write_bytes(b"x" * 1_000_001)
    assert agent.embedding_cached(tmp_path / "sentence-transformers")
    assert not agent.embedding_cached(tmp_path / "missing")


def test_apps_bridge_serves_only_static_apps(tmp_path):
    apps = tmp_path / "ui" / "apps"
    calc = apps / "calculator"
    calc.mkdir(parents=True)
    (calc / "index.html").write_text("<title>Calculator — StickLLM</title>\n", encoding="utf-8")
    (calc / "calc.js").write_text("/* 12*34 */\n", encoding="utf-8")
    (tmp_path / "ui" / "index.html").write_text("chat", encoding="utf-8")
    agent = _load(AGENT, "stickllm_agent_apps_only")
    root = apps
    assert agent.apps_target(root, "/apps/calculator/").name == "index.html"
    assert agent.apps_target(root, "/apps/calculator/calc.js").name == "calc.js"
    assert agent.apps_target(root, "/api/chat") is None
    assert agent.apps_target(root, "/api/vault") is None
    assert agent.apps_target(root, "/") is None
    assert agent.apps_target(root, "/apps/../index.html") is None
    assert agent.apps_target(root, "/index.html") is None
    try:
        agent.apps_server("0.0.0.0", 0, root)
    except SystemExit as exc:
        assert "all interfaces" in str(exc)
    else:
        raise AssertionError("apps bridge accepted 0.0.0.0")
    httpd = agent.apps_server("127.0.0.1", 0, root)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/apps/calculator/", timeout=5) as resp:
            page = resp.read().decode("utf-8")
            assert resp.status == 200
            assert "Calculator" in page
        for blocked in ("/api/chat", "/api/vault", "/", "/apps/../index.html"):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}{blocked}", timeout=5)
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
            else:
                raise AssertionError(blocked)
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/apps/calculator/",
            data=b"{}",
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as exc:
            assert exc.code == 404
        else:
            raise AssertionError("POST served an app")
    finally:
        httpd.shutdown()
        httpd.server_close()
    rules = agent.nft_ruleset()
    assert 'iifname "lo" accept' in rules
    assert rules.index('iifname "lo" accept') < rules.index('iifname "stickllm-a0" drop')
    assert "tcp dport { 8080, 8081, 8082 }" in rules
    assert 'iifname "stickllm-a0" ip daddr 172.30.0.1 tcp dport { 8080, 8081, 8082 } accept' in rules
    assert "192.168.0.0/16 drop" in rules
    assert "5099" not in rules
    assert "0.0.0.0:8081" not in rules
    assert "0.0.0.0:8080" not in rules
    assert "0.0.0.0:8082" not in rules
    script = _script()
    assert "apps-bridge" in script
    assert "ensure_apps" in script
    assert "0.0.0.0:8081" not in script
    assert "0.0.0.0:8082" not in script
    assert "open-app-bridge" in script
    assert "/stickllm-open-app.token:ro" in script
    assert "-p 127.0.0.1:5099:5099" in script
    run = script.split("docker_cli run --name", 1)[1].split("--entrypoint", 1)[0]
    assert ":8081" not in run
    assert ":8082" not in run
    assert "/opt/stickllm/ui" not in run
    assert 'iifname "lo" accept' in agent.nft_apply_text()


def test_apps_prompt_names_url_ids(tmp_path):
    vault = tmp_path / "vault"
    settings = tmp_path / "settings"
    vault.mkdir()
    settings.mkdir()
    mounts = tmp_path / "mounts"
    mounts.write_text(
        f"dev {vault} ext4 rw 0 0\ndev {settings} ext4 rw 0 0\n",
        encoding="utf-8",
    )
    agent = _load(
        AGENT,
        "stickllm_agent_apps_prompt",
        {
            "STICKLLM_VAULT_MNT": str(vault),
            "STICKLLM_SETTINGS_MNT": str(settings),
            "STICKLLM_MOUNTS_FILE": str(mounts),
        },
    )
    agent.ensure_apps_instructions()
    prompt = (
        vault
        / "addons"
        / "agent-zero"
        / "state"
        / "agents"
        / "agent0"
        / "prompts"
        / "agent.system.main.specifics.md"
    ).read_text(encoding="utf-8")
    note = (
        "StickLLM apps are at http://172.30.0.1:8081/apps/<id>/ "
        "(minesweeper, solitaire, tetris, notepad, calculator, files, media, monitor)."
    )
    rule = "When the user says open/start/show an app, use open_app, not the browser tool."
    assert note in prompt
    assert rule in prompt
    assert "http://172.30.0.1:8081/apps/minesweeper/" in prompt
    assert "minesweep" in prompt
    skill = (
        settings / "agent-zero" / "skills" / "stickllm-apps" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert note in skill
    assert rule in skill
    assert "URL id minesweeper" in skill or "minesweeper" in skill
    assert "minesweep" in skill
    tool = (
        vault
        / "addons"
        / "agent-zero"
        / "state"
        / "plugins"
        / "stickllm_apps"
        / "tools"
        / "open_app.py"
    ).read_text(encoding="utf-8")
    prompt_tool = (
        vault
        / "addons"
        / "agent-zero"
        / "state"
        / "plugins"
        / "stickllm_apps"
        / "prompts"
        / "agent.system.tool.open_app.md"
    ).read_text(encoding="utf-8")
    assert "class OpenApp" in tool
    assert "http://172.30.0.1:8082/open" in tool
    assert rule in prompt_tool
    assert "browser.py" not in tool


def test_open_app_allowlist_and_token(tmp_path):
    agent = _load(AGENT, "stickllm_agent_open_app")
    assert agent.open_app_id_ok("minesweeper") is True
    for good in ("files", "media", "monitor", "calculator", "solitaire", "tetris", "notepad"):
        assert agent.open_app_id_ok(good) is True
    for bad in (
        "minesweep",
        "Minesweeper",
        "../minesweeper",
        "minesweeper/../files",
        "http://127.0.0.1/apps/minesweeper/",
        "https://example.test",
        "onlyoffice",
        "",
        "minesweeper\n",
        " notepad",
        "files/../../etc/passwd",
        None,
    ):
        assert agent.open_app_id_ok(bad) is False
    token = "correct-token-value-0123456789"
    token_file = tmp_path / "open-app.token"
    token_file.write_text(token + "\n", encoding="utf-8")
    assert agent.open_app_token_ok(None, token) is False
    assert agent.open_app_token_ok("", token) is False
    assert agent.open_app_token_ok("Bearer " + ("x" * len(token)), token) is False
    assert agent.open_app_token_ok("Bearer " + token, token) is True
    assert agent.open_app_token_ok(token, "") is False
    apps = tmp_path / "apps"
    (apps / "minesweeper").mkdir(parents=True)
    (apps / "minesweeper" / "index.html").write_text("mines", encoding="utf-8")
    assert agent.open_app_page_ready(apps, "minesweeper") is True
    assert agent.open_app_page_ready(apps, "monitor") is False
    opened: list[str] = []
    httpd = agent.open_app_server(
        "127.0.0.1",
        0,
        root=apps,
        token_file=token_file,
        notify=lambda app_id: opened.append(app_id),
    )
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    def post(app_id, auth=None):
        data = json.dumps({"id": app_id}).encode()
        headers = {"Content-Type": "application/json"}
        if auth is not None:
            headers["Authorization"] = auth
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/open",
            data=data,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    try:
        code, _body = post("minesweeper")
        assert code == 401
        code, _body = post("minesweeper", "Bearer " + ("x" * len(token)))
        assert code == 401
        code, _body = post("minesweep", "Bearer " + token)
        assert code == 400
        code, _body = post("http://evil.test/apps/minesweeper/", "Bearer " + token)
        assert code == 400
        code, _body = post("../minesweeper", "Bearer " + token)
        assert code == 400
        code, _body = post("monitor", "Bearer " + token)
        assert code == 404
        code, body = post("minesweeper", "Bearer " + token)
        assert code == 200
        assert body["path"] == "/apps/minesweeper/"
        assert body["window"] == "stickllm-minesweeper"
        assert opened == ["minesweeper"]
        data = json.dumps({"id": "minesweeper", "dry_run": True}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/open",
            data=data,
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + token},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            dry = json.loads(resp.read().decode())
            assert resp.status == 200
        assert dry["ok"] is True
        assert opened == ["minesweeper"]
        try:
            agent.open_app_server(
                "0.0.0.0",
                0,
                root=apps,
                token_file=token_file,
                notify=lambda _app_id: None,
            )
        except SystemExit as exc:
            assert "all interfaces" in str(exc)
        else:
            raise AssertionError("open app control accepted 0.0.0.0")
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_open_app_event_stays_off_the_lan(tmp_path):
    token = "gateway-open-token-0123456789ab"
    token_file = tmp_path / "open-app.token"
    token_file.write_text(token + "\n", encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    pair = "paired-browser-token"
    (run / "auth.json").write_text(
        json.dumps(
            {
                "require_pair": True,
                "paired": True,
                "token_hash": hashlib.sha256(pair.encode()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    ui = tmp_path / "ui"
    page = ui / "apps" / "minesweeper"
    page.mkdir(parents=True)
    (page / "index.html").write_text("<!DOCTYPE html><title>Mines</title>", encoding="utf-8")
    env = {
        "STICKLLM_UI": str(ui),
        "STICKLLM_RUN": str(run),
        "STICKLLM_OPEN_APP_TOKEN_FILE": str(token_file),
        "STICKLLM_VAULT_MNT": str(tmp_path / "vault"),
        "STICKLLM_FILES_PORT": "9",
    }
    saved = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    gateway = _load(GATEWAY, "stickllm_gateway_open_app", env)

    class LanHandler(gateway.Handler):
        def _is_loopback(self) -> bool:
            return False

    lan = gateway.ThreadingHTTPServer(("127.0.0.1", 0), LanHandler)
    local = gateway.ThreadingHTTPServer(("127.0.0.1", 0), gateway.Handler)
    lan_port = lan.server_address[1]
    local_port = local.server_address[1]
    for httpd in (lan, local):
        httpd.daemon_threads = True
        threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def call(port, path, *, method="GET", auth=None, body=None, cookie=None):
        data = None if body is None else json.dumps(body).encode()
        headers = {}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = auth
        if cookie:
            headers["Cookie"] = cookie
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read().decode()
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = raw
                return resp.status, parsed
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode()
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {"raw": raw}
            return exc.code, parsed

    try:
        code, body = call(
            lan_port,
            "/api/ui/open-app",
            method="POST",
            auth="Bearer " + token,
            body={"id": "minesweeper"},
        )
        assert code == 403
        assert body["error"] == "loopback_only"
        code, body = call(lan_port, "/api/ui/events")
        assert code == 401
        assert body["error"] == "pair_required"
        code, _body = call(local_port, "/api/ui/open-app", method="POST", body={"id": "minesweeper"})
        assert code == 401
        code, _body = call(
            local_port,
            "/api/ui/open-app",
            method="POST",
            auth="Bearer wrong-token-value-0123456789",
            body={"id": "nope"},
        )
        assert code == 401
        code, body = call(
            local_port,
            "/api/ui/open-app",
            method="POST",
            auth="Bearer " + token,
            body={"id": "nope"},
        )
        assert code == 400
        code, body = call(
            local_port,
            "/api/ui/open-app",
            method="POST",
            auth="Bearer " + token,
            body={"id": "minesweeper"},
        )
        assert code == 200
        assert body["window"] == "stickllm-minesweeper"
        code, body = call(local_port, "/api/ui/open-app")
        assert code == 200
        assert body["id"] == "minesweeper"
        code, snap = call(
            lan_port,
            "/apps/minesweeper/?stickllm_open=1",
            cookie=f"stickllm_pair={pair}",
        )
        assert code == 200
        assert "Mines" in snap
        code, body = call(local_port, "/api/ui/open-app")
        assert body.get("loaded_from") == "127.0.0.1"
        sock = socket.create_connection(("127.0.0.1", local_port), timeout=3)
        sock.sendall(b"GET /api/ui/events HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        sock.settimeout(2)
        data = b""
        try:
            while b"open_app" not in data and len(data) < 12000:
                chunk = sock.recv(2048)
                if not chunk:
                    break
                data += chunk
        except (TimeoutError, socket.timeout):
            pass
        finally:
            sock.close()
        assert b"event: open_app" in data
        assert b"minesweeper" in data
    finally:
        lan.shutdown()
        local.shutdown()
        lan.server_close()
        local.server_close()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
