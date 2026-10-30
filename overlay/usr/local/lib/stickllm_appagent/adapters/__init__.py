"""Adapter interface (duck-typed):
  name, manual, verbs, description
  state() -> text   list_actions() -> text   do(line) -> (ok, msg)   undo() -> (ok, msg)
  begin_request(text) / end_request()      one user request = one undo step
optional, used by the frozen plan checker: ids(), simulate(plan) -> ([(ok,msg)], sim), edges()
test hooks: reset(start), export() -> JSON-able snapshot (objs / flows)"""
import os
HERE = os.path.dirname(os.path.abspath(__file__))
def manual(name): return open(os.path.join(HERE, "..", "manuals", name)).read()
