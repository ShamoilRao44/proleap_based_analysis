#!/usr/bin/env python3
"""Step 4: dependency graph of a codebase.

Usage:
    python3 graph/build_graph.py --out <analysis_dir> [--inventory <analysis_dir>/inventory.json]
"""
import argparse
import csv
import datetime
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from graph_lib import analysis, batch, common, loaders, mermaid, model, names, online, report  # noqa: E402


def build(out_dir, inventory_path):
    data = loaders.load_all(out_dir, inventory_path)
    r = names.Resolver(data)
    g = model.Graph()
    online.add_online(g, r, data)
    batch.add_batch(g, r, data)
    ana, entries = analysis.run(g, r, data)
    unresolved = sorted(r.unresolved, key=lambda u: (u["kind"], json.dumps(u, sort_keys=True)))
    d = g.to_dict()
    nodes_by_type = {}
    for n in d["nodes"]:
        nodes_by_type[n["type"]] = nodes_by_type.get(n["type"], 0) + 1
    edges_by_type = {}
    for e in d["edges"]:
        edges_by_type[e["type"]] = edges_by_type.get(e["type"], 0) + 1
    doc = {"schema": "cobol-graph/1", "generated": datetime.datetime.now().isoformat(timespec="seconds"),
           "codebase_root": data["root"],
           "inputs": {"cobol": len(data["cobol"]), "csd": len(data["csd"]), "jcl": len(data["jcl"]),
                      "proc": len(data["proc"]), "bms": len(data["bms"]), "ddl": len(data["ddl"]),
                      "ims": len(data["ims"]), "control": len(data["control"])},
           "stats": {"nodes_by_type": dict(sorted(nodes_by_type.items())),
                     "edges_by_type": dict(sorted(edges_by_type.items()))},
           "nodes": d["nodes"], "edges": d["edges"], "entry_points": entries, "unresolved": unresolved,
           "analysis": ana}
    entry_doc = analysis.entry_points_doc(g, r, data["root"])

    gdir = os.path.join(out_dir, "graph")
    common.write_json(os.path.join(gdir, "graph.json"), doc)
    common.write_json(os.path.join(gdir, "entry_points.json"), entry_doc)
    with io.open(os.path.join(gdir, "nodes.csv"), "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f, lineterminator="\n")
        wr.writerow(["id", "type", "name", "in_codebase"])
        for n in d["nodes"]:
            wr.writerow([n["id"], n["type"], n["name"], n["in_codebase"]])
    with io.open(os.path.join(gdir, "edges.csv"), "w", encoding="utf-8", newline="") as f:
        wr = csv.writer(f, lineterminator="\n")
        wr.writerow(["id", "type", "strength", "source", "target", "access", "count"])
        for e in d["edges"]:
            wr.writerow([e["id"], e["type"], e["strength"], e["source"], e["target"], e["access"], e["count"]])
    mermaid.write_all(g, gdir)
    report.write_report(os.path.join(gdir, "graph_report.md"), g, doc, ana, entry_doc, unresolved, data["root"])
    return doc, entry_doc


def main(argv):
    ap = argparse.ArgumentParser(description="Build the dependency graph from the facts of steps 1 to 3.")
    ap.add_argument("--out", required=True, help="analysis folder (same as for steps 1-3)")
    ap.add_argument("--inventory", help="inventory.json (default: <out>/inventory.json)")
    args = ap.parse_args(argv)
    inv = args.inventory or os.path.join(args.out, "inventory.json")
    doc, entry_doc = build(args.out, inv)
    print("[graph] %d nodes, %d edges, %d entry points" % (len(doc["nodes"]), len(doc["edges"]),
                                                          entry_doc["summary"]["entry_points"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
