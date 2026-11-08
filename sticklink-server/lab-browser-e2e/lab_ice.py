#!/usr/bin/env python3
"""ICE servers for Method C lab WebRTC.

openrelay.metered.ca currently sinks to 192.0.2.1 — unusable. Fetch short-lived
credentials from the public elixir-webrtc Rel deployment (UDP TURN) and keep
Google + StickLink STUN as fallbacks.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

_CACHE: tuple[float, list[dict]] | None = None
_TTL_S = 30 * 60


def fetch_ice_servers(force: bool = False) -> list[dict]:
    global _CACHE
    now = time.time()
    if not force and _CACHE and now - _CACHE[0] < _TTL_S:
        return _CACHE[1]

    servers: list[dict] = [
        {"urls": ["stun:stun.l.google.com:19302"]},
        {"urls": ["stun:stun.cloudflare.com:3478"]},
        {"urls": ["stun:relay-tor1.stickllm.com:3478"]},
    ]
    try:
        req = urllib.request.Request(
            "https://turn.elixir-webrtc.org/?service=turn&username=sticklink-lab",
            method="POST",
            headers={"Accept": "application/json", "User-Agent": "StickLink-lab-ice"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            doc = json.loads(r.read().decode("utf-8"))
        uris = doc.get("uris") or []
        user = doc.get("username") or ""
        pw = doc.get("password") or ""
        if uris and user and pw:
            # Prefer UDP; also advertise TCP twin if URI is udp-only.
            urls = list(uris)
            for u in list(uris):
                if "transport=udp" in u:
                    urls.append(u.replace("transport=udp", "transport=tcp"))
            servers.append({"urls": urls, "username": user, "credential": pw})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        # Keep STUN-only; same-LAN host candidates still work for lab E2E.
        servers.append({"_ice_warn": f"elixir TURN fetch failed: {e}"})  # type: ignore[dict-item]

    # Strip internal warn key from RTCConfiguration consumers
    clean = [s for s in servers if "urls" in s]
    _CACHE = (now, clean)
    return clean


def aiortc_ice():
    """Build aiortc RTCConfiguration from fetch_ice_servers()."""
    from aiortc import RTCConfiguration, RTCIceServer

    ice = []
    for s in fetch_ice_servers():
        urls = s.get("urls") or []
        if not urls:
            continue
        kw = {"urls": urls}
        if s.get("username"):
            kw["username"] = s["username"]
            kw["credential"] = s.get("credential") or ""
        ice.append(RTCIceServer(**kw))
    return RTCConfiguration(iceServers=ice)
