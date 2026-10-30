"""0.5.5: Node-RED http-in urls never shadow the editor, and checks see the flow's output, not the editor page."""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "overlay" / "usr" / "local" / "lib"))
from stickllm_appagent.adapters.nodered import NodeRedAdapter  # noqa: E402
from stickllm_appagent.adapters.nr_tool import editor_collision, editor_html, safe_http_url  # noqa: E402

EDITOR = '<!DOCTYPE html>\n<html>\n<head>\n<title>Node-RED</title>\n<script src="red/red.min.js"></script></head></html>'


class _FakeNR(BaseHTTPRequestHandler):
    """Admin API + http-in at one root like the stick (httpAdminRoot = httpNodeRoot = /). An http-in whose
    chain reaches a template answers with its text; set shadow=True to answer every path with the editor."""
    flows: list = []
    shadow = False

    def log_message(self, *a): pass

    def _send(self, code, body, ctype="text/html"):
        b = body.encode(); self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path == "/flows": return self._send(200, json.dumps(_FakeNR.flows), "application/json")
        if self.path == "/" or _FakeNR.shadow: return self._send(200, EDITOR)
        by = {n["id"]: n for n in _FakeNR.flows}
        for n in _FakeNR.flows:
            if n["type"] == "http in" and n.get("url") == self.path:
                for w in n.get("wires", [[]])[0]:
                    if by.get(w, {}).get("type") == "template": return self._send(200, by[w].get("template", ""), "text/plain")
        self._send(404, "<html><title>Error</title><pre>Cannot GET %s</pre></html>" % self.path)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0); body = self.rfile.read(n)
        if self.path == "/flows": _FakeNR.flows = json.loads(body); return self._send(204, "")
        self._send(404, "")


def _server():
    _FakeNR.flows = []; _FakeNR.shadow = False
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeNR)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def test_url_helpers():
    for u in ("/", "", "/flows", "/red/x", "/settings?a=1", "/NODES", "/auth/login", "/favicon.ico"):
        assert editor_collision(u), u
    for u in ("/hello", "/api/x", "/flowsx", "/redirect"):
        assert not editor_collision(u), u
    assert safe_http_url("/") == "/hello"
    assert safe_http_url("/", "Greeting Page") == "/greeting-page"
    assert safe_http_url("/", "", {"/hello"}) == "/hello-2"
    assert safe_http_url("/flows") == "/app/flows"
    assert safe_http_url("/ok") == "/ok"
    assert editor_html(EDITOR) and not editor_html("hi there") and not editor_html("<html><title>Error</title></html>")


def test_adapter_rewrites_root_url_and_checks_the_flow_output():
    srv, url = _server()
    try:
        a = NodeRedAdapter(url, start=[]); a.begin_request("a page that says hi")
        assert a.do("tab T")[0]
        ok, out = a.do("add w1 http-in method=get url=/")
        assert ok and "url=/hello" in out and "Node-RED editor" in out
        assert [n["url"] for n in _FakeNR.flows if n["type"] == "http in"] == ["/hello"]  # deployed, never "/"
        a.do('add w2 template text="hi there"'); a.do("add w3 http-response"); a.do("wire w1 w2")
        ok, out = a.do("wire w2 w3")  # chain complete: the post-deploy check calls it once
        assert ok and 'check GET /hello: HTTP 200 "hi there"' in out
        ok, out = a.do("test GET /")  # the request's "/" goes to where the endpoint moved
        assert ok and "HTTP 200: hi there" in out and "/hello" in out
        ok, out = a.do("add w4 http-in method=get")
        assert ok and "url=/hello-2" in out
        ok, out = a.do("set w1 url=/flows")
        assert ok and "url=/app/flows" in out
    finally:
        srv.shutdown()


def test_editor_page_is_never_a_passing_check():
    srv, url = _server()
    try:
        a = NodeRedAdapter(url, start=[]); a.begin_request("x")
        ok, out = a.do("test GET /")
        assert not ok and "editor page" in out
        a.do("tab T"); a.do("add w1 http-in method=get url=/x"); a.do('add w2 template text="T"'); a.do("add w3 http-response")
        a.do("wire w1 w2"); _FakeNR.shadow = True
        ok, out = a.do("wire w2 w3")
        assert not ok and "ERROR: check GET /x returned the Node-RED editor page" in out
        ok, out = a.do("test GET /x")
        assert not ok and "editor page" in out
    finally:
        srv.shutdown()


def test_manual_and_actions_warn_against_root():
    src = (ROOT / "overlay/usr/local/lib/stickllm_appagent/adapters/nodered.py").read_text(encoding="utf-8")
    assert "never /: that is the editor" in src
