"""0.6.2 (C + GPU): safe boot IOMMU off, titleless maximise, stacked toasts,
browser yields to app windows, neutral GPU wording, SSH 'Not connected',
Vulkan card choice by link among near-equal cards."""
import subprocess
from pathlib import Path

from test_amd_vulkan_detect import _load_control

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay/usr/local/bin"


def test_safe_boot_iommu_off_grub_and_isolinux():
    g = (ROOT / "boot/grub.cfg").read_text()
    safe = g.split('menuentry "4 Safe boot', 1)[1].split("}", 1)[0]
    assert "amd_iommu=off" in safe
    iso = (ROOT / "boot/isolinux/live.cfg").read_text()
    block = iso.split("label stickllm-safe", 1)[1]
    assert "4 Safe boot" in block and "amd_iommu=off" in block and "live-config.noautologin" in block
    # The normal entries keep the IOMMU on.
    assert "amd_iommu" not in iso.split("label stickllm-safe", 1)[0]


def test_xfwm_titleless_maximize():
    x = (ROOT / "overlay/etc/stickllm/xfce/xdg/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml").read_text()
    assert '<property name="titleless_maximize" type="bool" value="true"/>' in x


def test_toasts_stack_with_close_button():
    app = (ROOT / "ui/app.js").read_text()
    body = app.split("function toast(msg, opts)", 1)[1].split("\nfunction ", 1)[0]
    assert "toastStack" in body and "toastX" in body and "appendChild(item)" in body
    css = (ROOT / "ui/style.css").read_text()
    assert ".toastStack{" in css and ".toastX{" in css


def test_app_windows_raise_above_browser():
    d = (ROOT / "ui/desktop.js").read_text()
    assert "function browserCovers()" in d and "function yieldBrowser()" in d
    assert 'browserOp(x.id, "minimise")' in d
    open_app = d.split("function openApp(id) {", 1)[1][:300]
    assert "yieldBrowser()" in open_app
    assert "if (browserCovers()) { yieldBrowser(); wm.focus(b.dataset.app); }" in d


def test_gpu_panel_wording_neutral():
    app = (ROOT / "ui/app.js").read_text()
    assert "No NVIDIA GPUs found" not in app
    assert "AMD and Intel cards run through Vulkan" in app


def test_ssh_line_not_connected_without_lan_ip():
    src = (BIN / "stickllm-bootstatus").read_text()
    fn = src.split("ssh_password_line() {", 1)[1].split("\n}\n", 1)[0]
    assert 'host="${ip:-Not connected}"' in fn and '127.*' in fn
    assert "waiting for the network" not in fn


def test_vulkan_near_equal_cards_prefer_x16(tmp_path, monkeypatch):
    c = _load_control(tmp_path, monkeypatch)
    rows = [
        {"backend": "vulkan", "index": 0, "device": "Vulkan0", "total_mib": 8192, "free_mib": 7900,
         "link_width": 1, "link_mts": 8000},
        {"backend": "vulkan", "index": 1, "device": "Vulkan1", "total_mib": 8192, "free_mib": 7600,
         "link_width": 16, "link_mts": 8000},
    ]
    best = c.suitable_gpus(rows, need_bytes=20 * 1024 ** 3)
    assert [g["device"] for g in best] == ["Vulkan1"]
    # A card with far less free VRAM is not picked for its link.
    rows[1]["free_mib"] = 3000
    assert [g["device"] for g in c.suitable_gpus(rows, need_bytes=20 * 1024 ** 3)] == ["Vulkan0"]


def test_vk_display_name_format(tmp_path, monkeypatch):
    c = _load_control(tmp_path, monkeypatch)
    name = c.vk_display_name(0, "0000:10:00.0", 16, 8192)
    assert name.endswith("10:00.0 · 8 GB · PCIe x16") and "GPU" in name
    assert c.vk_display_name(1, "", 0, 0) == "GPU 2"
