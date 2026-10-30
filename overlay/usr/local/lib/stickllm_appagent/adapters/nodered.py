"""Node-RED adapter over the Admin HTTP API (port of intent/nr_app.py). Every successful edit is deployed
immediately; undo restores the flows from before the previous user request."""
import copy, json, os, shlex, urllib.error, urllib.request
from .nr_tool import NodeRed, editor_html
from . import manual

ACTIONS = """actions (one per line, key=value; quote values with spaces):
  tab NAME                     create or select a tab; new nodes go on the current tab
  delete_tab NAME              remove a whole tab and its nodes
  add ID TYPE key=value ...    add a node on the current tab. ID = a new short name (letters/digits/_)
  set ID key=value ...         change settings of an existing node
  wire FROM TO                 send FROM's output into TO (switch: FROM:1 = match, FROM:2 = otherwise)
  unwire FROM TO               remove a wire
  delete ID                    remove a node
  test GET /path | test POST /path BODY    call an HTTP endpoint
  undo                         revert the whole previous user request
  done                         finish this request
types and keys:
  inject  every=SECONDS once=true payload=timestamp|NUMBER|"text" topic=T
  debug   (none)          function code="JS ending with return msg;"
  change  set=payload to=VALUE      switch rule=gt|lt|eq|neq|gte|lte value=V
  http-in method=get|post url=/path (never /: that is the editor)    http-response (none)    template text="reply text"
Every successful edit is deployed automatically."""

def normalize_cmd(cmd):
    """tolerant input: words after key=value without '=' belong to that value (set w2 text=hello world)"""
    try: p = shlex.split(cmd)
    except ValueError: return cmd
    out = []; merged = False
    for t in p:
        if "=" not in t and out and "=" in out[-1] and not out[-1].startswith("="):
            out[-1] += " " + t; merged = True
        else: out.append(t)
    if not merged: return cmd
    def q(t):
        if "=" in t:
            k, _, v = t.partition("=")
            return '%s="%s"' % (k, v.replace('"', '\\"')) if (" " in v) else t
        return t
    return " ".join(q(t) for t in out)

class NodeRedAdapter:
    name = "nodered"
    description = "Node-RED flow editor (real instance, Admin HTTP API)"
    verbs = ["tab", "delete_tab", "add", "set", "wire", "unwire", "delete", "test"]
    def __init__(self, url, start=None):
        self.url = url.rstrip("/"); self.manual = manual("MANUAL_nodered.md")
        if start is not None: self._post(start)
        self.nr = NodeRed(self.url); self.turn_stack = []; self.history = []; self._log = []; self._text = ""; self._snapf = None
        self._checked = {}

    def _post(self, flows):
        req = urllib.request.Request(self.url + "/flows", data=json.dumps(flows).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Node-RED-Deployment-Type": "full"})
        urllib.request.urlopen(req, timeout=10).read()

    def reset(self, start): self.__init__(self.url, start)
    def export(self): return {"flows": self.nr.flows}

    def begin_request(self, text):
        self._snapf = copy.deepcopy(self.nr.flows); self._hist0 = list(self.history); self._log = []; self._text = text
    def end_request(self):
        if self._log:
            self.turn_stack.append((self._snapf, self._hist0)); self.history.append('"%s" -> %s' % (self._text, "; ".join(self._log)))

    def state(self):
        cur = [n.get("label") for n in self.nr.flows if n["type"] == "tab" and n["id"] == self.nr.cur]
        sh = self.nr.show(); s = sh.split("\n", 1)[1] if "\n" in sh else ""
        h = "\n".join("  %d. %s" % (i + 1, x) for i, x in enumerate(self.history[-6:])) or "  (empty)"
        return "FLOWS (all deployed):\n%s\nCURRENT TAB: %s\nHISTORY (oldest first, each line is one undo step):\n%s" % (s, cur[0] if cur else "none", h)

    def list_actions(self): return ACTIONS
    def ids(self): return [x["id"] for x in self.nr.flows if x["type"] != "tab"]
    def edges(self):
        return {(x["id"], d) for x in self.nr.flows if x["type"] != "tab" for ws in x.get("wires", []) for d in ws}
    def simulate(self, plan):
        sim = _NRSim(self); res = [sim.do(c) for c in plan]; return res, sim
    def snapshot(self): return copy.deepcopy(self.nr.flows)
    def undo(self): return self.do("undo")

    def do(self, cmd):
        c = cmd.strip().split(" ", 1)[0].lower()
        if c == "undo":
            if not self.turn_stack: return False, "ERROR: nothing to undo"
            flows, hist = self.turn_stack.pop(); self._post(flows); self.nr.reload(); self.history = hist
            self._snapf = copy.deepcopy(self.nr.flows); self._hist0 = list(hist); self._log = []
            if self.nr.cur and not any(n["id"] == self.nr.cur for n in self.nr.flows): self.nr.cur = None
            return True, "ok: undid the previous request"
        if c in ("deploy", "show"): return True, "ok (edits deploy automatically)" if c == "deploy" else self.state()
        if c == "done": return True, "done"
        cmd = normalize_cmd(cmd)
        ok, out = self.nr.run(cmd)
        if ok and self.nr.dirty:
            ok2, out2 = self.nr.run("deploy")
            if not ok2: return False, out2
            if c != "test": self._log.append(cmd.strip())
            ok, out = self.post_deploy_check(ok, out)
        return ok, out

    def endpoints(self):
        """deployed GET http-in nodes whose wires reach an http-response: {url: chain signature}"""
        by = {n["id"]: n for n in self.nr.flows if n["type"] != "tab"}; out = {}
        for n in by.values():
            if n["type"] != "http in" or n.get("method", "get") != "get" or not n.get("url"): continue
            seen, todo, done = set(), [n["id"]], False
            while todo:
                x = by.get(todo.pop())
                if not x or x["id"] in seen: continue
                seen.add(x["id"]); done = done or x["type"] == "http response"
                todo += [d for ws in x.get("wires", []) for d in ws]
            if done: out[n["url"]] = json.dumps(sorted((by[i]["id"], json.dumps(by[i], sort_keys=True)) for i in seen))
        return out

    def post_deploy_check(self, ok, out):
        """after a deploy, call each finished GET endpoint once (per change) and make sure the answer is the flow's
        output, not the Node-RED editor page that a missing or shadowing endpoint returns"""
        for url, sig in self.endpoints().items():
            if self._checked.get(url) == sig: continue
            self._checked[url] = sig
            try:
                with urllib.request.urlopen(self.url + url, timeout=4) as r: st, body = r.status, r.read(4000).decode(errors="replace")
            except urllib.error.HTTPError as e: st, body = e.code, e.read(4000).decode(errors="replace")
            except Exception as e: out += "; check GET %s: no answer (%s)" % (url, e.__class__.__name__); continue
            if editor_html(body):
                return False, out + "; ERROR: check GET %s returned the Node-RED editor page, not the flow's output" % url
            out += "; check GET %s: HTTP %s %s" % (url, st, json.dumps(body.strip()[:80]))
        return ok, out

class _NRSim:
    """staged-only copy for plan checking: same parser and validation, no HTTP"""
    def __init__(self, app):
        self.nr = copy.copy(app.nr); self.nr.flows = copy.deepcopy(app.nr.flows); self.nr.dirty = False
        self.turn_stack = copy.deepcopy(app.turn_stack)
    def do(self, cmd):
        c = cmd.strip().split(" ", 1)[0].lower()
        if c == "undo":
            if not self.turn_stack: return False, "ERROR: nothing to undo"
            self.nr.flows = copy.deepcopy(self.turn_stack.pop()[0])
            if self.nr.cur and not any(n["id"] == self.nr.cur for n in self.nr.flows): self.nr.cur = None
            return True, "ok: undid the previous request"
        if c in ("deploy", "show", "done", "test"): return True, "ok (not simulated)"
        return self.nr.run(normalize_cmd(cmd))
    ids = NodeRedAdapter.ids
    edges = NodeRedAdapter.edges
