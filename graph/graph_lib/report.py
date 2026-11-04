"""graph_report.md"""
import datetime
import json

from . import analysis as an
from .common import strip_prefix, write_text


def _table(w, header, rows):
    if not rows:
        w("none")
        return
    w("| " + " | ".join(header) + " |")
    w("|" + "|".join("---" for _ in header) + "|")
    for r in rows:
        w("| " + " | ".join(str(x) for x in r) + " |")


def _closure_from(g, start):
    seen = set([start])
    stack = [start]
    while stack:
        cur = stack.pop()
        nxt = set()
        for e in g.out_edges(cur, ("CALL", "LINK", "HANDLE_ABEND", "XCTL")):
            nxt.add(e["target"])
        for e in g.out_edges(cur, ("RETURN_TRANSID", "START_TRANSID")):
            for run in g.out_edges(e["target"], ("TRANSACTION_RUNS",)):
                nxt.add(run["target"])
        for n in nxt:
            if n not in seen:
                seen.add(n)
                stack.append(n)
    return seen


def write_report(path, g, doc, ana, entry_doc, unresolved, root):
    lines = []
    w = lines.append
    w("# Dependency graph: %s" % root)
    w("")
    w("Generated %s. %d nodes, %d edges." % (datetime.datetime.now().isoformat(timespec="seconds"),
                                              len(doc["nodes"]), len(doc["edges"])))
    w("")

    w("## Counts")
    w("")
    _table(w, ["Node type", "Count"], sorted(doc["stats"]["nodes_by_type"].items()))
    w("")
    strength = {}
    for e in doc["edges"]:
        strength[e["type"]] = e["strength"]
    _table(w, ["Edge type", "Strength", "Count"],
           [(k, strength.get(k, ""), v) for k, v in sorted(doc["stats"]["edges_by_type"].items())])
    w("")

    w("## Entry points")
    w("")
    w("### Transactions")
    w("")
    rows = []
    for e in doc["entry_points"]:
        if e["type"] == "transaction":
            tn = g.nodes[e["id"]]
            pn = g.nodes.get("program:" + e["program"])
            rows.append((tn["name"], e["program"], "yes" if pn and pn["in_codebase"] else "no",
                         ", ".join(tn["attrs"].get("defined_in", []))))
    _table(w, ["Transaction", "Program", "Program in codebase", "Defined in"], rows)
    w("")
    w("### Jobs")
    w("")
    rows = []
    for e in doc["entry_points"]:
        if e["type"] == "job":
            rows.append((strip_prefix(e["id"]), len(g.out_edges(e["id"], ("JOB_STEP",))), ", ".join(e["programs"])))
    _table(w, ["Job", "Steps", "Programs run"], rows)
    w("")
    w("### Candidate entry programs")
    w("")
    c = [e["id"] for e in doc["entry_points"] if e["type"] == "candidate_program"]
    w(", ".join(strip_prefix(x) for x in c) if c else "none")
    w("")

    w("## Entry-point programs")
    w("")
    _table(w, ["Program", "Entry type", "Confidence", "Transactions", "Jobs", "Also called"],
           [(e["name"], e["entry_type"], e["confidence"], ", ".join(e["transactions"]),
             ", ".join("%s:%s" % (j["job"], j["step"]) for j in e["jobs"]), "yes" if e["also_called"] else "no")
            for e in entry_doc["entry_points"]])
    w("")
    w("Not entry points:")
    w("")
    _table(w, ["Program", "Reason", "Called by", "Navigated from"],
           [(e["name"], e["reason"], ", ".join(e["hard_callers"]), ", ".join(e["nav_callers"]))
            for e in entry_doc["not_entry_points"]])
    w("")

    w("## Online flow")
    w("")
    any_t = False
    for e in doc["entry_points"]:
        if e["type"] != "transaction":
            continue
        any_t = True
        pid = "program:" + e["program"]
        if pid not in g.nodes:
            continue
        reach = _closure_from(g, pid)
        reach_names = sorted(strip_prefix(x) for x in reach if x != pid and x in g.nodes
                             and an.is_app(g.nodes[x]))
        maps = set()
        for x in reach:
            for me in g.out_edges(x, ("USES_MAP",)):
                maps.add(strip_prefix(me["target"]))
        w("- **%s** → %s; reaches: %s; mapsets: %s" % (strip_prefix(e["id"]), e["program"],
                                                      ", ".join(reach_names) or "-", ", ".join(sorted(maps)) or "-"))
    if not any_t:
        w("none")
    w("")

    w("## Batch jobs")
    w("")
    any_j = False
    for job in sorted(g.nodes_of("job"), key=lambda x: x["name"]):
        steps = [g.nodes[e["target"]] for e in g.out_edges(job["id"], ("JOB_STEP",))]
        if not steps:
            continue
        any_j = True
        w("### %s" % job["name"])
        w("")
        for s in steps:
            reads = set()
            writes = set()
            deletes = set()
            for e in g.out_edges(s["id"], ("STEP_DATASET", "IDCAMS_DEFINE", "IDCAMS_DELETE")):
                d = g.nodes[e["target"]]["name"]
                if e["access"] in ("read", "read_write"):
                    reads.add(d)
                if e["access"] in ("write", "read_write"):
                    writes.add(d)
                if e["access"] == "delete":
                    deletes.add(d)
            txt = "- %s: %s — reads: %s; writes: %s" % (s["attrs"].get("step_name"), s["attrs"].get("program"),
                                                       ", ".join(sorted(reads)) or "-",
                                                       ", ".join(sorted(writes)) or "-")
            if deletes:
                txt += "; deletes: " + ", ".join(sorted(deletes))
            w(txt)
        w("")
    if not any_j:
        w("none")
        w("")

    w("## Data stores")
    w("")
    _table(w, ["Dataset", "CICS files", "Online programs", "Batch programs", "Batch steps", "Shared"],
           [(s["dsn"], ", ".join(s["cics_files"]),
             ", ".join("%s (%s)" % (p["name"], p["access"]) for p in s["online_programs"]),
             ", ".join("%s (%s)" % (p["name"], p["access"]) for p in s["batch_programs"]),
             ", ".join("%s (%s)" % (p["name"], p["access"]) for p in s["batch_steps"]),
             "yes" if s["shared"] else "no") for s in ana["data_stores"]])
    w("")

    w("## Online programs that submit batch jobs")
    w("")
    _table(w, ["Program", "Queue"], [(s["program"], s["queue"]) for s in ana["batch_submitters"]])
    w("")

    w("## Fan-in / fan-out (top 20)")
    w("")
    _table(w, ["Program", "Hard in", "Hard out", "Nav in", "Nav out", "Data stores"],
           [(f["name"], f["hard_in"], f["hard_out"], f["nav_in"], f["nav_out"], f["data"]) for f in ana["fan"][:20]])
    w("")

    w("## Cycles")
    w("")
    w("Hard (CALL / LINK):")
    w("")
    if ana["sccs_hard"]:
        for c in ana["sccs_hard"]:
            w("- " + ", ".join(c))
    else:
        w("none")
    w("")
    w("Navigation (XCTL / RETURN TRANSID):")
    w("")
    if ana["sccs_navigation"]:
        for c in ana["sccs_navigation"]:
            w("- " + ", ".join(c))
    else:
        w("none")
    w("")

    w("## Orphans")
    w("")
    w(", ".join(ana["orphans"]) if ana["orphans"] else "none")
    w("")

    w("## Missing")
    w("")
    m = ana["missing"]
    w("### Programs")
    w("")
    _table(w, ["Program", "Referenced by"], [(p["name"], ", ".join(p["referenced_by"])) for p in m["programs"]])
    w("")
    w("### Copybooks (IBM)")
    w("")
    w(", ".join(m["copybooks"]["ibm"]) or "none")
    w("")
    w("### Copybooks (other)")
    w("")
    w(", ".join(m["copybooks"]["other"]) or "none")
    w("")
    for key, title in (("mapsets", "Mapsets"), ("cics_files", "CICS files"), ("transactions", "Transactions"),
                       ("datasets_unresolved", "Datasets with unresolved symbols")):
        w("### " + title)
        w("")
        w(", ".join(m[key]) or "none")
        w("")

    w("## Unused")
    w("")
    for key, title in (("copybooks", "Copybooks"), ("procs", "Procs"), ("mapsets", "Mapsets"),
                       ("control_cards", "Control cards")):
        w("### " + title)
        w("")
        w(", ".join(ana["unused"][key]) or "none")
        w("")

    w("## Unresolved")
    w("")
    if not unresolved:
        w("none")
        w("")
    by_kind = {}
    for u in unresolved:
        by_kind.setdefault(u["kind"], []).append(u)
    for kind in sorted(by_kind):
        w("### " + kind)
        w("")
        for u in by_kind[kind][:100]:
            w("- " + json.dumps(u, sort_keys=True))
        if len(by_kind[kind]) > 100:
            w("- ... %d more" % (len(by_kind[kind]) - 100))
        w("")
    write_text(path, "\n".join(lines))
