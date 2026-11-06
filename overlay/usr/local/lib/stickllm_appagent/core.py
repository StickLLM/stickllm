"""App-agent core: INTENT plan (json_schema, thinking off) -> frozen plan checker (one re-ask)
-> hybrid execution (harness runs plan lines; the LLM only repairs a failed line, max 2 tries, may skip).
Ported from agent-manuals/intent/agent.py (cond b + --check + --exec hybrid). checker.py is a verbatim copy."""
import json, re, time, urllib.error, urllib.request

class NoModel(RuntimeError):
    """the shared chat llama-server is not running (user has not loaded a model)"""

def chat(url, messages, think=False, temperature=0.0, grammar=None, schema=None, max_tokens=512, timeout=600):
    body = {"model": "x", "messages": messages, "temperature": temperature, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": think}, "cache_prompt": True}
    if grammar: body["grammar"] = grammar
    if schema: body["response_format"] = {"type": "json_schema", "json_schema": {"name": "plan", "schema": schema}}
    req = urllib.request.Request(url.rstrip("/") + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: d = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 503: raise NoModel("The model is still loading. Try again in a moment.")
        raise
    except (urllib.error.URLError, ConnectionError) as e:
        # 0.5.6: the app agent shares the chat model and never loads one itself
        raise NoModel("No model is loaded. Load one on the Models page (Qwen2.5-7B Q4_K_M is on the stick), then try again.")
    m = d["choices"][0]["message"]
    return (m.get("content") or ""), d.get("usage", {}), time.time() - t

def exec_grammar(verbs):
    alts = " | ".join('"%s"' % v for v in verbs)
    return 'root ::= (( %s ) (" " [^\\n]{1,200})?) | "undo" | "done" | "skip"\n' % alts

PLAN_SCHEMA = {"type": "object", "properties": {"understanding": {"type": "string", "maxLength": 300},
               "plan": {"type": "array", "items": {"type": "string", "maxLength": 200}, "minItems": 0, "maxItems": 8}},
               "required": ["understanding", "plan"]}

INTENT_SYS = """You are the INTENT step of an app agent. The user talks vaguely, over several turns. Turn the NEW REQUEST into a concrete plan of app actions.
Resolve every word like "it", "bigger", "bottom", "the other one" against the CURRENT STATE and the HISTORY, using the fixed meanings in the manual. Use real ids from the state.
Answer with JSON only: {"understanding": "<one sentence: what the user wants, which object>", "plan": ["<action>", ...]}
Each plan item is one action line exactly in the syntax of the action list. Use the fewest actions. Do not add "done".

ACTION LIST:
%s

MANUAL:
%s"""

RECHECK = """A deterministic check of your plan against the current state, the earlier requests and the manual found problems:
%s
Write the corrected plan for the NEW REQUEST: %s
Answer with JSON only, same format. Every plan item is one action line."""

REPAIR_SYS = """You fix one failed app action. Reply with exactly one corrected action line in the syntax of the action list, nothing else.
Keep the intent of the failed action. Use real ids from the STATE. Quote values that contain spaces.
Do not repeat the failed action unchanged. Do not do a later plan step; the harness runs those itself.
If the failed action is not needed in the current STATE (for example "nothing to undo"), reply: skip

ACTION LIST:
%s"""

def parse_plan(text):
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    t = re.sub(r"^```\w*\n?|```\s*$", "", t.strip()).strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m: return None, "no JSON"
    try: d = json.loads(m.group(0))
    except Exception as e: return None, "bad JSON %s" % e
    p = d.get("plan")
    if not isinstance(p, list): return None, "no plan list"
    return {"understanding": str(d.get("understanding", "")),
            "plan": [str(x).strip() for x in p if str(x).strip() and str(x).strip() != "done"]}, ""

def convo_text(prev):
    return "\n".join("%d. %s" % (i + 1, u) for i, u in enumerate(prev)) or "(this is the first request)"

def count_tokens(llm_url, text):
    """runtime tokenizer of the loaded model (llama-server /tokenize); raises when it cannot answer"""
    r = urllib.request.Request(llm_url.rstrip("/") + "/tokenize", data=json.dumps({"content": text}).encode(),
                               headers={"Content-Type": "application/json"})
    return len(json.loads(urllib.request.urlopen(r, timeout=10).read().decode())["tokens"])

def retrieved_notes(cfg, app, req):
    """stickman retrieval: the manual chunks of the capabilities this request matches (slides only).
    Empty when nothing matches or the tokenizer is unavailable; the full manual is in the prompt anyway."""
    idx = getattr(app, "retrieval", None)
    if idx is None: return ""
    try:
        found = idx.candidates(req, limit=4); ids = [r["id"] for r in found["candidates"]]
        if not ids: return ""
        out = idx.compile(ids, lambda t: count_tokens(cfg["llm_url"], t), budget=1024)
        return out.get("brief", "") if out.get("status") == "compiled" else ""
    except Exception:
        return ""

def intent(cfg, app, prev, req, extra=None):
    """prompt order = stable prefix (actions + manual, cached by llama-server) -> state -> history -> request"""
    sysm = INTENT_SYS % (app.list_actions(), app.manual)
    user = "CURRENT STATE:\n%s\n\nEARLIER REQUESTS IN THIS CONVERSATION:\n%s\n\nNEW REQUEST: %s" % (app.state(), convo_text(prev), req)
    notes = retrieved_notes(cfg, app, req)
    if notes: user += "\n\nNOTES FOR THIS REQUEST (from the manual):\n" + notes
    msgs = [{"role": "system", "content": sysm}, {"role": "user", "content": user}] + (extra or [])
    txt, use, dt = chat(cfg["llm_url"], msgs, temperature=cfg.get("temperature", 0.0), schema=PLAN_SCHEMA, max_tokens=700)
    plan, err = parse_plan(txt)
    return plan, err, dt, use, txt

def hybrid(cfg, app, plan, tries=2):
    """the harness runs each plan line; the LLM is only asked to repair a line that returned ERROR"""
    g = exec_grammar(app.verbs); log = []; tt = 0.0
    for i, step in enumerate(plan):
        ok, out = app.do(step); log.append({"cmd": step, "ok": ok, "out": out[:300], "by": "plan"})
        cur = step
        for _ in range(tries if not ok else 0):
            msgs = [{"role": "system", "content": REPAIR_SYS % app.list_actions()},
                    {"role": "user", "content": "STATE:\n%s\n\nFULL PLAN: %s\nFAILED ACTION: %s\nRESULT: %s\n\nCorrected action:" % (app.state(), plan, cur, out)}]
            try: txt, _, dt = chat(cfg["llm_url"], msgs, temperature=cfg.get("temperature", 0.0), grammar=g, max_tokens=120)
            except Exception as e: log.append({"cmd": None, "out": "server_error %s" % e}); break
            tt += dt; cur = txt.strip().splitlines()[0].strip() if txt.strip() else ""
            if cur in ("done", "skip", ""): log.append({"cmd": cur or "skip", "by": "repair"}); break
            if cur in plan[i + 1:] or cur == step: log.append({"cmd": "skip", "out": "repair proposed a plan step; skipped", "by": "repair"}); break
            ok, out = app.do(cur); log.append({"cmd": cur, "ok": ok, "out": out[:300], "by": "repair"})
            if ok: break
    return log, tt

def nodered_autowire(app, plan):
    """0.5.6: the 4B sometimes adds http-in -> template -> http-response without the
    `wire` steps, which deploys a dead endpoint. For http-in nodes this plan adds,
    append the missing wires along the plan order (the same steps the checker
    names). Never rewires a node that already sends somewhere."""
    if getattr(app, "name", "") != "nodered" or not hasattr(app, "simulate") or not plan:
        return []
    try:
        import checker as ck
    except ImportError:
        from . import checker as ck
    try:
        res, sim = app.simulate(plan)
    except Exception:
        return []
    if not all(ok for ok, _ in res):
        return []
    kinds = ck._flow_kinds(sim)
    edges = set(sim.edges()) if hasattr(sim, "edges") else set()
    senders = ck._senders(sim, kinds)
    goals = {i for i, k in kinds.items() if k in ck._HTTP_OUT}
    added = ck._added(plan)
    out = []
    for nid, typ in added:
        if typ not in ck._HTTP_IN or nid not in kinds or ck._reaches(nid, edges, goals):
            continue
        chain = ck._chain_for(nid, added, kinds)
        if len(chain) < 2 or kinds.get(chain[-1]) not in ck._HTTP_OUT:
            continue
        steps = []
        for a, b in zip(chain, chain[1:]):
            if (a, b) in edges:
                continue
            if a not in senders or any(x == a for x, _ in edges):
                steps = []
                break
            steps.append("wire %s %s" % (a, b))
        out += [s for s in steps if s not in out]
    return out

def act(cfg, app, sess, req, checker):
    """one user request = one undo step. sess = {"prev": [...], "tlog": TurnLog()}"""
    t0 = time.time(); rec = {"request": req}
    app.begin_request(req)
    try:
        try: plan, err, ti, use, raw = intent(cfg, app, sess["prev"], req)
        except NoModel as e:
            rec.update(error="no_model", message=str(e), understanding="", plan=[], results=[], state=app.state())
            return rec
        except Exception as e: plan, err, ti, use, raw = None, "llm_error %s" % e, 0.0, {}, ""
        flags = checker.check(app, plan["plan"], req, sess["tlog"]) if plan else ["The answer was not a valid JSON plan."]
        rec["check_flags"] = flags; rec["reask"] = False
        if flags and not err.startswith("llm_error"):
            extra = [{"role": "assistant", "content": raw}, {"role": "user", "content": RECHECK % ("\n".join("- " + f for f in flags), req)}]
            try:
                plan2, err2, ti2, _, raw2 = intent(cfg, app, sess["prev"], req, extra=extra); ti += ti2
                flags2 = checker.check(app, plan2["plan"], req, sess["tlog"]) if plan2 else ["invalid"]
                rec.update(reask=True, first_plan=plan, flags_after=flags2)
                if plan2 is not None and len(flags2) <= len(flags): plan, err = plan2, err2
                else: rec["kept_first"] = True
            except Exception as e: rec.update(reask=True, reask_err=str(e))
        pl = plan["plan"] if plan else []
        auto = nodered_autowire(app, pl)
        if auto:
            pl = pl + auto; rec["autowired"] = auto
        log, tex = hybrid(cfg, app, pl)
    finally:
        app.end_request()
    sess["tlog"].add(req, log, app); sess["prev"].append(req)
    rec.update(understanding=(plan or {}).get("understanding", ""), plan=pl, plan_err=err, results=log,
               t_intent=round(ti, 2), t_repair=round(tex, 2), t_total=round(time.time() - t0, 2), state=app.state())
    return rec
