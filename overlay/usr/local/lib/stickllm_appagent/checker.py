"""Deterministic PLAN CHECKER: runs between the INTENT step and execution.
Inputs are only things every app has under the universal API (state / list_actions / do / undo) plus three optional extras:
  app.ids()            ids of existing objects
  app.simulate(plan)   dry-run on a copy -> ([(ok, msg)], sim_app)
  app.edges()          (graph apps only) set of (from, to) wires
plus the app MANUAL (reference-rule phrases are read from it) and the harness's own turn log.
No scenario text is used. Each check returns a complaint string that is fed back to the intent model once."""
import re, shlex

# app-independent conversational cues. The manual's "Which object?" rules add their own quoted phrases (see from_manual).
DEFAULT_CUES = {
    "undo":    ["undo", "go back", "never mind", "nevermind", "revert", "scratch that"],
    "correct": ["the other one", "i meant", "not that one", "wrong one"],
    "instead": ["instead"],
    "same":    ["actually", "no,", "rather"],
    "other":   ["other one", "the other"],
    "remove":  ["delete", "remove", "get rid", "clear", "erase", "drop", "take away", "take out"],
    "new":     ["another", "one more", "a second", "new ", "also add", "add a", "add an"],
}

def norm(s): return " " + re.sub(r"[^a-z0-9,' ]+", " ", s.lower()).replace(",", " , ").strip() + " "

def phrase_in(req, ph):
    p = norm(ph).strip().replace(" ,", ",").replace(", ", ",").rstrip(",")
    r = norm(req).replace(" ,", ",").replace(", ", ",")
    p = re.sub(r"\b(x|\.\.\.|…)$", "", p).strip()
    return bool(p) and re.search(r"(^|[ ,])" + re.escape(p) + r"([ ,]|$)", r) is not None

def from_manual(manual):
    """read cue phrases from the manual's reference rules: a rule line whose action contains `undo` and 'redo'/'right object'
    is a correction rule, `undo` alone an undo rule, 'instead' an instead rule, 'never add' a change-the-same-object rule."""
    cues = {k: list(v) for k, v in DEFAULT_CUES.items()}; got = []
    for line in manual.splitlines():
        if not re.match(r"\s*\d+\.\s", line): continue
        quoted = [q for q in re.findall(r'"([^"]+)"', line)]
        if not quoted: continue
        l = line.lower()
        if "`undo`" in l and ("redo" in l or "right object" in l or "wrong object" in l): k = "correct"
        elif "`undo`" in l: k = "undo"
        elif "never add" in l or "same node" in l: k = "same"
        elif "instead" in l: k = "instead"
        else: continue
        for q in quoted:
            q = re.sub(r"\s*(x|\.\.\.|…)\s*$", "", q.strip().lower()).strip()
            if q and q not in cues[k] and q not in ("instead",):
                cues[k].append(q); got.append((k, q))
    return cues, got

def toks(cmd):
    try: return shlex.split(cmd)
    except ValueError: return cmd.split()

def verb(cmd): t = toks(cmd); return t[0].lower() if t else ""
def kvs(cmd): return {k.lower(): v for k, _, v in (t.partition("=") for t in toks(cmd)[1:] if "=" in t)}
def positionals(cmd): return [t for t in toks(cmd)[1:] if "=" not in t]

def targets(cmd, ids):
    """existing-object ids a command acts on (port suffix a:1 stripped). The first one is the primary target."""
    return [t.split(":")[0] for t in positionals(cmd) if t.split(":")[0] in ids]

class Turn:
    def __init__(self, req, cmds, outs, ids_after):
        self.req = req; self.cmds = cmds; self.undone = False
        created = [m for o in outs for m in re.findall(r"created (\w+)", o)]
        self.touched = []
        for c in cmds:
            if verb(c) == "undo": continue
            for t in positionals(c):
                t = t.split(":")[0]
                if (t in ids_after or t in created) and t not in self.touched: self.touched.append(t)
        for c in created:
            if c not in self.touched: self.touched.append(c)
    @property
    def is_undo(self): return bool(self.cmds) and all(verb(c) == "undo" for c in self.cmds)

class TurnLog:
    """harness-side log of what each earlier request actually executed (independent of the app)"""
    def __init__(self): self.turns = []
    def add(self, req, exec_log, app):
        ok = [e for e in exec_log if e.get("cmd") and e.get("ok")]
        t = Turn(req, [e["cmd"] for e in ok], [e.get("out", "") for e in ok], set(app.ids()))
        n_undo = sum(1 for c in t.cmds if verb(c) == "undo")
        for prev in reversed(self.turns):        # each undo reverts the latest request that is still in effect
            if n_undo == 0: break
            if not prev.undone and not prev.is_undo and prev.cmds: prev.undone = True; n_undo -= 1
        self.turns.append(t)
    def last(self): return self.turns[-1] if self.turns else None
    def last_effective(self):
        return next((t for t in reversed(self.turns) if not t.undone and not t.is_undo and t.touched), None)
    def last_undone(self):
        return next((t for t in reversed(self.turns) if t.undone), None)

class PlanChecker:
    def __init__(self, manual, verbs):
        self.cues, self.manual_cues = from_manual(manual); self.verbs = set(verbs) | {"undo"}
    def has(self, req, kind): return any(phrase_in(req, p) for p in self.cues[kind])

    def check(self, app, plan, req, log):
        """returns a list of complaint strings (empty = plan accepted)"""
        out = []; ids = set(app.ids()); last = log.last(); eff = log.last_effective()
        is_undo_req = self.has(req, "undo"); is_correct = self.has(req, "correct")
        is_instead = self.has(req, "instead"); is_same = self.has(req, "same") and not is_correct
        undos = [i for i, c in enumerate(plan) if verb(c) == "undo"]
        work = [c for c in plan if verb(c) != "undo"]
        # 1. syntax / ids / verbs: every line must be a known verb and succeed in a dry run
        if not plan and not self.has(req, "undo"):
            out.append("The plan is empty, but the request asks for a change.")
        for c in plan:
            if verb(c) not in self.verbs:
                out.append("`%s`: unknown action '%s'. Valid actions: %s." % (c, verb(c), ", ".join(sorted(self.verbs)))); break
        sim = None
        if hasattr(app, "simulate") and not out:
            res, sim = app.simulate(plan)
            for c, (ok, msg) in zip(plan, res):
                if not ok:
                    out.append("Step `%s` fails on the current state: %s" % (c, msg.replace("ERROR: ", ""))); break
        # 2. undo must be requested (an undo request, a correction, or 'instead' after a change that must not stay)
        if undos and not (is_undo_req or is_correct or is_instead):
            out.append("The plan contains `undo`, but the user did not ask to undo or correct anything. `undo` reverts the whole previous request. Remove it.")
        elif undos and last is not None and last.is_undo and not is_undo_req:
            out.append("The previous request was already an undo (it reverted \"%s\"). Another `undo` would also revert the request before that. Remove `undo`." %
                       (log.last_undone().req if log.last_undone() else "the request before"))
        if is_undo_req and not is_correct and not is_instead and not undos and not work:
            out.append("The user asked to undo: the plan should be `undo`.")
        # 2b. destructive steps (delete*) need a removal word in the request (undo is the way to take back a change)
        dels = [c for c in work if verb(c).startswith("delete")]
        if dels and not self.has(req, "remove"):
            own = [t.req for t in log.turns if not t.undone and set(targets(dels[0], ids)) & set(t.touched)]
            out.append("`%s` deletes %s%s, but the user did not ask to delete or remove anything. Keep it: remove the `%s` step." % (
                dels[0], ", ".join(targets(dels[0], ids)) or "something", (" (made by the earlier request \"%s\", which still stands)" % own[-1]) if own else "", verb(dels[0])))
        # 3. 'no, the other one' / 'I meant X': undo first, then the SAME change on a different object
        if is_correct and eff is not None and last is not None and not last.is_undo:
            prev_cmds = [c for c in last.cmds if verb(c) != "undo"]
            if not undos or undos[0] != 0:
                out.append("Correction request: the last request (\"%s\": %s) went to the wrong object. Start the plan with `undo`, then do the same change on the right object." % (last.req, "; ".join(prev_cmds)))
            if not work:
                out.append("The plan only undoes. After `undo`, redo the same change (%s) on the object the user means now." % "; ".join(prev_cmds))
            else:
                bad = [c for c in work if set(targets(c, ids)) & set(last.touched)]
                if bad: out.append("`%s` acts on %s again, the object of the last request. The user means a different object." % (bad[0], ", ".join(set(targets(bad[0], ids)) & set(last.touched))))
                pv = {verb(c) for c in prev_cmds}
                if pv and not ({verb(c) for c in work} & pv):
                    out.append("After the undo, repeat the same kind of change as before (%s) on the other object." % "; ".join(prev_cmds))
        # 4. 'the other one' anywhere: the target must differ from the last request's object
        elif self.has(req, "other") and eff is not None:
            bad = [c for c in work if set(targets(c, ids)) & set(eff.touched) and verb(c) != "add"]
            if bad: out.append("\"the other one\" means NOT %s (the object of the last request), but `%s` changes it." % (", ".join(eff.touched), bad[0]))
        # 5. pronoun 'it': the plan should act on the object of the most recent request (if that object still exists)
        if not is_correct and not self.has(req, "other") and re.search(r"\bit\b", req.lower()) and eff is not None:
            exp = [t for t in eff.touched if t in ids]
            prim = [targets(c, ids)[0] for c in work if targets(c, ids) and verb(c) != "add"]
            if exp and prim and not (set(prim) & set(exp)):
                out.append("\"it\" refers to %s (the object of the last request \"%s\"), but the plan changes %s." % (", ".join(exp), eff.req, ", ".join(dict.fromkeys(prim))))
        # 6. 'instead' / 'actually' right after an undo: redo the undone request with only the requested change
        if (is_instead or is_same) and last is not None and last.is_undo and not is_undo_req:
            u = log.last_undone()
            if u is not None:
                gone = [t for t in u.touched if t not in ids]
                if gone and not any(verb(c) == "add" for c in work):
                    out.append("The object of \"%s\" was undone and no longer exists. Re-create it by repeating that request's actions (%s), changing only what the new request says." % (u.req, "; ".join(u.cmds)))
                for c in [c for c in u.cmds if verb(c) == "add"]:
                    cand = [p for p in work if verb(p) == "add"]
                    if not cand: break
                    old_pos = [t for t in positionals(c) if t not in ids and t not in u.touched]
                    best = max(cand, key=lambda p: len(set(positionals(p)) & set(old_pos)) + len(set(kvs(p).items()) & set(kvs(c).items())))
                    miss = []
                    for t in old_pos:
                        if t not in positionals(best) and not phrase_in(req, t) and t not in u.touched: miss.append(t)
                    for k, v in kvs(c).items():
                        nv = kvs(best).get(k)
                        if nv != v and not (nv and phrase_in(req, nv)): miss.append("%s=%s" % (k, v))
                    if miss:
                        out.append("The undone request did `%s`. Redo it with only the change the user asked for; `%s` drops or changes %s, which the user did not ask to change." % (c, best, " ".join(miss)))
                        break
                pv = [verb(c) for c in u.cmds if verb(c) != "undo"]
                missing = [v for v in dict.fromkeys(pv) if pv.count(v) > [verb(c) for c in work].count(v)]
                if gone and missing and not out:
                    out.append("The undone request did: %s. Redo all of it with the change; the plan is missing: %s." % ("; ".join(u.cmds), ", ".join(missing)))
        # 7. 'actually / no, / instead' right after a change: change the same object, do not add a second one
        elif (is_same or is_instead) and last is not None and not last.is_undo and eff is not None and not self.has(req, "new"):
            still = [t for t in eff.touched if t in ids]
            if still and any(verb(c) == "add" for c in work):
                out.append("\"%s\" corrects the last request (%s). Change the same object (%s) again; do not add a new one." % (req, "; ".join(last.cmds), ", ".join(still)))
        # 8. graph apps: 'between A and B' means A -> new -> B, with the direct A -> B wire removed
        if sim is not None and hasattr(app, "edges") and re.search(r"\bbetween\b", req.lower()):
            e0, e1 = app.edges(), sim.edges(); new = set(sim.ids()) - ids
            for n in new:
                ins = {a for a, b in e1 if b == n and a in ids}; outs = {b for a, b in e1 if a == n and b in ids}
                for a in ins:
                    for b in outs:
                        if (a, b) in e1: out.append("'between': %s is still wired straight to %s, so messages bypass %s. Add `unwire %s %s`." % (a, b, n, a, b))
                if ins and not outs:
                    nx = sorted(b for a2, b in e0 if a2 in ins)
                    if nx: out.append("'between': %s gets input from %s but sends nowhere. Wire it on to %s." % (n, ", ".join(ins), ", ".join(nx)))
                if outs and not ins:
                    pv = sorted(a for a, b2 in e0 if b2 in outs and a in ids)
                    if pv: out.append("'between': %s sends to %s but gets no input. Wire %s into it." % (n, ", ".join(outs), ", ".join(pv)))
        return list(dict.fromkeys(out))
