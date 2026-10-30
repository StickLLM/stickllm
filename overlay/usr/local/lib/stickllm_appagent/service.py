"""StickLLM app agent service. Runs beside llama-server; StickLLM's chat UI calls it directly.
  GET  /apps                                   -> [{name, description, connected}]
  POST /act   {app, request, session}          -> {understanding, plan, results, state, ...}
  POST /undo  {app, session}                   -> {ok, message, state}
  GET  /state?app=&session=                    -> {state}
  POST /reset {app, session, start}            (test hook: load a scenario start; also clears that session)
ONLYOFFICE bridge (editor plugin): /oo/plugin/*, /oo/poll, /oo/result; test host page /oo/editor
usage: python3 service.py --port 8795 --llm-url http://127.0.0.1:8080 --nodered-url http://127.0.0.1:1880 --docs-url http://127.0.0.1:8083"""
import argparse, json, os, sys, threading, time, traceback, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import core
from checker import PlanChecker, TurnLog
from bridge import Bridge

class Service:
    def __init__(self, cfg):
        self.cfg = cfg; self.sessions = {}; self.locks = {}; self.bridge = Bridge(); self.checkers = {}
        self.apps = [a for a in cfg["apps"].split(",") if a]
    def make(self, app, start=None):
        if app == "slides":
            from adapters.slides import SimSlides; return SimSlides(start)
        if app == "nodered":
            from adapters.nodered import NodeRedAdapter; return NodeRedAdapter(self.cfg["nodered_url"], start)
        if app == "onlyoffice":
            from adapters.onlyoffice import OOSlides; return OOSlides(self.bridge, start)
        raise KeyError("unknown app %r (have: %s)" % (app, ", ".join(self.apps)))
    def lock(self, app): return self.locks.setdefault(app, threading.Lock())
    def session(self, app, sid, start=None, fresh=False):
        if app not in self.apps: raise KeyError("unknown app %r (have: %s)" % (app, ", ".join(self.apps)))
        k = (sid or "default", app)
        if fresh or k not in self.sessions:
            a = self.make(app, start)
            self.sessions[k] = {"app": a, "prev": [], "tlog": TurnLog(), "created": time.time()}
        return self.sessions[k]
    def checker(self, a):
        if a.name not in self.checkers: self.checkers[a.name] = PlanChecker(a.manual, a.verbs)
        return self.checkers[a.name]
    def list_apps(self):
        out = []
        for n in self.apps:
            d = {"slides": "simulated one-slide presentation editor (in memory)",
                 "nodered": "Node-RED flows (real instance at %s)" % self.cfg["nodered_url"],
                 "onlyoffice": "ONLYOFFICE presentation open in the editor (real document, via the editor plugin)"}.get(n, n)
            e = {"name": n, "description": d}
            if n == "onlyoffice": e["connected"] = self.bridge.connected()
            out.append(e)
        return out
    def act(self, body):
        app, req, sid = body.get("app"), (body.get("request") or "").strip(), body.get("session") or "default"
        if not req: raise ValueError("empty request")
        with self.lock(app):
            s = self.session(app, sid)
            return core.act(self.cfg, s["app"], s, req, self.checker(s["app"]))
    def undo(self, body):
        app, sid = body.get("app"), body.get("session") or "default"
        with self.lock(app):
            s = self.session(app, sid); a = s["app"]
            a.begin_request("undo"); ok, out = a.undo(); a.end_request()
            s["tlog"].add("undo", [{"cmd": "undo", "ok": ok, "out": out}], a); s["prev"].append("undo")
            return {"ok": ok, "message": out, "state": a.state()}
    def do(self, body):
        """debug: run action lines directly (no LLM) as one request"""
        app, sid = body.get("app"), body.get("session") or "default"
        with self.lock(app):
            s = self.session(app, sid); a = s["app"]; a.begin_request(body.get("request", "direct")); res = []
            for line in body.get("lines", []): ok, out = a.do(line); res.append({"cmd": line, "ok": ok, "out": out})
            a.end_request(); return {"results": res, "state": a.state(), **a.export()}
    def reset(self, body):
        app, sid = body.get("app"), body.get("session") or "default"
        with self.lock(app):
            s = self.session(app, sid, start=body.get("start"), fresh=True)
            return {"ok": True, "state": s["app"].state(), **s["app"].export()}
    def state(self, q):
        app, sid = q.get("app"), q.get("session") or "default"
        with self.lock(app):
            a = self.session(app, sid)["app"]; st = a.state()
            return {"state": st, **a.export()}

def plugin_file(svc, name):
    p = os.path.join(HERE, "plugin", name)
    if os.path.exists(p + ".tmpl"):
        return open(p + ".tmpl").read().replace("{{DOCS_URL}}", svc.cfg["docs_url"].rstrip("/"))
    return open(p).read() if os.path.exists(p) else None

EDITOR_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><title>app agent test editor</title>
<style>html,body,#ph{margin:0;height:100%%}</style></head><body><div id="ph"></div>
<script src="%(docs)s/web-apps/apps/api/documents/api.js"></script>
<script>new DocsAPI.DocEditor("ph", {
 document: {fileType: "pptx", key: "aa%(key)s", title: "agent-test.pptx", url: "%(self)s/oo/doc/blank.pptx",
   permissions: {edit: true}},
 documentType: "slide",
 editorConfig: {mode: "edit", callbackUrl: "%(self)s/oo/doc/callback", lang: "en",
   user: {id: "stickllm", name: "StickLLM"},%(cust)s
   plugins: {autostart: ["asc.{5A1C0E2B-7D4F-4E8A-9B6C-511C4A11A0E1}"], pluginsData: ["%(self)s/oo/plugin/config.json"]}},
 width: "100%%", height: "100%%"});</script></body></html>"""

def handler(svc):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *a): pass
        def send(self, code, obj, ctype="application/json"):
            b = obj if isinstance(obj, bytes) else (obj.encode() if isinstance(obj, str) else json.dumps(obj).encode())
            self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
            self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers(); self.wfile.write(b)
        def body(self):
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}
        def do_OPTIONS(self): self.send(204, b"")
        def do_GET(self):
            u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query))
            try:
                if u.path == "/health": return self.send(200, {"ok": True})
                if u.path == "/apps": return self.send(200, svc.list_apps())
                if u.path == "/state": return self.send(200, svc.state(q))
                if u.path == "/oo/poll":
                    j = svc.bridge.poll(q.get("client"))
                    return self.send(200, j) if j else self.send(204, b"")
                if u.path.startswith("/oo/plugin/"):
                    name = u.path[len("/oo/plugin/"):]; c = plugin_file(svc, name) if "/" not in name and ".." not in name else None
                    if c is None: return self.send(404, {"error": "not found"})
                    ct = {"json": "application/json", "html": "text/html", "js": "application/javascript"}.get(name.rsplit(".", 1)[-1], "text/plain")
                    return self.send(200, c, ct)
                if u.path == "/oo/editor":
                    return self.send(200, EDITOR_HTML % {"docs": svc.cfg["docs_url"].rstrip("/"), "self": svc.cfg["self_url"].rstrip("/"),
                                                         "key": int(time.time()),
                                                         # ?stickllm=1 mimics StickLLM's editor_config (plugins UI hidden).
                                                         "cust": "\n   customization: {autosave: true, forcesave: true, plugins: false},"
                                                                 if "stickllm=1" in (u.query or "") else ""}, "text/html")
                if u.path == "/oo/doc/blank.pptx":
                    return self.send(200, open(os.path.join(HERE, "blank.pptx"), "rb").read(),
                                     "application/vnd.openxmlformats-officedocument.presentationml.presentation")
                self.send(404, {"error": "not found"})
            except Exception as e: self.send(400, {"error": str(e)})
        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            try:
                b = self.body()
                if u.path == "/act": return self.send(200, svc.act(b))
                if u.path == "/undo": return self.send(200, svc.undo(b))
                if u.path == "/reset": return self.send(200, svc.reset(b))
                if u.path == "/oo/result": svc.bridge.result(b["id"], b.get("value")); return self.send(200, {"ok": True})
                if u.path == "/oo/doc/callback": return self.send(200, {"error": 0})
                if u.path == "/do" and svc.cfg.get("debug"): return self.send(200, svc.do(b))
                if u.path == "/oo/eval" and svc.cfg.get("debug"): return self.send(200, {"value": svc.bridge.run(b["body"], b.get("timeout", 30))})
                self.send(404, {"error": "not found"})
            except Exception as e:
                traceback.print_exc(); self.send(400, {"error": "%s: %s" % (type(e).__name__, e)})
    return H

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=os.environ.get("APPAGENT_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(os.environ.get("APPAGENT_PORT", "8795")))
    p.add_argument("--llm-url", default=os.environ.get("APPAGENT_LLM_URL", "http://127.0.0.1:8080"))
    p.add_argument("--nodered-url", default=os.environ.get("APPAGENT_NODERED_URL", "http://127.0.0.1:1880"))
    p.add_argument("--docs-url", default=os.environ.get("APPAGENT_DOCS_URL", "http://127.0.0.1:8083"))
    p.add_argument("--self-url", default=os.environ.get("APPAGENT_SELF_URL", ""))
    p.add_argument("--debug", action="store_true", help="enable /oo/eval (raw editor JS, development only)")
    p.add_argument("--apps", default=os.environ.get("APPAGENT_APPS", "slides,nodered,onlyoffice"))
    a = p.parse_args()
    cfg = {"llm_url": a.llm_url, "nodered_url": a.nodered_url, "docs_url": a.docs_url, "apps": a.apps,
           "self_url": a.self_url or "http://127.0.0.1:%d" % a.port, "temperature": 0.0, "debug": a.debug}
    svc = Service(cfg)
    srv = ThreadingHTTPServer((a.host, a.port), handler(svc)); srv.daemon_threads = True
    print("app agent on http://%s:%d  llm=%s apps=%s" % (a.host, a.port, a.llm_url, a.apps), flush=True)
    srv.serve_forever()

if __name__ == "__main__":
    main()
