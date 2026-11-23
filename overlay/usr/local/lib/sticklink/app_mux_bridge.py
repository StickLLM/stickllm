#!/usr/bin/env python3
"""StickLink app-mux v1 server side (Noise PT JSON).

Stick runtime copy of the lab reference bridge. Phone wire protocol unchanged
(APP-MUX-V1). Lab tree remains the frozen reference under lab-browser-e2e/.
"""
from __future__ import annotations

import asyncio
import gzip
import json
import re
import ssl
import time
from typing import Any, Callable, Awaitable
from urllib.parse import urlparse

import websockets

from sticklink.util import b64u, unb64u


def _strip_unsecured_banner(raw: bytes) -> bytes:
    """Drop A0's tunnel 'unsecured-connection' nag — StickLink Noise is the credential."""
    try:
        doc = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return raw
    banners = doc.get("banners")
    if not isinstance(banners, list):
        return raw
    doc["banners"] = [
        b
        for b in banners
        if not (isinstance(b, dict) and b.get("id") == "unsecured-connection")
    ]
    return json.dumps(doc).encode("utf-8")


_UNSECURED_HIDE = b"""<style data-sticklink-hide-unsecured="1">
[data-banner-id="unsecured-connection"],
.notification-item[data-id="unsecured-connection"],
.banner[data-id="unsecured-connection"]{display:none!important}
</style>"""


def _inject_lab_ux(raw: bytes, headers: dict) -> bytes:
    """Hide unsecured banner in top-level A0 HTML only (not x-component fragments)."""
    ct = (headers.get("content-type") or "").lower()
    if "text/html" not in ct:
        return raw
    head = raw[:400].lower()
    if b"<!doctype" not in head and b"<html" not in head:
        return raw
    if b"data-sticklink-hide-unsecured" in raw:
        return raw
    idx = raw.lower().rfind(b"</head>")
    if idx < 0:
        return raw
    return raw[:idx] + _UNSECURED_HIDE + raw[idx:]

# Decoded payload per http_chunk. Keep Noise PT + sess.frame b64 under
# worker SESS_BOX_MAX (64 KiB) / SESS_FRAME_MAX (96 KiB). 36 KiB payload is
# ~49 KiB PT JSON and ~65 KiB wire b64 — tight; 24 KiB leaves headroom.
CHUNK = 24 * 1024
MAX_BODY = 32 * 1024 * 1024  # A0 work-dir PDF/Doc downloads over StickLink
GZIP_MIN = 800
# Never gzip Content-Disposition: attachment — phone save-as needs identity body.
_ATTACHMENT_RE = re.compile(r"attachment", re.I)
# Incomplete chunked requests older than this get 408 (avoid 180s phone stalls).
REQ_BUF_TTL_SEC = 30.0

ALLOWED_PREFIXES = (
    "/agent-zero",
    "/socket.io",
    "/api/agent",
    "/api/csrf",
    "/api/pair/status",
    # open_app + app pages on the StickLink client (same StickLLM pairing).
    "/api/ui",
    "/apps",
)

# A0 often emits bare /public /plugins /js under embed; map like the old proxy.
_A0_BARE = (
    "/public/",
    "/plugins/",
    "/js/",
    "/components/",
    "/vendor/",
    "/ui/",
    "/extensions/",
    "/css/",
    "/api/",
    "/socket.io",
    "/index.css",
    "/index.js",
    "/sw.js",
    "/favicon",
)


def normalize_path(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    q = ""
    if "?" in path:
        path, q = path.split("?", 1)
        q = "?" + q
    if path.startswith("/agent-zero") or path.startswith("/socket.io") or path.startswith("/api/"):
        return path + q
    for pref in _A0_BARE:
        if path == pref.rstrip("/") or path.startswith(pref):
            return "/agent-zero" + path + q
    return path + q


def path_allowed(path: str) -> bool:
    p = normalize_path(path).split("?", 1)[0]
    if p.startswith("/agent-zero") or p.startswith("/socket.io"):
        return True
    return any(p == pref or p.startswith(pref + "/") for pref in ALLOWED_PREFIXES)


class AppMuxBridge:
    def __init__(
        self,
        *,
        stick_https: str,
        bridge_http,  # StickHttpBridge
        send_pt: Callable[[dict], None],
        log: Callable[[str], None],
        remint_token: Callable[[], str] | None = None,
    ):
        self.stick = stick_https.rstrip("/")
        self.http = bridge_http
        self.send_pt = send_pt
        self.log = log
        self.remint_token = remint_token
        self._req_buf: dict[str, dict[str, Any]] = {}
        # Chunks that arrived before http_req (Noise reorder) — keyed by rid.
        self._orphan_chunks: dict[str, list[dict]] = {}
        self._ws: dict[str, asyncio.Task] = {}
        self._ws_up: dict[str, Any] = {}
        self._http_sem = asyncio.Semaphore(8)

    async def handle(self, msg: dict) -> None:
        t = msg.get("t")
        if t == "http_req":
            await self._http_req(msg)
        elif t == "http_chunk" and msg.get("role") == "req":
            await self._http_chunk_req(msg)
        elif t == "ws_open":
            await self._ws_open(msg)
        elif t == "ws_data":
            await self._ws_data(msg)
        elif t == "ws_chunk":
            await self._ws_chunk(msg)
        elif t == "ws_close":
            await self._ws_close(msg)
        elif t == "ping":
            self.send_pt({"t": "pong"})

    def _purge_stale_req_bufs(self) -> None:
        """Fail chunked requests that never finished (lost eof / rate-dropped frame)."""
        now = time.monotonic()
        stale = [
            rid
            for rid, buf in self._req_buf.items()
            if now - float(buf.get("t0") or now) > REQ_BUF_TTL_SEC
        ]
        for rid in stale:
            self._req_buf.pop(rid, None)
            self._orphan_chunks.pop(rid, None)
            self.log(f"http_req {rid} chunk buffer timed out after {REQ_BUF_TTL_SEC:.0f}s")
            self.send_pt(
                {
                    "t": "http_res",
                    "id": rid,
                    "status": 408,
                    "headers": {"content-type": "text/plain"},
                    "body_b64": b64u(b"request body incomplete"),
                }
            )

    @staticmethod
    def _chunk_body_ready(buf: dict[str, Any]) -> bytes | None:
        """Reassemble by seq; ready when contiguous bytes cover body_len or eof."""
        by_seq: dict[int, bytes] = buf.get("by_seq") or {}
        if not by_seq:
            return None
        max_seq = max(by_seq)
        if any(i not in by_seq for i in range(max_seq + 1)):
            return None
        body = b"".join(by_seq[i] for i in range(max_seq + 1))
        expect = int(buf.get("expect") or 0)
        if expect > 0 and len(body) >= expect:
            return body[:expect] if len(body) > expect else body
        if buf.get("eof") and expect <= 0:
            return body
        if buf.get("eof") and expect > 0 and len(body) >= expect:
            return body[:expect]
        # eof seen and contiguous through eof seq, even if short (sender bug)
        if buf.get("eof") and buf.get("eof_seq") is not None and max_seq >= int(buf["eof_seq"]):
            return body
        return None

    async def _finish_chunked_req(self, rid: str, buf: dict[str, Any], body: bytes) -> None:
        self._req_buf.pop(rid, None)
        self._orphan_chunks.pop(rid, None)
        await self._do_http(rid, buf["method"], buf["path"], buf["headers"], body)

    async def _http_req(self, msg: dict) -> None:
        self._purge_stale_req_bufs()
        rid = str(msg.get("id") or "")
        method = str(msg.get("method") or "GET").upper()
        path = normalize_path(str(msg.get("path") or "/"))
        if not path_allowed(path):
            self.send_pt(
                {
                    "t": "http_res",
                    "id": rid,
                    "status": 403,
                    "headers": {"content-type": "text/plain"},
                    "body_b64": b64u(b"forbidden path"),
                }
            )
            return
        hdrs = msg.get("headers") if isinstance(msg.get("headers"), dict) else {}
        body_len = msg.get("body_len")
        if body_len is not None and not msg.get("body_b64"):
            buf = {
                "method": method,
                "path": path,
                "headers": hdrs,
                "by_seq": {},
                "expect": int(body_len),
                "eof": False,
                "eof_seq": None,
                "t0": time.monotonic(),
            }
            self._req_buf[rid] = buf
            # Drain chunks that arrived before this http_req (Noise reorder).
            pending = self._orphan_chunks.pop(rid, [])
            for early in pending:
                await self._http_chunk_req(early)
            if rid not in self._req_buf:
                return  # orphans already completed the request
            # Tell the phone the stick is ready for more chunks (optional; older
            # clients ignore unknown types).
            self.send_pt({"t": "http_ack", "id": rid, "expect": int(body_len)})
            held = self._req_buf.get(rid)
            if held is not None:
                ready = self._chunk_body_ready(held)
                if ready is not None:
                    await self._finish_chunked_req(rid, held, ready)
            return
        body = unb64u(msg["body_b64"]) if msg.get("body_b64") else None
        await self._do_http(rid, method, path, hdrs, body)

    async def _http_chunk_req(self, msg: dict) -> None:
        self._purge_stale_req_bufs()
        rid = str(msg.get("id") or "")
        buf = self._req_buf.get(rid)
        if not buf:
            # Noise can deliver chunk n+1 before http_req (nonce n). Stash it.
            orphan = self._orphan_chunks.setdefault(rid, [])
            if len(orphan) < 512:
                orphan.append(msg)
            return
        piece = unb64u(msg["body_b64"]) if msg.get("body_b64") else b""
        try:
            seq = int(msg.get("seq") if msg.get("seq") is not None else len(buf["by_seq"]))
        except (TypeError, ValueError):
            seq = len(buf["by_seq"])
        if seq < 0 or seq > 1_000_000:
            return
        buf["by_seq"][seq] = piece
        if msg.get("eof"):
            buf["eof"] = True
            buf["eof_seq"] = seq
        n = sum(len(c) for c in buf["by_seq"].values())
        if n > MAX_BODY:
            self._req_buf.pop(rid, None)
            self._orphan_chunks.pop(rid, None)
            self.send_pt(
                {
                    "t": "http_res",
                    "id": rid,
                    "status": 413,
                    "headers": {"content-type": "text/plain"},
                    "body_b64": b64u(b"body too large"),
                }
            )
            return
        # Finish on body_len even if eof frame was rate-dropped by the worker.
        ready = self._chunk_body_ready(buf)
        if ready is not None:
            await self._finish_chunked_req(rid, buf, ready)

    async def _do_http(self, rid: str, method: str, path: str, hdrs: dict, body: bytes | None) -> None:
        async with self._http_sem:
            t_up = time.perf_counter()
            try:
                res = await asyncio.to_thread(self.http.request, method, path, hdrs, body)
            except Exception as e:
                self.send_pt(
                    {
                        "t": "http_res",
                        "id": rid,
                        "status": 502,
                        "headers": {"content-type": "text/plain"},
                        "body_b64": b64u(str(e).encode()),
                    }
                )
                return
            # Pair Bearer expired / rotated — remint lab token once and retry.
            if res["status"] == 401 and self.remint_token is not None:
                self.log("http 401 — remint StickLink lab Bearer, retry once")
                try:
                    self.http.token = self.remint_token()
                    res = await asyncio.to_thread(self.http.request, method, path, hdrs, body)
                    res.setdefault("headers", {})["x-sticklink-token-refreshed"] = "1"
                except Exception as e:
                    self.log(f"token remint failed: {e}")
            # CSRF refresh once
            if res["status"] == 403 and method == "POST" and path.startswith("/agent-zero"):
                self.log("http 403 — remint CSRF on bridge, retry once")
                csrf_res = await asyncio.to_thread(
                    self.http.request,
                    "GET",
                    "/agent-zero/api/csrf_token",
                    {"Accept": "application/json"},
                    None,
                )
                if csrf_res["status"] == 200:
                    try:
                        csrf_doc = json.loads(unb64u(csrf_res["body_b64"]).decode())
                        new_tok = csrf_doc.get("token") or csrf_doc.get("csrf_token") or ""
                    except Exception:
                        new_tok = ""
                    if new_tok:
                        hdrs2 = dict(hdrs)
                        hdrs2["X-CSRF-Token"] = new_tok
                        res = await asyncio.to_thread(self.http.request, method, path, hdrs2, body)
                        res.setdefault("headers", {})["x-sticklink-csrf-refreshed"] = "1"
            raw = unb64u(res["body_b64"]) if res.get("body_b64") else b""
            headers = {k.lower(): v for k, v in (res.get("headers") or {}).items() if k.lower() != "set-cookie"}
            # Keep set-cookie in bridge jar only; optional surface for debug
            if "set-cookie" in (res.get("headers") or {}):
                headers["x-sticklink-set-cookie"] = "1"
            path_only = path.split("?", 1)[0]
            # StickLink auth is the credential — drop A0's tunnel "unsecured" nag.
            if method == "POST" and path_only.rstrip("/").endswith("/api/banners"):
                raw = _strip_unsecured_banner(raw)
            # Phone layout shim (was only on the old HTTP proxy).
            if method == "GET" and int(res["status"]) == 200:
                raw = _inject_lab_ux(raw, headers)
            upstream_ms = int((time.perf_counter() - t_up) * 1000)
            headers["x-sticklink-upstream-ms"] = str(upstream_ms)
            # content-encoding from stick is already decoded by urllib; note for perf.
            ce = (res.get("headers") or {}).get("content-encoding") or (res.get("headers") or {}).get(
                "Content-Encoding"
            )
            if ce:
                headers["x-sticklink-upstream-ce"] = str(ce)
            plain_len = len(raw)
            cd = str(headers.get("content-disposition") or "")
            is_attachment = bool(_ATTACHMENT_RE.search(cd)) or (
                "download_work_dir_file" in path_only
            )
            if is_attachment:
                # Preserve filename for phone WebView save; keep identity body.
                headers["x-sticklink-download"] = "1"
                if "content-disposition" not in headers and plain_len:
                    name = path_only.rsplit("/", 1)[-1] or "download"
                    headers["content-disposition"] = f'attachment; filename="{name}"'
            # Gzip on the Noise DC to cut base64 wire size (phone LTE).
            # Skip for attachments — corrupted/opaque gzip breaks phone downloads.
            if (not is_attachment) and plain_len >= GZIP_MIN:
                gz = gzip.compress(raw, compresslevel=6)
                if len(gz) + 64 < plain_len:
                    headers["x-sticklink-ce"] = "gzip"
                    headers["x-sticklink-plain-len"] = str(plain_len)
                    self.log(
                        f"http {method} {path} -> {res['status']} "
                        f"({plain_len} B → gz {len(gz)} B, up={upstream_ms}ms)"
                    )
                    await self._send_http_res(rid, int(res["status"]), headers, gz)
                    return
            headers["x-sticklink-compress"] = "none"
            self.log(f"http {method} {path} -> {res['status']} ({plain_len} B, up={upstream_ms}ms)")
            await self._send_http_res(rid, int(res["status"]), headers, raw)

    async def _send_http_res(self, rid: str, status: int, headers: dict, raw: bytes) -> None:
        if len(raw) <= CHUNK:
            self.send_pt(
                {
                    "t": "http_res",
                    "id": rid,
                    "status": status,
                    "headers": headers,
                    "body_b64": b64u(raw) if raw else None,
                }
            )
            return
        self.send_pt(
            {
                "t": "http_res",
                "id": rid,
                "status": status,
                "headers": headers,
                "body_len": len(raw),
            }
        )
        seq = 0
        for i in range(0, len(raw), CHUNK):
            piece = raw[i : i + CHUNK]
            eof = i + CHUNK >= len(raw)
            self.send_pt(
                {
                    "t": "http_chunk",
                    "id": rid,
                    "role": "res",
                    "seq": seq,
                    "eof": eof,
                    "body_b64": b64u(piece),
                }
            )
            seq += 1
            if seq % 8 == 0:
                await asyncio.sleep(0)  # yield for backpressure

    def _stick_ws_url(self, path: str) -> str:
        if path.startswith("ws"):
            return path
        if not path.startswith("/"):
            path = "/" + path
        base = self.stick.replace("https://", "wss://").replace("http://", "ws://")
        return base + path

    async def _ws_open(self, msg: dict) -> None:
        wid = str(msg.get("id") or "")
        path = str(msg.get("url") or "")
        if not path_allowed(path.split("?")[0] if "?" in path else path) and not path.startswith("/socket.io"):
            # socket.io often under /agent-zero/socket.io
            if not (path.startswith("/agent-zero") or path.startswith("/socket.io")):
                self.send_pt({"t": "ws_error", "id": wid, "message": "forbidden path"})
                return
        url = self._stick_ws_url(path)
        headers = {
            "Authorization": f"Bearer {self.http.token}",
            "X-StickLLM-Client": "ui",
            "X-StickLLM-Via": "sticklink",
            "Origin": self.http.origin,
            "User-Agent": "StickLink-lab-ws-mux",
        }
        cookie = self.http.cookie_header()
        if cookie:
            headers["Cookie"] = cookie
        try:
            ctx = ssl._create_unverified_context()
            # websockets 13.x (methodc-venv): extra_headers. Older forks used additional_headers.
            connect_kwargs = {
                "ssl": ctx,
                "max_size": 8 * 1024 * 1024,
                "open_timeout": 30,
            }
            import inspect

            params = inspect.signature(websockets.connect).parameters
            if "extra_headers" in params:
                connect_kwargs["extra_headers"] = headers
            elif "additional_headers" in params:
                connect_kwargs["additional_headers"] = headers
            up = await websockets.connect(url, **connect_kwargs)
        except Exception as e:
            self.log(f"ws_open fail {path}: {e}")
            self.send_pt({"t": "ws_error", "id": wid, "message": str(e)})
            return
        self._ws_up[wid] = up
        self.send_pt({"t": "ws_opened", "id": wid})
        self.log(f"ws_opened {wid} {path}")
        self._ws[wid] = asyncio.create_task(self._ws_reader(wid, up))

    async def _ws_reader(self, wid: str, up) -> None:
        try:
            async for message in up:
                if isinstance(message, bytes):
                    raw = message
                    binary = True
                else:
                    raw = message.encode("utf-8")
                    binary = False
                await self._send_ws_bytes(wid, raw, binary)
        except Exception as e:
            self.log(f"ws_reader {wid}: {e}")
            self.send_pt({"t": "ws_error", "id": wid, "message": str(e)})
        finally:
            self.send_pt({"t": "ws_close", "id": wid, "code": 1000, "reason": "upstream"})
            self._ws_up.pop(wid, None)
            self._ws.pop(wid, None)

    async def _send_ws_bytes(self, wid: str, raw: bytes, binary: bool) -> None:
        if len(raw) <= CHUNK:
            self.send_pt({"t": "ws_data", "id": wid, "binary": binary, "body_b64": b64u(raw)})
            return
        seq = 0
        for i in range(0, len(raw), CHUNK):
            piece = raw[i : i + CHUNK]
            self.send_pt(
                {
                    "t": "ws_chunk",
                    "id": wid,
                    "seq": seq,
                    "eof": i + CHUNK >= len(raw),
                    "binary": binary,
                    "body_b64": b64u(piece),
                }
            )
            seq += 1
            if seq % 8 == 0:
                await asyncio.sleep(0)

    async def _ws_data(self, msg: dict) -> None:
        wid = str(msg.get("id") or "")
        up = self._ws_up.get(wid)
        if not up:
            return
        raw = unb64u(msg["body_b64"]) if msg.get("body_b64") else b""
        try:
            if msg.get("binary"):
                await up.send(raw)
            else:
                await up.send(raw.decode("utf-8", "replace"))
        except Exception as e:
            self.send_pt({"t": "ws_error", "id": wid, "message": str(e)})

    async def _ws_chunk(self, msg: dict) -> None:
        # assemble per-id then forward — reuse simple buffer on self
        wid = str(msg.get("id") or "")
        key = "_wsc_" + wid
        buf = getattr(self, key, None)
        if buf is None:
            buf = {"chunks": [], "binary": bool(msg.get("binary"))}
            setattr(self, key, buf)
        piece = unb64u(msg["body_b64"]) if msg.get("body_b64") else b""
        buf["chunks"].append(piece)
        if msg.get("eof"):
            raw = b"".join(buf["chunks"])
            delattr(self, key)
            await self._ws_data({"id": wid, "binary": buf["binary"], "body_b64": b64u(raw)})

    async def _ws_close(self, msg: dict) -> None:
        wid = str(msg.get("id") or "")
        up = self._ws_up.pop(wid, None)
        task = self._ws.pop(wid, None)
        if task:
            task.cancel()
        if up:
            try:
                await up.close(code=int(msg.get("code") or 1000), reason=str(msg.get("reason") or ""))
            except Exception:
                pass
        self.send_pt({"t": "ws_close", "id": wid, "code": msg.get("code") or 1000, "reason": msg.get("reason") or ""})
