"""0.6.0 (A1): Agent Zero image bundled on the ISO, loaded offline."""
import gzip
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import re
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "overlay/usr/local/lib/stickllm_agent.py"
AGENT_SH = ROOT / "overlay/usr/local/bin/stickllm-agent"
BUNDLE = ROOT / "scripts/lib/a0_bundle.py"
PIN = ROOT / "overlay/usr/local/share/stickllm/agent-zero.pin"


def _load(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def _sha(b):
    return "sha256:" + hashlib.sha256(b).hexdigest()


def _layer(name, data):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as t:
        info = tarfile.TarInfo(name)
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue())


def _fake(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    config = json.dumps({"architecture": "amd64", "rootfs": {"type": "layers"}}).encode()
    layers = [_layer("a", b"x" * 5000), _layer("b", b"y" * 9000)]
    manifest = json.dumps({
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "config": {"mediaType": "application/vnd.oci.image.config.v1+json", "digest": _sha(config), "size": len(config)},
        "layers": [{"mediaType": "application/vnd.oci.image.layer.v1.tar+gzip", "digest": _sha(l), "size": len(l)} for l in layers],
    }).encode()
    for blob in [config] + layers:
        (cache / _sha(blob)[7:]).write_bytes(blob)
    (cache / ("manifest-" + _sha(manifest)[7:] + ".json")).write_bytes(manifest)
    pin = tmp_path / "agent-zero.pin"
    pin.write_text(
        "image=agent0ai/agent-zero\nversion=v2.15\n"
        f"amd64_digest={_sha(manifest)}\nconfig_digest={_sha(config)}\n")
    return pin, cache, config, layers


def test_pin_has_the_config_digest_of_the_amd64_manifest():
    text = PIN.read_text()
    assert "amd64_digest=sha256:fb62c7f081fd6c16d19807c0dc7eb7f9b710ba5de541d0547f8031433916cde2" in text
    assert "config_digest=sha256:6eca4f3190ab7cafe9b49703dc98f184acddfbd44130f64396213f3f57bcdbd4" in text
    assert "Not baked into the ISO" not in text


def test_pack_splits_into_verified_parts_docker_can_load(tmp_path, monkeypatch):
    b = _load(BUNDLE, "a0_bundle_t1")
    monkeypatch.setattr(b, "PART_SIZE", 4096)
    pin, cache, config, layers = _fake(tmp_path)
    out = tmp_path / "out"
    doc = b.pack(b.parse_pin(pin), cache, out)
    assert len(doc["parts"]) > 1 and all(p["size"] <= 4096 for p in doc["parts"])
    assert b.verify(out) == 0
    assert doc["tag"] == "stickllm/agent-zero:v2.15"
    tar_bytes = b"".join((out / p["name"]).read_bytes() for p in doc["parts"])
    assert len(tar_bytes) == doc["tar_size"]
    with tarfile.open(fileobj=io.BytesIO(tar_bytes)) as t:
        m = json.load(t.extractfile("manifest.json"))
        assert m[0]["RepoTags"] == ["stickllm/agent-zero:v2.15"]
        assert _sha(t.extractfile(m[0]["Config"]).read()) == _sha(config)
        assert [_sha(t.extractfile(n).read()) for n in m[0]["Layers"]] == [_sha(l) for l in layers]
    # A damaged part is caught.
    first = out / doc["parts"][0]["name"]
    first.write_bytes(b"z" + first.read_bytes()[1:])
    assert b.verify(out) == 1


def test_pack_refuses_a_tampered_blob(tmp_path):
    b = _load(BUNDLE, "a0_bundle_t2")
    pin, cache, config, layers = _fake(tmp_path)
    (cache / _sha(layers[0])[7:]).write_bytes(b"evil")
    # The cached blob fails its sha256 so fetch re-downloads; no network here.
    def fake_blob(reg, digest, dest, size=None):
        if dest.exists() and b._sha256_file(dest) == digest:
            return
        raise SystemExit("download failed")
    b._fetch_blob = fake_blob
    try:
        b.pack(b.parse_pin(pin), cache, tmp_path / "out")
    except SystemExit:
        pass
    else:
        raise AssertionError("tampered blob was packed")


def _bundle_on_medium(tmp_path, monkeypatch):
    b = _load(BUNDLE, "a0_bundle_t3")
    monkeypatch.setattr(b, "PART_SIZE", 4096)
    pin, cache, _, _ = _fake(tmp_path)
    medium = tmp_path / "medium"
    doc = b.pack(b.parse_pin(pin), cache, medium)
    a = _load(AGENT, "stickllm_agent_bundle")
    monkeypatch.setattr(a, "PIN_PATH", pin)
    monkeypatch.setattr(a, "STATUS_PATH", tmp_path / "status.json")
    return a, medium, doc


def test_bundle_stream_checks_parts_and_reports_progress(tmp_path, monkeypatch):
    a, medium, doc = _bundle_on_medium(tmp_path, monkeypatch)
    info = a.bundle_info((tmp_path / "nope", medium))
    assert info and info["dir"] == str(medium)
    sink = io.BytesIO()
    assert a.bundle_stream(sink, info) == 0
    assert sink.getvalue() == b"".join((medium / p["name"]).read_bytes() for p in doc["parts"])
    st = json.loads((tmp_path / "status.json").read_text())
    # 0.6.2 (A4): loading is step 1 of 6 (0-55% of the whole install bar).
    assert st["state"] == "installing" and st["progress"] == 55 and st.get("step") == 2
    last = medium / doc["parts"][-1]["name"]
    data = last.read_bytes()
    last.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))  # same size, wrong hash
    assert a.bundle_stream(io.BytesIO(), a.bundle_info((medium,))) == 3
    last.unlink()
    assert a.bundle_info((medium,)) is None  # incomplete bundle is ignored


def test_bundle_for_another_pin_is_ignored(tmp_path, monkeypatch):
    a, medium, _ = _bundle_on_medium(tmp_path, monkeypatch)
    other = tmp_path / "other.pin"
    other.write_text(PIN.read_text())
    monkeypatch.setattr(a, "PIN_PATH", other)
    assert a.bundle_info((medium,)) is None


def test_image_on_disk_accepts_the_loaded_local_tag(tmp_path, monkeypatch):
    a = _load(AGENT, "stickllm_agent_tag")
    cfg = a.config_digest()
    repo = tmp_path / "image" / "overlay2"
    repo.mkdir(parents=True)
    path = repo / "repositories.json"
    path.write_text(json.dumps({"Repositories": {"stickllm/agent-zero": {"stickllm/agent-zero:v2.15": cfg}}}))
    assert a.image_on_disk(tmp_path) is True
    path.write_text(json.dumps({"Repositories": {"stickllm/agent-zero": {"stickllm/agent-zero:v2.15": "sha256:" + "0" * 64}}}))
    assert a.image_on_disk(tmp_path) is False


def test_docker_root_prefers_existing_ssd_then_the_stick(tmp_path, monkeypatch):
    a = _load(AGENT, "stickllm_agent_drive")
    monkeypatch.delenv("STICKLLM_DOCKER_DIR", raising=False)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(a, "DATA_MNT", data)
    mounts = f"/dev/sdb3 {data} ext4 rw 0 0\n"
    ssd = tmp_path / "ssd" / "stickllm-docker"
    monkeypatch.setattr(a, "free_bytes", lambda p: 64 << 30)
    # No SSD data-root yet: the stick's data partition.
    assert a.choose_docker_root(mounts_text=mounts, ssd_root=ssd, pref="auto") == data / "stickllm-docker"
    # An SSD data-root that already holds images (0.5.x) is kept.
    (ssd / "image").mkdir(parents=True)
    assert a.choose_docker_root(mounts_text=mounts, ssd_root=ssd, pref="auto") == ssd
    assert a.choose_docker_root(mounts_text=mounts, ssd_root=ssd, pref="usb") == data / "stickllm-docker"
    # No drive mounted at all: nothing to choose.
    monkeypatch.setattr(a, "free_bytes", lambda p: 1 << 30)
    assert a.choose_docker_root(mounts_text="", ssd_root=None, pref="auto") is None


def test_installer_loads_the_bundle_before_any_pull():
    sh = AGENT_SH.read_text()
    install = sh[sh.index("cmd_install() {"):sh.index("# stickllm-agent.service owns the container")]
    assert install.index("bundle-info") < install.index("docker_cli pull")
    assert "load_bundle" in install and 'smoke_image "$tag"' in install
    start = sh.index("load_bundle() {")
    loader = sh[start:sh.index("\n}\n", start)]
    assert "bundle-stream | docker_cli load" in loader and "config-digest" in loader
    # First agent start loads the bundle, never an automatic network pull.
    ready = sh[sh.index("cmd_image_ready() {"):sh.index("run_ref() {")]
    assert "stickllm-agent-install.service" in ready and "bundle-info" in ready
    assert 'ref="$(run_ref)"' in sh


def test_build_bundles_agent_zero_on_the_iso():
    build = (ROOT / "scripts/lib/docker-build-live.sh").read_text()
    assert "a0_bundle.py pack" in build and "config/includes.binary/stickllm/agent-zero" in build
    assert "/stickllm-out/cache/agent-zero" in build
    assert re.search(r'VERSION="\$\{STICKLLM_VERSION:-\d+\.\d+\.\d+\}"', (ROOT / "scripts/build.sh").read_text(encoding="utf-8"))


def test_a5_ui_status_line():
    app = (ROOT / "ui/app.js").read_text()
    body = app.split("function agentProgressLine", 1)[1].split("\nasync function ", 1)[0]
    for word in ("Loading Agent Zero from the stick", "Downloading Agent Zero", "Checking Agent Zero",
                 "Agent Zero is starting", "step ${s.step} of ${s.steps}", "%"):
        assert word in body
    link = app.split("async function refreshAgentLink", 1)[1].split("\nasync function ", 1)[0]
    assert "agentProgressLine(s)" in link and "s.bundled" in link
