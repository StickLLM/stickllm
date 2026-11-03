"""StickLLM's own browser apps for the app agent (0.5.6, MIT).

Notepad, Calculator, Solitaire, Tetris, Minesweeper, and Media run in the user's browser.
The Browser skill opens Chromium on the stick screen; the chat page runs those actions
through stickllm-control (browser_open / browser_status / browser_window).

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


_RANKS = "A23456789TJQK"
_RED = set("HD")


def _pile_cards(text):
    text = (text or "").strip()
    if not text or text == "-":
        return []
    out = []
    for tok in text.split():
        if tok and set(tok) <= {"#"}:
            out.extend("#" * len(tok))
        else:
            card = tok.upper().replace("10", "T")
            if re.fullmatch(r"[A2-9TJQK][SHDC]", card):
                out.append(card)
    return out


def _solitaire_legal(piles, src, dst, card):
    """Klondike check. Returns (ok, error). Empty destination piles may be missing from STATE."""
    if src in ("stock",) or dst in ("stock", "waste") or src == dst:
        return False, "ERROR: move from waste or a tableau pile onto a foundation or a tableau pile"
    src_cards = _pile_cards(piles.get(src, ""))
    face = [c for c in src_cards if c != "#"]
    if not face:
        return False, "ERROR: %s has no face-up card" % src
    if card:
        if card not in face:
            return False, "ERROR: %s is not face up on %s" % (card, src)
        moving = face[face.index(card):]
    else:
        moving = [face[-1]]
    bottom = moving[0]
    dest_top = ""
    for c in _pile_cards(piles.get(dst, "")):
        if c != "#":
            dest_top = c
    if dst.startswith("f"):
        if len(moving) != 1:
            return False, "ERROR: only one card can go to a foundation"
        if not dest_top:
            if bottom[0] != "A":
                return False, "ERROR: only an ace starts an empty foundation, %s is not an ace" % bottom
        elif bottom[1] != dest_top[1] or _RANKS.index(bottom[0]) != _RANKS.index(dest_top[0]) + 1:
            return False, "ERROR: %s does not follow %s (same suit, next rank up)" % (bottom, dest_top)
        return True, ""
    if dst.startswith("t"):
        if not dest_top:
            if bottom[0] != "K":
                return False, "ERROR: only a king goes on an empty tableau pile, %s is not a king" % bottom
        elif (bottom[1] in _RED) == (dest_top[1] in _RED) or _RANKS.index(bottom[0]) != _RANKS.index(dest_top[0]) - 1:
            return False, "ERROR: %s cannot sit on %s (next rank down, other colour)" % (bottom, dest_top)
        return True, ""
    return False, "ERROR: bad pile %s" % dst


class SolitaireApp(ClientApp):
    name = "solitaire"; description = "Solitaire (StickLLM's card game, in your browser)"
    verbs = ["move", "draw", "newgame"]
    PILES = {"waste", "f1", "f2", "f3", "f4", "t1", "t2", "t3", "t4", "t5", "t6", "t7"}
    ACTIONS = """actions (one per line). Piles: waste f1-f4 (foundations) t1-t7 (tableau). Cards: rank A 2-9 T J Q K + suit S H D C.
  move FROM->TO [CARD]   move the top card, or the face-up CARD and the cards on it. Refused when the move is illegal.
  draw                   turn over the next stock card
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
        if v == "move" and len(tk) in (2, 3):
            m = re.fullmatch(r"(\w+)->(\w+)", tk[1].lower())
            if not m or m.group(1) not in self.PILES or m.group(2) not in self.PILES or m.group(1) == m.group(2):
                return False, "ERROR: use move FROM->TO with piles waste f1-f4 t1-t7"
            piles = self.client_state.get("piles") or {}
            if not piles:
                return False, "ERROR: no board yet (is Solitaire open?)"
            card = ""
            if len(tk) == 3:
                card = tk[2].upper().replace("10", "T")
                if not re.fullmatch(r"[A2-9TJQK][SHDC]", card):
                    return False, "ERROR: bad card %s" % tk[2]
            ok, err = _solitaire_legal(piles, m.group(1), m.group(2), card)
            if not ok:
                return False, err
            a = {"move": "%s->%s" % (m.group(1), m.group(2))}
            if card:
                a["card"] = card
            self.actions.append(a); return True, "OK"
        return False, "ERROR: unknown or malformed action %r" % line
    def undo(self):
        self.actions.append({"undo": True}); return True, "OK the game's Undo is pressed in the app window"


class TetrisApp(ClientApp):
    name = "tetris"; description = "Tetris (StickLLM's falling-block game, in your browser)"
    verbs = ["start", "newgame", "pause", "resume", "left", "right", "rotate", "softdrop", "harddrop", "place"]
    ACTIONS = """actions (one per line):
  start                  begin a game when status is ready
  newgame                deal a new game
  pause                  stop gravity
  resume                 continue
  left [N]               move left N squares (default 1)
  right [N]              move right N squares
  rotate [N]             turn the piece N times
  softdrop [N]           drop one row N times
  harddrop               drop the piece to the stack
  place COL ROT          drop so the leftmost block is in column COL after rotation ROT (0-3)
  place suggested        drop on the suggested col and rot printed in STATE
  done                   finish this request"""
    def state(self):
        st = self.client_state
        if not st or st.get("status") in (None, "", "loading"):
            return "TETRIS: no state (is the game open?)"
        lines = ["TETRIS status=%s mode=%s score=%s lines=%s next=%s" % (
            st.get("status", ""), st.get("mode", ""), st.get("score", ""), st.get("lines", ""), st.get("next", ""))]
        cur = st.get("current") or {}
        if cur:
            lines.append("piece %s rot=%s col=%s" % (cur.get("type", ""), cur.get("rot", ""), cur.get("col", "")))
        sug = (st.get("suggest") or {}).get("place") or {}
        if sug:
            lines.append("suggested place col=%s rot=%s" % (sug.get("col", ""), sug.get("rot", "")))
        view = st.get("view") or st.get("board") or []
        if view:
            lines.append("BOARD top to bottom, columns 0-9, # settled, @ falling:")
            lines.extend(str(row) for row in view[:22])
        return "\n".join(lines)
    def _n(self, tk):
        if len(tk) == 1:
            return 1
        if len(tk) == 2 and tk[1].isdigit() and 1 <= int(tk[1]) <= 20:
            return int(tk[1])
        return 0
    def do(self, line):
        tk = _toks(line.strip()); v = tk[0].lower() if tk else ""
        if v == "start" and len(tk) == 1: self.actions.append({"start": True}); return True, "OK"
        if v == "newgame" and len(tk) == 1: self.actions.append({"new_game": True}); return True, "OK"
        if v == "pause" and len(tk) == 1: self.actions.append({"pause": True}); return True, "OK"
        if v == "resume" and len(tk) == 1: self.actions.append({"resume": True}); return True, "OK"
        if v in ("left", "right", "rotate", "softdrop"):
            n = self._n(tk)
            if not n: return False, "ERROR: %s takes an optional count from 1 to 20" % v
            key = {"softdrop": "soft_drop"}.get(v, v)
            self.actions.append({key: n}); return True, "OK"
        if v == "harddrop" and len(tk) == 1: self.actions.append({"hard_drop": True}); return True, "OK"
        if v == "place" and len(tk) == 2 and tk[1].lower() == "suggested":
            self.actions.append({"place": "suggested"}); return True, "OK"
        if v == "place" and len(tk) == 3 and tk[1].isdigit() and tk[2].isdigit():
            col, rot = int(tk[1]), int(tk[2])
            if not (0 <= col <= 9 and 0 <= rot <= 3):
                return False, "ERROR: place COL ROT uses column 0-9 and rotation 0-3"
            self.actions.append({"place": {"col": col, "rot": rot}}); return True, "OK"
        return False, "ERROR: unknown or malformed action %r" % line


class MinesweeperApp(ClientApp):
    name = "minesweeper"; description = "Minesweeper (StickLLM's board, in your browser)"
    verbs = ["reveal", "flag"]
    ACTIONS = """actions (one per line). Row 0 is the top. Column 0 is the left.
  reveal ROW COL    open that covered square
  flag ROW COL      mark or unmark that covered square as a mine
  done              finish this request"""
    def state(self):
        grid = str(self.client_state.get("grid") or "")
        if not grid.strip():
            return "MINESWEEPER: no state (is the game open?)"
        rows = grid.split("\n")
        width = max(len(r) for r in rows)
        return ("MINESWEEPER %d rows, %d columns. # covered, F flag, digit = mines beside an open square, * exploded mine.\n%s"
                % (len(rows), width, grid))
    def _cell(self, tk):
        if len(tk) != 3 or not tk[1].isdigit() or not tk[2].isdigit():
            return None
        return int(tk[1]), int(tk[2])
    def _on_board(self, row, col):
        grid = str(self.client_state.get("grid") or "")
        if not grid.strip():
            return False, "ERROR: no board yet (is Minesweeper open?)"
        rows = grid.split("\n")
        if row < 0 or row >= len(rows) or col < 0 or col >= len(rows[row]):
            return False, "ERROR: row %d column %d is off the board" % (row, col)
        return True, rows[row][col]
    def do(self, line):
        tk = _toks(line.strip()); v = tk[0].lower() if tk else ""
        cell = self._cell(tk)
        if v in ("reveal", "flag") and cell:
            ok, got = self._on_board(*cell)
            if not ok:
                return False, got
            if v == "reveal" and got == "F":
                return False, "ERROR: that square is flagged; do not reveal it"
            if v == "reveal" and got not in ("#", "F"):
                return False, "ERROR: that square is already open"
            if v == "flag" and got not in ("#", "F"):
                return False, "ERROR: only a covered square can be flagged"
            self.actions.append({v: [cell[0], cell[1]]}); return True, "OK"
        return False, "ERROR: unknown or malformed action %r" % line


class MediaApp(ClientApp):
    name = "media"; description = "Media: pictures, audio, and video in a folder"
    verbs = ["open", "up", "root", "play", "pause"]
    ACTIONS = """actions (one per line):
  open "NAME"    open a file or folder whose name is in STATE
  up             parent folder
  root "ID"      switch to a folder root id printed in STATE
  play           play the audio or video already on stage
  pause          pause it
  done           finish this request"""
    def state(self):
        st = self.client_state
        if not st:
            return "MEDIA: no state (is Media open?)"
        entries = st.get("entries") or []
        names = ", ".join(("%s/" % e.get("name") if e.get("dir") else str(e.get("name"))) for e in entries[:40])
        return "MEDIA root=%s path=%s file=%s kind=%s paused=%s\nHERE: %s" % (
            st.get("root", ""), st.get("path", ""), st.get("file", ""), st.get("kind", ""),
            st.get("paused", ""), names or "(empty)")
    def do(self, line):
        tk = _toks(line.strip()); v = tk[0].lower() if tk else ""
        if v == "up" and len(tk) == 1: self.actions.append({"up": True}); return True, "OK"
        if v == "play" and len(tk) == 1:
            if self.client_state.get("kind") not in ("audio", "video"):
                return False, "ERROR: nothing to play (open an audio or video file first)"
            self.actions.append({"play": True}); return True, "OK"
        if v == "pause" and len(tk) == 1:
            if self.client_state.get("kind") not in ("audio", "video"):
                return False, "ERROR: nothing to pause"
            self.actions.append({"pause": True}); return True, "OK"
        if v == "root" and len(tk) == 2:
            self.actions.append({"root": tk[1]}); return True, "OK"
        if v == "open" and len(tk) >= 2:
            name = " ".join(tk[1:])
            entries = self.client_state.get("entries") or []
            if entries and not any(str(e.get("name")) == name for e in entries):
                return False, "ERROR: %r is not in this folder" % name
            self.actions.append({"open": name}); return True, "OK"
        return False, "ERROR: unknown or malformed action %r" % line


class BrowserApp(ClientApp):
    name = "browser"; description = "Browser: Chromium windows on the stick screen"
    verbs = ["open", "page", "focus", "close", "minimise", "restore", "maximise"]
    ACTIONS = """actions (one per line). Windows in STATE have an id.
  open "https://SITE"          open that http or https page
  page TITLE ||| HTML          write an HTML document and open it in the browser. HTML may contain quotes. Use \\n for a new line. One page, at most 64 KB. An unlocked vault also keeps a copy in vault/Programs.
  focus ID                     bring that window to the front
  close ID                     close that window (the only window's id may be omitted)
  minimise ID                  hide that window
  restore ID                   show it again
  maximise ID                  fill the screen
  undo                         close the only open window
  done                         finish this request"""
    def state(self):
        wins = self.client_state.get("windows") or []
        if not wins:
            return "BROWSER: no windows open."
        lines = ["BROWSER %d window(s):" % len(wins)]
        for w in wins[:12]:
            lines.append("id=%s title=%s url=%s" % (w.get("id", ""), w.get("page_title") or w.get("title") or "", w.get("url", "")))
        return "\n".join(lines)
    def _url(self, raw):
        u = raw.strip()
        if not re.match(r"https?://", u, re.I):
            if re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/\S*)?", u):
                u = "https://" + u
            else:
                return ""
        if len(u) > 2000 or re.search(r"[\s<>\"']", u):
            return ""
        if not re.match(r"https?://[A-Za-z0-9.-]+", u, re.I):
            return ""
        return u
    def _id(self, token):
        wins = self.client_state.get("windows") or []
        if not token:
            return wins[0].get("id", "") if len(wins) == 1 else ""
        for w in wins:
            if str(w.get("id") or "") == token:
                return token
        low = token.lower()
        hits = [w for w in wins if low in str(w.get("title") or "").lower()
                or low in str(w.get("page_title") or "").lower() or low in str(w.get("url") or "").lower()]
        if len(hits) == 1:
            return str(hits[0].get("id") or "")
        if not wins and re.fullmatch(r"[0-9a-f]{8,16}", token):
            return token
        return ""
    def _window(self, v, tk):
        token = tk[1] if len(tk) == 2 else ""
        if len(tk) > 2:
            return False, "ERROR: %s takes one window id" % v
        bid = self._id(token)
        if not bid:
            return False, "ERROR: name the window (several are open)" if (self.client_state.get("windows") or []) else "ERROR: no browser window is open"
        key = "op" if v in ("minimise", "restore", "maximise") else v
        if key == "op":
            self.actions.append({"id": bid, "op": v})
        else:
            self.actions.append({v: bid})
        return True, "OK"
    def do(self, line):
        tk = _toks(line.strip()); v = tk[0].lower() if tk else ""
        if v == "undo" and len(tk) == 1:
            return self.undo()
        if v == "open" and len(tk) >= 2:
            url = self._url(" ".join(tk[1:]))
            if not url:
                return False, "ERROR: open needs an http or https address"
            self.actions.append({"open": url, "title": "Browser"})
            return True, "OK"
        if v == "page":
            return self._page(line)
        if v in ("focus", "close", "minimise", "restore", "maximise"):
            return self._window(v, tk)
        return False, "ERROR: unknown or malformed action %r" % line
    def _page(self, line):
        rest = line.strip()[4:].strip()
        if "|||" in rest:
            title, html = rest.split("|||", 1)
        else:
            tk = _toks(line.strip())
            if len(tk) < 3:
                return False, "ERROR: page TITLE ||| HTML"
            title, html = tk[1], " ".join(tk[2:])
        title = re.sub(r"[\x00-\x1f\x7f]", "", title).strip().strip('"')[:80] or "Page"
        html = html.strip().replace("\\n", "\n").replace("\\t", "\t")
        if not html:
            return False, "ERROR: the page has no HTML"
        if len(html.encode("utf-8")) > 65536:
            return False, "ERROR: that page is over 64 KB"
        self.actions.append({"page": {"title": title, "html": html}})
        return True, "OK page %s" % title
    def undo(self):
        wins = self.client_state.get("windows") or []
        if len(wins) != 1 or not wins[0].get("id"):
            return False, "ERROR: say which browser window to close"
        self.actions.append({"close": wins[0]["id"]})
        return True, "OK closing the browser window"


CLIENT_APPS = {
    "notepad": NotepadApp, "calculator": CalculatorApp, "solitaire": SolitaireApp,
    "tetris": TetrisApp, "minesweeper": MinesweeperApp, "media": MediaApp, "browser": BrowserApp,
}
