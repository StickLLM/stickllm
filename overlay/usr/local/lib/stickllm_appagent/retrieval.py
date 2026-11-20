"""Local retrieval primitives. No model, network, execution, or eval.

Candidates are suggestions, never an assertion of complete intent coverage.
The caller must validate slots/targets and coverage before executing a plan.
"""
import hashlib
import json
import re


STOP = {
    "a", "an", "the", "of", "to", "and", "or", "in", "on", "it", "its", "be",
    "is", "for", "with", "that", "this", "from", "by", "as", "at", "into",
}
GENERIC = {"text", "box", "words", "word", "type", "font", "slide", "letter", "letters"}


def words(text):
    return re.findall(r"[a-z0-9]+", text.lower().replace("centre", "center").replace("colour", "color"))


COLOR_NAMES = {
    "red", "blue", "green", "yellow", "teal", "black", "white", "orange", "purple",
    "pink", "brown", "navy", "gray", "grey",
}


def normalize_plan(lines):
    """Drop the non-id token selection and put fill arguments in id-then-colour order."""
    out = []
    for line in lines:
        parts = line.split()
        if not parts:
            continue
        if parts[0].lower() != "add":
            parts = [p for p in parts if p.lower() != "selection"]
        if len(parts) >= 3 and parts[0].lower() == "fill" and parts[1].lower() in COLOR_NAMES and re.fullmatch(r"s\d+", parts[2]):
            parts = [parts[0], parts[2], parts[1]] + parts[3:]
        if parts:
            out.append(" ".join(parts))
    return out


class ManualIndex:
    def __init__(self, pack, action_contract):
        # action_contract must come from the adapter, not from the pack.
        if pack.get("adapter") != "experiment.slides_sim":
            raise ValueError("unsupported adapter")
        self.capabilities = {}
        for cap in pack["capabilities"]:
            key = cap["id"]
            if key in self.capabilities:
                raise ValueError("duplicate capability: " + key)
            if not cap["actions"] or set(cap["actions"]) - set(action_contract):
                raise ValueError("unknown action mapping: " + key)
            if not cap.get("verify"):
                raise ValueError("missing verification: " + key)
            self.capabilities[key] = cap
        self.closure(list(self.capabilities))  # missing dependencies and cycles
        canonical = json.dumps({"pack": pack, "contract": action_contract},
                               sort_keys=True, separators=(",", ":"))
        self.fingerprint = hashlib.sha256(canonical.encode()).hexdigest()

    def closure(self, ids):
        result, active, seen = [], set(), set()

        def visit(key):
            if key in active:
                raise ValueError("dependency cycle")
            if key not in self.capabilities:
                raise ValueError("unknown capability: " + key)
            if key in seen:
                return
            active.add(key)
            for dep in sorted(self.capabilities[key]["requires"]):
                visit(dep)
            active.remove(key)
            seen.add(key)
            result.append(key)

        for key in ids:
            visit(key)
        return result

    def candidates(self, request, limit=4):
        if limit < 1:
            raise ValueError("limit must be positive")
        query_text = " ".join(words(request))
        query = set(query_text.split()) - STOP
        ranked = []
        for key, cap in self.capabilities.items():
            matched = []
            score = 0
            for cue in cap["cues"]:
                cue_tokens = words(cue)
                if len(cue_tokens) >= 2 and " ".join(cue_tokens) in query_text:
                    score += 5
                    matched.extend(w for w in cue_tokens if w not in STOP)
                elif len(cue_tokens) == 1 and cue_tokens[0] not in STOP and cue_tokens[0] not in GENERIC and cue_tokens[0] in query:
                    score += 2
                    matched.append(cue_tokens[0])
            if score:
                ranked.append({"id": key, "score": score, "matched": sorted(set(matched))})
        shape = bool({"rectangle", "shape", "fill"} & query)
        letter = bool({"letter", "letters", "wording", "font", "title", "heading"} & query)
        colour = bool(COLOR_NAMES & query) or "color" in query
        if shape and not letter:
            ranked = [row for row in ranked if row["id"] != "slides.text.color"]
        if shape and not colour and "fill" not in query:
            ranked = [row for row in ranked if row["id"] != "slides.objects.fill"]
        ranked.sort(key=lambda r: (-r["score"], r["id"]))
        return {"status": "candidates_only", "candidates": ranked[:limit],
                "overflow": len(ranked) > limit, "pack_hash": self.fingerprint}

    def compile(self, ids, count_tokens, budget=2048):
        """count_tokens must use the runtime tokenizer; never estimate silently."""
        if not ids or len(ids) != len(set(ids)):
            raise ValueError("empty or duplicate selection")
        selected = self.closure(ids)
        sections = [
            "Use the id printed on the matching OBJECTS line. Named words beat the selected object.",
            "If the user says selected or it, use the id printed on the SELECTION line.",
            "Never write the letters ID. Never write the word selection.",
            "A box created by add earlier in this plan has no id yet. The next lines omit the id.",
            "A box already listed keeps the id printed on its line.",
        ]
        for key in selected:
            sections.append(self.capabilities[key]["instructions"])
        parts = []
        for key in selected:
            for verb in self.capabilities[key]["actions"]:
                if verb not in parts:
                    parts.append(verb)
        parts = [v for v in parts if v in ("add", "placeholder")] + [v for v in parts if v not in ("add", "placeholder")]
        sections.append(
            "Parts of this request. Write one line for each part, in this order. Do not put two parts on one line.\n"
            + "\n".join(parts))
        brief = "\n\n".join(sections)
        tokens = count_tokens(brief)
        if not isinstance(tokens, int) or isinstance(tokens, bool) or tokens < 0:
            raise ValueError("invalid tokenizer result")
        if tokens > budget:
            return {"status": "budget_exceeded", "tokens": tokens, "capability_ids": selected}
        return {"status": "compiled", "brief": brief, "tokens": tokens,
                "capability_ids": selected, "parts": parts, "pack_hash": self.fingerprint}


def verify_readback(expected, observed, source):
    """Compare normalized fields from an independent editor readback.

    Target IDs and expected values must be bound before mutation. This function
    never creates getters or treats a simulator/draw acknowledgement as evidence.
    """
    if source != "editor_readback" or not expected:
        return "unverified"
    missing = False
    for key, value in expected.items():
        if key not in observed:
            missing = True
        elif type(observed[key]) is not type(value) or observed[key] != value:
            return "fail"
    return "unverified" if missing else "pass"
