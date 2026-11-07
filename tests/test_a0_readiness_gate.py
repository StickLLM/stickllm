"""Agent Zero readiness must mean "A0 answers", not "the port is open".

The container publishes 5099 through docker-proxy, which binds and accepts the
port as soon as the container is created — up to a minute before A0 starts
listening inside it. A bare TCP connect therefore reports "up" during a window
where every request through /agent-zero/ still fails, which is what made the
desktop announce "Agent Zero is ready" and then paint
"127.0.0.1 refused to connect".
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"
AGENT_LIB = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_agent.py"
AGENT_UNIT = ROOT / "overlay" / "etc" / "systemd" / "system" / "stickllm-agent.service"
USB_SETTINGS = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-usb-settings"


@pytest.fixture(scope="module")
def gateway() -> str:
    return GATEWAY.read_text(encoding="utf-8")


def test_http_readiness_helper_exists(gateway: str) -> None:
    assert "def _agent_http_ready(" in gateway
    assert "/api/csrf_token" in gateway


def test_status_never_uses_a_bare_port_check(gateway: str) -> None:
    """Every upstream_up decision goes through the HTTP probe."""
    assert "upstream_up=_agent_port_open()" not in gateway
    assert gateway.count("upstream_up=_agent_http_ready()") == 3


def test_embed_proxy_gated_on_the_same_rule(gateway: str) -> None:
    """Otherwise the embed can 502 inside a request status just called running."""
    assert "if not _agent_http_ready(5099):" in gateway
    assert "agent_not_running" in gateway


def test_a_5xx_upstream_is_not_ready(gateway: str) -> None:
    """A dead upstream answers 5xx through the proxy; that must not count."""
    assert "resp.status < 500" in gateway


class TestSeedRepair:
    """A truncated reference store must not brick A0 permanently."""

    @pytest.fixture(scope="class")
    def lib(self) -> str:
        return AGENT_LIB.read_text(encoding="utf-8")

    def test_repair_helper_exists(self, lib: str) -> None:
        assert "def repair_reference_store(" in lib
        assert "repositories.json" in lib

    def test_ensure_seeded_repairs_an_existing_image_dir(self, lib: str) -> None:
        """The old code only refreshed image/ when it was missing entirely."""
        assert "repaired = repair_reference_store(" in lib

    def test_repair_keeps_a_good_file(self, lib: str) -> None:
        assert "dst.is_file() and dst.stat().st_size > 0" in lib


def _sections(text: str) -> dict[str, list[str]]:
    """Split a unit file into section -> directive lines.

    Section headers are matched only at the start of a line and comments are
    dropped, so prose mentioning "[Service]" does not land in the wrong bucket.
    """
    out: dict[str, list[str]] = {}
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            out.setdefault(current, [])
            continue
        out.setdefault(current, []).append(line)
    return out


class TestAgentUnit:
    @pytest.fixture(scope="class")
    def unit(self) -> dict[str, list[str]]:
        return _sections(AGENT_UNIT.read_text(encoding="utf-8"))

    def test_start_limits_are_in_the_unit_section(self, unit) -> None:
        keys = [line.split("=", 1)[0] for line in unit["Unit"]]
        assert "StartLimitIntervalSec" in keys
        assert "StartLimitBurst" in keys

    def test_start_limits_are_not_in_the_service_section(self, unit) -> None:
        """There systemd logs "Unknown key" and ignores them, so Restart=always
        retries a broken dependency forever instead of giving up."""
        keys = [line.split("=", 1)[0] for line in unit["Service"]]
        assert "StartLimitIntervalSec" not in keys
        assert "StartLimitBurst" not in keys


class TestSettingsRecovery:
    """An interrupted unlock used to leave A0 stuck at settings_missing."""

    @pytest.fixture(scope="class")
    def script(self) -> str:
        return USB_SETTINGS.read_text(encoding="utf-8")

    def test_a_live_mapper_is_adopted(self, script: str) -> None:
        """Else a second open dies with "Device stickllm-settings already exists"."""
        assert "adopt_open_mapper()" in script
        assert 'adopt_open_mapper "$part"' in script

    def test_a_mapper_on_another_device_is_dropped(self, script: str) -> None:
        assert 'cryptsetup close "$MAPPER_NAME"' in script

    def test_a_missing_filesystem_is_only_made_under_init(self, script: str) -> None:
        """luksFormat can land and mkfs still not run; never reformat blindly."""
        assert 'STICKLLM_SETTINGS_INIT:-' in script
        assert "mkfs.ext4 -F -L STICKLLM-SETTINGS" in script
