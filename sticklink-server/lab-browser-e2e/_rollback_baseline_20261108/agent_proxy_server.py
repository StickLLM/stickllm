#!/usr/bin/env python3
"""Local reverse proxy: Cloudflare tunnel → stick /agent-zero with lab pair token.

Also serves the join page. After Method C pair.joined, phone can use Agent Zero
without waiting for WebRTC/TURN (cellular often fails ICE).
"""
from __future__ import annotations

import json
import select
import socket
import ssl
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
STICK_HOST = "192.168.72.50"
STICK = f"https://{STICK_HOST}"
CTX = ssl._create_unverified_context()


def log(msg: str):
    print(f"{time.strftime('%H:%M:%S')} proxy: {msg}", flush=True)


def read_session() -> dict | None:
    p = STATE / "agent-session.json"
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not doc.get("token"):
        return None
    if doc.get("exp") and time.time() > float(doc["exp"]):
        return None
    return doc


def stick_fetch(method: str, path: str, headers: dict, body: bytes | None, token: str):
    url = STICK.rstrip("/") + path
    hdrs = {
        "Authorization": f"Bearer {token}",
        "X-StickLLM-Client": "ui",
        "Accept": headers.get("Accept") or headers.get("accept") or "*/*",
        "User-Agent": headers.get("User-Agent") or "StickLink-lab-proxy",
    }
    # Forward browser Cookie (A0 CSRF session) + CSRF headers.
    for k, v in headers.items():
        lk = k.lower()
        if lk in ("host", "connection", "content-length", "authorization"):
            continue
        if lk.startswith("sec-"):
            continue
        hdrs[k] = v
    req = urllib.request.Request(url, data=body, method=method, headers=hdrs)
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=120) as r:
            return r.status, _response_headers(r), r.read()
    except urllib.error.HTTPError as e:
        return e.code, _response_headers(e), e.read()


def _response_headers(r) -> list[tuple[str, str]]:
    """Preserve multi Set-Cookie (dict would collapse them)."""
    out: list[tuple[str, str]] = []
    get_all = getattr(r.headers, "get_all", None)
    if callable(get_all):
        for k in r.headers.keys():
            if k.lower() == "set-cookie":
                for v in get_all(k) or []:
                    out.append((k, v))
            else:
                out.append((k, r.headers.get(k)))
        # dedupe non-cookie keys (getheaders iterates duplicates)
        seen = set()
        uniq: list[tuple[str, str]] = []
        for k, v in out:
            if k.lower() == "set-cookie":
                uniq.append((k, v))
                continue
            lk = k.lower()
            if lk in seen:
                continue
            seen.add(lk)
            uniq.append((k, v))
        return uniq
    return list(r.headers.items())


# A0 often emits path-absolute URLs (/public/…, /plugins/…) even when the SPA
# is served under /agent-zero/. On the stick, gateway embed shim + HTML rewrite
# cover most of that; dynamic <img src> still hits bare roots. Map those to
# /agent-zero/… when talking to the stick.
_A0_BARE_PREFIXES = (
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


def _stick_path(path: str) -> str:
    """Map tunnel path → stick path (always under /agent-zero when needed)."""
    if path.startswith("/agent-zero"):
        return path
    if path.startswith("/api/agent") or path.startswith("/api/csrf"):
        return path
    for pref in _A0_BARE_PREFIXES:
        if path == pref.rstrip("/") or path.startswith(pref):
            return "/agent-zero" + path
    return path


def _proxy_paths(path: str) -> bool:
    if path.startswith("/agent-zero") or path.startswith("/api/agent") or path.startswith("/socket.io") or path.startswith("/api/csrf"):
        return True
    for pref in _A0_BARE_PREFIXES:
        if path == pref.rstrip("/") or path.startswith(pref):
            return True
    return False


def _strip_unsecured_banner(body: bytes) -> bytes:
    try:
        doc = json.loads(body.decode("utf-8", "replace"))
    except Exception:
        return body
    banners = doc.get("banners")
    if not isinstance(banners, list):
        return body
    doc["banners"] = [b for b in banners if not (isinstance(b, dict) and b.get("id") == "unsecured-connection")]
    return json.dumps(doc).encode("utf-8")


# Phone/tunnel UX: composer + mobile layout. Inject ONLY into the top-level SPA
# document — never into A0 x-component HTML fragments (that appends <style>/<script>
# into every component and breaks phone layout: overlapping rails, 0x0 chat-history).
_LAB_UX_SHIM = b"""<style data-stickllm-lab-ux="1">
#chat-input-container{flex:1 1 auto!important;min-width:0!important}
#chat-buttons-wrapper{flex:0 0 auto!important;flex-shrink:0!important;margin-left:auto}
#send-button{flex-shrink:0!important;z-index:6;position:relative}
.input-row{max-width:100%!important;box-sizing:border-box;overflow:visible!important}
#input-section{padding-bottom:calc(var(--sl-kb,0px) + env(safe-area-inset-bottom,0px))!important}
#send-button.stop .material-symbols-outlined,
#send-button.send-queue .material-symbols-outlined{font-size:0!important;width:0;overflow:hidden}
#send-button.stop::before{content:"STOP";font:700 11px/1 system-ui,sans-serif;letter-spacing:.04em}
#send-button.send-queue::before{content:"SEND";font:700 11px/1 system-ui,sans-serif;letter-spacing:.04em}
/* StickLink phone: hide right-canvas rail; keep chat full-bleed under mobile sidebar. */
@media (max-width:768px){
  html,body{overflow-x:hidden!important;max-width:100vw!important}
  #right-panel,.welcome-host,#chat-area-wrapper{max-width:100vw!important;box-sizing:border-box!important;min-width:0!important}
  body.right-canvas-mobile-mode .right-canvas-rail,
  body.right-canvas-mobile-mode .right-canvas-handle,
  body.right-canvas-overlay-mode .right-canvas-rail,
  body.right-canvas-mobile-mode [class*="right-canvas-rail"],
  .right-canvas-rail{display:none!important;visibility:hidden!important;pointer-events:none!important}
  #chat-input-container,.input-row,#input-section{max-width:calc(100vw - 16px)!important}
  #chat-history{min-width:0!important;flex:1 1 auto!important}
  .chat-container{max-width:100%!important;left:auto!important;transform:none!important}
  /* A0 leaves #left-panel fixed+open after chat select; force drawer closed unless .panel (no .hidden). */
  #left-panel.panel.hidden{left:0!important;transform:translateX(-105%)!important;pointer-events:none!important}
}
</style>
<script data-stickllm-lab-ux="1">(function(){
if(window.__stickllmLabUx)return; window.__stickllmLabUx=1;
/* Match A0 sidebar-store isMobile() (<=768), not a wider heuristic. */
function isPhone(){ return Math.max(document.documentElement.clientWidth||0, window.innerWidth||0) <= 768; }
function sendNow(){
  try{
    var s=window.Alpine&&Alpine.store&&Alpine.store("chatInput");
    if(s&&typeof s.activateSendButton==="function"){s.activateSendButton();return true;}
    if(s&&typeof s.sendMessage==="function"){s.sendMessage();return true;}
    var b=document.getElementById("send-button"); if(b){b.click();return true;}
  }catch(e){}
  return false;
}
document.addEventListener("keydown",function(e){
  if(e.key!=="Enter"||e.shiftKey||e.isComposing||e.keyCode===229)return;
  var t=e.target; if(!t||!t.closest)return;
  if(!t.closest("#chat-input"))return;
  e.preventDefault(); e.stopPropagation();
  sendNow();
},true);
function kb(){
  var vv=window.visualViewport; if(!vv)return;
  var gap=Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
  document.documentElement.style.setProperty("--sl-kb", gap+"px");
}
function closeSidebar(){
  try{
    if(!isPhone()) return;
    var s=window.Alpine&&Alpine.store&&Alpine.store("sidebar");
    if(s){
      try{ if(typeof s.close==="function") s.close(); }catch(e){}
      s.isOpen=false;
    }
    var left=document.getElementById("left-panel");
    if(left){ left.classList.add("hidden"); }
  }catch(e){}
}
function fixPhoneCanvas(){
  try{
    if(!isPhone()) return;
    document.body.classList.remove("right-canvas-open");
    var stores=["rightCanvas","right_canvas","canvas"];
    for(var i=0;i<stores.length;i++){
      try{
        var s=window.Alpine&&Alpine.store&&Alpine.store(stores[i]);
        if(!s) continue;
        if(s.isOpen && typeof s.close==="function") s.close();
        else if(s.isOpen) s.isOpen=false;
      }catch(e){}
    }
    document.querySelectorAll(".right-canvas-rail,[class*='right-canvas-rail']").forEach(function(el){
      el.style.display="none";
    });
  }catch(e){}
}
var __slCloseUntil=0;
function requestCloseSidebar(ms){
  __slCloseUntil=Date.now()+(ms||2500);
}
function pumpClose(){
  try{
    if(!isPhone()) return;
    if(Date.now()>__slCloseUntil) return;
    var right=document.getElementById("right-panel");
    if(right&&right.classList.contains("chat-active")) closeSidebar();
  }catch(e){}
}
function fixPhoneLayout(){
  fixPhoneCanvas();
  pumpClose();
}
/* Selecting a chat leaves Alpine sidebar.isOpen=true on touch widths - close drawer. */
document.addEventListener("click",function(e){
  if(!isPhone()||!e.target||!e.target.closest) return;
  if(!e.target.closest("#left-panel")) return;
  // Chat select is async; keep trying to close for a couple seconds.
  requestCloseSidebar(3000);
  [40,120,300,700,1200,2000,2800].forEach(function(ms){ setTimeout(pumpClose, ms); });
},true);
if(window.visualViewport){
  visualViewport.addEventListener("resize",kb);
  visualViewport.addEventListener("scroll",kb);
  kb();
}
function watchRightPanel(){
  try{
    var right=document.getElementById("right-panel");
    if(!right||right.__slWatched||!window.MutationObserver) return;
    right.__slWatched=1;
    var had=right.classList.contains("chat-active");
    new MutationObserver(function(){
      var now=right.classList.contains("chat-active");
      if(now&&!had){ requestCloseSidebar(2000); pumpClose(); }
      had=now;
    }).observe(right,{attributes:true,attributeFilter:["class"]});
  }catch(e){}
}
function boot(){
  fixPhoneCanvas();
  watchRightPanel();
  setTimeout(watchRightPanel, 500);
  setTimeout(watchRightPanel, 2000);
  setInterval(function(){ watchRightPanel(); pumpClose(); }, 500);
}
if(document.readyState==="loading") document.addEventListener("DOMContentLoaded", boot);
else boot();
document.addEventListener("alpine:initialized", function(){ watchRightPanel(); fixPhoneCanvas(); });
})();</script>"""


def _inject_lab_ux(body: bytes, headers) -> bytes:
    ctype = ""
    items = headers.items() if isinstance(headers, dict) else headers
    for k, v in items:
        if k.lower() == "content-type":
            ctype = (v or "").split(";")[0].strip().lower()
            break
    if ctype not in ("text/html", "application/xhtml+xml"):
        return body
    if b"data-stickllm-lab-ux" in body:
        return body
    # Top-level SPA only. A0 x-components are mini documents that start with
    # <html> (no doctype) — injecting into those duplicates CSS/JS and breaks
    # phone layout (sidebar overlap, 0x0 regions, corrupt chat chrome).
    low = body.lstrip().lower()
    if not low.startswith(b"<!doctype"):
        return body
    idx = body.lower().find(b"</head>")
    if idx >= 0:
        return body[:idx] + _LAB_UX_SHIM + body[idx:]
    idx = body.lower().find(b"</body>")
    if idx >= 0:
        return body[:idx] + _LAB_UX_SHIM + body[idx:]
    return body


def _rewrite_set_cookie(raw: str) -> str:
    parts = []
    for p in raw.split(";"):
        p = p.strip()
        if not p:
            continue
        if p.lower().startswith("domain="):
            continue
        parts.append(p)
    # Tunnel is always HTTPS (trycloudflare). Safari rejects non-Secure
    # cookies on HTTPS pages → CSRF 403 → skeleton UI forever.
    if not any(p.lower() == "secure" for p in parts):
        parts.append("Secure")
    if not any(p.lower().startswith("samesite=") for p in parts):
        parts.append("SameSite=None")
    else:
        # Lax can drop cookies on some mobile redirects; None+Secure is safer
        # for the Cloudflare tunnel origin.
        parts = [
            ("SameSite=None" if p.lower().startswith("samesite=") else p)
            for p in parts
        ]
    return "; ".join(parts)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, headers, body: bytes):
        self.send_response(code)
        skip = {"transfer-encoding", "connection", "content-encoding", "content-length"}
        items = headers.items() if isinstance(headers, dict) else headers
        for k, v in items:
            if k.lower() in skip:
                continue
            # Drop stick CSP that breaks embed on tunnel origin — loosen for lab
            if k.lower() == "content-security-policy":
                continue
            if k.lower() == "set-cookie":
                # Keep A0 CSRF session cookie; strip Domain so it binds to tunnel host
                v = _rewrite_set_cookie(str(v))
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,PATCH,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        if (self.headers.get("Upgrade") or "").lower() == "websocket":
            self._handle_websocket()
            return
        self._handle()

    def do_HEAD(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def _handle_websocket(self):
        """Raw TCP tunnel for Socket.IO / Agent Zero websockets."""
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = ("?" + parsed.query) if parsed.query else ""
        if not _proxy_paths(path):
            self._send(404, {"Content-Type": "text/plain"}, b"ws path not proxied")
            return
        sess = read_session()
        if not sess:
            self._send(401, {"Content-Type": "text/plain"}, b"pair_required")
            return
        full = _stick_path(path) + qs

        raw = socket.create_connection((STICK_HOST, 443), timeout=30)
        ups = CTX.wrap_socket(raw, server_hostname=STICK_HOST)
        try:
            lines = [
                f"GET {full} HTTP/1.1",
                f"Host: {STICK_HOST}",
                f"Authorization: Bearer {sess['token']}",
                "X-StickLLM-Client: ui",
                "Connection: Upgrade",
                "Upgrade: websocket",
            ]
            for k in (
                "Sec-WebSocket-Key",
                "Sec-WebSocket-Version",
                "Sec-WebSocket-Extensions",
                "Sec-WebSocket-Protocol",
                "Origin",
                "Cookie",
            ):
                v = self.headers.get(k)
                if v:
                    lines.append(f"{k}: {v}")
            ups.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())

            # Read upstream status + headers
            buf = b""
            while b"\r\n\r\n" not in buf:
                chunk = ups.recv(4096)
                if not chunk:
                    raise RuntimeError("upstream closed during WS handshake")
                buf += chunk
            head, rest = buf.split(b"\r\n\r\n", 1)
            status_line = head.split(b"\r\n", 1)[0].decode("latin1", "replace")
            if " 101 " not in status_line and not status_line.endswith(" 101"):
                log(f"WS upgrade failed: {status_line}")
                self._send(502, {"Content-Type": "text/plain"}, head[:500])
                return

            # Relay 101 to client (rewrite Set-Cookie Domain if present)
            out_lines = []
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"set-cookie:"):
                    try:
                        raw = line.decode("latin1").split(":", 1)[1].strip()
                        line = ("Set-Cookie: " + _rewrite_set_cookie(raw)).encode("latin1")
                    except Exception:
                        pass
                out_lines.append(line)
            self.wfile.write(b"\r\n".join(out_lines) + b"\r\n\r\n")
            self.wfile.flush()
            if rest:
                self.wfile.write(rest)
                self.wfile.flush()
            log(f"WS {full} upgraded")

            # Blocking bidirectional copy. Non-blocking + select on Windows SSL
            # surfaces SSLWantRead as fatal and flaps Socket.IO every ~1s, so the
            # phone UI stops receiving agent replies even when message_async works.
            client = self.connection
            client.setblocking(True)
            ups.setblocking(True)
            client.settimeout(300)
            ups.settimeout(300)

            def _pipe(src, dst, label: str):
                try:
                    while True:
                        try:
                            data = src.recv(65536)
                        except ssl.SSLWantReadError:
                            continue
                        except ssl.SSLWantWriteError:
                            continue
                        except (TimeoutError, socket.timeout):
                            continue
                        if not data:
                            break
                        try:
                            dst.sendall(data)
                        except ssl.SSLWantWriteError:
                            # rare; retry once
                            dst.sendall(data)
                except Exception as e:
                    log(f"WS {label} close: {e}")
                finally:
                    try:
                        dst.shutdown(socket.SHUT_WR)
                    except Exception:
                        pass

            t = threading.Thread(target=_pipe, args=(client, ups, "c2s"), daemon=True)
            t.start()
            _pipe(ups, client, "s2c")
            t.join(timeout=5)
        except Exception as e:
            log(f"WS proxy error: {e}")
        finally:
            try:
                ups.close()
            except Exception:
                pass
            try:
                self.close_connection = True
            except Exception:
                pass

    def _handle(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = ("?" + parsed.query) if parsed.query else ""

        # Lab readiness for phone after Method C join
        if path == "/lab/ready":
            sess = read_session()
            body = json.dumps(
                {"ok": bool(sess), "agent": "/agent-zero/", "via": "sticklink-lab" if sess else None}
            ).encode()
            self._send(200 if sess else 503, {"Content-Type": "application/json"}, body)
            return

        # Fresh ICE/TURN for Method C WebRTC (replaces sinkholed openrelay).
        if path == "/lab/ice":
            try:
                from lab_ice import fetch_ice_servers

                body = json.dumps({"iceServers": fetch_ice_servers(force=True)}).encode()
                self._send(
                    200,
                    {
                        "Content-Type": "application/json",
                        "Cache-Control": "no-store",
                    },
                    body,
                )
            except Exception as e:
                self._send(
                    502,
                    {"Content-Type": "application/json"},
                    json.dumps({"error": str(e)}).encode(),
                )
            return

        if path == "/lab/open-agent":
            sess = read_session()
            if not sess:
                self._send(503, {"Content-Type": "text/plain"}, b"session not ready - finish pair.join first")
                return
            html = (
                "<!DOCTYPE html><meta charset=utf-8>"
                "<meta http-equiv=refresh content='0;url=/agent-zero/'>"
                "<p>Opening Agent Zero…</p>"
            ).encode()
            self._send(200, {"Content-Type": "text/html; charset=utf-8"}, html)
            return

        # Static join assets
        if path.startswith("/browser/") or path.startswith("/node_modules/") or path == "/favicon.ico":
            rel = path.lstrip("/")
            fp = ROOT / rel
            if not fp.is_file() or ".." in path:
                self._send(404, {"Content-Type": "text/plain"}, b"not found")
                return
            data = fp.read_bytes()
            ctype = "application/octet-stream"
            if path.endswith(".html"):
                ctype = "text/html; charset=utf-8"
            elif path.endswith(".js") or path.endswith(".mjs"):
                ctype = "text/javascript; charset=utf-8"
            elif path.endswith(".css"):
                ctype = "text/css; charset=utf-8"
            elif path.endswith(".json"):
                ctype = "application/json"
            elif path.endswith(".svg"):
                ctype = "image/svg+xml"
            elif path.endswith(".png"):
                ctype = "image/png"
            self._send(200, {"Content-Type": ctype}, data)
            return

        # Agent Zero + related API through stick
        if _proxy_paths(path):
            sess = read_session()
            if not sess:
                self._send(
                    401,
                    {"Content-Type": "application/json"},
                    b'{"error":"pair_required","message":"StickLink lab session not ready"}',
                )
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            hdrs = {k: v for k, v in self.headers.items()}
            upstream = _stick_path(path) + qs
            status, rh, rb = stick_fetch(self.command, upstream, hdrs, body, sess["token"])
            # Tunnel host looks "non-local" to A0 — drop the unsecured-connection
            # banner (StickLink lab token is the auth). Do not enable A0 AUTH_LOGIN
            # here or the UI would demand a second login wall.
            if path.rstrip("/").endswith("/api/banners") or upstream.rstrip("/").endswith("/api/banners"):
                if self.command == "POST":
                    rb = _strip_unsecured_banner(rb)
            if self.command == "GET" and status == 200:
                rb = _inject_lab_ux(rb, rh)
            self._send(status, rh, rb)
            note = f" (→ {upstream})" if upstream != path + qs else ""
            log(f"{self.command} {path}{note} -> {status} ({len(rb)} B)")
            return

        if path == "/" or path == "":
            self.send_response(302)
            self.send_header("Location", "/browser/agent_join.html")
            self.end_headers()
            return

        self._send(404, {"Content-Type": "text/plain"}, b"not found")


def serve(port: int):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    log(f"listening http://127.0.0.1:{port}")
    return httpd
