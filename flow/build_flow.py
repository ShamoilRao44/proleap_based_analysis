#!/usr/bin/env python3
"""Step 4b: state dependency analysis, main entry points and activity flow.

Usage:
    python3 flow/build_flow.py --out <analysis_dir>
"""
import argparse
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow_lib import batch_order, common, diagrams, entry, loaders, process, report, state  # noqa: E402


def now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def build(out_dir):
    data = loaders.load(out_dir)
    st = state.build_state(data)
    known = set(data["final"])
    entries = {}
    for n in data["online"]:
        entries[n] = entry.first_entry(data["final"][n], data["raw"].get(n), known)
    on = process.build_process(data, st, entries)
    batch = batch_order.build_batch(data["graph"])
    main = process.build_main_entry_points(data, st, on, batch)
    gen = now()
    root = data["root"]

    fdir = os.path.join(out_dir, "flow")
    st_doc = dict(st)
    st_doc.update({"generated": gen, "codebase_root": root})
    common.write_json(os.path.join(fdir, "state_dependencies.json"), st_doc)
    common.write_json(os.path.join(fdir, "process_flow.json"),
                      {"schema": "process-flow/1", "generated": gen, "codebase_root": root, "online": on,
                       "batch": batch})
    main_doc = dict(main)
    main_doc.update({"generated": gen, "codebase_root": root})
    common.write_json(os.path.join(fdir, "main_entry_points.json"), main_doc)
    diagrams.write_all(fdir, on, batch)
    warnings = data["warnings"] + st["warnings"]
    report.write_report(os.path.join(fdir, "flow_report.md"), root, st, on, batch, main, warnings)
    return on, batch


def main(argv):
    ap = argparse.ArgumentParser(description="Build the activity flow from the facts and the graph.")
    ap.add_argument("--out", required=True, help="analysis folder (same as for steps 1-4)")
    args = ap.parse_args(argv)
    on, batch = build(args.out)
    print("[flow] %d online programs, %d roots, %d jobs" % (len(on["programs"]), len(on["roots"]),
                                                           len(batch["jobs"])))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
