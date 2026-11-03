"""StickLLM's own browser apps (Notepad, Calculator, Solitaire) for the app agent (0.5.6, MIT).

These apps run in the user's browser, not on the stick, so the service cannot touch them.
The chat page reads the app's state over the same-origin BroadcastChannel "stickllm-appbridge"
(ui/apps/stickllm-bridge.js), sends it with the request, and the service answers with
`client_actions`: the window.stickllmApp.act() calls the chat page then runs in that app window.
do() checks each action line against the client state (Notepad text is simulated exactly), so the
frozen plan checker and the repair step work as for the other apps. Undo is done by the chat page
(Notepad: put the previous text back; Solitaire: the game's own Undo button)."""
import json, re, shlex
from . import manual

CALC_KEYS = set("0123456789.+-*/%=") | {"C", "±", "⌫"}


def _toks(line):
    try: return shlex.split(line)
    except ValueError: return line.split()


class ClientApp:
    """base: state comes from the client; do() records client actions"""
    name = ""; verbs = []; ACTIONS = ""
    def __init__(self, start=None):
        self.client_state = start if isinstance(start, dict) else {}
        self.actions = []; self.done_actions = []
    @property
    def manual(self): return manual("MANUAL_%s.md" % self.name)
    def set_client_state(self, st):
        self.client_state = st if isinstance(st, dict) else {}
    def list_actions(self): return self.ACTIONS
    def ids(self): return []
    def begin_request(self, text): self.actions = []
    def end_request(self): self.done_actions = list(self.actions)
    def export(self): return {"client_actions": list(self.actions)}
    def reset(self, start=None): self.__init__(start)
    def undo(self): return False, "ERROR: undo for %s runs in the app window (the chat page does it)" % self.name
    def state(self): return json.dumps(self.client_state, ensure_ascii=False)[:4000]


class NotepadApp(ClientApp):
    name = "notepad"; description = "Notepad (StickLLM's text editor app, in your browser)"
    verbs = ["settext", "append", "replace", "clear", "saveas"]
    ACTIONS = """actions (one per line; quote text that contains spaces; \\n in text = new line):
  settext "TEXT"          replace the whole document with TEXT
  append "TEXT"           add TEXT at the end (starts a new line when the document is not empty)
  replace "OLD" "NEW"     replace every OLD with NEW
  clear                   empty the document
  saveas                  open Notepad's Save As dialog (the user picks the file name)
  undo                    put back the text from before the previous request
  done                    finish this request"""
    def __init__(self, start=None):
        super().__init__(start); self.hist = []; self._before = ""
    def text(self): return str(self.client_state.get("text") or "")
    def begin_request(self, text): self.actions = []; self._before = self.text()
    def end_request(self):
        if any("set_text" in a for a in self.actions) and not getattr(self, "_undoing", False): self.hist.append(self._before)
        self._undoing = False; self.done_actions = list(self.actions)
    def undo(self):
        if not self.hist: return False, "ERROR: nothing to undo"
        t = self.hist.pop(); self._undoing = True
        self.client_state = dict(self.client_state, text=t); self.actions.append({"set_text": t})
        return True, "OK text from before the previous request is back"
    def state(self):
        t = self.text()
        lines = t.split("\n")
        head = "NOTEPAD document: %d characters, %d lines." % (len(t), len(lines) if t else 0)
        shown = t if len(t) <= 3000 else t[:1500] + "\n[...]\n" + t[-1400:]
        return head + "\nTEXT:\n" + (shown or "(empty)")
    def _set(self, t):
        self.client_state = dict(self.client_state, text=t)
        self.actions.append({"set_text": t})
    def do(self, line):
        tk = _toks(line.strip()); v = tk[0].lower() if tk else ""
        if v == "undo" and len(tk) == 1: return self.undo()
        unq = lambda s: s.replace("\\n", "\n")
        if v == "settext" and len(tk) >= 2: self._set(unq(" ".join(tk[1:]))); return True, "OK text set"
        if v == "append" and len(tk) >= 2:
            t = self.text(); add = unq(" ".join(tk[1:]))
            self._set(t + ("\n" if t and not t.endswith("\n") else "") + add); return True, "OK appended"
        if v == "replace" and len(tk) == 3:
            t = self.text(); old, new = unq(tk[1]), unq(tk[2])
            if not old or old not in t: return False, "ERROR: %r is not in the document" % old
            self._set(t.replace(old, new)); return True, "OK replaced %d" % t.count(old)
        if v == "clear" and len(tk) == 1: self._set(""); return True, "OK cleared"
        if v == "saveas" and len(tk) == 1: self.actions.append({"save_as": True}); return True, "OK Save As opened"
        return False, "ERROR: unknown or malformed action %r" % line


class CalculatorApp(ClientApp):
    name = "calculator"; description = "Calculator (StickLLM's calculator app, in your browser)"
    verbs = ["keys", "clear"]
    ACTIONS = """actions (one per line):
  keys "SEQUENCE"   press calculator keys in order. Keys: 0-9 . + - * / % = C ± ⌫  (C clears, ⌫ deletes one digit)
                    e.g. keys "C12*7=" computes 12 x 7. Use * for times and / for divided by.
  clear             press C
  done              finish this request"""
    def state(self): return "CALCULATOR display: %s" % (self.client_state.get("display") or "0")
    def do(self, line):
        tk = _toks(line.strip()); v = tk[0].lower() if tk else ""
        if v == "clear" and len(tk) == 1: self.actions.append({"expr": "C"}); return True, "OK cleared"
        if v == "keys" and len(tk) >= 2:
            seq = "".join(tk[1:]).replace("x", "*").replace("×", "*").replace("÷", "/").replace(" ", "")
            bad = [c for c in seq if c not in CALC_KEYS]
            if not seq or bad: return False, "ERROR: not calculator keys: %s" % "".join(bad)
            self.actions.append({"expr": seq}); return True, "OK pressed %s" % seq
        return False, "ERROR: unknown or malformed action %r" % line


class SolitaireApp(ClientApp):
    name = "solitaire"; description = "Solitaire (StickLLM's card game, in your browser)"
    verbs = ["move", "draw", "click", "newgame"]
    PILES = {"waste", "f1", "f2", "f3", "f4", "t1", "t2", "t3", "t4", "t5", "t6", "t7"}
    ACTIONS = """actions (one per line). Piles: stock waste f1-f4 (foundations) t1-t7 (tableau). Cards: rank A 2-9 T J Q K + suit S H D C.
  move FROM->TO [CARD]   move the top card (or the face-up CARD and the cards on it) e.g. move t3->f1, move t2->t5 9H
  draw                   turn over the next stock card
  click PILE             click the top card of a pile (auto-moves it when the game allows)
  newgame                deal a new game
  undo                   the game's Undo button
  done                   finish this request"""
    def state(self):
        st = self.client_state; piles = st.get("piles") or {}
        if not piles: return "SOLITAIRE: no state (is the game open?)"
        lines = ["SOLITAIRE score=%s stock=%s%s" % (st.get("score", ""), st.get("stock_count", "?"), " WON" if st.get("won") else "")]
        lines += ["%s: %s" % (k, piles[k]) for k in ["waste", "f1", "f2", "f3", "f4", "t1", "t2", "t3", "t4", "t5", "t6", "t7"] if k in piles]
        return "\n".join(lines) + "\nTop card is last. # = face down."
    def do(self, line):
        tk = _toks(line.strip()); v = tk[0].lower() if tk else ""
        if v == "undo" and len(tk) == 1: self.actions.append({"undo": True}); return True, "OK"
        if v == "draw" and len(tk) == 1: self.actions.append({"draw": True}); return True, "OK"
        if v == "newgame" and len(tk) == 1: self.actions.append({"new_game": True}); return True, "OK"
        if v == "click" and len(tk) == 2 and tk[1].lower() in self.PILES: self.actions.append({"click": tk[1].lower()}); return True, "OK"
        if v == "move" and len(tk) in (2, 3):
            m = re.fullmatch(r"(\w+)->(\w+)", tk[1].lower())
            if not m or m.group(1) not in self.PILES or m.group(2) not in self.PILES or m.group(1) == m.group(2):
                return False, "ERROR: use move FROM->TO with piles waste f1-f4 t1-t7"
            a = {"move": "%s->%s" % (m.group(1), m.group(2))}
            if len(tk) == 3:
                c = tk[2].upper().replace("10", "T")
                if not re.fullmatch(r"[A2-9TJQK][SHDC]", c): return False, "ERROR: bad card %s" % tk[2]
                a["card"] = c
            self.actions.append(a); return True, "OK"
        return False, "ERROR: unknown or malformed action %r" % line
    def undo(self):
        self.actions.append({"undo": True}); return True, "OK the game's Undo is pressed in the app window"


CLIENT_APPS = {"notepad": NotepadApp, "calculator": CalculatorApp, "solitaire": SolitaireApp}
