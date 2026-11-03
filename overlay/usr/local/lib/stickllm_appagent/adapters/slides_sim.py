"""Text-state slide simulator with the universal app API: state() / list_actions() / do(cmd) / undo().
Coordinates in points on a 960x540 slide (= 16:9 pptx, 12192000x6858000 EMU; 1 pt = 12700 EMU).
Every action maps 1:1 onto the ONLYOFFICE Office JS Presentation API (see to_onlyoffice_js)."""
import copy, math, re, shlex

W, H, MARGIN = 960, 540, 20
COLORS = {"red": "#FF0000", "blue": "#1F5FD6", "green": "#2E9E44", "yellow": "#FFD500", "orange": "#FF8C00",
          "purple": "#7B2FBE", "pink": "#FF69B4", "black": "#000000", "white": "#FFFFFF", "gray": "#808080",
          "grey": "#808080", "brown": "#8B4513", "teal": "#008080", "navy": "#001F7A", "lightblue": "#87CEEB"}
TYPES = ["rect", "ellipse", "triangle", "textbox"]
ANCHORS = ["center", "top", "bottom", "left", "right", "top-left", "top-right", "bottom-left", "bottom-right"]
SIZES = {"tiny": 0.02, "small": 0.05, "medium": 0.1, "large": 0.25, "huge": 0.6}

ACTIONS = """actions (one per line, key=value, no spaces around =):
  add TYPE [fill=COLOR] [size=FRACTION|w=PT h=PT] [aspect=page|square] [at=ANCHOR|x=PT y=PT] [text="..."]
        TYPE: rect ellipse triangle textbox. size=FRACTION is the share of the PAGE AREA (0.33 = a third of the page).
        defaults: fill=blue size=0.1 aspect=page (square for ellipse/triangle) at=center. A textbox needs text="...". New id is returned (s1, s2 ...).
  scale ID FACTOR            grow/shrink both sides about the centre (1.25 = 25% bigger, 0.8 = smaller)
  resize ID w=PT h=PT        set exact size, keeps the centre
  move ID at=ANCHOR          place at a page anchor with 20pt margin: center top bottom left right top-left top-right bottom-left bottom-right
  move ID x=PT y=PT          top-left corner to exact position
  nudge ID dx=PT dy=PT       shift relative (+dx right, +dy down)
  fill ID COLOR              COLOR: red blue green yellow orange purple pink black white gray brown teal navy lightblue or #RRGGBB (for a textbox = text colour)
  settext ID "new text"     change the words of a textbox
  delete ID
  addslide                   add one blank slide at the end of the deck (it becomes the shown slide)
  nextslide                  show the next slide
  prevslide                  show the previous slide
  undo                       revert the whole previous user request (repeat to go further back)
  done                       finish this request"""

def color_hex(c):
    c = c.strip().lower()
    if c in COLORS: return COLORS[c]
    if re.fullmatch(r"#[0-9a-f]{6}", c): return c.upper()
    raise ValueError("unknown colour %s (use a name from the list or #RRGGBB)" % c)

def pos_name(o):
    cx, cy = o["x"] + o["w"] / 2, o["y"] + o["h"] / 2
    nt, nb = o["y"] <= MARGIN + 5, o["y"] + o["h"] >= H - MARGIN - 5
    nl, nr = o["x"] <= MARGIN + 5, o["x"] + o["w"] >= W - MARGIN - 5
    v = "top" if nt and not nb else "bottom" if nb and not nt else ("top" if cy < H / 3 else "bottom" if cy > 2 * H / 3 else "")
    h = "left" if nl and not nr else "right" if nr and not nl else ("left" if cx < W / 3 else "right" if cx > 2 * W / 3 else "")
    return "-".join([p for p in (v, h) if p]) or "center"

class SlideApp:
    name = "slides"
    def __init__(self, objects=None):
        self.objs = []; self.next_id = 1; self.selection = None; self.history = []; self.turn_stack = []
        for o in objects or []:
            o = dict(o); o.setdefault("id", "s%d" % self.next_id); o.setdefault("text", "")
            self.next_id = max(self.next_id, int(o["id"][1:]) + 1); self.objs.append(o)
        self._turn_snapshot = None; self._turn_log = []; self._turn_text = ""
        # deck navigation (stickman 7f3b75e): slides in the deck and the shown one
        self.slides = [{"id": 1}]; self._next_slide = 2; self.current = 0

    def showing(self):
        if not self.slides: return 0
        if self.current < 0 or self.current >= len(self.slides): self.current = max(0, len(self.slides) - 1)
        return self.slides[self.current]["id"]

    def deck_action_js(self, verb):
        """ONLYOFFICE statements for one deck action (stickman 7f3b75e). AddSlide selects the new slide."""
        if verb == "addslide":
            return "var __pres = Api.GetPresentation(); __pres.AddSlide(Api.CreateSlide());"
        if verb == "nextslide":
            return ("var __pres = Api.GetPresentation(); var __i = __pres.GetCurSlideIndex();"
                    " if (__i + 1 >= __pres.GetSlidesCount()) { throw new Error('no next slide'); }"
                    " if (typeof editor !== 'undefined' && editor && editor.goToPage) editor.goToPage(__i + 1);")
        if verb == "prevslide":
            return ("var __pres = Api.GetPresentation(); var __i = __pres.GetCurSlideIndex();"
                    " if (__i <= 0) { throw new Error('no previous slide'); }"
                    " if (typeof editor !== 'undefined' && editor && editor.goToPage) editor.goToPage(__i - 1);")
        raise ValueError("no deck action %s" % verb)

    # ---- turn bookkeeping (one user request = one undo step) ----
    def begin_request(self, text):
        self._turn_snapshot = self._snap(); self._turn_log = []; self._turn_text = text
    def end_request(self):
        if self._turn_log:
            self.turn_stack.append(self._turn_snapshot)
            self.history.append('"%s" -> %s' % (self._turn_text, "; ".join(self._turn_log)))
        self._turn_snapshot = None
    def _snap(self):
        return copy.deepcopy((self.objs, self.next_id, self.selection, self.history,
                              getattr(self, "slides", [{"id": 1}]), getattr(self, "_next_slide", 2), getattr(self, "current", 0)))

    # ---- universal API ----
    def state(self):
        sl = getattr(self, "slides", [{"id": 1}])
        lines = ["PAGE %dx%d pt. SLIDES %d showing=%d (objects below are on the shown slide). Margin %d." % (
            W, H, len(sl), self.showing() if sl else 1, MARGIN), "OBJECTS (back to front):"]
        if not self.objs: lines.append("  (none)")
        for o in self.objs:
            area = 100.0 * o["w"] * o["h"] / (W * H)
            t = (' text="%s"' % o["text"]) if o["type"] == "textbox" or o["text"] else ""
            cname = next((k for k, v in COLORS.items() if v == o["fill"]), o["fill"])
            lines.append("  %s %s fill=%s(%s) x=%d y=%d w=%d h=%d area=%.0f%% pos=%s%s" % (
                o["id"], o["type"], cname, o["fill"], o["x"], o["y"], o["w"], o["h"], area, pos_name(o), t))
        lines.append("SELECTION: %s" % (self.selection or "none"))
        lines.append("HISTORY (oldest first, each line is one undo step):")
        for i, h in enumerate(self.history[-6:]): lines.append("  %d. %s" % (i + 1, h))
        if not self.history: lines.append("  (empty)")
        return "\n".join(lines)

    def list_actions(self): return ACTIONS

    # ---- optional universal-API extras used by the plan checker ----
    def ids(self): return [o["id"] for o in self.objs]
    def simulate(self, plan):
        """dry-run: apply the plan to a copy; returns ([(ok, msg)], sim_app). The real app is untouched."""
        sim = copy.deepcopy(self); res = [sim.do(c) for c in plan]; return res, sim

    def get(self, oid):
        for o in self.objs:
            if o["id"] == oid: return o
        raise ValueError("no object %s (existing: %s)" % (oid, ", ".join(x["id"] for x in self.objs) or "none"))

    def _clamp(self, o):
        o["w"] = max(4, min(o["w"], W)); o["h"] = max(4, min(o["h"], H))
        o["x"] = max(0, min(o["x"], W - o["w"])); o["y"] = max(0, min(o["y"], H - o["h"]))
        for k in "xywh": o[k] = int(round(o[k]))

    def _anchor(self, o, a):
        if a not in ANCHORS: raise ValueError("unknown anchor %s (use %s)" % (a, " ".join(ANCHORS)))
        x = (W - o["w"]) / 2; y = (H - o["h"]) / 2
        if "top" in a: y = MARGIN
        if "bottom" in a: y = H - o["h"] - MARGIN
        if "left" in a: x = MARGIN
        if "right" in a: x = W - o["w"] - MARGIN
        o["x"], o["y"] = x, y

    def do(self, cmd):
        """returns (ok, message). Never raises."""
        try:
            return True, self._do(cmd.strip())
        except Exception as e:
            return False, "ERROR: %s" % e

    def _do(self, cmd):
        try: p = shlex.split(cmd)
        except ValueError as e: raise ValueError("bad quoting (%s)" % e)
        if not p: raise ValueError("empty command")
        v = p[0].lower(); kv = {}; pos = []
        last = None
        for t in p[1:]:
            if "=" in t: k, _, val = t.partition("="); last = k.lower(); kv[last] = val
            elif last is not None: kv[last] += " " + t   # tolerant: unquoted multi-word value (text=hello world)
            else: pos.append(t)
        def num(k, d=None):
            if k not in kv:
                if d is None: raise ValueError("%s needs %s=" % (v, k))
                return d
            return float(kv[k].rstrip("pt%"))
        if v == "done": return "done"
        if v == "undo":
            if not self.turn_stack: raise ValueError("nothing to undo")
            snap = self.turn_stack.pop()
            self.objs, self.next_id, self.selection, self.history = snap[:4]
            if len(snap) > 4: self.slides, self._next_slide, self.current = snap[4:7]
            self._turn_snapshot = self._snap(); self._turn_log = []
            return "ok: undid the previous request"
        if v == "add":
            if not pos or pos[0] not in TYPES: raise ValueError("add needs a TYPE: %s" % " ".join(TYPES))
            t = pos[0]; o = {"id": "s%d" % self.next_id, "type": t, "fill": color_hex(kv.get("fill", "black" if t == "textbox" else "blue")),
                             "text": kv.get("text", "Text" if t == "textbox" else "")}
            if "w" in kv or "h" in kv:
                o["w"] = num("w", num("h", 100)); o["h"] = num("h", o["w"])
            else:
                s = kv.get("size", "0.1"); s = SIZES.get(s, None) or float(s.rstrip("%")) / (100 if s.endswith("%") else 1)
                if not 0 < s <= 1: raise ValueError("size is a fraction of the page area between 0 and 1")
                asp = kv.get("aspect", "square" if t in ("ellipse", "triangle") else "page")
                if t == "textbox" and "size" not in kv and "aspect" not in kv: o["w"], o["h"] = 400, 60
                elif asp == "square": o["w"] = o["h"] = math.sqrt(s * W * H)
                else: o["w"], o["h"] = W * math.sqrt(s), H * math.sqrt(s)
            if "x" in kv or "y" in kv: o["x"], o["y"] = num("x", 0), num("y", 0)
            else: o["x"], o["y"] = 0, 0; self._anchor(o, kv.get("at", "center"))
            self._clamp(o); self.objs.append(o); self.next_id += 1; self.selection = o["id"]
            self._turn_log.append("add %s %s" % (t, o["id"])); return "ok: created %s" % o["id"]
        if v == "addslide":
            self.slides[self.current]["objs"] = self.objs
            self.slides.append({"id": self._next_slide}); self._next_slide += 1
            self.current = len(self.slides) - 1; self.objs = []; self.selection = None
            self._turn_log.append("addslide"); return "ok: %d slides, showing %d" % (len(self.slides), self.showing())
        if v in ("nextslide", "prevslide"):
            step = 1 if v == "nextslide" else -1
            if not 0 <= self.current + step < len(self.slides): raise ValueError("no %s slide" % ("next" if step > 0 else "previous"))
            self.slides[self.current]["objs"] = self.objs
            self.current += step; self.selection = None
            self.objs = self.slides[self.current].pop("objs", [])
            self._turn_log.append(v); return "ok: showing %d" % self.showing()
        if not pos: raise ValueError("%s needs an object ID" % v)
        o = self.get(pos[0]); self.selection = o["id"]
        cx, cy = o["x"] + o["w"] / 2, o["y"] + o["h"] / 2
        if v == "scale":
            if len(pos) < 2: raise ValueError("scale ID FACTOR")
            f = float(pos[1].rstrip("x%")) / (100 if pos[1].endswith("%") else 1)
            if not 0.05 <= f <= 10: raise ValueError("FACTOR is a multiplier like 1.25 or 0.8")
            o["w"] *= f; o["h"] *= f; o["x"], o["y"] = cx - o["w"] / 2, cy - o["h"] / 2
        elif v == "resize":
            o["w"] = num("w", o["w"]); o["h"] = num("h", o["h"]); o["x"], o["y"] = cx - o["w"] / 2, cy - o["h"] / 2
        elif v == "move":
            if "at" in kv: self._anchor(o, kv["at"])
            elif "x" in kv or "y" in kv: o["x"] = num("x", o["x"]); o["y"] = num("y", o["y"])
            else: raise ValueError("move ID at=ANCHOR or move ID x=PT y=PT")
        elif v == "nudge":
            o["x"] += num("dx", 0); o["y"] += num("dy", 0)
        elif v == "fill":
            c = pos[1] if len(pos) > 1 else kv.get("color", kv.get("fill"))   # tolerant: fill s1 fill=red
            if not c: raise ValueError("fill ID COLOR")
            o["fill"] = color_hex(c)
        elif v == "settext":
            if len(pos) < 2: raise ValueError('settext ID "new text"')
            o["text"] = pos[1]
        elif v == "delete":
            self.objs.remove(o); self.selection = None
        else:
            raise ValueError("unknown action %s. %s" % (v, "valid: add scale resize move nudge fill settext delete addslide nextslide prevslide undo done"))
        if v != "delete": self._clamp(o)
        self._turn_log.append(cmd); return "ok: %s %s -> x=%d y=%d w=%d h=%d" % (v, o["id"], o["x"], o["y"], o["w"], o["h"]) if v != "delete" else "ok: deleted %s" % o["id"]

    # ---- path to the real app ----
    def to_onlyoffice_js(self):
        """Office JS (Presentation API) that rebuilds the current slide; runs via a plugin's
        Asc.plugin.callCommand (Community Edition) or connector.callCommand (Developer Edition)."""
        geo = {"rect": "rect", "ellipse": "ellipse", "triangle": "triangle", "textbox": "rect"}
        out = ["var s = Api.GetPresentation().GetSlideByIndex(0); s.RemoveAllObjects();"]
        for o in self.objs:
            r, g, b = (int(o["fill"][i:i + 2], 16) for i in (1, 3, 5))
            fill = "Api.CreateNoFill()" if o["type"] == "textbox" else "Api.CreateSolidFill(Api.CreateRGBColor(%d,%d,%d))" % (r, g, b)
            out.append('var o = Api.CreateShape("%s", %d, %d, %s, Api.CreateStroke(0, Api.CreateNoFill())); o.SetPosition(%d, %d);'
                       % (geo[o["type"]], o["w"] * 12700, o["h"] * 12700, fill, o["x"] * 12700, o["y"] * 12700))
            if o["text"]:
                out.append('var p = Api.CreateParagraph(); p.AddText(%r); o.GetDocContent().Push(p);' % o["text"])
            out.append("s.AddObject(o);")
        return "\n".join(out)

if __name__ == "__main__":
    a = SlideApp()
    for req, cmds in [("Draw a red box about 1/3 of the page", ["add rect fill=red size=0.33"]),
                      ("now make it bigger", ["scale s1 1.25"]), ("move it to the bottom", ["move s1 at=bottom"])]:
        a.begin_request(req)
        for c in cmds: print(c, "->", a.do(c))
        a.end_request()
    print(a.state()); a.begin_request("undo"); print(a.do("undo")); a.end_request(); print(a.state()); print(a.to_onlyoffice_js())
