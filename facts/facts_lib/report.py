"""Index file and readable report of a facts run."""
import datetime
import io
import os

from . import common


def write_index(out_dir, entries, codebase_root=None):
    """facts/_index.json"""
    obj = {"schema": "cobol-facts-index/1", "generated": datetime.datetime.now().isoformat(timespec="seconds"),
           "codebase_root": codebase_root, "programs": entries}
    common.write_json(os.path.join(out_dir, "facts", "_index.json"), obj)


def _unresolved(final):
    out = []
    for t in final["transfers"]:
        if t["unresolved"]:
            out.append((t["kind"], (t["target"] or {}).get("text") or (t["target"] or {}).get("var"), t["loc"]))
    for r in final["resources"]:
        if r["unresolved"]:
            nm = r["name"] or {}
            out.append((r["kind"], nm.get("text") or nm.get("var"), r["loc"]))
    return out


def write_report(out_dir, finals, diffs, meta):
    """facts/facts_report.md"""
    names = sorted(finals)
    skipped = meta.get("skipped") or []
    lines = []
    w = lines.append
    w("# COBOL facts: %s" % meta.get("codebase_root"))
    w("")
    w("Generated %s. %d programs with facts, %d skipped." % (
        meta.get("generated") or datetime.datetime.now().isoformat(timespec="seconds"), len(names), len(skipped)))
    w("")
    w("## Summary")
    w("")
    w("| Program | Source | Status | Syntax errors | Line map exact | Kind | Paragraphs | Dead | "
      "Transfers (unresolved) | Resources (unresolved) | Missing copybooks |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    for n in names:
        f = finals[n]
        q = f["quality"]
        tu = sum(1 for t in f["transfers"] if t["unresolved"])
        ru = sum(1 for r in f["resources"] if r["unresolved"])
        w("| %s | %s | %s | %d | %.1f%% | %s | %d | %d | %d (%d) | %d (%d) | %d |" % (
            n, f["source"], q["status"], q["syntax_error_count"], q["line_map_exact_ratio"] * 100, f["kind"],
            len(f["procedure"]["paragraphs"]), len(f["dead_paragraphs"]), len(f["transfers"]), tu,
            len(f["resources"]), ru, len(q["missing_copybooks"])))
    for s in skipped:
        w("| %s | - | %s | - | - | - | - | - | - | - | - |" % (s["name"], s["reason"]))
    w("")

    w("## Programs using the text fallback")
    w("")
    fb = [(n, finals[n]["quality"].get("fallback_reason")) for n in names if finals[n]["source"] == "text"]
    if not fb:
        w("none")
    for n, reason in fb:
        w("- %s: %s" % (n, reason))
    w("")

    w("## Unresolved dynamic targets")
    w("")
    rows = []
    for n in names:
        for kind, var, loc in _unresolved(finals[n]):
            rows.append((n, kind, var, loc))
    if not rows:
        w("none")
    else:
        w("| Program | Kind | Variable | Location |")
        w("|---|---|---|---|")
        for n, kind, var, loc in rows:
            fname = finals[n]["files"][loc[0]]["path"] if loc[0] < len(finals[n]["files"]) else "?"
            w("| %s | %s | %s | %s:%s |" % (n, kind, var, fname, loc[1]))
    w("")

    w("## Missing copybooks")
    w("")
    missing = {}
    for n in names:
        for m in finals[n]["quality"]["missing_copybooks"]:
            missing.setdefault(m, []).append(n)
    if not missing:
        w("none")
    for m in sorted(missing):
        w("- %s: %s" % (m, ", ".join(missing[m])))
    w("")

    w("## Parser vs text differences")
    w("")
    any_diff = False
    for n in sorted(diffs):
        for cat, d in sorted(diffs[n].items()):
            any_diff = True
            w("- %s / %s: proleap_only %s; text_only %s" % (n, cat, d["proleap_only"] or "-", d["text_only"] or "-"))
    if not any_diff:
        w("none")
    w("")

    w("## Top unresolved data names")
    w("")
    total = {}
    for n in names:
        for u in finals[n]["unresolved_names"]:
            total[u["name"]] = total.get(u["name"], 0) + u["count"]
    if not total:
        w("none")
    else:
        w("| Name | Uses |")
        w("|---|---|")
        for name, cnt in sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))[:50]:
            w("| %s | %d |" % (name, cnt))
    w("")

    path = os.path.join(out_dir, "facts", "facts_report.md")
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
