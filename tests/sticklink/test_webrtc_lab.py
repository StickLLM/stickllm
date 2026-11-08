"""Noise-over-DataChannel framing (loopback; no aiortc required)."""
from __future__ import annotations

import asyncio
import json
import os

import pytest

from conftest import VECTORS

from sticklink import crypto, noise, webrtc_lab

V = json.loads((VECTORS / "ikpsk2-v2.json").read_text()) if (VECTORS / "ikpsk2-v2.json").exists() else None
h = bytes.fromhex


@pytest.mark.skipif(V is None, reason="ikpsk2-v2.json missing")
def test_frame_roundtrip():
    raw = webrtc_lab.pack_frame(webrtc_lab.T_MSG1, b"abc")
    buf = bytearray(raw + webrtc_lab.pack_frame(webrtc_lab.T_ABORT, b"nope")[:2])  # incomplete tail
    frames = webrtc_lab.unpack_frames(buf)
    assert frames == [(webrtc_lab.T_MSG1, b"abc")]
    assert len(buf) == 2


@pytest.mark.skipif(V is None, reason="ikpsk2-v2.json missing")
def test_noise_over_loopback():
    os.environ["STICKLINK_TESTING"] = "1"
    os.environ["STICKLINK_LAB"] = "1"
    pro = h(V["prologue"])
    init = webrtc_lab.NoiseOverChannel(
        role="initiator",
        static_priv=h(V["kvm_static"]),
        remote_static=h(V["stick_static_pub"]),
        psk=h(V["psk"]),
        prologue=pro,
        send=None,
        e_priv=h(V["kvm_eph"]),
    )
    resp = webrtc_lab.NoiseOverChannel(
        role="responder",
        static_priv=h(V["stick_static"]),
        remote_static=h(V["kvm_static_pub"]),
        psk=h(V["psk"]),
        prologue=pro,
        send=None,
        e_priv=h(V["stick_eph"]),
    )
    got = []

    async def on_pt(pt: bytes):
        got.append(pt)

    resp.on_plaintext = on_pt

    async def run():
        lb = webrtc_lab.LoopbackChannel()
        t1, t2 = lb.wire(init, resp)
        await init.start_initiator()
        for _ in range(50):
            if init.session is not None and resp.session is not None:
                break
            await asyncio.sleep(0.01)
        assert init.session is not None and resp.session is not None
        assert init.session.handshake_hash == resp.session.handshake_hash == h(V["handshake_hash"])
        await init.send_plaintext(V["transport_plain"].encode())
        for _ in range(50):
            if got:
                break
            await asyncio.sleep(0.01)
        assert got == [V["transport_plain"].encode()]
        t1.cancel(); t2.cancel()

    asyncio.run(run())


def test_aiortc_probe_is_boolean():
    assert isinstance(webrtc_lab.aiortc_available(), bool)
