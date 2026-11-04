"""Graph analysis: roles, entry points, cycles, fan-in/out, data stores, missing and unused items."""
import datetime

from . import access
from .common import strip_prefix

HARD = ("CALL", "LINK", "HANDLE_ABEND")
ENTRY_INCOMING = ("CALL", "LINK", "XCTL", "HANDLE_ABEND", "TRANSACTION_RUNS", "STEP_RUNS")
DATA_EDGES = ("PROGRAM_CICS_FILE", "PROGRAM_DATASET", "PROGRAM_DB2_TABLE", "PROGRAM_TS_QUEUE", "PROGRAM_TD_QUEUE")


def is_app(n):
    a = n["attrs"]
    return (n["type"] == "program" and n["in_codebase"] is True and not a.get("system")
            and not a.get("utility"))


def _closure(seeds, adj):
    seen = set(seeds)
    stack = list(seeds)
    while stack:
        cur = stack.pop()
        for nxt in adj.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def tarjan(nodes, adj):
    """Iterative Tarjan SCC. adj: node -> iterable of nodes. Returns a list of components (lists)."""
    index = {}
    low = {}
    on_stack = set()
    stack = []
    result = []
    counter = [0]
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(sorted(adj.get(root, ()))))]
        index[root] = low[root] = counter[0]
        counter[0] += 1
        stack.append(root)
        on_stack.add(root)
        while work:
            v, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on_stack.add(w)
                    work.append((w, iter(sorted(adj.get(w, ())))))
                    advanced = True
                    break
                elif w in on_stack:
                    low[v] = min(low[v], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                result.append(comp)
    return result


def _sccs(app_ids, adj):
    comps = [sorted(strip_prefix(x) for x in c) for c in tarjan(sorted(app_ids), adj) if len(c) > 1]
    comps.sort(key=lambda c: (-len(c), c[0]))
    return comps


def program_graphs(g):
    """-> (hard adjacency, navigation adjacency) over all program nodes, self edges removed."""
    hard = {}
    nav = {}
    for e in g.edges.values():
        t = e["type"]
        s, d = e["source"], e["target"]
        if t in HARD and s.startswith("program:") and d.startswith("program:") and s != d:
            hard.setdefault(s, set()).add(d)
        elif t == "XCTL" and s != d:
            nav.setdefault(s, set()).add(d)
        elif t in ("RETURN_TRANSID", "START_TRANSID") and s.startswith("program:"):
            for run in g.out_edges(d, ("TRANSACTION_RUNS",)):
                if run["target"] != s:
                    nav.setdefault(s, set()).add(run["target"])
    return hard, nav


def entry_points_doc(g, r, root):
    """Builds the entry-points.json document (section 8.8 of the plan)."""
    apps = sorted(n["id"] for n in g.nodes.values() if is_app(n))
    app_set = set(apps)
    unresolved_dynamic = sum(1 for u in r.unresolved if u.get("kind") == "dynamic_transfer"
                             and u.get("transfer_kind") in ("CALL", "LINK"))
    entries = []
    others = []
    for pid in apps:
        node = g.nodes[pid]
        name = node["name"]
        trans = sorted(strip_prefix(e["source"]) for e in g.in_edges(pid, ("TRANSACTION_RUNS",)))
        jobs = []
        for e in g.in_edges(pid, ("STEP_RUNS",)):
            sa = g.nodes[e["source"]]["attrs"]
            jobs.append({"job": sa.get("job"), "step": sa.get("step_name")})
        jobs.sort(key=lambda x: (str(x["job"]), str(x["step"])))
        hard_callers = sorted(set(strip_prefix(e["source"]) for e in g.in_edges(pid, HARD)
                                  if e["source"] in app_set and e["source"] != pid))
        nav = set()
        for e in g.in_edges(pid, ("XCTL",)):
            if e["source"] in app_set and e["source"] != pid:
                nav.add(strip_prefix(e["source"]))
        for tr in g.in_edges(pid, ("TRANSACTION_RUNS",)):
            for e in g.in_edges(tr["source"], ("RETURN_TRANSID", "START_TRANSID")):
                if e["source"] in app_set and e["source"] != pid:
                    nav.add(strip_prefix(e["source"]))
        nav_callers = sorted(nav)
        calls = set()
        for e in g.out_edges(pid, HARD):
            tn = g.nodes[e["target"]]
            calls.add(tn["name"] + (" (system)" if tn["attrs"].get("system") else ""))
        xctl_to = sorted(set(g.nodes[e["target"]]["name"] for e in g.out_edges(pid, ("XCTL",))))
        copybooks = len(set(e["target"] for e in g.out_edges(pid, ("COPY",))))
        base = {"name": name, "kind": node["attrs"].get("kind"), "path": node["attrs"].get("path")}
        if trans or jobs:
            if trans and jobs:
                et = "both"
            elif trans:
                et = "cics_transaction"
            else:
                et = "jcl_job"
            notes = ["also called by other programs"] if hard_callers else []
            d = dict(base)
            d.update({"entry_type": et, "confidence": "confirmed", "transactions": trans, "jobs": jobs,
                      "hard_callers": hard_callers, "also_called": bool(hard_callers), "nav_callers": nav_callers,
                      "calls": sorted(calls), "xctl_to": xctl_to, "copybooks": copybooks, "notes": notes})
            entries.append(d)
        elif not hard_callers and not nav_callers:
            notes = ["no caller, no transaction and no job in the codebase: dead code or started from outside "
                     "(scheduler, other system)"]
            if unresolved_dynamic > 0:
                notes.append("%d dynamic CALL/LINK targets are unresolved in the codebase; this program may be "
                             "one of them" % unresolved_dynamic)
            d = dict(base)
            d.update({"entry_type": "candidate", "confidence": "heuristic", "transactions": [], "jobs": [],
                      "hard_callers": [], "also_called": False, "nav_callers": [], "calls": sorted(calls),
                      "xctl_to": xctl_to, "copybooks": copybooks, "notes": notes})
            entries.append(d)
        else:
            d = dict(base)
            d.update({"reason": "called" if hard_callers else "navigation target", "hard_callers": hard_callers,
                      "nav_callers": nav_callers})
            others.append(d)
    counts = {}
    for e in entries:
        counts[e["entry_type"]] = counts.get(e["entry_type"], 0) + 1
    return {
        "schema": "entry-points/1", "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "codebase_root": root,
        "rule": "entry point = application program started by a CICS transaction or a JCL step, or with no "
                "CALL/LINK caller; XCTL is navigation and is not counted as a dependency",
        "summary": {"entry_points": len(entries), "cics_transaction": counts.get("cics_transaction", 0),
                    "jcl_job": counts.get("jcl_job", 0), "both": counts.get("both", 0),
                    "candidate": counts.get("candidate", 0), "not_entry_points": len(others),
                    "unresolved_dynamic_calls": unresolved_dynamic},
        "entry_points": entries, "not_entry_points": others}


def run(g, r, data):
    """Computes the analysis. Returns (analysis dict, graph entry_points list)."""
    apps = sorted(n["id"] for n in g.nodes.values() if is_app(n))
    app_set = set(apps)
    hard, nav = program_graphs(g)
    both_adj = {}
    for adj in (hard, nav):
        for k, v in adj.items():
            both_adj.setdefault(k, set()).update(v)

    # reach and roles
    online_seeds = set(e["target"] for e in g.edges.values() if e["type"] == "TRANSACTION_RUNS")
    batch_seeds = set(e["target"] for e in g.edges.values() if e["type"] == "STEP_RUNS")
    reach_online = _closure(online_seeds, both_adj)
    reach_batch = _closure(batch_seeds, hard)
    for n in g.nodes.values():
        if n["type"] != "program":
            continue
        o = n["id"] in reach_online
        b = n["id"] in reach_batch
        n["attrs"]["role"] = "both" if (o and b) else "online" if o else "batch" if b else "unreached"

    candidates = []
    for pid in apps:
        inc = [e for e in g.in_edges(pid, ENTRY_INCOMING) if e["source"] != pid]
        if not inc:
            candidates.append(g.nodes[pid]["name"])
    orphans = sorted(g.nodes[p]["name"] for p in apps if g.nodes[p]["attrs"].get("role") == "unreached")

    # cycles
    hard_app = {k: set(x for x in v if x in app_set) for k, v in hard.items() if k in app_set}
    nav_app = {k: set(x for x in v if x in app_set) for k, v in nav.items() if k in app_set}
    sccs_hard = _sccs(apps, hard_app)
    sccs_nav = _sccs(apps, nav_app)

    # fan-in / fan-out
    fan = []
    for pid in apps:
        data_targets = set()
        for e in g.out_edges(pid, DATA_EDGES):
            data_targets.add(e["target"])
        fan.append({"name": g.nodes[pid]["name"],
                    "hard_in": len(set(s for s, ds in hard.items() if pid in ds and s != pid)),
                    "hard_out": len(set(hard.get(pid, ())) - {pid}),
                    "nav_in": len(set(s for s, ds in nav.items() if pid in ds and s != pid)),
                    "nav_out": len(set(nav.get(pid, ())) - {pid}), "data": len(data_targets)})
    fan.sort(key=lambda x: (-x["hard_in"], -x["nav_in"], x["name"]))

    # data stores
    stores = []
    for n in sorted(g.nodes_of("dataset"), key=lambda x: x["name"]):
        if n["attrs"].get("temp"):
            continue
        files = [g.nodes[e["source"]] for e in g.in_edges(n["id"], ("CICS_FILE_DATASET",))]
        online = {}
        for f in files:
            for e in g.in_edges(f["id"], ("PROGRAM_CICS_FILE",)):
                nm = g.nodes[e["source"]]["name"]
                online[nm] = access.combine(online.get(nm), e["access"])
        batch_p = {}
        for e in g.in_edges(n["id"], ("PROGRAM_DATASET",)):
            nm = g.nodes[e["source"]]["name"]
            batch_p[nm] = access.combine(batch_p.get(nm), e["access"])
        batch_s = {}
        for e in g.in_edges(n["id"], ("STEP_DATASET", "IDCAMS_DEFINE", "IDCAMS_DELETE")):
            sa = g.nodes[e["source"]]["attrs"]
            nm = "%s:%s" % (sa.get("job"), sa.get("step_name"))
            batch_s[nm] = access.combine(batch_s.get(nm), e["access"])
        writers = sorted(set(k for d in (online, batch_p, batch_s) for k, a in d.items()
                             if a in ("write", "read_write")))
        readers = sorted(set(k for d in (online, batch_p, batch_s) for k, a in d.items()
                             if a in ("read", "read_write")))
        stores.append({"id": n["id"], "dsn": n["name"], "gdg": bool(n["attrs"].get("gdg")),
                       "cics_files": sorted(f["name"] for f in files),
                       "online_programs": [{"name": k, "access": v} for k, v in sorted(online.items())],
                       "batch_programs": [{"name": k, "access": v} for k, v in sorted(batch_p.items())],
                       "batch_steps": [{"name": k, "access": v} for k, v in sorted(batch_s.items())],
                       "writers": writers, "readers": readers,
                       "shared": bool(online) and bool(batch_p or batch_s)})

    # missing
    miss_prog = []
    for n in sorted(g.nodes_of("program"), key=lambda x: x["name"]):
        a = n["attrs"]
        if n["in_codebase"] is False and not a.get("system") and not a.get("utility"):
            refs = sorted(set(strip_prefix(e["source"]) for e in g.in_edges(
                n["id"], ("CALL", "LINK", "XCTL", "HANDLE_ABEND", "TRANSACTION_RUNS", "STEP_RUNS", "CSD_DEFINES"))))
            miss_prog.append({"name": n["name"], "referenced_by": refs})
    ibm = []
    other = []
    for n in sorted(g.nodes_of("copybook"), key=lambda x: x["name"]):
        if n["in_codebase"] is False:
            (ibm if n["attrs"].get("system") else other).append(n["name"])
    missing = {
        "programs": miss_prog,
        "copybooks": {"ibm": ibm, "other": other},
        "mapsets": sorted(n["name"] for n in g.nodes_of("mapset")
                          if n["in_codebase"] is False and g.in_edges(n["id"], ("USES_MAP",))),
        "cics_files": sorted(n["name"] for n in g.nodes_of("cics_file") if n["in_codebase"] is False),
        "transactions": sorted(n["name"] for n in g.nodes_of("transaction") if n["in_codebase"] is False),
        "datasets_unresolved": sorted(n["name"] for n in g.nodes_of("dataset") if n["attrs"].get("unresolved")),
    }
    used_cpy = set()
    for e in g.edges.values():
        if e["type"] in ("COPY", "SQL_INCLUDE", "SYMBOLIC_MAP"):
            used_cpy.add(e["target"])
    unused_cpy = sorted(set(rec["name"].upper() for rec in data.get("inventory", [])
                            if rec.get("type") in ("copybook", "dclgen")
                            and "copybook:" + rec["name"].upper() not in used_cpy))
    unused = {
        "copybooks": unused_cpy,
        "procs": sorted(n["name"] for n in g.nodes_of("proc") if not g.in_edges(n["id"], ("JOB_USES_PROC",))),
        "mapsets": sorted(n["name"] for n in g.nodes_of("mapset")
                          if n["in_codebase"] is True and not g.in_edges(n["id"], ("USES_MAP",))),
        "control_cards": sorted(n["name"] for n in g.nodes_of("control_card")
                                if not g.in_edges(n["id"], ("STEP_CONTROL_CARD",))),
    }
    submitters = []
    for e in g.edges.values():
        if e["type"] == "PROGRAM_TD_QUEUE" and e["access"] in ("write", "read_write"):
            q = g.nodes[e["target"]]
            if q["attrs"].get("internal_reader"):
                submitters.append({"program": g.nodes[e["source"]]["name"], "queue": q["name"]})
    submitters.sort(key=lambda x: (x["program"], x["queue"]))

    analysis = {"reach": {"online": sorted(strip_prefix(x) for x in reach_online),
                          "batch": sorted(strip_prefix(x) for x in reach_batch)},
                "candidates": sorted(candidates), "orphans": orphans, "sccs_hard": sccs_hard,
                "sccs_navigation": sccs_nav, "fan": fan, "data_stores": stores, "missing": missing,
                "unused": unused, "batch_submitters": submitters}

    entries = []
    for n in sorted(g.nodes_of("transaction"), key=lambda x: x["name"]):
        runs = g.out_edges(n["id"], ("TRANSACTION_RUNS",))
        if runs:
            entries.append({"type": "transaction", "id": n["id"], "program": strip_prefix(runs[0]["target"])})
    for n in sorted(g.nodes_of("job"), key=lambda x: x["name"]):
        progs = set()
        for je in g.out_edges(n["id"], ("JOB_STEP",)):
            for se in g.out_edges(je["target"], ("STEP_RUNS",)):
                progs.add(strip_prefix(se["target"]))
        entries.append({"type": "job", "id": n["id"], "programs": sorted(progs)})
    for name in sorted(candidates):
        entries.append({"type": "candidate_program", "id": "program:" + name,
                        "reason": "no caller, no transaction, no job"})
    return analysis, entries
