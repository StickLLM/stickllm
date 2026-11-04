"""0.5.9 monitor cleanup: real card names, model badge only while running, every drive."""
import importlib.util
import os
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = ROOT / "overlay" / "usr" / "local" / "lib" / "stickllm_system.py"


def _load():
    spec = importlib.util.spec_from_file_location("stickllm_system_mon059", SYSTEM)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_card_names_cmp_and_amd():
    m = _load()
    assert m.card_name("NVIDIA Graphics Device", "NVIDIA GA100 [CMP 170HX]", "10de:20c2") == "NVIDIA CMP 170HX"
    assert m.card_name("NVIDIA Graphics Device", "NVIDIA Device 20c2", "10de:20c2") == "NVIDIA CMP 170HX"
    assert m.card_name("NVIDIA Graphics Device", "", "10de:20c2") == "NVIDIA CMP 170HX"
    assert m.card_name("NVIDIA GeForce RTX 3090", "NVIDIA GA102 [GeForce RTX 3090]", "10de:2204") == "NVIDIA GeForce RTX 3090"
    assert m.card_name("", "AMD Ellesmere [Radeon RX 470/480/570/570X/580/580X/590]", "1002:67df").startswith("AMD Radeon RX 470")
    assert m.card_name("", "", "1002:67df") == "AMD Radeon RX 470/480/570/580"


def test_compute_apps_match_by_pid_or_name():
    m = _load()
    text = ("4242, /usr/local/bin/stickllm-run, 00000000:C2:00.0, 12900\n"
            "999, python3, 00000000:81:00.0, 300\n"
            "77, llama-server, 00000000:81:00.0, 1000\n")
    got = m.parse_compute_apps(text, main_pid=4242)
    assert got == {"0000:c2:00.0": 12900, "0000:81:00.0": 1000}
    assert m.parse_compute_apps(text, main_pid=None) == {"0000:81:00.0": 1000}


def test_stopped_service_never_holds_the_model(tmp_path, monkeypatch):
    m = _load()
    run = tmp_path / "run"
    run.mkdir()
    (run / "llama-runtime.env").write_text("backend=cuda\n")
    (run / "llama-plan.env").write_text("STICKLLM_PLAN_DEVICES=2\nSTICKLLM_PLAN_GPU_COUNT=1\n")
    monkeypatch.setattr(m, "RUN_DIR", run)
    monkeypatch.setattr(m.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(m, "pci_names", lambda: {})
    monkeypatch.setattr(m, "pci_id", lambda bdf, root=None: "10de:2204")
    monkeypatch.setattr(m, "_llama_main_pid", lambda: None)
    row = "2, 00000000:C2:00.0, NVIDIA GeForce RTX 3090, 12000, 24576, 50, 0, 30, 350, 40, 210, 405, 1, 16"

    def fake_run(argv, timeout=4):
        if any("query-compute-apps" in a for a in argv):
            return ""  # no process list: placement fallback
        return row + "\n"

    monkeypatch.setattr(m, "_run", fake_run)
    assert m._nvidia_rows(running=False)[0]["holds_model"] is False
    assert m._nvidia_rows(running=True)[0]["holds_model"] is True
    assert m.model_running({"available": True, "llama_up": False, "service": "inactive"}) is False
    assert m.model_running({"available": True, "llama_up": False, "service": "active"}) is True
    st = m.status_line({"available": True, "name": "Qwen3.5-4B Q4_K_M.gguf", "service": "inactive", "llama_up": False},
                       {"gpus": [{"index": 2, "temperature_c": 50, "holds_model": False}]}, {})
    assert st == "stopped · Qwen3.5-4B Q4_K_M"


def _blk(sb: Path, cls: Path, devs: Path, name, sectors, model="", rot="0", usb=False, parts=()):
    real = devs / ("usb1/host" if usb else "pci0") / "block" / name
    real.mkdir(parents=True)
    (real / "size").write_text(str(sectors))
    (real / "removable").write_text("1" if usb else "0")
    (real / "queue").mkdir()
    (real / "queue" / "rotational").write_text(rot)
    (real / "device").mkdir()
    (real / "device" / "model").write_text(model + "\n")
    os.symlink(real, sb / name)
    os.symlink(real, cls / name)
    for p in parts:
        (real / p).mkdir()
        (real / p / "partition").write_text("1")
        os.symlink(real / p, cls / p)


def test_drives_list_all_with_roles_and_io(tmp_path):
    m = _load()
    sysd = tmp_path / "sys"
    sb, cls, devs = sysd / "block", sysd / "class" / "block", sysd / "devices"
    for d in (sb, cls, devs):
        d.mkdir(parents=True)
    _blk(sb, cls, devs, "sda", 120000000, "Ultra Fit", usb=True, parts=("sda1", "sda2"))
    _blk(sb, cls, devs, "nvme0n1", 3907029168, "Fanxiang S880 2TB", parts=("nvme0n1p1",))
    _blk(sb, cls, devs, "sdb", 7814037168, "WDC WD40EFRX", rot="1")
    _blk(sb, cls, devs, "loop0", 1000)
    dm = devs / "virtual" / "block" / "dm-0"
    (dm / "slaves").mkdir(parents=True)
    (dm / "size").write_text("100")
    os.symlink(cls / "nvme0n1p1", dm / "slaves" / "nvme0n1p1")
    os.symlink(dm, sb / "dm-0")
    os.symlink(dm, cls / "dm-0")
    mounts = ("/dev/sda1 /run/live/medium iso9660 ro 0 0\n"
              "/dev/sda2 /run/live/persistence ext4 rw 0 0\n"
              f"/dev/{'nvme0n1p1'} /mnt/stickllm-host ext4 rw 0 0\n"
              f"/dev/{'nvme0n1p1'} /mnt/bind-copy ext4 rw 0 0\n"
              "/dev/dm-0 /var/lib/stickllm/vault ext4 rw 0 0\n"
              "/dev/loop0 /run/live/rootfs/filesystem.squashfs squashfs ro 0 0\n")
    U = namedtuple("U", "total used free")
    usage = lambda p: U(100 * 2**30, 40 * 2**30, 60 * 2**30)
    # /dev/<name> realpath: fake by making _dev_name pure basename
    m._dev_name = lambda dev: os.path.basename(dev)
    m._LAST_IO.clear()
    stats1 = "8 0 sda 1 0 0 0 1 0 0 0 0 0 0\n259 0 nvme0n1 1 0 0 0 1 0 0 0 0 0 0\n"
    stats2 = "8 0 sda 1 0 2000 0 1 0 0 0 0 0 0\n259 0 nvme0n1 1 0 2000000 0 1 0 4000 0 0 1500 0\n"
    kw = dict(sys_block=sb, mounts_text=mounts, usage=usage, vault_mnt="/var/lib/stickllm/vault",
              models_path="/mnt/stickllm-host/stickllm/models")
    m.drives_block(diskstats_text=stats1, now=100.0, **kw)
    rows = m.drives_block(diskstats_text=stats2, now=102.0, **kw)
    by = {r["name"]: r for r in rows}
    assert set(by) == {"sda", "nvme0n1", "sdb"}  # loop/dm skipped
    assert [r["name"] for r in rows][:2] == ["sda", "nvme0n1"]
    assert by["sda"]["roles"] == ["boot"] and by["sda"]["kind"] == "USB"
    assert set(by["nvme0n1"]["roles"]) == {"models", "vault"} and by["nvme0n1"]["kind"] == "NVMe"
    assert by["sdb"]["kind"] == "HDD" and by["sdb"]["mounts"] == []
    assert len(by["nvme0n1"]["mounts"]) == 2  # host fs once (bind copy skipped) + vault on dm-0
    assert by["nvme0n1"]["read_mb_s"] == round(2000000 * 512 / 2 / 1e6, 1)
    assert by["sda"]["read_mb_s"] == round(2000 * 512 / 2 / 1e6, 1)
    assert by["nvme0n1"]["size"] == 3907029168 * 512
    # utilisation: io_ticks delta 1500 ms over a 2 s sample = 75 % busy
    assert by["nvme0n1"]["busy_percent"] == 75.0
    assert by["sda"]["busy_percent"] == 0.0
    assert by["sdb"]["busy_percent"] is None  # no diskstats line


def test_parse_diskstats_io_ticks_and_busy_cap():
    m = _load()
    st = m.parse_diskstats("8 0 sda 1 0 10 0 1 0 20 0 0 777 0\n8 1 sdb 1 0 10 0 1 0 20\n")
    assert st["sda"] == (10, 20, 777)
    assert st["sdb"] == (10, 20, None)  # short (old kernel) line: no busy %


def test_n_ctx_is_server_ctx_not_sum_of_slots():
    m = _load()
    # llama-server --ctx-size 65536 --parallel 4 with a unified KV cache: every
    # slot reports the full 65536, the old sum made it 262144.
    slots = [{"id": i, "n_ctx": 65536, "n_past": 0} for i in range(4)]
    props = {"default_generation_settings": {"n_ctx": 65536}, "total_slots": 4}
    assert m.server_n_ctx(props, slots) == 65536
    assert m.server_n_ctx(None, slots) == 65536            # /props missing: max, not sum
    assert m.server_n_ctx({"default_generation_settings": {}}, [{"n_ctx": 16384}] * 4) == 16384
    assert m.server_n_ctx({"n_ctx": 32768}, None) == 32768  # older top-level shape
    assert m.server_n_ctx(None, None) is None


def test_llama_live_uses_props_n_ctx(monkeypatch):
    m = _load()
    import io, json as _json
    bodies = {
        "/metrics": "llamacpp:predicted_tokens_seconds 42.5\n",
        "/slots": _json.dumps([{"id": i, "n_ctx": 65536, "n_past": 1000} for i in range(4)]),
        "/props": _json.dumps({"default_generation_settings": {"n_ctx": 65536}}),
    }

    class R(io.BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_open(url, timeout=None):
        u = url if isinstance(url, str) else url.full_url
        for k, v in bodies.items():
            if u.endswith(k):
                return R(v.encode())
        raise OSError("nope")

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    out = m.llama_live(8080)
    assert out["n_ctx"] == 65536
    assert out["ctx_used"] == 4000 and out["gen_tok_s"] == 42.5
