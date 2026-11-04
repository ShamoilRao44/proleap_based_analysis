"""First-entry analysis: what a program does when it is started with an empty COMMAREA."""
import collections
import re

from . import common

FIRST = re.compile(r"\bEIBCALEN\b\s*(=|EQUAL(\s+TO)?|IS\s+EQUAL(\s+TO)?)\s*(0|ZERO|ZEROS|ZEROES)\b", re.I)
SEND = re.compile(r"\bSEND\s+(MAP|TEXT)\b", re.I)
MAX_DEPTH = 4


def _empty(outcome):
    return {"found": False, "paragraph": None, "statement_id": None, "loc": None, "condition": None,
            "outcome": outcome, "handoff_targets": [], "path_resolved": True, "events": [],
            "expected_callers": []}


def expected_callers(final, condition, own, known_programs):
    """Program names held in constants that the first-entry condition compares against."""
    toks = set(common.tokens(condition))
    out = set()
    for it in final.get("data_items", []):
        if it["level"] == 88 or it.get("name") not in toks:
            continue
        for v in it.get("values") or []:
            if v.get("kind") == "string":
                val = str(v.get("value") or "").strip().upper()
                if val in known_programs and val != own:
                    out.add(val)
    return sorted(out)


def first_entry(final, raw, known_programs):
    if raw is None:
        return _empty("unknown")
    stmts = raw.get("statements") or []
    pars = [p["name"] for p in raw.get("paragraphs", [])]
    real = [p["name"] for p in raw.get("paragraphs", []) if not p.get("declaratives")]
    if not real or not stmts:
        return _empty("none")
    main = real[0]
    by_id = dict((s["id"], s) for s in stmts)
    kids = collections.defaultdict(list)
    by_par = collections.defaultdict(list)
    for s in stmts:
        if s.get("parent") is not None:
            kids[s["parent"]].append(s["id"])
        by_par[s["paragraph"]].append(s)

    def tests_in(par):
        return [s for s in by_par.get(par, []) if s["type"] == "if" and FIRST.search(s.get("condition") or "")]

    cands = tests_in(main)
    if not cands:
        for s in by_par.get(main, []):
            if s["type"] == "perform" and not s.get("inline") and s.get("target"):
                cands += tests_in(s["target"])
    if not cands:
        return _empty("none")
    root = min(cands, key=lambda s: s["id"])

    def subtree(i):
        out = []
        stack = [i]
        while stack:
            x = stack.pop()
            out.append(x)
            stack.extend(kids.get(x, ()))
        return out

    then_ids = sorted(set(x for k in kids.get(root["id"], ()) if by_id[k].get("branch") == "then"
                          for x in subtree(k)))

    transfers = dict((t["stmt_id"], t) for t in final.get("transfers", [])
                     if t.get("stmt_id") is not None and t["kind"] in ("XCTL", "LINK"))
    events = []
    visited = set()

    def expand(par, depth):
        if par in visited or depth >= MAX_DEPTH:
            return
        visited.add(par)
        walk(sorted(s["id"] for s in by_par.get(par, [])), depth)

    def walk(ids, depth):
        for i in ids:
            s = by_id[i]
            t = s["type"]
            if t == "move" and s.get("from_literal") is not None:
                lit = str(s["from_literal"]).strip().strip("'\"").strip().upper()
                for n in s.get("to") or []:
                    events.append(("assign", n, lit))
            elif t == "initialize":
                events.append(("init",))
            elif t == "execCics":
                if SEND.search(s.get("exec_text") or ""):
                    events.append(("send",))
                if i in transfers:
                    events.append(("transfer", i))
            elif t == "perform" and not s.get("inline") and s.get("target"):
                target = s["target"]
                if s.get("thru") and target in pars and s["thru"] in pars:
                    a, b = pars.index(target), pars.index(s["thru"])
                    for p in pars[a:b + 1]:
                        expand(p, depth + 1)
                else:
                    expand(target, depth + 1)

    walk(then_ids, 0)

    last = {}
    targets = []
    path_resolved = True
    for e in events:
        if e[0] == "assign":
            last[e[1]] = e[2]
        elif e[0] == "transfer":
            t = transfers[e[1]]
            var = (t.get("target") or {}).get("var")
            if var and var in last:
                targets.append(last[var])
            else:
                targets.extend(x["value"] for x in t.get("resolved_targets", []))
                if var:
                    path_resolved = False
    own = final["name"]
    kinds = [e[0] for e in events]
    handoff = sorted(set(targets))
    if any(t != own for t in handoff):
        outcome = "handoff"
    elif "send" in kinds:
        outcome = "own_screen"
    elif "init" in kinds:
        outcome = "self_initialising"
    else:
        outcome = "other"
    loc = None
    for d in final.get("decisions", []):
        if d.get("stmt_id") == root["id"]:
            loc = d.get("loc")
            break
    cond = root.get("condition") or ""
    return {"found": True, "paragraph": root["paragraph"], "statement_id": root["id"], "loc": loc,
            "condition": cond, "outcome": outcome, "handoff_targets": handoff, "path_resolved": path_resolved,
            "events": kinds, "expected_callers": expected_callers(final, cond, own, known_programs)}
