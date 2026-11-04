"""Prerequisites, classification, roots, levels and navigation direction of the online programs."""
import collections

from . import common

REASONS = {
    "self_initialising": "starts with its own state reset, no evidence of a predecessor",
    "none": "no first-entry test found",
    "unknown": "no first-entry test found",
    "other": "first-entry branch does neither hand off nor show a screen",
}


def _loc_text(fe):
    if fe.get("loc"):
        return "line %s" % fe["loc"][1]
    return "line ?"


def _transaction_map(graph):
    tx_runs = collections.defaultdict(list)
    tx_of = collections.defaultdict(list)
    for e in graph["edges"]:
        if e["type"] == "TRANSACTION_RUNS":
            prog = common.strip_prefix(e["target"])
            tx_runs[e["source"]].append(prog)
            tx_of[prog].append(common.strip_prefix(e["source"]))
    return tx_runs, tx_of


def _navigation_edges(graph, online_set, tx_runs):
    seen = set()
    out = []
    for e in graph["edges"]:
        t = e["type"]
        if not e["source"].startswith("program:"):
            continue
        a = common.strip_prefix(e["source"])
        if a not in online_set:
            continue
        det = (e.get("details") or [{}])[0]
        if t in ("XCTL", "LINK") and e["target"].startswith("program:"):
            targets = [common.strip_prefix(e["target"])]
        elif t in ("RETURN_TRANSID", "START_TRANSID"):
            targets = list(tx_runs.get(e["target"], ()))
        else:
            continue
        for b in targets:
            if b == a or b not in online_set or (a, b, t) in seen:
                continue
            seen.add((a, b, t))
            out.append({"source": a, "target": b, "type": t, "how": det.get("how"),
                        "guards": det.get("guards") or []})
    out.sort(key=lambda x: (x["source"], x["target"], x["type"]))
    return out


def build_process(data, state, entries):
    online = list(data["online"])
    online_set = set(online)
    graph = data["graph"]
    tx_runs, tx_of = _transaction_map(graph)
    cell_names = dict((c["id"], c["names"]) for c in state["cells"])

    prereqs = dict((b, {}) for b in online)
    for B in online:
        fe = entries[B]
        for A in fe["handoff_targets"]:
            if A != B and A in online_set:
                prereqs[B].setdefault((A, "handoff"), "%s hands off to %s when started without a COMMAREA (%s %s)"
                                      % (B, A, fe.get("paragraph"), _loc_text(fe)))
        sp = state["programs"].get(B)
        for rq in (sp["requirements"] if sp else []):
            if rq["status"] != "produced":
                continue
            for A in rq["producers"]:
                if A in online_set and A != B:
                    prereqs[B].setdefault((A, "state"), "%s needs %s that %s sets (%s)"
                                          % (B, ", ".join(cell_names.get(rq["cell"], [rq["cell"]])), A, rq["kind"]))
        for A in fe["expected_callers"]:
            if A in online_set and A != B:
                prereqs[B].setdefault((A, "expected_caller"), "%s checks it was called from %s" % (B, A))

    prereq_list = {}
    for B in online:
        prereq_list[B] = [{"program": a, "kind": k, "evidence": ev} for (a, k), ev in sorted(prereqs[B].items())]

    classification = {}
    for B in online:
        hard = [p for p in prereq_list[B] if p["kind"] in ("handoff", "state")]
        soft = [p for p in prereq_list[B] if p["kind"] == "expected_caller"]
        if hard:
            classification[B] = "needs_prior"
        elif soft:
            classification[B] = "expects_caller"
        elif entries[B]["outcome"] == "own_screen":
            classification[B] = "starter"
        else:
            classification[B] = "unclear"

    dependents = collections.defaultdict(set)
    for B in online:
        for p in prereq_list[B]:
            if p["kind"] in ("handoff", "state"):
                dependents[p["program"]].add(B)

    roots = sorted(b for b in online if classification[b] == "starter" and tx_of.get(b))
    certainty = {}
    for b in online:
        if b in roots:
            certainty[b] = "certain" if dependents.get(b) else "probable"
        else:
            certainty[b] = None

    # levels
    edges = []
    incident = set()
    for B in online:
        for p in prereq_list[B]:
            edges.append((p["program"], B))
            incident.add(p["program"])
            incident.add(B)
    state_level, cyclic = common.scc_levels(incident, edges)
    nav = _navigation_edges(graph, online_set, tx_runs)
    level = {}
    source = {}
    for b in online:
        if b in incident:
            level[b] = state_level[b]
            source[b] = "state"
        elif b in roots:
            level[b] = 0
            source[b] = "state"
    # navigation distance from the roots for the others
    adj = collections.defaultdict(set)
    for e in nav:
        adj[e["source"]].add(e["target"])
    dist = dict((r, 0) for r in roots)
    queue = collections.deque(roots)
    while queue:
        cur = queue.popleft()
        for nxt in sorted(adj.get(cur, ())):
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
    for b in online:
        if b not in level:
            level[b] = dist.get(b)
            source[b] = "navigation"

    for e in nav:
        la, lb = level.get(e["source"]), level.get(e["target"])
        if la is None or lb is None:
            e["direction"] = "unknown"
        elif lb > la:
            e["direction"] = "forward"
        elif lb < la:
            e["direction"] = "back"
        else:
            e["direction"] = "lateral"

    programs = {}
    for b in online:
        sp = state["programs"].get(b) or {}
        programs[b] = {"transactions": sorted(tx_of.get(b, [])), "first_entry": entries[b],
                       "requires": sp.get("requires", []), "provides": sp.get("provides", []),
                       "prerequisites": prereq_list[b], "classification": classification[b],
                       "certainty": certainty[b], "level": level[b], "level_source": source[b],
                       "cyclic_prerequisites": b in cyclic, "dependents": sorted(dependents.get(b, []))}
    by_level = collections.defaultdict(list)
    for b in online:
        by_level[level[b]].append(b)
    levels = [{"level": l, "programs": sorted(by_level[l])} for l in sorted(k for k in by_level if k is not None)]
    if None in by_level:
        levels.append({"level": None, "programs": sorted(by_level[None])})
    unclear = [{"name": b, "reason": REASONS.get(entries[b]["outcome"], REASONS["other"])}
               for b in online if classification[b] == "unclear"]
    return {"roots": roots, "programs": programs, "levels": levels, "navigation_edges": nav, "unclear": unclear}


def build_main_entry_points(data, state, process, batch):
    cells = state["cells"]
    roots = []
    for r in process["roots"]:
        p = process["programs"][r]
        fe = p["first_entry"]
        dep = p["dependents"]
        ev = ["first entry (%s %s): shows its own screen" % (fe.get("paragraph"), _loc_text(fe))]
        if dep:
            ev.append("%d programs hand off to it when started without a COMMAREA: %s" % (len(dep), ", ".join(dep)))
        if not p["requires"]:
            ev.append("no state required from other programs")
        for c in cells:
            if c["origin_producers"] == [r]:
                ev.append("only program that sets %s" % ", ".join(c["names"]))
        roots.append({"name": r, "transactions": p["transactions"], "certainty": p["certainty"],
                      "dependents": dep, "evidence": ev})
    starts = [{"job": j["job"], "runs_programs": j["runs_programs"], "defines": j["defines"]}
              for j in batch["jobs"] if j["level"] == 0 and j["defines"]]
    return {
        "schema": "main-entry-points/1",
        "rule": ("A main entry point is a program that works with no earlier program (it shows its own first "
                 "screen when started without a COMMAREA and needs no state set by another program) and that "
                 "other programs depend on. Programs that hand off to another program when started without a "
                 "COMMAREA, or need state another program sets, are not entry points. Navigation links between "
                 "screens (XCTL) do not make a program an entry point."),
        "online": {"roots": roots, "unclear": process["unclear"]},
        "batch": {"starts": starts,
                  "note": ("Jobs with no predecessor by dataset definition. The order between independent jobs "
                           "is not in the code (scheduler or run book).")}}
