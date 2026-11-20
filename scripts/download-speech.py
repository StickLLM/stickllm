#!/usr/bin/env python3
"""Download pinned speech assets for the image build. Not used on the stick.

Public URLs only. No Hugging Face token. Writes models/speech/ and SHA256SUMS.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "models" / "speech"

# name, url, sha256 or "", extra checks
ASSETS = [
    {
        "name": "ggml-tiny.en.bin",
        "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.en.bin",
        "sha256": "921e4cf8686fdd993dcd081a5da5b6c365bfde1162e72b08d75ac75289920b1f",
        "sha1": "c78c86eb1a8faa21b369bcd33207cc90d64ae9df",
    },
    {
        "name": "kitten_tts_mini_v0_8.onnx",
        "url": "https://huggingface.co/KittenML/kitten-tts-mini-0.8/resolve/main/kitten_tts_mini_v0_8.onnx",
        "sha256": "0f5bbae4fc4800c98dbc544a87ecfa79510de2fb8222db30d12e5bfe9177df91",
        "size": 78268016,
    },
    {
        "name": "voices.npz",
        "url": "https://huggingface.co/KittenML/kitten-tts-mini-0.8/resolve/main/voices.npz",
        "sha256": "40ad2638952b77b7b2f30127e2608e169fc69dd256b53bd8aaa3409a33193c42",
        "size": 3278902,
    },
    {
        "name": "config.json",
        "url": "https://huggingface.co/KittenML/kitten-tts-mini-0.8/resolve/main/config.json",
        "sha256": "6b160bc9b19e24ecb21e84bc14f8a7da21fdf47ec72d42450bc5cf514b61804a",
    },
    {
        "name": "whisper.cpp-v1.8.7.tar.gz",
        "url": "https://github.com/ggml-org/whisper.cpp/archive/refs/tags/v1.8.7.tar.gz",
        "sha256": "0b988ba5053cfa720f6d399f3f21885b01c4222178be435ca2272d6872717554",
    },
    {
        "name": "onnxruntime-1.20.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
        "url": "https://files.pythonhosted.org/packages/11/ac/4120dfb74c8e45cce1c664fc7f7ce010edd587ba67ac41489f7432eb9381/onnxruntime-1.20.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
        "sha256": "5eec64c0269dcdb8d9a9a53dc4d64f87b9e0c19801d9321246a53b7eb5a7d1bc",
    },
]


def digest(path: Path, algo: str) -> str:
    h = hashlib.new(algo)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".partial")
    req = urllib.request.Request(url, headers={"User-Agent": "stickllm-image-build"})
    print(f"Downloading {dest.name}", flush=True)
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as out:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
    tmp.replace(dest)


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    lines = []
    for asset in ASSETS:
        path = DEST / asset["name"]
        expect = asset.get("sha256") or ""
        if path.is_file() and expect and digest(path, "sha256") == expect:
            print(f"OK cached {path.name}", flush=True)
        elif path.is_file() and not expect and asset.get("sha1") and digest(path, "sha1") == asset["sha1"]:
            print(f"OK cached {path.name}", flush=True)
        else:
            if path.is_file() and not expect and path.stat().st_size > 0 and not asset.get("sha1"):
                print(f"OK cached {path.name} (hash recorded below)", flush=True)
            else:
                fetch(asset["url"], path)
        got = digest(path, "sha256")
        if expect and got != expect:
            print(f"ERROR sha256 mismatch {path.name}", file=sys.stderr)
            print(f"  expected {expect}", file=sys.stderr)
            print(f"  got      {got}", file=sys.stderr)
            return 1
        if asset.get("sha1") and digest(path, "sha1") != asset["sha1"]:
            print(f"ERROR sha1 mismatch {path.name}", file=sys.stderr)
            return 1
        if asset.get("size") and path.stat().st_size != asset["size"]:
            print(f"ERROR size mismatch {path.name}", file=sys.stderr)
            return 1
        lines.append(f"{got}  {path.name}")
        print(f"SHA256 {got}  {path.name}", flush=True)
    sums = DEST / "SHA256SUMS"
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {sums}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
