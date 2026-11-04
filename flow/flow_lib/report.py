"""flow_report.md"""
import collections
import datetime

from . import common


def _table(w, header, rows):
    if not rows:
        w("none")
        return
    w("| " + " | ".join(header) + " |")
    w("|" + "|".join("---" for _ in header) + "|")
    for r in rows:
        w("| " + " | ".join(str(x) for x in r) + " |")


def write_report(path, root, state, process, batch, main, warnings):
    on = process
    lines = []
    w = lines.append
    w("# Activity flow: %s" % root)
    w("")
    w("Generated %s. %d online programs, %d roots, %d jobs." % (
        datetime.datetime.now().isoformat(timespec="seconds"), len(on["programs"]), len(on["roots"]),
        len(batch["jobs"])))
    w("")

    w("## Main entry points")
    w("")
    w("### Online")
    w("")
    if not main["online"]["roots"]:
        w("No program qualifies as a main entry point.")
        w("")
    for r in main["online"]["roots"]:
        w("**%s** (transactions: %s; %s)" % (r["name"], ", ".join(r["transactions"]) or "-", r["certainty"]))
        w("")
        for ev in r["evidence"]:
            w("- " + ev)
        w("")
    w("### Unclear programs")
    w("")
    _table(w, ["Program", "Reason"], [(u["name"], u["reason"]) for u in main["online"]["unclear"]])
    w("")
    w("### Batch starts")
    w("")
    _table(w, ["Job", "Runs programs", "Defines"],
           [(s["job"], ", ".join(s["runs_programs"]) or "-", ", ".join(s["defines"])) for s in main["batch"]["starts"]])
    w("")

    w("## How the classification works")
    w("")
    w("- **starter**: shows its own first screen when started without a COMMAREA and needs nothing from another program.")
    w("- **needs_prior**: hands off to another program when started without a COMMAREA, or needs state that another program sets.")
    w("- **expects_caller**: checks that it was called from a particular program (soft evidence).")
    w("- **unclear**: no evidence either way; a person must decide.")
    w("- **certain**: a starter that other programs depend on. **probable**: a starter nobody depends on.")
    w("")

    w("## Online programs")
    w("")
    rows = []
    for name in sorted(on["programs"]):
        p = on["programs"][name]
        rows.append((name, p["classification"], p["level"] if p["level"] is not None else "?",
                     ", ".join("%s (%s)" % (x["program"], x["kind"]) for x in p["prerequisites"]) or "-",
                     p["first_entry"]["outcome"]))
    _table(w, ["Program", "Classification", "Level", "Prerequisites", "First entry"], rows)
    w("")

    w("## Levels")
    w("")
    for lv in on["levels"]:
        w("- Level %s: %s" % (lv["level"] if lv["level"] is not None else "unknown", ", ".join(lv["programs"])))
    w("")

    w("## Back and lateral navigation")
    w("")
    counts = collections.Counter(e["direction"] for e in on["navigation_edges"])
    w("forward %d, back %d, lateral %d, unknown %d" % (counts["forward"], counts["back"], counts["lateral"],
                                                       counts["unknown"]))
    w("")
    back = collections.defaultdict(list)
    for e in on["navigation_edges"]:
        if e["direction"] == "back":
            back[e["target"]].append(e["source"])
    for t in sorted(back):
        w("- back to %s from: %s" % (t, ", ".join(sorted(set(back[t])))))
    w("")

    w("## State fields")
    w("")
    rows = []
    for c in state["cells"]:
        if not c["origin_producers"]:
            continue
        cons = c["consumers"]
        cs = ", ".join(cons[:8]) + (" +%d" % (len(cons) - 8) if len(cons) > 8 else "")
        rows.append((c["id"], ", ".join(c["names"]), "yes" if c["shared"] else "no",
                     ", ".join(c["origin_producers"]), cs))
    _table(w, ["Cell", "Names", "Shared", "Origin producers", "Consumers"], rows)
    w("")

    w("## Unproduced requirements")
    w("")
    rows = []
    for name in sorted(state["programs"]):
        for rq in state["programs"][name]["requirements"]:
            if rq["status"] == "unproduced":
                rows.append((name, rq["cell"], rq["kind"]))
    _table(w, ["Program", "Cell", "Kind"], rows)
    w("")

    w("## Batch job order")
    w("")
    by_level = collections.defaultdict(list)
    for j in batch["jobs"]:
        by_level[j["level"]].append(j)
    for l in sorted(by_level):
        w("### Level %d" % l)
        w("")
        for j in by_level[l]:
            pre = ", ".join(p["job"] for p in j["predecessors"]) or "-"
            w("- %s (after: %s)" % (j["job"], pre))
        w("")
    w("### Datasets defined by more than one job")
    w("")
    _table(w, ["Dataset", "Definers", "Users"],
           [(m["dataset"], ", ".join(m["definers"]), ", ".join(m["users"])) for m in batch["multi_definer"]])
    w("")
    w("### External inputs")
    w("")
    _table(w, ["Dataset", "Used by"], [(e["dataset"], ", ".join(e["users"])) for e in batch["external_inputs"]])
    w("")
    w("### Jobs the online system depends on")
    w("")
    op = batch["online_prerequisites"]
    for r in op["required_jobs"]:
        w("- %s: %s" % (r["job"], ", ".join(r["datasets"])))
    for o in op["one_of"]:
        w("- one of %s: %s" % (", ".join(o["jobs"]), ", ".join(o["datasets"])))
    for e in op["external"]:
        w("- provided from outside: %s" % e)
    if not (op["required_jobs"] or op["one_of"] or op["external"]):
        w("none")
    w("")

    w("## Warnings")
    w("")
    if not warnings:
        w("none")
    for x in warnings[:100]:
        w("- " + x)
    if len(warnings) > 100:
        w("- ... %d more" % (len(warnings) - 100))
    w("")
    common.write_text(path, "\n".join(lines))
