"""Adapter interface (duck-typed):
  name, manual, verbs, description
  state() -> text   list_actions() -> text   do(line) -> (ok, msg)   undo() -> (ok, msg)
  begin_request(text) / end_request()      one user request = one undo step
optional, used by the frozen plan checker: ids(), simulate(plan) -> ([(ok,msg)], sim), edges()
test hooks: reset(start), export() -> JSON-able snapshot (objs / flows)"""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
def manual(name): return open(os.path.join(HERE, "..", "manuals", name)).read()


def slide_index(verbs):
    """Stickman slide retrieval pack (packs/slides-working-slice.json) limited to the capabilities whose
    actions this adapter runs. Returns a retrieval.ManualIndex or None when the pack is missing or invalid."""
    import json, sys
    root = os.path.join(HERE, "..")
    if root not in sys.path: sys.path.insert(0, root)
    try:
        from retrieval import ManualIndex
        pack = json.load(open(os.path.join(root, "packs", "slides-working-slice.json"), encoding="utf-8"))
        contract = list(verbs) + ["undo", "done"]
        pack = dict(pack, capabilities=[c for c in pack["capabilities"] if set(c["actions"]) <= set(contract)
                                        and all(r in [x["id"] for x in pack["capabilities"]] for r in c["requires"])])
        return ManualIndex(pack, contract)
    except Exception:
        return None
