"""Load graph, final facts and raw facts."""
import glob
import os

from . import common


def load(out_dir):
    graph = common.load_json(os.path.join(out_dir, "graph", "graph.json"))
    final = {}
    for p in sorted(glob.glob(os.path.join(out_dir, "facts", "cobol", "*.json"))):
        if os.path.basename(p).startswith("_"):
            continue
        d = common.load_json(p)
        final[d["name"]] = d
    raw = {}
    for p in sorted(glob.glob(os.path.join(out_dir, "facts", "raw", "*.raw.json"))):
        d = common.load_json(p)
        raw[d["name"]] = d
    warnings = []
    for n in sorted(final):
        if n not in raw:
            warnings.append("no raw facts for %s: statement-level analysis skipped" % n)
    return {"root": graph.get("codebase_root"), "final": final, "raw": raw, "graph": graph,
            "online": sorted(n for n, d in final.items() if d.get("kind") == "cics_online"),
            "warnings": warnings}
