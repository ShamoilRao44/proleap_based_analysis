"""scan_index.json and scan_report.md"""
import datetime
import io
import os

from . import common

KINDS = ["csd", "jcl", "proc", "bms", "ddl", "ims", "control"]


def write_index(out_dir, entries, root):
    obj = {"schema": "scan-index/1", "generated": datetime.datetime.now().isoformat(timespec="seconds"),
           "codebase_root": root, "entries": entries}
    common.write_json(os.path.join(out_dir, "facts", "scan_index.json"), obj)


def _table(w, header, rows):
    w("| " + " | ".join(header) + " |")
    w("|" + "|".join("---" for _ in header) + "|")
    for r in rows:
        w("| " + " | ".join(str(x) for x in r) + " |")


def _list(w, rows, header):
    if not rows:
        w("none")
        return
    _table(w, header, rows)


def write_report(out_dir, data):
    """data: root, entries, facts {kind: [facts]}, checks, not_scanned {type: n}, unresolved, skipped"""
    entries = data["entries"]
    facts = data["facts"]
    checks = data["checks"]
    lines = []
    w = lines.append
    w("# Scan report: %s" % data["root"])
    w("")
    w("Generated %s. %d files." % (datetime.datetime.now().isoformat(timespec="seconds"), len(entries)))
    w("")

    w("## Summary by kind")
    w("")
    rows = []
    for k in KINDS:
        es = [e for e in entries if e["kind"] == k]
        rows.append((k, len(es), sum(1 for e in es if e["status"] == "error"),
                     sum(1 for e in es if e["status"] == "skipped_encoding")))
    _table(w, ["Kind", "Files", "Errors", "Skipped"], rows)
    w("")
    ns = data["not_scanned"]
    w("Not scanned by this step: assembler %d, asm_macro %d" % (ns.get("assembler", 0), ns.get("asm_macro", 0)))
    w("")

    w("## CSD")
    w("")
    any_csd = False
    for f in facts.get("csd", []):
        any_csd = True
        w("- %s: %s" % (f["name"], ", ".join("%s %d" % kv for kv in f["summary"]["by_type"].items()) or "empty"))
    for kind in ("jcl", "proc"):
        for f in facts.get(kind, []):
            for s in (f.get("flat_steps") or f.get("steps") or []):
                ic = s.get("utility_data", {}).get("inline_csd")
                if ic:
                    any_csd = True
                    cnt = {}
                    for d in ic["definitions"]:
                        cnt[d["type"]] = cnt.get(d["type"], 0) + 1
                    w("- %s (inline, step %s): %s" % (f["name"], s["name"],
                                                      ", ".join("%s %d" % kv for kv in sorted(cnt.items()))))
    if not any_csd:
        w("none")
    w("")

    w("## JCL")
    w("")
    rows = []
    for kind in ("jcl", "proc"):
        for f in facts.get(kind, []):
            nf = [s for s in (f.get("flat_steps") or []) if s["kind"] == "proc" and s.get("proc_found") is False]
            nf_names = sorted(set(s["proc"] for s in nf)) or sorted(
                u["name"] for u in f.get("procs_used", []) if not u["found"])
            rows.append((f["name"], f["kind"], f["summary"]["steps"], f["summary"]["flat_steps"],
                         len(f["programs_run"]), ", ".join(nf_names) or "-", len(f["unresolved_symbols"])))
    _list(w, rows, ["Member", "Kind", "Steps", "Flat steps", "Programs run", "Procs not found",
                    "Unresolved symbols"])
    w("")

    w("## Cross-checks")
    w("")
    w("### C1 CSD programs without source")
    w("")
    w("CSD files:")
    w("")
    _list(w, checks["C1_files"], ["CSD file", "Program"])
    w("")
    w("Inline CSDs in JCL:")
    w("")
    _list(w, checks["C1_inline"], ["JCL member", "Step", "Program"])
    w("")
    w("### C2 CSD transactions whose program has no PROGRAM definition in the same CSD file")
    w("")
    _list(w, checks["C2"], ["CSD file", "Transaction", "Program"])
    w("")
    w("### C3 Mapsets")
    w("")
    w("(a) MAPSET definitions in CSD files without BMS source:")
    w("")
    _list(w, checks["C3_a"], ["CSD file", "Mapset"])
    w("")
    w("(b) MAPSET definitions in inline CSDs without BMS source (informational):")
    w("")
    _list(w, checks["C3_b"], ["JCL member", "Step", "Mapset"])
    w("")
    w("(c) BMS mapsets without any MAPSET definition in CSD files or inline CSDs:")
    w("")
    _list(w, checks["C3_c"], ["BMS file", "Mapset"])
    w("")
    w("### C4 JCL programs not in the codebase")
    w("")
    _list(w, checks["C4"], ["JCL member", "Step", "Program"])
    w("")
    w("### C5 Procs not found")
    w("")
    _list(w, checks["C5"], ["JCL member", "Step", "Proc"])
    w("")
    if not checks["has_cobol"]:
        for t in ("C6 CICS files used by COBOL but not defined in any CSD FILE",
                  "C7 Batch DD names", "C8 Mapsets used by COBOL without BMS source and without CSD MAPSET",
                  "C9 DB2 tables used by COBOL but not defined in DDL, DCLGEN or inline SQL"):
            w("### " + t)
            w("")
            w("skipped: no COBOL facts found")
            w("")
    else:
        w("### C6 CICS files used by COBOL but not defined in any CSD FILE")
        w("")
        _list(w, checks["C6"], ["Program", "File"])
        w("")
        w("### C7 Batch DD names")
        w("")
        w("(a) expected by the program but missing in the step:")
        w("")
        _list(w, [(a, b, c, ", ".join(d)) for a, b, c, d in checks["C7_missing"]],
              ["JCL member", "Step", "Program", "Missing DDs"])
        w("")
        w("(b) present in the step but not used by the program:")
        w("")
        _list(w, [(a, b, c, ", ".join(d)) for a, b, c, d in checks["C7_extra"]],
              ["JCL member", "Step", "Program", "Extra DDs"])
        w("")
        w("### C8 Mapsets used by COBOL without BMS source and without CSD MAPSET")
        w("")
        _list(w, checks["C8"], ["Program", "Mapset"])
        w("")
        w("### C9 DB2 tables used by COBOL but not defined in DDL, DCLGEN or inline SQL (informational)")
        w("")
        _list(w, checks["C9"], ["Program", "Table"])
        w("")

    w("## Unresolved JCL symbols")
    w("")
    rows = []
    for kind in ("jcl", "proc"):
        for f in facts.get(kind, []):
            if f["unresolved_symbols"]:
                rows.append((f["name"], ", ".join(f["unresolved_symbols"])))
    _list(w, rows, ["Member", "Names"])
    w("")

    w("## Warnings")
    w("")
    allw = []
    counts = {}
    for kind in KINDS:
        for f in facts.get(kind, []):
            for msg in f.get("warnings", []):
                allw.append((kind, f["name"], msg))
                counts[kind] = counts.get(kind, 0) + 1
    if not allw:
        w("none")
    else:
        w("Counts: " + ", ".join("%s %d" % kv for kv in sorted(counts.items())))
        w("")
        for kind, name, msg in allw[:50]:
            w("- %s %s: %s" % (kind, name, msg))
    w("")
    path = os.path.join(out_dir, "facts", "scan_report.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
