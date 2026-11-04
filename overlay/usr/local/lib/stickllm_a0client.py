#!/usr/bin/env python3
"""Small client for the local Agent Zero API (127.0.0.1:5099), 0.6.0 (A3).

A0 has no login on the stick, but its API is CSRF protected:
  GET /api/csrf_token (with an Origin header) -> {ok, token, runtime_id} + a
  Flask session cookie; POSTs then carry X-CSRF-Token and that cookie.

Used for Agent Zero's Whisper STT and Kokoro TTS. The chat app falls back to
the built-in whisper.cpp / KittenTTS whenever anything here fails.
Never logs audio, transcripts or tokens.
"""
from __future__ import annotations

import http.client
import json
import socket
import threading
import time

HOST = "127.0.0.1"
PORT = 5099
ORIGIN = f"http://{HOST}:{PORT}"


class A0Error(Exception):
    pass


class A0Client:
    def __init__(self, host: str = HOST, port: int = PORT):
        self.host = host
        self.port = port
        self._lock = threading.Lock()
        self._token = ""
        self._cookie = ""
        self._ready_cache: dict[str, tuple[float, bool]] = {}

    def port_open(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=0.3):
                return True
        except OSError:
            return False

    def _request(self, method: str, path: str, body: dict | None, timeout: float,
                 headers: dict | None = None) -> tuple[int, dict, list[str]]:
        conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        try:
            data = json.dumps(body).encode("utf-8") if body is not None else None
            h = {"Origin": ORIGIN, "Referer": ORIGIN + "/", "Accept": "application/json"}
            if data is not None:
                h["Content-Type"] = "application/json"
            h.update(headers or {})
            conn.request(method, path, body=data, headers=h)
            resp = conn.getresponse()
            raw = resp.read(64 * 1024 * 1024)
            cookies = resp.headers.get_all("Set-Cookie") or []
            try:
                doc = json.loads(raw.decode("utf-8")) if raw else {}
            except ValueError:
                doc = {"_text": raw[:200].decode("utf-8", "replace")}
            if not isinstance(doc, dict):
                doc = {"_value": doc}
            return resp.status, doc, cookies
        except (OSError, http.client.HTTPException) as e:
            raise A0Error(e.__class__.__name__) from e
        finally:
            conn.close()

    def _login(self) -> None:
        status, doc, cookies = self._request("GET", "/api/csrf_token", None, 5)
        if status != 200 or not doc.get("token"):
            raise A0Error(f"csrf {status}")
        jar = []
        for c in cookies:
            first = c.split(";", 1)[0].strip()
            if "=" in first:
                jar.append(first)
        self._token = str(doc["token"])
        self._cookie = "; ".join(jar)

    def post(self, path: str, body: dict, timeout: float = 120) -> dict:
        with self._lock:
            if not self._token:
                self._login()
            token, cookie = self._token, self._cookie
        for attempt in (0, 1):
            status, doc, _ = self._request(
                "POST", path, body, timeout,
                {"X-CSRF-Token": token, "Cookie": cookie},
            )
            if status == 403 and attempt == 0:
                # A0 restarted (new runtime id) or the session expired.
                with self._lock:
                    self._login()
                    token, cookie = self._token, self._cookie
                continue
            if status != 200:
                raise A0Error(f"http {status}")
            return doc
        raise A0Error("csrf refused")

    def plugin_ready(self, plugin: str, ttl: float = 15) -> bool:
        """enabled and model downloaded. Cached briefly; never downloads."""
        now = time.time()
        hit = self._ready_cache.get(plugin)
        if hit and now - hit[0] < ttl:
            return hit[1]
        ok = False
        if self.port_open():
            try:
                doc = self.post(f"/api/plugins/{plugin}/status", {}, timeout=5)
                model = doc.get("model") or {}
                ok = bool(doc.get("enabled")) and bool(model.get("ready"))
            except A0Error:
                ok = False
        self._ready_cache[plugin] = (now, ok)
        return ok

    def transcribe(self, audio_b64: str) -> str:
        doc = self.post("/api/plugins/_whisper_stt/transcribe", {"audio": audio_b64}, timeout=120)
        if not doc.get("success"):
            raise A0Error("transcribe failed")
        return str(doc.get("text") or "")

    def synthesize(self, text: str) -> str:
        doc = self.post("/api/plugins/_kokoro_tts/synthesize", {"text": text}, timeout=120)
        audio = doc.get("audio")
        if not doc.get("success") or not isinstance(audio, str) or not audio:
            raise A0Error("synthesize failed")
        if audio.startswith("data:"):
            audio = audio.split(",", 1)[-1]
        return audio


CLIENT = A0Client()
