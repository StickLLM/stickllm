#!/usr/bin/env python3
"""0.6.2 (A1): put Agent Zero's memory model (MiniLM) on the ISO.

Agent Zero loads sentence-transformers/all-MiniLM-L6-v2 at start. On the stick
that download waited on Hugging Face (no egress yet) and hung the start. The
build fetches the pinned revision once (cached in <cache>), checks the
weights' sha256, and writes:

  <out>/minilm.json            {"repo", "revision", "files": {name: sha256}}
  <out>/files/<name>           the snapshot files

stickllm-agent seeds these into the container's HF cache and starts A0 with
HF_HUB_OFFLINE=1.

usage: minilm_bundle.py pack <cache-dir> <out-dir>
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

REPO = "sentence-transformers/all-MiniLM-L6-v2"
REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
FILES = (
    "config.json",
    "config_sentence_transformers.json",
    "modules.json",
    "sentence_bert_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.txt",
    "model.safetensors",
    "1_Pooling/config.json",
)
PINNED = {
    "model.safetensors": ("53aa51172d142c89d9012cce15ae4d6cc0ca6895895114379cacb4fab128d9db", 90868376),
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(name: str, dest: Path) -> None:
    url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "stickllm-build"})
            with urllib.request.urlopen(req, timeout=60) as r, tmp.open("wb") as out:
                shutil.copyfileobj(r, out, 1 << 20)
            tmp.replace(dest)
            return
        except OSError as e:
            last = e
            time.sleep(2 + attempt * 3)
    raise SystemExit(f"minilm: download failed for {name}: {last}")


def good(name: str, path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    pin = PINNED.get(name)
    if pin is None:
        return True
    return path.stat().st_size == pin[1] and sha256(path) == pin[0]


def pack(cache: Path, out: Path) -> dict:
    cache = cache / REVISION
    sums: dict[str, str] = {}
    for name in FILES:
        src = cache / name
        if not good(name, src):
            print(f"[minilm] fetching {name}", flush=True)
            fetch(name, src)
            if not good(name, src):
                raise SystemExit(f"minilm: {name} failed its sha256/size check")
        sums[name] = sha256(src)
    files = out / "files"
    if files.exists():
        shutil.rmtree(files)
    for name in FILES:
        dst = files / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cache / name, dst)
    doc = {"repo": REPO, "revision": REVISION, "files": sums}
    (out / "minilm.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return doc


def main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] != "pack":
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    doc = pack(Path(argv[2]), Path(argv[3]))
    print(f"[minilm] {doc['repo']}@{doc['revision'][:12]} bundled ({len(doc['files'])} files)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
