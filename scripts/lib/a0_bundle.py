#!/usr/bin/env python3
"""Agent Zero image bundle for the ISO (StickLLM 0.6.0, A1).

Builds a docker-archive tar of the pinned amd64 image straight from the
registry blobs, so the build host needs no Docker image store at all (Docker
Desktop's containerd store and the stick's docker.io 20.10 classic store save
and load different formats). Every blob is checked against its sha256: the
manifest against the pin's amd64_digest, the config against the pin's
config_digest, each layer against the manifest. The layers stay gzip (as
pulled), so nothing is recompressed and docker 20.10 `docker load` accepts
the tar as is. Its image ID is the config digest.

The tar is split into 1 GiB parts (agent-zero.tar.part-000 ...): ISO 9660
level 1/2 cannot hold a file of 4 GiB or more, and small parts keep the
stick's read-and-verify progress smooth. bundle.json lists every part with
its size and sha256.

  a0_bundle.py fetch <pin> <cache-dir>          download + verify blobs (resumable)
  a0_bundle.py pack  <pin> <cache-dir> <out>    write parts + bundle.json
  a0_bundle.py verify <out>                     re-hash parts against bundle.json
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

PART_SIZE = 1 << 30
REGISTRY = "https://registry-1.docker.io"
AUTH = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull"
ACCEPT = ("application/vnd.oci.image.manifest.v1+json,"
          "application/vnd.docker.distribution.manifest.v2+json")
LOCAL_TAG = "stickllm/agent-zero"
BUNDLE_FORMAT = 1


def parse_pin(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    for key in ("image", "version", "amd64_digest", "config_digest"):
        if not out.get(key):
            raise SystemExit(f"a0_bundle: pin is missing {key}")
    return out


def local_tag(pin: dict) -> str:
    return f"{LOCAL_TAG}:{pin['version']}"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


class _Registry:
    def __init__(self, repo: str):
        self.repo = repo
        self.token = ""

    def _auth(self) -> None:
        with urllib.request.urlopen(AUTH.format(repo=self.repo), timeout=60) as r:
            self.token = json.load(r)["token"]

    def open(self, path: str, accept: str = ""):
        for attempt in range(2):
            if not self.token:
                self._auth()
            req = urllib.request.Request(REGISTRY + path)
            req.add_header("Authorization", "Bearer " + self.token)
            if accept:
                req.add_header("Accept", accept)
            try:
                return urllib.request.urlopen(req, timeout=120)
            except urllib.error.HTTPError as exc:
                if exc.code == 401 and attempt == 0:
                    self.token = ""
                    continue
                raise
        raise RuntimeError("unreachable")


def _fetch_blob(reg: _Registry, digest: str, dest: Path, size: int | None = None) -> None:
    if dest.exists() and _sha256_file(dest) == digest:
        return
    tmp = dest.with_suffix(".part")
    for attempt in range(4):
        try:
            with reg.open(f"/v2/{reg.repo}/blobs/{digest}") as r, tmp.open("wb") as f:
                got, last = 0, 0.0
                for chunk in iter(lambda: r.read(1 << 20), b""):
                    f.write(chunk)
                    got += len(chunk)
                    if size and time.time() - last > 5:
                        last = time.time()
                        print(f"  {digest[7:19]} {got * 100 // size}%", flush=True)
            break
        except OSError as exc:
            print(f"  retry {digest[7:19]} ({exc})", flush=True)
            time.sleep(3 * (attempt + 1))
    else:
        raise SystemExit(f"a0_bundle: download failed for {digest}")
    if _sha256_file(tmp) != digest:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"a0_bundle: sha256 mismatch for {digest}")
    os.replace(tmp, dest)


def fetch(pin: dict, cache: Path) -> dict:
    cache.mkdir(parents=True, exist_ok=True)
    reg = _Registry(pin["image"])
    mpath = cache / ("manifest-" + pin["amd64_digest"][7:] + ".json")
    if not (mpath.exists() and _sha256_file(mpath) == pin["amd64_digest"]):
        with reg.open(f"/v2/{reg.repo}/manifests/{pin['amd64_digest']}", ACCEPT) as r:
            body = r.read()
        if "sha256:" + hashlib.sha256(body).hexdigest() != pin["amd64_digest"]:
            raise SystemExit("a0_bundle: manifest does not match amd64_digest")
        mpath.write_bytes(body)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    if manifest["config"]["digest"] != pin["config_digest"]:
        raise SystemExit("a0_bundle: manifest config is not the pinned config_digest")
    for layer in manifest["layers"]:
        if not layer["mediaType"].endswith("tar+gzip") and not layer["mediaType"].endswith("tar.gzip"):
            raise SystemExit(f"a0_bundle: layer type {layer['mediaType']} cannot be loaded by docker 20.10")
    blobs = [manifest["config"]] + manifest["layers"]
    total = sum(int(b["size"]) for b in blobs)
    print(f"a0_bundle: {len(manifest['layers'])} layers, {total / 1e9:.2f} GB", flush=True)
    for b in blobs:
        _fetch_blob(reg, b["digest"], cache / b["digest"][7:], int(b["size"]))
    return manifest


class _SplitWriter(io.RawIOBase):
    """File-like sink that rotates to a new part every PART_SIZE bytes."""

    def __init__(self, out: Path, stem: str, part_size: int | None = None):
        self.out, self.stem, self.part_size = out, stem, part_size or PART_SIZE
        self.parts: list[dict] = []
        self.f = None
        self.h = None
        self.n = 0
        self.total = 0

    def writable(self) -> bool:
        return True

    def _rotate(self) -> None:
        self._close_part()
        name = f"{self.stem}.part-{len(self.parts):03d}"
        self.f = (self.out / name).open("wb")
        self.h = hashlib.sha256()
        self.n = 0
        self.parts.append({"name": name})

    def _close_part(self) -> None:
        if self.f is not None:
            self.f.close()
            self.parts[-1].update(size=self.n, sha256="sha256:" + self.h.hexdigest())
            self.f = None

    def write(self, b) -> int:
        mv = memoryview(b)
        done = 0
        while done < len(mv):
            if self.f is None or self.n >= self.part_size:
                self._rotate()
            take = min(len(mv) - done, self.part_size - self.n)
            chunk = mv[done:done + take]
            self.f.write(chunk)
            self.h.update(chunk)
            self.n += take
            self.total += take
            done += take
        return done

    def close(self) -> None:
        self._close_part()
        super().close()


def pack(pin: dict, cache: Path, out: Path) -> dict:
    manifest = fetch(pin, cache)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("agent-zero.tar.part-*"):
        old.unlink()
    cfg_hex = pin["config_digest"][7:]
    layer_names = [l["digest"][7:] + ".tar.gz" for l in manifest["layers"]]
    archive_manifest = [{"Config": cfg_hex + ".json", "RepoTags": [local_tag(pin)], "Layers": layer_names}]
    sink = _SplitWriter(out, "agent-zero.tar")
    with tarfile.open(fileobj=sink, mode="w|", format=tarfile.USTAR_FORMAT) as tar:
        def add(name: str, src: Path | None = None, data: bytes | None = None) -> None:
            info = tarfile.TarInfo(name)
            info.mtime = 0
            info.mode = 0o644
            if data is not None:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            else:
                info.size = src.stat().st_size
                with src.open("rb") as f:
                    tar.addfile(info, f)
        add(cfg_hex + ".json", cache / cfg_hex)
        for layer, name in zip(manifest["layers"], layer_names):
            add(name, cache / layer["digest"][7:])
        # manifest.json last: docker load reads the whole archive first anyway.
        add("manifest.json", data=json.dumps(archive_manifest).encode())
        add("repositories", data=json.dumps({LOCAL_TAG: {pin["version"]: cfg_hex}}).encode())
    sink.close()
    doc = {
        "format": BUNDLE_FORMAT,
        "image": pin["image"],
        "version": pin["version"],
        "amd64_digest": pin["amd64_digest"],
        "config_digest": pin["config_digest"],
        "tag": local_tag(pin),
        "tar_size": sink.total,
        "parts": sink.parts,
    }
    (out / "bundle.json").write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"a0_bundle: {len(sink.parts)} parts, {sink.total / 1e9:.2f} GB -> {out}", flush=True)
    return doc


def verify(out: Path) -> int:
    doc = json.loads((out / "bundle.json").read_text(encoding="utf-8"))
    bad = 0
    for p in doc["parts"]:
        path = out / p["name"]
        if not path.is_file() or path.stat().st_size != p["size"] or _sha256_file(path) != p["sha256"]:
            print(f"a0_bundle: BAD {p['name']}", file=sys.stderr)
            bad += 1
        if p["size"] >= 4 * (1 << 30):
            print(f"a0_bundle: {p['name']} is 4 GiB or more (ISO 9660 limit)", file=sys.stderr)
            bad += 1
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if len(argv) >= 4 and argv[1] == "fetch":
        fetch(parse_pin(Path(argv[2])), Path(argv[3]))
        return 0
    if len(argv) >= 5 and argv[1] == "pack":
        pack(parse_pin(Path(argv[2])), Path(argv[3]), Path(argv[4]))
        return verify(Path(argv[4]))
    if len(argv) >= 3 and argv[1] == "verify":
        return verify(Path(argv[2]))
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
