"""App-mux large POST bodies must finish fast (no 180s StickDroid stall).

Reproduces StickDroid image-send hangs: ~250 KiB multipart over StickLink stalled
until the client mux timeout when:
  - http_chunk arrived before http_req (Noise reorder) and was dropped, or
  - eof was lost and the stick waited forever for msg.eof.

These tests drive AppMuxBridge directly (the stick mux). 250 KiB and 2 MiB
chunked POSTs must complete in under 5 s, including out-of-order chunks and
missing eof when body_len is satisfied.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "overlay" / "usr" / "local" / "lib"))

from sticklink.app_mux_bridge import CHUNK, AppMuxBridge  # noqa: E402
from sticklink.util import b64u  # noqa: E402


class _EchoHttp:
    """Stand-in for LocalA0Bridge — echoes body length, no network."""

    token = "test-token"
    origin = "https://127.0.0.1"

    def cookie_header(self) -> str:
        return ""

    def request(self, method, path, hdrs, body):
        raw = body or b""
        return {
            "status": 200,
            "headers": {"content-type": "application/octet-stream", "x-echo-len": str(len(raw))},
            "body_b64": b64u(raw[:64] + f"|len={len(raw)}".encode()),
        }


def _chunks_for(body: bytes, chunk: int = CHUNK):
    out = []
    seq = 0
    for i in range(0, len(body), chunk):
        piece = body[i : i + chunk]
        out.append(
            {
                "t": "http_chunk",
                "id": "r1",
                "role": "req",
                "seq": seq,
                "eof": i + chunk >= len(body),
                "body_b64": b64u(piece),
            }
        )
        seq += 1
    return out


async def _run_upload(body: bytes, *, reorder: bool = False, drop_eof: bool = False) -> list[dict]:
    sent: list[dict] = []
    bridge = AppMuxBridge(
        stick_https="https://127.0.0.1",
        bridge_http=_EchoHttp(),
        send_pt=lambda o: sent.append(dict(o)),
        log=lambda m: None,
    )
    rid = "r1"
    req = {
        "t": "http_req",
        "id": rid,
        "method": "POST",
        "path": "/agent-zero/api/message_async",
        "headers": {"content-type": "multipart/form-data; boundary=x"},
        "body_len": len(body),
    }
    chunks = _chunks_for(body)
    if drop_eof and chunks:
        chunks[-1] = dict(chunks[-1])
        chunks[-1]["eof"] = False
    if reorder and len(chunks) >= 2:
        # Deliver first data chunk before http_req (Noise reorder).
        await bridge.handle(chunks[0])
        await bridge.handle(req)
        for c in chunks[1:]:
            await bridge.handle(c)
    else:
        await bridge.handle(req)
        for c in chunks:
            await bridge.handle(c)
    # Allow _do_http thread + response send.
    for _ in range(50):
        if any(m.get("t") == "http_res" and m.get("id") == rid for m in sent):
            break
        await asyncio.sleep(0.02)
    return sent


@pytest.mark.parametrize("nbytes", [250_000, 2 * 1024 * 1024])
def test_large_body_under_5s(nbytes):
    body = bytes((i * 17) & 0xFF for i in range(nbytes))
    t0 = time.perf_counter()
    sent = asyncio.run(_run_upload(body))
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"{nbytes} B took {elapsed:.2f}s (limit 5s)"
    res = [m for m in sent if m.get("t") == "http_res" and m.get("id") == "r1"]
    assert res, f"no http_res for {nbytes} B; got {[m.get('t') for m in sent[:10]]}"
    assert int(res[0]["status"]) == 200


def test_250k_reordered_chunks_and_missing_eof_under_5s():
    """Chunks before http_req + no eof flag must still finish via body_len."""
    nbytes = 250_000
    body = bytes((i * 31) & 0xFF for i in range(nbytes))
    t0 = time.perf_counter()
    sent = asyncio.run(_run_upload(body, reorder=True, drop_eof=True))
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"reordered/missing-eof took {elapsed:.2f}s"
    res = [m for m in sent if m.get("t") == "http_res" and m.get("id") == "r1"]
    assert res and int(res[0]["status"]) == 200
    assert any(m.get("t") == "http_ack" for m in sent)


def test_chunk_constant_fits_sess_box():
    """Document wire budget: CHUNK payload → Noise frame < 64 KiB SESS_BOX_MAX."""
    # PT JSON ≈ 80 + b64(CHUNK); wire ≈ 8 + PT + 16; must stay under 65536.
    pt_est = 96 + ((CHUNK + 2) // 3) * 4
    wire_est = 8 + pt_est + 16
    assert wire_est < 65_536, f"CHUNK={CHUNK} wire~{wire_est} exceeds SESS_BOX_MAX"
