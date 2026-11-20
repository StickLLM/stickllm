#!/usr/bin/env python3
"""Build-time fetch and verify for allowlisted Agent Zero plugins.

Every third-party plugin is banned unless it is listed in
overlay/usr/local/share/stickllm/agent-zero-plugins.allow with a full commit
SHA and a tree hash. This runs only inside the ISO build. The stick never
fetches plugins at runtime.

Allowlist line format (whitespace separated, '#' starts a comment):
  name  repo_url  commit_sha40  license  tree_sha256

tree_sha256 is the sha256 of the text made of one line per file
"<file sha256>  <relative path>\n", paths sorted bytewise, .git excluded.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REPO_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause"}
# Names we own or that Agent Zero ships. A third-party plugin must not shadow them.
RESERVED = {"stickllm_apps"}


class AllowlistError(ValueError):
    pass


def parse_allowlist(text: str) -> list[dict]:
    entries: list[dict] = []
    seen: set[str] = set()
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 5:
            raise AllowlistError(f"line {lineno}: want 5 fields, got {len(parts)}")
        name, repo, commit, lic, tree = parts
        if not NAME_RE.match(name) or name.startswith("_") or name in RESERVED:
            raise AllowlistError(f"line {lineno}: bad plugin name {name!r}")
        if name in seen:
            raise AllowlistError(f"line {lineno}: duplicate plugin {name!r}")
        if not REPO_RE.match(repo):
            raise AllowlistError(f"line {lineno}: repo must be a https://github.com/<owner>/<repo> URL")
        if not SHA_RE.match(commit):
            raise AllowlistError(f"line {lineno}: commit must be a full 40-char SHA")
        if lic not in LICENSES:
            raise AllowlistError(f"line {lineno}: license {lic!r} is not on the OSI allow set")
        if not HASH_RE.match(tree):
            raise AllowlistError(f"line {lineno}: tree_sha256 must be 64 hex chars")
        seen.add(name)
        entries.append({"name": name, "repo": repo, "commit": commit, "license": lic, "tree_sha256": tree})
    return entries


def tree_hash(root: Path) -> str:
    root = Path(root)
    lines: list[bytes] = []
    paths = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fn in filenames:
            full = Path(dirpath) / fn
            if full.is_symlink():
                raise AllowlistError(f"symlink not allowed in plugin tree: {full.relative_to(root)}")
            paths.append(full.relative_to(root).as_posix())
    for rel in sorted(paths, key=lambda p: p.encode()):
        digest = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        lines.append(f"{digest}  {rel}\n".encode())
    return hashlib.sha256(b"".join(lines)).hexdigest()


def _git(args: list[str], cwd: Path) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    out = subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def fetch(entry: dict, dest: Path) -> None:
    """Shallow fetch exactly one commit. No submodules, no LFS, no hooks."""
    dest.mkdir(parents=True)
    _git(["init", "-q"], dest)
    _git(["-c", "protocol.version=2", "fetch", "-q", "--depth", "1", "--no-tags",
          entry["repo"], entry["commit"]], dest)
    _git(["-c", "core.hooksPath=/dev/null", "checkout", "-q", "--detach", "FETCH_HEAD"], dest)


def verify(entry: dict, src: Path) -> None:
    if (src / ".git").exists():
        head = _git(["rev-parse", "HEAD"], src)
        if head != entry["commit"]:
            raise AllowlistError(f"{entry['name']}: commit {head} != pinned {entry['commit']}")
    if not (src / "plugin.yaml").is_file():
        raise AllowlistError(f"{entry['name']}: plugin.yaml missing")
    got = tree_hash(src)
    if got != entry["tree_sha256"]:
        raise AllowlistError(f"{entry['name']}: tree sha256 {got} != pinned {entry['tree_sha256']}")


def install(src: Path, dest: Path) -> None:
    """Copy without .git. Files 0644, dirs 0755, owned by the build user (root)."""
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns(".git"), symlinks=False)
    for dirpath, dirnames, filenames in os.walk(dest):
        os.chmod(dirpath, 0o755)
        for fn in filenames:
            os.chmod(Path(dirpath) / fn, 0o644)


def bake(allow_path: Path, out_dir: Path, work: Path | None = None, fetcher=fetch) -> list[str]:
    entries = parse_allowlist(Path(allow_path).read_text(encoding="utf-8"))
    out_dir = Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    tmp = Path(work) if work else Path(tempfile.mkdtemp(prefix="a0-plugins-"))
    baked = []
    try:
        for entry in entries:
            src = tmp / entry["name"]
            if src.exists():
                shutil.rmtree(src)
            fetcher(entry, src)
            verify(entry, src)
            install(src, out_dir / entry["name"])
            # Re-hash the installed copy so a bad copy also fails the build.
            if tree_hash(out_dir / entry["name"]) != entry["tree_sha256"]:
                raise AllowlistError(f"{entry['name']}: installed copy does not match pin")
            baked.append(entry["name"])
    finally:
        if not work:
            shutil.rmtree(tmp, ignore_errors=True)
    manifest = "".join(
        f"{e['name']} {e['commit']} {e['tree_sha256']}\n" for e in entries
    )
    (out_dir / "MANIFEST").write_text(manifest, encoding="utf-8")
    os.chmod(out_dir / "MANIFEST", 0o644)
    os.chmod(out_dir, 0o755)
    return baked


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "tree-hash" and len(argv) == 3:
        print(tree_hash(Path(argv[2])))
        return 0
    if len(argv) >= 2 and argv[1] == "check" and len(argv) == 3:
        for e in parse_allowlist(Path(argv[2]).read_text(encoding="utf-8")):
            print(e["name"], e["commit"])
        return 0
    if len(argv) == 4 and argv[1] == "bake":
        try:
            names = bake(Path(argv[2]), Path(argv[3]))
        except (AllowlistError, subprocess.CalledProcessError) as exc:
            print(f"a0-plugins: FAIL {exc}", file=sys.stderr)
            return 1
        print("a0-plugins: baked " + (" ".join(names) or "(none)"))
        return 0
    print("usage: a0_plugins.py {tree-hash DIR|check ALLOW|bake ALLOW OUTDIR}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
