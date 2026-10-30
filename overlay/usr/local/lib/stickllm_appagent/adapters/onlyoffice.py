"""ONLYOFFICE presentation adapter (real document). The free editions have no Automation API, so the service
talks to a small system plugin inside the open editor (plugin/): it runs Presentation API JS (Api.*) with
Asc.plugin.callCommand and returns JSON. state() reads the real slide back every time (shapes, preset geometry,
fill colour, text, text colour, position and size in EMU). Action syntax and meanings are the slides manual's:
SlideApp's parser computes the target model, the adapter applies the difference to the document with Api calls,
then reads the document back. One user request = one undo step (snapshot restore through the same diff path)."""
import copy, json, re
from .slides_sim import SlideApp, COLORS, W, H
from . import manual

EMU = 12700
GEO = {"rect": "rect", "ellipse": "ellipse", "triangle": "triangle", "textbox": "rect"}

READ_JS = r"""
var a = S.GetAllShapes(), out = [];
function rgb(f){ var c = f && f.color; c = c && ((c.color && c.color.rgba) || c.rgba); return c ? [c.red, c.green, c.blue] : null; }
function firstRunFill(n){ if (!n || typeof n !== 'object') return null;
  if (n.type === 'run' && n.rPr && n.rPr.uniFill && n.rPr.uniFill.fill) return rgb(n.rPr.uniFill.fill);
  for (var k in n) { var r = firstRunFill(n[k]); if (r) return r; } return null; }
for (var i = 0; i < a.length; i++) {
  var o = a[i], j = {}; try { j = JSON.parse(o.ToJSON()); } catch (e) {}
  var sp = j.spPr || {}, g = sp.custGeom || sp.prstGeom || sp.geometry || {}, f = (sp.fill && sp.fill.fill) || null;
  var txt = [], dc = o.GetDocContent();
  if (dc) for (var k = 0; k < dc.GetElementsCount(); k++) { var t = dc.GetElement(k).GetText().replace(/[\r\n]+$/, ''); if (t) txt.push(t); }
  if (!o.GetName()) o.SetName('__new' + i);
  out.push({name: o.GetName(), preset: g.preset || null, fill: f ? (f.type === 'noFill' ? 'none' : rgb(f)) : null,
            x: o.GetPosX(), y: o.GetPosY(), w: o.GetWidth(), h: o.GetHeight(), text: txt.join(' '), tcolor: firstRunFill(j.content)});
}
return out;"""

FIND_JS = "function F(n){ var a = S.GetAllShapes(); for (var i = 0; i < a.length; i++) if (a[i].GetName() === n) return a[i]; throw new Error('no shape ' + n + ' in the document'); }\n"

def hexrgb(h): return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
def js(s): return json.dumps(s)

def text_js(var, o):
    """set the text of shape `var` (one paragraph); textbox fill = text colour"""
    r, g, b = hexrgb(o["fill"]) if o["type"] == "textbox" else (0, 0, 0)
    col = ("r.SetFill(Api.CreateSolidFill(Api.CreateRGBColor(%d,%d,%d)));" % (r, g, b)) if o["type"] == "textbox" else ""
    return ("(function(){ var dc = %s.GetDocContent(); dc.RemoveAllElements(); var p = dc.GetElement(0);"
            " if (!p) { p = Api.CreateParagraph(); dc.Push(p); } p.RemoveAllElements(); var r = p.AddText(%s); %s })();\n") % (var, js(o["text"] or ""), col)

def fill_js(o):
    if o["type"] == "textbox": return "Api.CreateNoFill()"
    return "Api.CreateSolidFill(Api.CreateRGBColor(%d,%d,%d))" % hexrgb(o["fill"])

def create_js(o):
    s = ("var o = Api.CreateShape(%s, %d, %d, %s, Api.CreateStroke(0, Api.CreateNoFill())); o.SetPosition(%d, %d); o.SetName(%s);\n"
         % (js(GEO[o["type"]]), o["w"] * EMU, o["h"] * EMU, fill_js(o), o["x"] * EMU, o["y"] * EMU, js(o["id"])))
    if o["text"] or o["type"] == "textbox": s += text_js("o", o)
    return s + "S.AddObject(o);\n"

def diff_js(before, after):
    b = {o["id"]: o for o in before}; a = {o["id"]: o for o in after}; out = [FIND_JS]
    for i in b:
        if i not in a: out.append("F(%s).Delete();\n" % js(i))
    for o in after:
        if o["id"] not in b: out.append(create_js(o)); continue
        p = b[o["id"]]
        if p["type"] != o["type"]:
            out.append("F(%s).Delete();\n" % js(o["id"])); out.append(create_js(o)); continue
        v = "F(%s)" % js(o["id"])
        if (p["w"], p["h"]) != (o["w"], o["h"]): out.append("%s.SetSize(%d, %d);\n" % (v, o["w"] * EMU, o["h"] * EMU))
        if (p["x"], p["y"]) != (o["x"], o["y"]): out.append("%s.SetPosition(%d, %d);\n" % (v, o["x"] * EMU, o["y"] * EMU))
        if p["fill"] != o["fill"] and o["type"] != "textbox": out.append("%s.SetFill(%s);\n" % (v, fill_js(o)))
        if p["text"] != o["text"] or (o["type"] == "textbox" and p["fill"] != o["fill"]):
            out.append("(function(){ var t = %s; %s })();\n" % (v, text_js("t", o)))
    return "".join(out) + "return 'ok';"

class OOSlides(SlideApp):
    name = "onlyoffice"
    description = "ONLYOFFICE presentation (real document via the editor plugin)"
    verbs = ["add", "scale", "resize", "move", "nudge", "fill", "settext", "delete"]

    def __init__(self, bridge, start=None):
        SlideApp.__init__(self, start or []); self.bridge = bridge; self.manual = manual("MANUAL_slides.md")
        if start is not None:   # test hook: make the real slide match the scenario start
            self.bridge.run("S.RemoveAllObjects();\n" + diff_js([], self.objs).replace("return 'ok';", "") + "return 'ok';")
        self.read()

    # ---- read the real document ----
    def read(self):
        shapes = self.bridge.run(READ_JS); objs = []; rename = []
        for s in shapes:
            pre = s.get("preset") or "rect"
            t = {"ellipse": "ellipse", "triangle": "triangle"}.get(pre, "rect")
            if t == "rect" and s.get("fill") in ("none", None) and s.get("text"): t = "textbox"
            if t == "textbox": col = s.get("tcolor") or [0, 0, 0]
            else: col = s["fill"] if isinstance(s.get("fill"), list) else [128, 128, 128]
            oid = s["name"]
            if not re.fullmatch(r"s\d+", oid):   # a shape the agent did not create (e.g. drawn by the user)
                nid = "s%d" % self.next_id; self.next_id += 1; rename.append((oid, nid)); oid = nid
            self.next_id = max(self.next_id, int(oid[1:]) + 1)
            objs.append({"id": oid, "type": t, "fill": "#%02X%02X%02X" % tuple(col),
                         "x": int(round(s["x"] / EMU)), "y": int(round(s["y"] / EMU)),
                         "w": int(round(s["w"] / EMU)), "h": int(round(s["h"] / EMU)), "text": s.get("text") or ""})
        if rename:
            self.bridge.run(FIND_JS + "".join("F(%s).SetName(%s);\n" % (js(a), js(b)) for a, b in rename) + "return 'ok';")
        self.objs = objs
        if self.selection and self.selection not in [o["id"] for o in objs]: self.selection = None
        return objs

    def state(self):
        self.read(); return SlideApp.state(self)

    def begin_request(self, text):
        self.read(); SlideApp.begin_request(self, text)

    def simulate(self, plan):
        sim = SlideApp.__new__(SlideApp)
        sim.__dict__.update(copy.deepcopy({k: v for k, v in self.__dict__.items() if k != "bridge"}))
        return [sim.do(c) for c in plan], sim

    def do(self, cmd):
        try: self.read()
        except Exception as e: return False, "ERROR: cannot read the document (%s)" % e
        before = copy.deepcopy(self.objs); saved = copy.deepcopy((self.next_id, self.selection, self.history, self.turn_stack, self._turn_log))
        ok, msg = SlideApp.do(self, cmd)
        if not ok or msg == "done": return ok, msg
        try:
            self.bridge.run(diff_js(before, self.objs)); target = {o["id"]: o for o in self.objs}; self.read()
        except Exception as e:
            self.next_id, self.selection, self.history, self.turn_stack, self._turn_log = saved
            try: self.read()
            except Exception: self.objs = before
            return False, "ERROR: the editor refused the change (%s)" % e
        # report what the document now says (not what we intended)
        bad = [i for i, o in target.items() if not any(r["id"] == i and abs(r["x"] - o["x"]) <= 2 and abs(r["y"] - o["y"]) <= 2
               and abs(r["w"] - o["w"]) <= 2 and abs(r["h"] - o["h"]) <= 2 and r["fill"] == o["fill"] for r in self.objs)]
        if bad: msg += " (warning: document differs for %s)" % ", ".join(bad)
        m = re.match(r"ok: (\w+) (s\d+)", msg)
        if m and m.group(1) not in ("deleted",):
            r = next((o for o in self.objs if o["id"] == m.group(2)), None)
            if r: msg = re.sub(r"-> x=.*", "-> x=%d y=%d w=%d h=%d (read back from the document)" % (r["x"], r["y"], r["w"], r["h"]), msg)
        return True, msg

    def undo(self): return self.do("undo")
    def reset(self, start): self.__init__(self.bridge, start)
    def export(self): return {"objs": self.objs}
