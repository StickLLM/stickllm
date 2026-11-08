"""Async client for the sticklink signalling WebSocket (server/API.md §1-4, §7)."""
from __future__ import annotations

import asyncio
import itertools
import json
from urllib.parse import urlencode

import websockets

SUBPROTOCOL = "sticklink.1"
MAX_FRAME = 4096


class SigError(Exception):
    def __init__(self, code: str, retry=None):
        super().__init__(code)
        self.code, self.retry = code, retry


class SigClient:
    def __init__(self, base_url: str, log=print):
        self.base_url, self.log = base_url, log
        self.ws = None
        self.nonce = None
        self.events: asyncio.Queue = asyncio.Queue()
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._reader = self._pinger = None
        self.closed = asyncio.Event()
        self.close_code = None

    async def connect(self, query: dict, timeout: float = 10.0) -> dict:
        url = self.base_url + ("&" if "?" in self.base_url else "?") + urlencode(query)
        self.ws = await asyncio.wait_for(
            websockets.connect(url, subprotocols=[SUBPROTOCOL], max_size=MAX_FRAME * 2, ping_interval=None,
                               open_timeout=timeout), timeout)
        if self.ws.subprotocol != SUBPROTOCOL:
            raise SigError("subprotocol")
        welcome = json.loads(await asyncio.wait_for(self.ws.recv(), timeout))
        if welcome.get("t") != "welcome":
            raise SigError("no welcome")
        from .util import unb64u
        self.nonce = unb64u(welcome["n"], 32)
        self._reader = asyncio.create_task(self._read())
        self._pinger = asyncio.create_task(self._ping())
        return welcome

    async def _read(self):
        try:
            async for raw in self.ws:
                if not isinstance(raw, str) or len(raw) > MAX_FRAME:
                    continue
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                if m.get("t") == "pong":
                    continue
                mid = m.get("id")
                fut = self._pending.pop(mid, None) if isinstance(mid, int) else None
                if fut and not fut.done():
                    fut.set_result(m)
                else:
                    self.events.put_nowait(m)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.close_code = getattr(self.ws, "close_code", None)
            for f in self._pending.values():
                if not f.done():
                    f.set_exception(SigError("closed"))
            self.closed.set()
            self.events.put_nowait({"t": "_closed", "code": self.close_code})

    async def _ping(self):
        try:
            while True:
                await asyncio.sleep(25)
                await self.ws.send('{"t":"ping"}')
        except Exception:
            pass

    async def send(self, msg: dict):
        raw = json.dumps(msg, separators=(",", ":"))
        if len(raw) > MAX_FRAME:
            raise SigError("size")
        await self.ws.send(raw)

    async def request(self, msg: dict, timeout: float = 10.0) -> dict:
        mid = next(self._ids)
        msg = {"t": msg["t"], "id": mid, **{k: v for k, v in msg.items() if k != "t"}}
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self.send(msg)
        rep = await asyncio.wait_for(fut, timeout)
        if rep.get("t") == "err":
            raise SigError(rep.get("code", "?"), rep.get("retry"))
        return rep

    async def close(self):
        for t in (self._pinger, self._reader):
            if t:
                t.cancel()
        if self.ws:
            await self.ws.close()
