"""0.5.2 fix 10: container DNS follows the host, quiet pre-unlock settings open."""
import importlib.util
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "overlay/usr/local/lib/stickllm_agent.py"
VAULT = ROOT / "overlay/usr/local/bin/stickllm-vault"
SETTINGS = ROOT / "overlay/usr/local/bin/stickllm-usb-settings"
AGENT_SH = ROOT / "overlay/usr/local/bin/stickllm-agent"


def _agent():
    spec = importlib.util.spec_from_file_location("stickllm_agent_fix10", AGENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_host_resolvers_first_then_public(tmp_path):
    a = _agent()
    stub = tmp_path / "stub.conf"
    stub.write_text("nameserver 127.0.0.53\noptions edns0\n")
    real = tmp_path / "resolv.conf"
    real.write_text("# dhcp\nnameserver 192.168.72.1\nnameserver fe80::1%eth0\nnameserver 192.168.72.1\nnameserver 10.0.0.2\nnameserver 8.8.8.8\n")
    assert a.host_dns_servers([str(stub), str(real)], override="") == ["192.168.72.1", "10.0.0.2", "1.1.1.1"]


def test_only_loopback_stub_falls_back_to_public(tmp_path):
    a = _agent()
    stub = tmp_path / "stub.conf"
    stub.write_text("nameserver 127.0.0.53\n")
    assert a.host_dns_servers([str(stub), str(tmp_path / "missing")], override="") == ["1.1.1.1", "9.9.9.9"]


def test_override_and_garbage(tmp_path):
    a = _agent()
    assert a.host_dns_servers([], override="9.9.9.9 nope 127.0.0.1 1.0.0.1") == ["9.9.9.9", "1.0.0.1"]


def test_nft_allows_dns_only_to_lan_resolvers():
    a = _agent()
    # v0.5.3: all configured resolvers (LAN + public) get port 53; raw internet is dropped.
    rules = a.nft_ruleset(dns_servers=["192.168.72.1", "1.1.1.1", "8.8.8.8"])
    assert "192.168.72.1" in rules
    assert "1.1.1.1" in rules
    assert "8.8.8.8" in rules
    assert "udp dport 53 accept" in rules
    assert rules.index("dport 53 accept") < rules.index("ip daddr 192.168.0.0/16 drop")
    plain = a.nft_ruleset()
    assert "dport 53" not in plain
    assert "ip daddr 192.168.0.0/16 drop" in plain
    assert "169.254.0.0/16 drop" in plain
    assert "100.100.100.200 drop" in plain
    assert "tcp dport 18080 accept" in plain
    agent_out = plain.split("chain agent_out", 1)[1].split("chain input", 1)[0]
    lines = [
        ln.strip()
        for ln in agent_out.splitlines()
        if ln.strip() and ln.strip() not in ("{", "}") and not ln.strip().startswith("type ")
    ]
    assert lines[-1] == "drop"


def test_agent_container_and_embedding_use_dns_args():
    text = AGENT_SH.read_text()
    assert "--dns 1.1.1.1" not in text
    assert text.count('"${DNS_ARGS[@]}"') == 2
    assert '"$LIB" dns-servers' in text


def test_settings_open_nothing_yet_is_exit_3_and_quiet():
    s = SETTINGS.read_text()
    body = s[s.index("cmd_open() {"):s.index("add_existing_key_slots()")]
    assert body.count("exit 3") == 2
    v = VAULT.read_text()
    sync = v[v.index("sync_usb_settings() {"):v.index("maybe_bind_from_settings() {")]
    assert "warning: usb settings open failed" not in sync
    assert '"$rc" -ne 3' in sync
    # init=1 paths still warn for real failures
    assert "warning: usb settings open-or-init failed" in sync


def test_sync_usb_settings_runtime(tmp_path):
    v = VAULT.read_text()
    sync = v[v.index("sync_usb_settings() {"):v.index("maybe_bind_from_settings() {")]
    out = {}
    for rc in (0, 1, 3):
        helper = tmp_path / f"h{rc}"
        helper.write_text(f"#!/bin/bash\n[[ $1 == open ]] && exit {rc}\nexit 0\n")
        helper.chmod(0o755)
        script = f"LOCATION_FILE=/dev/null\nsettings_helper() {{ echo {helper}; }}\n{sync}\nsync_usb_settings secretpass 0\n"
        p = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
        assert p.returncode == 0
        assert "secretpass" not in p.stderr
        out[rc] = p.stderr
    assert out[0] == "" and out[3] == ""
    assert "note: usb settings not opened before vault unlock (rc=1)" in out[1]
    assert "warning" not in out[1]


def test_version_is_053_everywhere():
    import json as _json
    assert _json.loads((ROOT / "overlay/opt/stickllm/ui/stickllm.json").read_text())["version"] == "0.5.4"
    assert '<span class="mono" id="aboutVer">StickLLM v0.5.4</span>' in (ROOT / "ui/index.html").read_text()
    b = (ROOT / "scripts/build.sh").read_text()
    assert 'VERSION="${STICKLLM_VERSION:-0.5.4}"' in b and "|v0.5.2)" in b
