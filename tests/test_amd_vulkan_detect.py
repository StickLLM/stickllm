"""AMD/Vulkan GPU detection + user context size (fix/amd-vulkan-detect).

pick-gpus fills a real Vulkan GPU count / free VRAM from amdgpu sysfs (vulkaninfo
heap fallback) and picks the card with the most free VRAM; the planner offloads
to that one device; llama-start passes --device VulkanN and honours the user's
STICKLLM_CTX_SIZE (capped, never raised)."""
import importlib.machinery
import importlib.util
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "overlay" / "usr" / "local" / "bin"
UNIT = ROOT / "overlay" / "etc" / "systemd" / "system" / "stickllm-llama.service"
GiB = 1024 ** 3

VK_TWO_RX570 = """\
VkPhysicalDeviceProperties:
	deviceType        = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
	deviceName        = AMD Radeon RX 570 Series (RADV POLARIS10)
VkPhysicalDevicePCIBusInfoPropertiesEXT:
	pciDomain   = 0
	pciBus      = {bus0}
	pciDevice   = 0
	pciFunction = 0
VkPhysicalDeviceMemoryProperties:
	memoryHeaps: count = 2
		memoryHeaps[0]:
			size   = 3221225472 (0xc0000000) (3.00 GiB)
			flags:
				None
		memoryHeaps[1]:
			size   = 8589934592 (0x200000000) (8.00 GiB)
			flags: count = 1
				MEMORY_HEAP_DEVICE_LOCAL_BIT
VkPhysicalDeviceProperties:
	deviceType        = PHYSICAL_DEVICE_TYPE_DISCRETE_GPU
	deviceName        = AMD Radeon RX 570 Series (RADV POLARIS10)
VkPhysicalDevicePCIBusInfoPropertiesEXT:
	pciDomain   = 0
	pciBus      = {bus1}
	pciDevice   = 0
	pciFunction = 0
VkPhysicalDeviceMemoryProperties:
	memoryHeaps: count = 2
		memoryHeaps[0]:
			size   = 3221225472 (0xc0000000) (3.00 GiB)
			flags:
				None
		memoryHeaps[1]:
			size   = 8589934592 (0x200000000) (8.00 GiB)
			flags: count = 1
				MEMORY_HEAP_DEVICE_LOCAL_BIT
VkPhysicalDeviceProperties:
	deviceType        = PHYSICAL_DEVICE_TYPE_CPU
	deviceName        = llvmpipe (LLVM 15.0.6, 256 bits)
VkPhysicalDeviceMemoryProperties:
	memoryHeaps: count = 1
		memoryHeaps[0]:
			size   = 2147483648 (0x80000000) (2.00 GiB)
			flags: count = 1
				MEMORY_HEAP_DEVICE_LOCAL_BIT
"""


def _exe(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _sysfs(root: Path, cards: dict, links: dict | None = None, power: dict | None = None) -> Path:
    """cards: {"card0": ("0000:10:00.0", total_bytes, used_bytes), ...}
    links: {"card0": {"current_link_width": "16", ...}}; power: {"card1": "auto"}"""
    drm = root / "drm"
    devs = root / "devices"
    drv = root / "drivers" / "amdgpu"
    drv.mkdir(parents=True)
    drm.mkdir()
    for card, (pci, total, used) in cards.items():
        d = devs / pci
        d.mkdir(parents=True)
        (d / "driver").symlink_to(drv)
        if total is not None:
            (d / "mem_info_vram_total").write_text(f"{total}\n")
            (d / "mem_info_vram_used").write_text(f"{used}\n")
        for name, val in ((links or {}).get(card) or {}).items():
            (d / name).write_text(f"{val}\n")
        if (power or {}).get(card):
            (d / "power").mkdir()
            (d / "power" / "control").write_text(power[card] + "\n")
        (drm / card).mkdir()
        (drm / card / "device").symlink_to(d)
    (drm / "card0-DP-1").mkdir()  # connector entries must be skipped
    return drm


LD_DEFAULT = ("8029", "8186")


def _pick(tmp_path: Path, *, drm: Path, vulkaninfo: str | None, ld_free=LD_DEFAULT, extra_env=None):
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir(exist_ok=True)
    _exe(fakebin / "nvidia-smi", "exit 9\n")
    _exe(fakebin / "lspci", "exit 0\n")
    lines = "".join(
        f'echo "  Vulkan{i}: AMD Radeon RX 570 Series (RADV POLARIS10) (8192 MiB, {f} MiB free)"\n'
        for i, f in enumerate(ld_free))
    vk_bin = _exe(tmp_path / "llama-server-vulkan", 'echo "Available devices:"\n' + lines)
    if vulkaninfo is None:
        vki = str(tmp_path / "no-vulkaninfo")
    else:
        (tmp_path / "vk.txt").write_text(vulkaninfo, encoding="utf-8")
        vki = str(_exe(tmp_path / "vulkaninfo", f'cat "{tmp_path / "vk.txt"}"\n'))
    run = tmp_path / "run"
    env = {k: v for k, v in os.environ.items() if not k.startswith("STICKLLM_")}
    env.update({
        "PATH": f"{fakebin}:{env.get('PATH', '/usr/bin:/bin')}",
        "STICKLLM_RUN": str(run),
        "STICKLLM_DRM_ROOT": str(drm),
        "STICKLLM_VULKANINFO": vki,
        "STICKLLM_LLAMA_VULKAN": str(vk_bin),
        "STICKLLM_LLAMA_CUDA": str(tmp_path / "no-cuda"),
    })
    env.update(extra_env or {})
    p = subprocess.run(["bash", str(BIN / "stickllm-pick-gpus")], env=env, capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    vals = {}
    envf = run / "cuda.env"
    if envf.is_file():
        for line in envf.read_text().splitlines():
            k, _, v = line.partition("=")
            vals[k] = v
    return vals, p.stderr


RX570 = 8 * GiB


def test_pick_vulkan_sysfs_count_and_best_card(tmp_path):
    drm = _sysfs(tmp_path, {
        "card0": ("0000:10:00.0", RX570, 170 * 1024 * 1024),  # display card
        "card1": ("0000:21:00.0", RX570, 5 * 1024 * 1024),
    })
    v, err = _pick(tmp_path, drm=drm, vulkaninfo=VK_TWO_RX570.format(bus0=16, bus1=33))
    assert v["STICKLLM_BACKEND"] == "vulkan"
    assert v["STICKLLM_GPU_COUNT"] == "2"
    assert v["STICKLLM_VULKAN_GPUS"] == "0:8192:8022:0:0,1:8192:8187:0:0"
    assert v["STICKLLM_VULKAN_DEVICE"] == "Vulkan1"
    assert v["STICKLLM_VRAM_FREE_MIB"] == "8187"
    assert v["STICKLLM_VRAM_TOTAL_MIB"] == "8192"
    assert "(sysfs)" in err


def test_pick_vulkan_maps_by_pci_bus_not_card_number(tmp_path):
    # vulkaninfo lists bus 0x21 first → Vulkan0 is card1.
    drm = _sysfs(tmp_path, {
        "card0": ("0000:10:00.0", RX570, 6 * GiB),
        "card1": ("0000:21:00.0", RX570, 1 * GiB),
    })
    v, _ = _pick(tmp_path, drm=drm, vulkaninfo=VK_TWO_RX570.format(bus0=33, bus1=16))
    assert v["STICKLLM_VULKAN_GPUS"] == "0:8192:7168:0:0,1:8192:2048:0:0"
    assert v["STICKLLM_VULKAN_DEVICE"] == "Vulkan0"


def test_pick_vulkan_falls_back_to_vulkaninfo_heaps(tmp_path):
    drm = _sysfs(tmp_path, {"card0": ("0000:10:00.0", None, None), "card1": ("0000:21:00.0", None, None)})
    v, err = _pick(tmp_path, drm=drm, vulkaninfo=VK_TWO_RX570.format(bus0=16, bus1=33))
    assert v["STICKLLM_GPU_COUNT"] == "2"  # llvmpipe (CPU) excluded
    assert v["STICKLLM_VULKAN_GPUS"] == "0:8192:8192:0:0,1:8192:8192:0:0"
    assert v["STICKLLM_VULKAN_DEVICE"] == "Vulkan0"
    assert v["STICKLLM_VRAM_FREE_MIB"] == "8192"
    assert "(vulkaninfo)" in err


def test_pick_vulkan_sysfs_only_uses_pci_order(tmp_path):
    drm = _sysfs(tmp_path, {
        "card1": ("0000:21:00.0", RX570, 0),
        "card0": ("0000:10:00.0", RX570, 2 * GiB),
    })
    v, _ = _pick(tmp_path, drm=drm, vulkaninfo=None)
    assert v["STICKLLM_VULKAN_GPUS"] == "0:8192:6144:0:0,1:8192:8192:0:0"
    assert v["STICKLLM_VULKAN_DEVICE"] == "Vulkan1"


def test_pick_replaces_unwritable_stale_cuda_env(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can write read-only files")
    run = tmp_path / "run"
    run.mkdir()
    stale = run / "cuda.env"
    stale.write_text("STICKLLM_BACKEND=vulkan\nSTICKLLM_GPU_COUNT=0\nSTICKLLM_VRAM_FREE_MIB=0\n")
    stale.chmod(0o444)  # like root-owned 644 seen by User=stickllm-llama
    drm = _sysfs(tmp_path, {"card0": ("0000:10:00.0", RX570, 0)})
    v, err = _pick(tmp_path, drm=drm, vulkaninfo=VK_TWO_RX570.format(bus0=16, bus1=99))
    assert v["STICKLLM_GPU_COUNT"] in ("1", "2")
    assert v["STICKLLM_VRAM_FREE_MIB"] != "0"
    assert oct(stale.stat().st_mode & 0o777) == "0o644"


def test_pick_logs_write_errors(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root bypasses dir permissions")
    run = tmp_path / "run"
    run.mkdir()
    (run / "cuda.env").write_text("STICKLLM_GPU_COUNT=0\n")
    run.chmod(0o555)
    try:
        drm = _sysfs(tmp_path, {"card0": ("0000:10:00.0", RX570, 0)})
        _, err = _pick(tmp_path, drm=drm, vulkaninfo=None)
    finally:
        run.chmod(0o755)
    assert "ERROR" in err and "cuda.env" in err


def test_pick_gpus_cuda_path_untouched():
    s = (BIN / "stickllm-pick-gpus").read_text(encoding="utf-8")
    assert "if (( total >= 16000 )); then" in s
    assert 'write_env "$ids" cuda' in s
    assert "} >\"$OUT\" 2>/dev/null || true" not in s  # errors no longer swallowed


def test_unit_runs_pick_gpus_as_root():
    u = UNIT.read_text(encoding="utf-8")
    assert "ExecStartPre=-+/usr/local/bin/stickllm-pick-gpus" in u
    assert "ExecStartPre=-/usr/local/bin/stickllm-pick-gpus" not in u
    assert "User=stickllm-llama" in u


# --- planner ---------------------------------------------------------------

def _load_control(tmp_path, monkeypatch):
    monkeypatch.setenv("STICKLLM_RUN", str(tmp_path / "run"))
    (tmp_path / "run").mkdir(exist_ok=True)
    loader = importlib.machinery.SourceFileLoader("stickllm_control_amd", str(BIN / "stickllm-control"))
    spec = importlib.util.spec_from_loader("stickllm_control_amd", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _meta_qwen25_3b():
    a = "qwen2"
    return {"general.architecture": a, f"{a}.block_count": 36, f"{a}.context_length": 32768,
            f"{a}.embedding_length": 2048, f"{a}.attention.head_count": 16,
            f"{a}.attention.head_count_kv": 2}


def test_planner_vulkan_rows_from_cuda_env(tmp_path, monkeypatch):
    c = _load_control(tmp_path, monkeypatch)
    (tmp_path / "run" / "cuda.env").write_text(
        "STICKLLM_BACKEND=vulkan\nSTICKLLM_GPU_COUNT=2\nSTICKLLM_VULKAN_GPUS=0:8192:8030,1:8192:8187\n")
    rows = c.vulkan_gpu_rows()
    assert [(g["device"], g["total_mib"], g["free_mib"]) for g in rows] == [
        ("Vulkan0", 8192, 8030), ("Vulkan1", 8192, 8187)]
    monkeypatch.setattr(c, "nvidia_gpu_rows", lambda: [])
    best = c.suitable_gpus()
    assert len(best) == 1 and best[0]["device"] == "Vulkan1"
    plan = c.plan_gpu_fit(file_bytes=int(1.93 * 1e9), ctx=2048, meta=_meta_qwen25_3b())
    assert plan["fit"] == "full" and plan["gpu_count"] == 1
    assert plan["n_gpu_layers"] == 37 and plan["devices"] == "Vulkan1"
    assert plan["tensor_split"] == "" and plan["ctx"] == 2048 and plan["ctx_max"] == 32768
    shell = c.write_offload_plan(dict(plan))["shell"]
    assert "STICKLLM_PLAN_DEVICES=Vulkan1" in shell and "STICKLLM_PLAN_CTX_MAX=32768" in shell


def test_planner_vulkan_ignored_for_cuda_backend(tmp_path, monkeypatch):
    c = _load_control(tmp_path, monkeypatch)
    (tmp_path / "run" / "cuda.env").write_text(
        "STICKLLM_BACKEND=cuda\nSTICKLLM_VULKAN_GPUS=0:8192:8030\n")
    assert c.vulkan_gpu_rows() == []
    rows = [{"index": 0, "total_mib": 24576, "free_mib": 24000},
            {"index": 1, "total_mib": 24576, "free_mib": 23000},
            {"index": 2, "total_mib": 8192, "free_mib": 8000}]
    plan = c.plan_gpu_fit(file_bytes=40 * GiB, ctx=8192, meta={}, gpus=rows)
    assert plan["gpu_count"] == 2 and plan["devices"] == "0,1"
    assert plan["tensor_split"] == "24000,23000"


def test_planner_ctx_capped_to_train_never_raised(tmp_path, monkeypatch):
    c = _load_control(tmp_path, monkeypatch)
    rows = [{"index": 1, "device": "Vulkan1", "total_mib": 8192, "free_mib": 8000, "backend": "vulkan"}]
    p = c.plan_gpu_fit(file_bytes=2 * GiB, ctx=65536, meta=_meta_qwen25_3b(), gpus=rows)
    assert p["ctx"] == 32768
    p = c.plan_gpu_fit(file_bytes=2 * GiB, ctx=2048, meta=_meta_qwen25_3b(), gpus=rows)
    assert p["ctx"] == 2048


# --- llama-start --------------------------------------------------------------

def _start(tmp_path, backend, extra_env=None, cuda_env=None):
    model = tmp_path / "m.gguf"
    model.write_bytes(b"GGUF")
    out = tmp_path / "args.txt"
    fake = _exe(tmp_path / "fake-llama", f'printf "%s\\n" "$@" > {out}\n')
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    if cuda_env is not None:
        (run / "cuda.env").write_text(cuda_env)
    env = {k: v for k, v in os.environ.items() if not k.startswith("STICKLLM_")}
    env.update({
        "STICKLLM_MODEL": str(model), "STICKLLM_BACKEND": backend, "STICKLLM_RUN": str(run),
        "STICKLLM_LLAMA_CPU": str(fake), "STICKLLM_LLAMA_CUDA": str(fake), "STICKLLM_LLAMA_VULKAN": str(fake),
        "STICKLLM_LIB_CPU": str(tmp_path / "nolib"), "STICKLLM_LIB_VULKAN": str(tmp_path / "nolibvk"),
    })
    env.update(extra_env or {})
    p = subprocess.run(["bash", str(BIN / "stickllm-llama-start")], env=env, capture_output=True,
                       text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return out.read_text().split("\n"), p.stderr


@pytest.mark.parametrize("ctx", ["2048", "4096", "8192"])
def test_llama_start_honours_user_ctx(tmp_path, ctx):
    a, err = _start(tmp_path, "cpu", {"STICKLLM_CTX_SIZE": ctx})
    assert a[a.index("--ctx-size") + 1] == ctx
    assert "raising ctx-size" not in err


def test_llama_start_ctx_from_model_env(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    model = tmp_path / "m.gguf"
    (run / "model.env").write_text(f"STICKLLM_MODEL={model}\nSTICKLLM_CTX_SIZE=2048\n")
    a, _ = _start(tmp_path, "cpu", {"STICKLLM_MODEL": ""})
    assert a[a.index("--ctx-size") + 1] == "2048"


def test_llama_start_ctx_capped_never_raised(tmp_path):
    a, err = _start(tmp_path, "cpu", {"STICKLLM_CTX_SIZE": "65536", "STICKLLM_PLAN_CTX_MAX": "32768"})
    assert a[a.index("--ctx-size") + 1] == "32768" and "capping ctx-size" in err
    a, _ = _start(tmp_path, "cpu", {"STICKLLM_CTX_SIZE": "2048", "STICKLLM_PLAN_CTX_MAX": "32768"})
    assert a[a.index("--ctx-size") + 1] == "2048"
    a, _ = _start(tmp_path, "cpu", {})
    assert a[a.index("--ctx-size") + 1] == "32768"  # unset → old default


def test_llama_start_vulkan_single_device(tmp_path):
    cuda_env = ("STICKLLM_BACKEND=vulkan\nSTICKLLM_GPU_COUNT=2\nSTICKLLM_VRAM_FREE_MIB=8187\n"
                "STICKLLM_VULKAN_DEVICE=Vulkan1\nSTICKLLM_VULKAN_GPUS=0:8192:8030,1:8192:8187\n")
    a, _ = _start(tmp_path, "vulkan", {"STICKLLM_CTX_SIZE": "2048", "STICKLLM_PLAN_NGL": "37",
                                       "STICKLLM_PLAN_GPU_COUNT": "1", "STICKLLM_PLAN_DEVICES": "Vulkan1"},
                  cuda_env=cuda_env)
    assert a[a.index("--device") + 1] == "Vulkan1"
    assert a[a.index("--n-gpu-layers") + 1] == "37"
    assert a[a.index("--ctx-size") + 1] == "2048"
    assert "--tensor-split" not in a


def test_llama_start_vulkan_no_device_when_ngl_zero(tmp_path):
    a, _ = _start(tmp_path, "vulkan", {"STICKLLM_PLAN_NGL": "0", "STICKLLM_PLAN_DEVICES": "Vulkan1"},
                  cuda_env="STICKLLM_BACKEND=vulkan\n")
    assert "--device" not in a


def test_llama_start_cuda_has_no_vulkan_device(tmp_path):
    s = (BIN / "stickllm-llama-start").read_text(encoding="utf-8")
    cuda_block = s[s.index("# 1) CUDA"):s.index("# 2) Vulkan")]
    assert "--device" not in cuda_block


# --- PCIe link ranking / PCI mapping / runtime PM (x16 over x1 riser) --------

MiB = 1024 * 1024
LINK_X16 = {"current_link_width": "16", "current_link_speed": "2.5 GT/s PCIe",
            "max_link_width": "16", "max_link_speed": "8.0 GT/s PCIe"}
LINK_X1 = {"current_link_width": "1", "current_link_speed": "2.5 GT/s PCIe",
           "max_link_width": "16", "max_link_speed": "8.0 GT/s PCIe"}


def test_pick_vulkan_prefers_x16_over_x1_riser(tmp_path):
    # The test rig: card0 x16 (display, 170 MiB used), card1 on an x1 riser.
    drm = _sysfs(tmp_path, {
        "card0": ("0000:10:00.0", RX570, 170 * MiB),
        "card1": ("0000:21:00.0", RX570, 5 * MiB),
    }, links={"card0": LINK_X16, "card1": LINK_X1})
    v, err = _pick(tmp_path, drm=drm, vulkaninfo=VK_TWO_RX570.format(bus0=16, bus1=33),
                   ld_free=("8022", "8187"))
    assert v["STICKLLM_VULKAN_GPUS"] == "0:8192:8022:16:2500,1:8192:8187:1:2500"
    assert v["STICKLLM_VULKAN_DEVICE"] == "Vulkan0"
    assert v["STICKLLM_VULKAN_PCI"] == "0000:10:00.0"
    assert v["STICKLLM_VULKAN_LINK"] == "x16@2500MT/s"
    assert v["STICKLLM_VRAM_FREE_MIB"] == "8022"
    assert "WARN" not in err


def test_pick_vulkan_x16_mapping_follows_pci_not_order(tmp_path):
    # vulkaninfo lists the riser card (bus 0x21) first → Vulkan1 is the x16 card0.
    drm = _sysfs(tmp_path, {
        "card0": ("0000:10:00.0", RX570, 170 * MiB),
        "card1": ("0000:21:00.0", RX570, 5 * MiB),
    }, links={"card0": LINK_X16, "card1": LINK_X1})
    v, _ = _pick(tmp_path, drm=drm, vulkaninfo=VK_TWO_RX570.format(bus0=33, bus1=16),
                 ld_free=("8187", "8022"))
    assert v["STICKLLM_VULKAN_GPUS"] == "0:8192:8187:1:2500,1:8192:8022:16:2500"
    assert v["STICKLLM_VULKAN_DEVICE"] == "Vulkan1"
    assert v["STICKLLM_VULKAN_PCI"] == "0000:10:00.0"


def test_pick_vulkan_matches_full_pci_address_same_bus(tmp_path):
    vk = VK_TWO_RX570.format(bus0=16, bus1=16)
    vk = vk.replace("pciDevice   = 0", "pciDevice   = 1", 1)  # Vulkan0 = 10:01.0
    drm = _sysfs(tmp_path, {
        "card0": ("0000:10:00.0", RX570, 1 * GiB),
        "card1": ("0000:10:01.0", RX570, 3 * GiB),
    })
    v, _ = _pick(tmp_path, drm=drm, vulkaninfo=vk, ld_free=("5120", "7168"))
    assert v["STICKLLM_VULKAN_GPUS"] == "0:8192:5120:0:0,1:8192:7168:0:0"


def test_pick_vulkan_link_falls_back_to_max_link(tmp_path):
    only_max_x16 = {"max_link_width": "16", "max_link_speed": "8.0 GT/s PCIe"}
    only_max_x4 = {"max_link_width": "4", "max_link_speed": "8.0 GT/s PCIe"}
    drm = _sysfs(tmp_path, {
        "card0": ("0000:10:00.0", RX570, 2 * GiB),
        "card1": ("0000:21:00.0", RX570, 0),
    }, links={"card0": only_max_x16, "card1": only_max_x4})
    v, _ = _pick(tmp_path, drm=drm, vulkaninfo=VK_TWO_RX570.format(bus0=16, bus1=33),
                 ld_free=("6144", "8192"))
    assert v["STICKLLM_VULKAN_GPUS"] == "0:8192:6144:16:8000,1:8192:8192:4:8000"
    assert v["STICKLLM_VULKAN_DEVICE"] == "Vulkan0"


def test_pick_vulkan_x16_without_room_loses_to_roomy_card(tmp_path):
    drm = _sysfs(tmp_path, {
        "card0": ("0000:10:00.0", RX570, 6 * GiB),   # x16 but only 2048 MiB free
        "card1": ("0000:21:00.0", RX570, 0),
    }, links={"card0": LINK_X16, "card1": LINK_X1})
    v, _ = _pick(tmp_path, drm=drm, vulkaninfo=VK_TWO_RX570.format(bus0=16, bus1=33),
                 ld_free=("2048", "8192"))
    assert v["STICKLLM_VULKAN_DEVICE"] == "Vulkan1"


def test_pick_vulkan_warns_when_list_devices_disagrees(tmp_path):
    drm = _sysfs(tmp_path, {
        "card0": ("0000:10:00.0", RX570, 170 * MiB),
        "card1": ("0000:21:00.0", RX570, 5 * MiB),
    }, links={"card0": LINK_X16, "card1": LINK_X1})
    _, err = _pick(tmp_path, drm=drm, vulkaninfo=None, ld_free=("4000", "8187"))
    assert "WARN Vulkan0 --list-devices free=4000MiB" in err


def test_pick_vulkan_pins_runtime_pm_on_chosen_card_only(tmp_path):
    drm = _sysfs(tmp_path, {
        "card0": ("0000:10:00.0", RX570, 170 * MiB),
        "card1": ("0000:21:00.0", RX570, 5 * MiB),
    }, links={"card0": LINK_X16, "card1": LINK_X1}, power={"card0": "auto", "card1": "auto"})
    _, err = _pick(tmp_path, drm=drm, vulkaninfo=VK_TWO_RX570.format(bus0=16, bus1=33),
                   ld_free=("8022", "8187"))
    devs = tmp_path / "devices"
    assert (devs / "0000:10:00.0" / "power" / "control").read_text().strip() == "on"
    assert (devs / "0000:21:00.0" / "power" / "control").read_text().strip() == "auto"
    assert "runtime PM pinned on" in err


def test_pick_vulkan_runtime_pm_pin_can_be_disabled(tmp_path):
    drm = _sysfs(tmp_path, {"card0": ("0000:10:00.0", RX570, 0)},
                 links={"card0": LINK_X16}, power={"card0": "auto"})
    _pick(tmp_path, drm=drm, vulkaninfo=VK_TWO_RX570.format(bus0=16, bus1=99),
          ld_free=("8192",), extra_env={"STICKLLM_VK_PM_PIN": "0"})
    assert (tmp_path / "devices" / "0000:10:00.0" / "power" / "control").read_text().strip() == "auto"


def test_planner_prefers_link_among_cards_that_fit(tmp_path, monkeypatch):
    c = _load_control(tmp_path, monkeypatch)
    (tmp_path / "run" / "cuda.env").write_text(
        "STICKLLM_BACKEND=vulkan\nSTICKLLM_GPU_COUNT=2\n"
        "STICKLLM_VULKAN_GPUS=0:8192:8022:16:2500,1:8192:8187:1:2500\n")
    rows = c.vulkan_gpu_rows()
    assert [(g["device"], g["link_width"], g["link_mts"]) for g in rows] == [
        ("Vulkan0", 16, 2500), ("Vulkan1", 1, 2500)]
    monkeypatch.setattr(c, "nvidia_gpu_rows", lambda: [])
    plan = c.plan_gpu_fit(file_bytes=int(1.93 * 1e9), ctx=2048, meta=_meta_qwen25_3b())
    assert plan["devices"] == "Vulkan0" and plan["fit"] == "full" and plan["n_gpu_layers"] == 37


def test_planner_link_only_counts_when_plan_fits(tmp_path, monkeypatch):
    c = _load_control(tmp_path, monkeypatch)
    rows = [
        {"index": 0, "device": "Vulkan0", "total_mib": 8192, "free_mib": 3000,
         "link_width": 16, "link_mts": 8000, "backend": "vulkan"},
        {"index": 1, "device": "Vulkan1", "total_mib": 8192, "free_mib": 8000,
         "link_width": 1, "link_mts": 2500, "backend": "vulkan"},
    ]
    # ~3.6 GiB needed: only Vulkan1 has room, so link does not matter.
    plan = c.plan_gpu_fit(file_bytes=int(1.93 * 1e9), ctx=2048, meta=_meta_qwen25_3b(), gpus=rows)
    assert plan["devices"] == "Vulkan1"
    # Neither fits a huge model: most free VRAM wins (partial offload).
    plan = c.plan_gpu_fit(file_bytes=20 * GiB, ctx=2048, meta=_meta_qwen25_3b(), gpus=rows)
    assert plan["devices"] == "Vulkan1" and plan["fit"] == "partial"


def test_planner_accepts_old_three_field_rows(tmp_path, monkeypatch):
    c = _load_control(tmp_path, monkeypatch)
    (tmp_path / "run" / "cuda.env").write_text(
        "STICKLLM_BACKEND=vulkan\nSTICKLLM_VULKAN_GPUS=0:8192:8030,1:8192:8187,bad:1\n")
    rows = c.vulkan_gpu_rows()
    assert [(g["device"], g["link_width"]) for g in rows] == [("Vulkan0", 0), ("Vulkan1", 0)]
