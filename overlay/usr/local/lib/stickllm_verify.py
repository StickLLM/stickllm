#!/usr/bin/env python3
"""StickLLM verified list: pinned hashes for apps, Agent Zero plugins and models.

The ISO ships ``/usr/local/share/stickllm/verified.json``, generated from the
*.pin files, agent-zero-plugins.allow and the model catalog by
``scripts/pins.py manifest``. Nothing here installs anything.

States
  verified    the item is on the list and its hash matches the pin.
  changed     the app's upstream tag now points at a different image than the
              pin. The new build is blocked until Nink updates the pin; the
              last verified version (the pinned digest) can still be installed.
  blocked     a hash was checked and does not match the pin.
  unverified  not on the list. Allowed only after the user confirms the
              warning on screen (UNVERIFIED_WARNING).
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

MANIFEST = Path(os.environ.get("STICKLLM_VERIFIED", "/usr/local/share/stickllm/verified.json"))
RUN_DIR = Path(os.environ.get("STICKLLM_RUN", "/run/stickllm"))
UPSTREAM_CACHE_NAME = "upstream-digests.json"
UPSTREAM_TTL = 6 * 3600
UNVERIFIED_WARNING = "Not verified by StickLLM: this hasn't been checked and may be unsafe"
# The Apps page and Agent Zero call ONLYOFFICE "docs"; the pin is onlyoffice.pin.
APP_KEYS = {"docs": "onlyoffice"}
LABELS = {
    "verified": "Verified",
    "changed": "Changed upstream",
    "blocked": "Blocked",
    "unverified": "Not verified",
}
_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_IMAGE_RE = re.compile(r"[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*")
_TAG_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,127}")
_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


def load_manifest(path: Path | None = None) -> dict:
    try:
        doc = json.loads((path or MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"apps": {}, "plugins": {}, "models": {}}
    if not isinstance(doc, dict):
        return {"apps": {}, "plugins": {}, "models": {}}
    for key in ("apps", "plugins", "models"):
        if not isinstance(doc.get(key), dict):
            doc[key] = {}
    return doc


def app_key(app_id: str) -> str:
    return APP_KEYS.get(app_id, app_id)


def app_pin(app_id: str, manifest: dict | None = None) -> dict | None:
    pin = (manifest or load_manifest())["apps"].get(app_key(app_id))
    if not isinstance(pin, dict):
        return None
    if not _DIGEST_RE.fullmatch(str(pin.get("manifest_digest") or "")):
        return None
    if not _DIGEST_RE.fullmatch(str(pin.get("amd64_digest") or "")):
        return None
    return pin


# ------------------------------------------------------------ upstream


def _cache_path() -> Path:
    return RUN_DIR / UPSTREAM_CACHE_NAME


def _read_cache() -> dict:
    try:
        doc = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_cache(doc: dict) -> None:
    try:
        RUN_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _cache_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, _cache_path())
    except OSError:
        pass


def cached_upstream(image: str, tag: str) -> str | None:
    row = _read_cache().get(f"{image}:{tag}")
    if isinstance(row, dict) and _DIGEST_RE.fullmatch(str(row.get("digest") or "")):
        return str(row["digest"])
    return None


def registry_digest(image: str, tag: str, timeout: float = 6.0) -> str | None:
    """Docker Hub digest the tag points at now (the OCI index), or None offline."""
    if not _IMAGE_RE.fullmatch(image) or not _TAG_RE.fullmatch(tag):
        return None
    scope = urllib.parse.quote(f"repository:{image}:pull", safe="")
    try:
        with urllib.request.urlopen(
            f"https://auth.docker.io/token?service=registry.docker.io&scope={scope}", timeout=timeout
        ) as resp:
            token = json.loads(resp.read().decode("utf-8") or "{}").get("token") or ""
        req = urllib.request.Request(
            f"https://registry-1.docker.io/v2/{image}/manifests/{tag}",
            method="HEAD",
            headers={"Authorization": "Bearer " + token, "Accept": _ACCEPT, "User-Agent": "StickLLM-verify"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            digest = (resp.headers.get("Docker-Content-Digest") or "").strip()
    except (OSError, ValueError, urllib.error.URLError):
        return None
    return digest if _DIGEST_RE.fullmatch(digest) else None


def upstream_digest(image: str, tag: str, *, fetch=None, max_age: float = UPSTREAM_TTL) -> str | None:
    key = f"{image}:{tag}"
    cache = _read_cache()
    row = cache.get(key)
    now = time.time()
    if isinstance(row, dict) and now - float(row.get("at") or 0) < max_age:
        digest = str(row.get("digest") or "")
        return digest if _DIGEST_RE.fullmatch(digest) else None
    digest = (fetch or registry_digest)(image, tag)
    if digest:
        cache[key] = {"digest": digest, "at": now}
        _write_cache(cache)
    return digest


# ------------------------------------------------------------ apps


def app_status(app_id: str, *, check_upstream: bool = False, fetch=None, manifest: dict | None = None) -> dict:
    """Verification for a catalog app. check_upstream asks Docker Hub (cached 6 h);
    without it only an earlier cached answer is used, so the Apps page makes no
    network calls."""
    pin = app_pin(app_id, manifest)
    if pin is None:
        return {
            "id": app_id,
            "status": "unverified",
            "label": LABELS["unverified"],
            "message": UNVERIFIED_WARNING + ".",
            "confirm_required": True,
        }
    image, version = str(pin.get("image") or ""), str(pin.get("version") or "")
    tag = str(pin.get("tag") or version)
    if check_upstream:
        upstream = upstream_digest(image, tag, fetch=fetch)
    else:
        upstream = cached_upstream(image, tag)
    out = {
        "id": app_id,
        "image": image,
        "version": version,
        "tag": tag,
        "manifest_digest": pin["manifest_digest"],
        "amd64_digest": pin["amd64_digest"],
        "upstream_digest": upstream or "",
        "upstream_checked": bool(upstream),
    }
    if upstream and upstream != pin["manifest_digest"]:
        out.update(
            status="changed",
            label=LABELS["changed"],
            confirm_required=True,
            offer="verified_version",
            message=(
                f"{image}:{tag} changed upstream since StickLLM checked it. "
                "The new build is blocked until StickLLM verifies it. "
                f"You can install the last verified version ({version}, {pin['manifest_digest'][:19]}…)."
            ),
        )
        return out
    out.update(status="verified", label=LABELS["verified"], confirm_required=False,
               message=f"Verified by StickLLM: {image}:{version} pinned to {pin['manifest_digest'][:19]}….")
    return out


# ------------------------------------------------------------ plugins


def plugin_status(name: str, *, commit: str = "", tree: str = "", manifest: dict | None = None) -> dict:
    pin = (manifest or load_manifest())["plugins"].get(name)
    if not isinstance(pin, dict):
        return {"name": name, "status": "unverified", "label": LABELS["unverified"],
                "message": UNVERIFIED_WARNING + ".", "confirm_required": True}
    out = {"name": name, "repo": pin.get("repo", ""), "commit": pin.get("commit", ""), "tree_sha256": pin.get("tree_sha256", "")}
    if (commit and commit != pin.get("commit")) or (tree and tree != pin.get("tree_sha256")):
        out.update(status="blocked", label=LABELS["blocked"], confirm_required=True,
                   message="Plugin files do not match the verified hash. It is not loaded until StickLLM verifies it.")
        return out
    out.update(status="verified", label=LABELS["verified"], confirm_required=False,
               message="Verified by StickLLM at commit " + str(pin.get("commit", ""))[:12] + ".")
    return out


# ------------------------------------------------------------ models


def model_key(repo: str, file: str) -> str:
    return f"{repo}/{file}"


def model_status(repo: str, file: str, sha256: str = "", *, manifest: dict | None = None) -> dict:
    want = (manifest or load_manifest())["models"].get(model_key(repo, file))
    sha = str(sha256 or "").lower()
    if not isinstance(want, str) or not _SHA_RE.fullmatch(want):
        return {"status": "unverified", "label": LABELS["unverified"], "message": UNVERIFIED_WARNING + ".",
                "confirm_required": True}
    if sha and sha != want:
        return {"status": "blocked", "label": LABELS["blocked"], "sha256": want, "confirm_required": True,
                "message": "The file's sha256 does not match the verified hash. Not loaded."}
    return {"status": "verified", "label": LABELS["verified"], "sha256": want, "confirm_required": False,
            "message": "Verified by StickLLM (Hugging Face LFS sha256 pinned)."}


def summary(manifest: dict | None = None) -> dict:
    """Everything on the verified list with its offline status (no network)."""
    doc = manifest or load_manifest()
    return {
        "ok": True,
        "warning": UNVERIFIED_WARNING,
        "generated": doc.get("generated", ""),
        "apps": [app_status(k, manifest=doc) for k in sorted(doc["apps"])],
        "plugins": [plugin_status(k, manifest=doc) for k in sorted(doc["plugins"])],
        "models": [dict(model_status(*k.rsplit("/", 1), manifest=doc), id=k) for k in sorted(doc["models"])],
    }


if __name__ == "__main__":  # pragma: no cover - manual check on a stick
    print(json.dumps(summary(), indent=1))
