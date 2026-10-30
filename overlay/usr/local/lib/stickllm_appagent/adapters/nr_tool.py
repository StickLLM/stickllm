"""Text tool for Node-RED (Admin HTTP API). One command per call; returns a short text result.
Edits are staged locally and only reach Node-RED on `deploy` (like the editor's Deploy button)."""
import json, re, shlex, urllib.request, urllib.error

TYPES = {  # tool type -> (node-red type, allowed keys, is_sink)
    "inject": ("inject", {"every", "once", "payload", "topic", "name"}, False),
    "debug": ("debug", {"name"}, True),
    "function": ("function", {"code", "name"}, False),
    "change": ("change", {"set", "to", "name"}, False),
    "switch": ("switch", {"rule", "value", "name"}, False),
    "http-in": ("http in", {"method", "url", "name"}, False),
    "http-response": ("http response", {"status", "name"}, True),
    "template": ("template", {"text", "name"}, False),
}
RTYPES = {v[0]: k for k, v in TYPES.items()}
SW = {"gt", "lt", "eq", "neq", "gte", "lte"}
HELP = ("commands: tab NAME | delete_tab NAME | add ID TYPE key=value ... | set ID key=value ... | wire FROM[:PORT] TO | "
        "unwire FROM TO | delete ID | deploy | show | test GET|POST /path [body] | done. types: " + ", ".join(TYPES))

# Node-RED serves its editor and Admin API at "/" (httpAdminRoot) and http-in
# flows at "/" too (httpNodeRoot). An http-in on "/" or on an editor path
# (/flows, /red/..., ...) shadows the editor, so those urls are rewritten.
EDITOR_PATHS = {"", "flows", "flow", "nodes", "settings", "auth", "icons", "locales", "library", "red", "vendor",
                "theme", "comms", "debug", "inject", "context", "plugins", "diagnostics", "credentials", "projects",
                "core", "types", "favicon.ico", "index.html", "editor"}
DEFAULT_HTTP_URL = "/hello"

def editor_collision(url):
    """True when an http-in url would shadow the Node-RED editor or its Admin API"""
    seg = str(url or "").split("?", 1)[0].strip("/").split("/", 1)[0].lower()
    return seg in EDITOR_PATHS

def safe_http_url(url, name="", taken=()):
    """a non-root url for an http-in node: url itself when safe, else /<name> or /hello (unique)"""
    if url and not editor_collision(url): return url
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:30]
    base = "/" + slug if slug and not editor_collision(slug) else DEFAULT_HTTP_URL
    if url and not editor_collision(base):
        rest = str(url).strip("/")
        if rest and base == DEFAULT_HTTP_URL: base = "/app/" + re.sub(r"[^A-Za-z0-9/_-]+", "-", rest)
    cand, i = base, 2
    while cand in taken: cand = "%s-%d" % (base, i); i += 1
    return cand

def editor_html(body):
    """the Node-RED editor page (what an http-in shadowed, or a missing endpoint, returns at /)"""
    b = str(body or "")[:4000].lower()
    return "<html" in b and ("<title>node-red</title>" in b or "red/red.min.js" in b or "red/red.js" in b or "red.init(" in b)

def _num(s):
    try: float(s); return True
    except ValueError: return False

class NodeRed:
    def __init__(self, url="http://127.0.0.1:1880"):
        self.url = url.rstrip("/"); self.reload(); self.cur = None; self.notes = []; self.rewrites = {}

    def _req(self, method, path, body=None, headers=None, raw=False):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        h = {"Content-Type": "application/json"}; h.update(headers or {})
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                b = r.read(); return r.status, (b.decode(errors="replace") if raw else (json.loads(b) if b else None))
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode(errors="replace")
        except Exception as e:
            return 0, "no response (%s) - an http-in flow must end in http-response" % e.__class__.__name__

    def reload(self):
        _, self.flows = self._req("GET", "/flows"); self.dirty = False

    # ---------- helpers
    def tab_id(self, name):
        for n in self.flows:
            if n["type"] == "tab" and n.get("label") == name: return n["id"]
    def node(self, nid):
        for n in self.flows:
            if n["id"] == nid and n["type"] != "tab": return n
    def kv(self, parts):
        out = {}
        for p in parts:
            if "=" not in p: raise ValueError("expected key=value, got '%s'" % p)
            k, v = p.split("=", 1); out[k.strip().lower()] = v
        return out

    def apply_props(self, n, t, kv):
        rt, allowed, _ = TYPES[t]
        bad = set(kv) - allowed
        if bad: raise ValueError("%s does not take %s (allowed: %s)" % (t, ", ".join(sorted(bad)), ", ".join(sorted(allowed))))
        if "name" in kv: n["name"] = kv["name"]
        if t == "inject":
            if "every" in kv:
                if not _num(kv["every"]): raise ValueError("every= must be seconds, e.g. every=5")
                n["repeat"] = kv["every"]
            if "once" in kv: n["once"] = kv["once"].lower() == "true"
            if "payload" in kv:
                v = kv["payload"]
                if v == "timestamp": n["payload"], n["payloadType"] = "", "date"
                elif _num(v): n["payload"], n["payloadType"] = v, "num"
                else: n["payload"], n["payloadType"] = v, "str"
            if "topic" in kv: n["topic"] = kv["topic"]
        elif t == "function":
            if "code" in kv: n["func"] = kv["code"]
        elif t == "change":
            r = n["rules"][0]
            if "set" in kv: r["p"] = kv["set"].replace("msg.", "")
            if "to" in kv: r["to"] = kv["to"]; r["tot"] = "num" if _num(kv["to"]) else "str"
        elif t == "switch":
            if "rule" in kv:
                if kv["rule"] not in SW: raise ValueError("rule must be one of " + ", ".join(sorted(SW)))
                n["rules"][0]["t"] = kv["rule"]
            if "value" in kv:
                n["rules"][0]["v"] = kv["value"]; n["rules"][0]["vt"] = "num" if _num(kv["value"]) else "str"
        elif t == "http-in":
            if "method" in kv:
                if kv["method"].lower() not in ("get", "post", "put", "delete"): raise ValueError("method must be get or post")
                n["method"] = kv["method"].lower()
            if "url" in kv:
                if not kv["url"].startswith("/"): raise ValueError("url must start with /")
                n["url"] = kv["url"]
            if "url" in kv or not n.get("url"):
                want = n.get("url", "")
                taken = {x.get("url") for x in self.flows if x.get("type") == "http in" and x.get("id") != n.get("id")}
                n["url"] = safe_http_url(want, n.get("name", ""), taken)
                if n["url"] != want:
                    if want: self.rewrites[want] = n["url"]
                    self.notes.append(("url %s is the Node-RED editor, so this endpoint uses %s instead" % (want, n["url"]))
                                      if want else "no url given, so this endpoint uses %s" % n["url"])
        elif t == "http-response":
            if "status" in kv: n["statusCode"] = kv["status"]
        elif t == "template":
            if "text" in kv: n["template"] = kv["text"]

    def new_node(self, nid, t):
        base = {"id": nid, "z": self.cur, "name": "", "x": 150 + 180 * (len(self.flows) % 5), "y": 80 + 60 * (len(self.flows) // 5)}
        if t == "inject": base.update(type="inject", props=[{"p": "payload"}, {"p": "topic", "vt": "str"}], repeat="", crontab="",
                                      once=False, onceDelay=0.1, topic="", payload="", payloadType="date", wires=[[]])
        elif t == "debug": base.update(type="debug", active=True, tosidebar=True, console=False, tostatus=False, complete="payload",
                                       targetType="msg", wires=[])
        elif t == "function": base.update(type="function", func="return msg;", outputs=1, wires=[[]])
        elif t == "change": base.update(type="change", rules=[{"t": "set", "p": "payload", "pt": "msg", "to": "", "tot": "str"}], wires=[[]])
        elif t == "switch": base.update(type="switch", property="payload", propertyType="msg",
                                        rules=[{"t": "eq", "v": "", "vt": "str"}, {"t": "else"}], checkall="true", outputs=2, wires=[[], []])
        elif t == "http-in": base.update(type="http in", url="", method="get", upload=False, wires=[[]])
        elif t == "http-response": base.update(type="http response", statusCode="", headers={}, wires=[])
        elif t == "template": base.update(type="template", field="payload", fieldType="msg", format="handlebars", syntax="mustache",
                                          template="", output="str", wires=[[]])
        return base

    def describe(self, n):
        t = RTYPES.get(n["type"], n["type"]); p = []
        if n.get("name"): p.append('name="%s"' % n["name"])
        if t == "inject":
            if n.get("repeat"): p.append("every=%s" % n["repeat"])
            if n.get("once"): p.append("once=true")
            p.append("payload=" + ("timestamp" if n.get("payloadType") == "date" else '"%s"' % n.get("payload", "")))
            if n.get("topic"): p.append('topic="%s"' % n["topic"])
        elif t == "function": p.append('code="%s"' % n.get("func", "").replace("\n", " "))
        elif t == "change": r = n["rules"][0]; p.append('set=%s to="%s"' % (r.get("p"), r.get("to")))
        elif t == "switch": r = n["rules"][0]; p.append("rule=%s value=%s" % (r.get("t"), r.get("v")))
        elif t == "http-in": p.append("method=%s url=%s" % (n.get("method"), n.get("url")))
        elif t == "template": p.append('text="%s"' % n.get("template"))
        w = n.get("wires", [])
        if len(w) == 1 and w[0]: p.append("-> " + ",".join(w[0]))
        elif len(w) > 1: p.append("-> " + " ".join("%d:%s" % (i + 1, ",".join(x) or "-") for i, x in enumerate(w)))
        return "  %s %s %s" % (n["id"], t, " ".join(p))

    def show(self):
        out = ["(staged changes NOT deployed)" if self.dirty else "(deployed)"]
        for tab in [n for n in self.flows if n["type"] == "tab"]:
            nodes = [n for n in self.flows if n.get("z") == tab["id"]]
            out.append("tab %s%s: %d nodes" % (tab["label"], " <- current" if tab["id"] == self.cur else "", len(nodes)))
            out += [self.describe(n) for n in nodes]
        if len(out) == 1: out.append("no tabs")
        return "\n".join(out)

    # ---------- command entry
    def run(self, line):
        """returns (ok, text)"""
        line = line.strip()
        try:
            parts = shlex.split(line)
        except ValueError as e:
            return False, "ERROR: bad quoting (%s)" % e
        if not parts: return False, "ERROR: empty command. " + HELP
        c, a = parts[0].lower(), parts[1:]
        self.notes = []
        try:
            if c == "tab":
                if len(a) != 1: raise ValueError("usage: tab NAME")
                tid = self.tab_id(a[0])
                if tid is None:
                    tid = "tab_" + re.sub(r"\W", "_", a[0])
                    self.flows.append({"id": tid, "type": "tab", "label": a[0], "disabled": False, "info": ""}); self.dirty = True
                    self.cur = tid; return True, "ok: created tab %s (now current)" % a[0]
                self.cur = tid; return True, "ok: tab %s is now current" % a[0]
            if c == "delete_tab":
                if len(a) != 1: raise ValueError("usage: delete_tab NAME")
                tid = self.tab_id(a[0])
                if tid is None: raise ValueError("no tab named %s" % a[0])
                self.flows = [n for n in self.flows if n["id"] != tid and n.get("z") != tid]; self.dirty = True
                if self.cur == tid: self.cur = None
                return True, "ok: deleted tab %s (deploy to apply)" % a[0]
            if c == "add":
                if self.cur is None: raise ValueError("no current tab; use `tab NAME` first")
                if len(a) < 2: raise ValueError("usage: add ID TYPE key=value ...")
                nid, t = a[0], a[1].lower()
                if t not in TYPES: raise ValueError("unknown type %s; types: %s" % (t, ", ".join(TYPES)))
                if not re.fullmatch(r"[A-Za-z0-9_]+", nid): raise ValueError("ID must be letters/digits/_")
                if self.node(nid) or self.tab_id(nid): raise ValueError("ID %s already exists" % nid)
                n = self.new_node(nid, t); self.apply_props(n, t, self.kv(a[2:]))
                self.flows.append(n); self.dirty = True
                return True, "ok: added" + self.describe(n)[1:] + "".join(" (note: %s)" % x for x in self.notes)
            if c == "set":
                if len(a) < 2: raise ValueError("usage: set ID key=value ...")
                n = self.node(a[0])
                if not n: raise ValueError("no node %s" % a[0])
                self.apply_props(n, RTYPES[n["type"]], self.kv(a[1:])); self.dirty = True
                return True, "ok: " + self.describe(n).strip() + "".join(" (note: %s)" % x for x in self.notes)
            if c in ("wire", "unwire"):
                if len(a) != 2: raise ValueError("usage: %s FROM[:PORT] TO" % c)
                src, port = (a[0].split(":") + ["1"])[:2]
                s, d = self.node(src), self.node(a[1])
                if not s: raise ValueError("no node %s" % src)
                if not d: raise ValueError("no node %s" % a[1])
                if not port.isdigit() or not 1 <= int(port) <= len(s["wires"]):
                    raise ValueError("%s has %d output(s); it cannot send" % (src, len(s["wires"])) if not s["wires"] else "port must be 1..%d" % len(s["wires"]))
                ws = s["wires"][int(port) - 1]
                if c == "wire":
                    if a[1] in ws: raise ValueError("already wired")
                    if d["type"] == "inject" or d["type"] == "http in": raise ValueError("%s has no input" % a[1])
                    ws.append(a[1])
                else:
                    if a[1] not in ws: raise ValueError("not wired")
                    ws.remove(a[1])
                self.dirty = True; return True, "ok: " + self.describe(s).strip()
            if c == "delete":
                if len(a) != 1 or not self.node(a[0]): raise ValueError("usage: delete ID (existing node)")
                self.flows = [n for n in self.flows if n["id"] != a[0]]
                for n in self.flows:
                    for ws in n.get("wires", []):
                        if a[0] in ws: ws.remove(a[0])
                self.dirty = True; return True, "ok: deleted %s" % a[0]
            if c == "deploy":
                if not self.dirty: raise ValueError("nothing changed since last deploy")
                problems = []
                for n in self.flows:
                    t = RTYPES.get(n["type"])
                    if n["type"] == "http in" and not n.get("url"): problems.append("%s needs url=" % n["id"])
                st, body = self._req("POST", "/flows", self.flows, {"Node-RED-Deployment-Type": "full"})
                if st not in (200, 204): return False, "ERROR: deploy failed (%s) %s" % (st, str(body)[:200])
                self.reload()
                return True, "ok: deployed %d nodes" % len([n for n in self.flows if n["type"] != "tab"]) + \
                    ("; warnings: " + "; ".join(problems) if problems else "")
            if c == "show": return True, self.show()
            if c == "test":
                if len(a) < 2 or a[0].upper() not in ("GET", "POST"): raise ValueError("usage: test GET|POST /path [body]")
                if a[1] in self.rewrites:
                    self.notes.append("%s was moved to %s" % (a[1], self.rewrites[a[1]])); a[1] = self.rewrites[a[1]]
                st, body = self._req(a[0].upper(), a[1], (" ".join(a[2:])).encode() if a[0].upper() == "POST" else None,
                                     {"Content-Type": "text/plain"}, raw=True)
                if editor_html(body):
                    return False, ("ERROR: %s %s returned the Node-RED editor page, not a flow's output (no http-in serves it; "
                                   "use a path like %s)" % (a[0].upper(), a[1], DEFAULT_HTTP_URL))
                return True, "HTTP %s: %s" % (st, str(body)[:200]) + ("  (note: staged changes are not deployed)" if self.dirty else "") + \
                    "".join(" (note: %s)" % x for x in self.notes)
            if c == "done": return True, "ok: done"
            raise ValueError("unknown command %s. %s" % (c, HELP))
        except ValueError as e:
            return False, "ERROR: %s" % e

if __name__ == "__main__":
    import sys
    nr = NodeRed(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:1880")
    for line in sys.stdin:
        ok, out = nr.run(line); print(out, flush=True)
