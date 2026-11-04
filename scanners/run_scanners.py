#!/usr/bin/env python3
"""Driver for step 3: scanners for CSD, JCL/PROC, BMS, DDL/DCLGEN, IMS and control cards.

Usage:
    python3 scanners/run_scanners.py --inventory <analysis_dir>/inventory.json --out <analysis_dir>
                                     [--codebase ROOT] [--only NAME[,NAME...]]
"""
import argparse
import glob
import io
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scan_lib import bms, common, control, crosscheck, csd, ddl, ims, jcl, report  # noqa: E402

TYPE_TO_KIND = {"csd": "csd", "jcl": "jcl", "proc": "proc", "bms": "bms", "ddl": "ddl", "dclgen": "ddl",
                "ims_dbd": "ims", "ims_psb": "ims", "control_card": "control"}


class LazyMembers(object):
    """Lines of JCL-like members by upper member name, read on demand."""

    def __init__(self, root, recs):
        self.root = root
        self.paths = {}
        self.cache = {}
        for r in sorted(recs, key=lambda x: x["path"]):
            self.paths.setdefault(r["name"].upper(), os.path.join(root, r["path"]))

    def get(self, name, default=None):
        key = name.upper()
        if key not in self.paths:
            return default
        if key not in self.cache:
            self.cache[key] = common.split_lines(common.read_text(self.paths[key]))
        return self.cache[key]


def main(argv):
    ap = argparse.ArgumentParser(description="Scan CSD, JCL, BMS, DDL, IMS and control card files.")
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--codebase")
    ap.add_argument("--only")
    args = ap.parse_args(argv)

    inv = common.load_json(args.inventory)
    root = args.codebase or inv["meta"]["codebase_root"]
    out = args.out
    only = set(x.strip().upper() for x in args.only.split(",")) if args.only else None
    os.makedirs(os.path.join(out, "facts", "logs"), exist_ok=True)
    err_log = os.path.join(out, "facts", "logs", "scan_errors.log")
    if os.path.exists(err_log):
        os.remove(err_log)

    files = sorted(inv["files"], key=lambda f: f["path"])
    symbolic = {}
    for f in files:
        if f["type"] == "copybook" and f.get("subtype") == "bms_symbolic_map":
            symbolic.setdefault(f["name"].upper(), f["path"])
    member_types = ("jcl", "proc", "control_card", "other_source", "unknown")
    members = LazyMembers(root, [f for f in files if f["type"] in member_types
                                 and f.get("encoding") not in ("ebcdic", "binary")])
    source_names = set()
    for f in files:
        if f["type"] in ("cobol_program", "assembler"):
            source_names.add(f["name"].upper())
            if f.get("declared_name"):
                source_names.add(f["declared_name"].upper())
    ctx = {"procs": {}, "members": members}

    def log_error(f, text):
        with io.open(err_log, "a", encoding="utf-8") as fh:
            fh.write("== %s\n%s\n" % (f["path"], text))

    def path_of(f):
        return os.path.join(root, f["path"])

    # pass 1: PROC members (unexpanded)
    procs = [f for f in files if f["type"] == "proc" and f.get("encoding") not in ("ebcdic", "binary")]
    declared = {}
    for f in procs:
        try:
            lines = common.split_lines(common.read_text(path_of(f)))
            raw = jcl.parse_member(lines, f["name"], ctx)
            ctx["procs"][f["name"].upper()] = raw
            if raw["declared_name"]:
                declared.setdefault(raw["declared_name"].upper(), raw)
        except Exception:
            log_error(f, traceback.format_exc())
    for k, v in declared.items():
        ctx["procs"].setdefault(k, v)

    # passes 2 and 3
    entries = []
    facts = dict((k, []) for k in ("csd", "jcl", "proc", "bms", "ddl", "ims", "control"))
    used_names = {}
    ok = errors = skipped = 0
    order = [f for f in files if f["type"] in TYPE_TO_KIND and f["type"] not in ("jcl", "proc")] + \
            [f for f in files if f["type"] in ("jcl", "proc")]
    for f in order:
        kind = TYPE_TO_KIND[f["type"]]
        if only and f["name"].upper() not in only:
            continue
        entry = {"kind": kind, "name": f["name"], "facts_name": None, "path": f["path"], "facts_file": None,
                 "status": "ok", "summary": {}}
        if f.get("encoding") in ("ebcdic", "binary"):
            entry["status"] = "skipped_encoding"
            skipped += 1
            entries.append(entry)
            continue
        try:
            p = path_of(f)
            if kind == "csd":
                res = csd.scan_file(p, f, root)
            elif kind in ("jcl", "proc"):
                res = jcl.scan_file(p, f, root, ctx)
            elif kind == "bms":
                res = bms.scan_file(p, f, root, symbolic)
            elif kind == "ddl":
                res = ddl.scan_file(p, f, root)
            elif kind == "ims":
                res = ims.scan_file(p, f, root)
            else:
                res = control.scan_file(p, f, root)
            n = used_names.get((kind, f["name"]), 0) + 1
            used_names[(kind, f["name"])] = n
            fname = f["name"] if n == 1 else "%s~%d" % (f["name"], n)
            rel = "%s/%s.json" % (kind, fname)
            common.write_json(os.path.join(out, "facts", rel), res)
            entry["facts_name"] = fname
            entry["facts_file"] = rel
            entry["summary"] = res.get("summary", {})
            facts[kind].append(res)
            ok += 1
        except Exception:
            entry["status"] = "error"
            log_error(f, traceback.format_exc())
            errors += 1
        entries.append(entry)

    # cobol facts (step 2), if present
    cobol = {}
    for p in glob.glob(os.path.join(out, "facts", "cobol", "*.json")):
        if os.path.basename(p).startswith("_"):
            continue
        try:
            c = common.load_json(p)
            cobol[c.get("name") or os.path.splitext(os.path.basename(p))[0]] = c
        except Exception:
            pass

    checks = crosscheck.compute({"csd": facts["csd"], "jcl": facts["jcl"], "proc": facts["proc"],
                                 "bms": facts["bms"], "ddl": facts["ddl"], "source_names": source_names,
                                 "cobol": cobol})
    not_scanned = {}
    for f in files:
        if f["type"] in ("assembler", "asm_macro"):
            not_scanned[f["type"]] = not_scanned.get(f["type"], 0) + 1
    report.write_index(out, entries, root)
    report.write_report(out, {"root": root, "entries": entries, "facts": facts, "checks": checks,
                              "not_scanned": not_scanned})
    print("[scan] %d files: %d ok, %d errors, %d skipped" % (len(entries), ok, errors, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
