"""v0.8.3: setup wizard storage_targets must offer USB HDDs (not only internal)."""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CTL = ROOT / "overlay/usr/local/bin/stickllm-control"
APP = ROOT / "ui/app.js"
CATALOG = ROOT / "config/models/catalog.toml"


def _ctl(monkeypatch):
    # stickllm-control imports fcntl (Linux-only); stub on Windows hosts.
    if "fcntl" not in sys.modules:
        sys.modules["fcntl"] = types.ModuleType("fcntl")
    monkeypatch.setenv("STICKLLM_CATALOG", str(CATALOG))
    loader = importlib.machinery.SourceFileLoader("stickllm_control_v083usb", str(CTL))
    spec = importlib.util.spec_from_loader("stickllm_control_v083usb", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_list_storage_targets_includes_usb_hotplug(monkeypatch, tmp_path):
    """Regression: RM/HOTPLUG used to hide Seagate / STICKLLM-EXT from setup."""
    ctl = _ctl(monkeypatch)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(ctl, "MNT", data)
    monkeypatch.setattr(ctl, "_path_is_dir", lambda p: Path(p).is_dir())
    monkeypatch.setattr(ctl, "_free_bytes", lambda p: 40 * 1024**3)
    monkeypatch.setattr(ctl, "_boot_live_disk_name", lambda: "sda")
    monkeypatch.setattr(ctl, "read_json", lambda *a, **k: {})
    monkeypatch.setattr(ctl, "get_preferred_models_dir", lambda: None)
    monkeypatch.setattr(ctl, "vault_download_models_dir", lambda: None)

    lsblk_doc = {
        "blockdevices": [
            {
                "name": "sda",
                "type": "disk",
                "size": "64000000000",
                "rm": True,
                "hotplug": True,
                "tran": "usb",
                "model": "StickLLM",
                "children": [
                    {
                        "name": "sda3",
                        "path": "/dev/sda3",
                        "type": "part",
                        "size": "50000000000",
                        "fstype": "ext4",
                        "mountpoint": "/mnt/stickllm-data",
                        "pkname": "sda",
                        "label": "STICKLLM-DATA",
                    }
                ],
            },
            {
                "name": "sdb",
                "type": "disk",
                "size": "2000398934016",
                "rm": True,
                "hotplug": True,
                "tran": "usb",
                "model": "ST2000LM007-1R17",
                "children": [
                    {
                        "name": "sdb1",
                        "path": "/dev/sdb1",
                        "type": "part",
                        "size": "2000397803008",
                        "fstype": "ext4",
                        "mountpoint": None,
                        "pkname": "sdb",
                        "label": "STICKLLM-EXT",
                        "partlabel": "",
                    }
                ],
            },
            {
                "name": "nvme0n1",
                "type": "disk",
                "size": "512110190592",
                "rm": False,
                "hotplug": False,
                "tran": "nvme",
                "model": "Samsung SSD 980",
                "children": [
                    {
                        "name": "nvme0n1p2",
                        "path": "/dev/nvme0n1p2",
                        "type": "part",
                        "size": "500000000000",
                        "fstype": "ext4",
                        "mountpoint": None,
                        "pkname": "nvme0n1",
                        "label": "",
                    }
                ],
            },
        ]
    }

    def fake_run(cmd, *a, **k):
        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        if cmd and cmd[0] == "lsblk" and "-J" in cmd:
            R.stdout = json.dumps(lsblk_doc)
            return R()
        return R()

    monkeypatch.setattr(ctl.subprocess, "run", fake_run)
    out = ctl.list_storage_targets()
    assert out["ok"] is True
    kinds = {u["kind"] for u in out["unmounted"]}
    assert "usb_unmounted" in kinds
    assert "ssd_unmounted" in kinds
    usb = next(u for u in out["unmounted"] if u["kind"] == "usb_unmounted")
    assert usb["device"] == "/dev/sdb1"
    assert "STICKLLM-EXT" in usb["label"]
    assert "ST2000LM007" in usb["label"] or "ST2000LM007" in (usb.get("model") or "")
    assert str(usb["suggested_mount"]).startswith("/mnt/stickllm-host/")
    # Boot stick partition must not appear as a host Mount target
    assert not any(u.get("device") == "/dev/sda3" for u in out["unmounted"])
    ssd = next(u for u in out["unmounted"] if u["kind"] == "ssd_unmounted")
    assert ssd["device"] == "/dev/nvme0n1p2"


def test_ui_setup_offers_usb_and_change_drive():
    s = APP.read_text(encoding="utf-8")
    assert "refreshWizardStorage" in s
    assert "Choose a different drive" in s
    assert "wizRefreshDrives" in s
    assert "usb_unmounted" in s or 'd.kind === "usb"' in s
    # Must not restart the whole wizard after Mount (old bug).
    stor = s.split("} else if (step === STEP_STOR)", 1)[1].split(
        "} else if (step === STEP_VAULT)", 1
    )[0]
    assert "refreshWizardStorage" in stor
    assert "openSetupWizard({ force: true })" not in stor
