"""0.5.5: /api/health says a not-yet-bound vault is present-locked (not "No vault set up")."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATEWAY = ROOT / "overlay" / "usr" / "local" / "bin" / "stickllm-gateway"


def _load(tmp_path: Path):
    os.environ.setdefault("STICKLLM_RUN", str(tmp_path / "run"))
    loader = importlib.machinery.SourceFileLoader("gw_vault_usb", str(GATEWAY))
    spec = importlib.util.spec_from_loader("gw_vault_usb", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_vault_health_usb_settings(tmp_path):
    gw = _load(tmp_path)
    data = tmp_path / "data"
    data.mkdir()
    gw.VAULT_META_DIRS = (data / "vault-meta", tmp_path / "var-meta")
    gw.vault_unlocked = lambda: False
    gw.vault_configured = lambda: False
    assert gw.vault_health() == {"status": "absent", "mounted": False}
    (data / "stickllm-settings-part.json").write_text("{}", encoding="utf-8")
    assert gw.vault_health() == {"status": "absent", "mounted": False, "usb_settings": "present-locked"}
    gw.vault_configured = lambda: True
    assert gw.vault_health() == {"status": "locked", "mounted": False}
    gw.vault_unlocked = lambda: True
    assert gw.vault_health() == {"status": "unlocked", "mounted": True}
