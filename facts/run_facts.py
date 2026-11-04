#!/usr/bin/env python3
"""Driver for step 2: facts of every COBOL program of a codebase.

Usage:
    python3 facts/run_facts.py --inventory <analysis_dir>/inventory.json --out <analysis_dir>
                               --jar <path>/cobol-ast-runner.jar
                               [--codebase ROOT] [--jobs 1] [--timeout 300] [--xmx 2g]
                               [--only NAME[,NAME...]] [--no-proleap] [--java java]
"""
import argparse
import datetime
import io
import os
import subprocess
import sys
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from facts_lib import common, textscan, build, compare, report  # noqa: E402


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Extract facts of all COBOL programs of a codebase.")
    ap.add_argument("--inventory", required=True, help="inventory.json written by inventory.py")
    ap.add_argument("--out", required=True, help="analysis folder; facts go to <out>/facts")
    ap.add_argument("--jar", help="cobol-ast-runner.jar (not needed with --no-proleap)")
    ap.add_argument("--codebase", help="codebase root (default: from inventory.json)")
    ap.add_argument("--jobs", type=int, default=1, help="parallel Java processes (default 1)")
    ap.add_argument("--timeout", type=int, default=300, help="seconds per program (default 300)")
    ap.add_argument("--xmx", default="2g", help="Java heap per process (default 2g)")
    ap.add_argument("--only", help="comma separated program names")
    ap.add_argument("--no-proleap", action="store_true", help="text scan only")
    ap.add_argument("--java", default="java", help="java executable (default java)")
    return ap.parse_args(argv)


def write_timeout_raw(raw_dir, row, timeout):
    name, path, fmt, charset = row
    common.write_json(os.path.join(raw_dir, name + ".raw.json"), {
        "schema": "cobol-raw-facts/1", "name": name, "program_file": path, "parser": "proleap", "format": fmt,
        "charset": charset, "status": "timeout", "error": "timeout after %d s (driver)" % timeout,
        "parse_ms": 0, "preprocessed_file": None, "missing_copybooks": [], "syntax_error_count": 0,
        "syntax_errors": []})


def run_list(k, rows, list_file, raw_dir, log_file, args, cb_dirs):
    failures = 0
    while True:
        remaining = [r for r in rows if not os.path.exists(os.path.join(raw_dir, r[0] + ".raw.json"))]
        if not remaining:
            break
        cmd = [args.java, "-Xmx" + args.xmx, "-cp", args.jar, "local.cobol.facts.FactsRunner",
               "--list", list_file, "--out", raw_dir, "--timeout-sec", str(args.timeout)]
        for d in cb_dirs:
            cmd += ["--copybooks", d]
        try:
            with open(log_file, "ab") as log:
                p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                   timeout=args.timeout * len(remaining) + 120)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            write_timeout_raw(raw_dir, remaining[0], args.timeout)
            rc = 4
        except OSError as e:
            print("[proleap] list %d: cannot start java: %s" % (k, e))
            return
        print("[proleap] list %d: exit code %d" % (k, rc))
        if rc == 0:
            break
        if rc == 4:
            continue
        failures += 1
        if failures >= 2:
            break


def main(argv):
    args = parse_args(argv)
    inv = common.load_json(args.inventory)
    root = args.codebase or inv["meta"]["codebase_root"]
    out = args.out
    raw_dir = os.path.join(out, "facts", "raw")
    cobol_dir = os.path.join(out, "facts", "cobol")
    logs_dir = os.path.join(out, "facts", "logs")
    for d in (raw_dir, cobol_dir, logs_dir):
        os.makedirs(d, exist_ok=True)

    only = set(x.strip().upper() for x in args.only.split(",")) if args.only else None
    programs = []
    skipped = []
    for f in inv["files"]:
        if f["type"] != "cobol_program":
            continue
        if only and f["name"].upper() not in only:
            continue
        if f.get("encoding") in ("ebcdic", "binary"):
            skipped.append({"name": f["name"], "reason": "skipped_encoding"})
            continue
        programs.append(f)
    programs.sort(key=lambda f: f["name"])

    cb_dirs = sorted(set(os.path.dirname(os.path.abspath(os.path.join(root, f["path"])))
                         for f in inv["files"] if f["type"] in ("copybook", "dclgen")))
    cidx = {}
    for f in inv["files"]:
        if f["type"] in ("copybook", "dclgen"):
            cidx.setdefault(f["name"].upper(), []).append(f["path"])

    def fmt_of(f):
        return "FIXED" if f.get("source_format") == "fixed" else "VARIABLE"

    rows = [(f["name"], os.path.abspath(os.path.join(root, f["path"])), fmt_of(f),
             "ISO-8859-1" if f.get("encoding") == "latin-1" else "UTF-8") for f in programs]

    if not args.no_proleap and rows:
        if not args.jar:
            print("--jar is required unless --no-proleap is given")
            return 1
        jobs = max(1, min(args.jobs, len(rows)))
        lists = [rows[i::jobs] for i in range(jobs)]
        threads = []
        for k, lst in enumerate(lists):
            lf = os.path.join(logs_dir, "list_%d.tsv" % k)
            with io.open(lf, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("".join("\t".join(r) + "\n" for r in lst))
            t = threading.Thread(target=run_list, args=(k, lst, lf, raw_dir,
                                                        os.path.join(logs_dir, "java_%d.log" % k), args, cb_dirs))
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

    finals = {}
    diffs = {}
    entries = []
    n_proleap = n_text = 0
    err_log = os.path.join(logs_dir, "build_errors.log")
    if os.path.exists(err_log):
        os.remove(err_log)

    def log_error(name, text):
        with io.open(err_log, "a", encoding="utf-8") as fh:
            fh.write("== %s\n%s\n" % (name, text))

    for f in programs:
        name = f["name"]
        path = os.path.abspath(os.path.join(root, f["path"]))
        fmt = fmt_of(f)
        orig = common.split_lines(common.read_text(path))
        ctx = {"codebase_root": root, "inventory_record": f, "copybook_index": cidx, "original_lines": orig}

        text_final = None
        text_raw = None
        try:
            text_raw = textscan.scan(path, fmt, name, cidx)
            text_final = build.build(text_raw, orig, ctx)
        except Exception:
            log_error(name, traceback.format_exc())

        final = None
        diff = {}
        reason = None
        raw_path = os.path.join(raw_dir, name + ".raw.json")
        raw = None
        if args.no_proleap or not os.path.exists(raw_path):
            reason = "no_proleap_output"
        else:
            raw = common.load_json(raw_path)
            if raw.get("status") not in ("ok", "syntax_errors"):
                reason = "status_%s" % raw.get("status")
            elif not (raw.get("divisions") or {}).get("procedure"):
                reason = "no_procedure_division"
            elif not raw.get("paragraphs") and text_raw is not None and text_raw.get("paragraphs"):
                reason = "no_paragraphs_found"
        if reason is None:
            try:
                pp = common.split_lines(common.read_text(os.path.join(raw_dir, raw["preprocessed_file"])))
                final = build.build(raw, pp, ctx)
                if text_final is not None:
                    diff = compare.compare(final, text_final)
                    final = compare.merge_text_only(final, text_final, diff)
            except Exception:
                log_error(name, traceback.format_exc())
                final = None
                diff = {}
                reason = "build_error"
        if final is None:
            final = text_final
            if final is not None:
                final["quality"]["fallback_reason"] = reason
                if raw is not None and raw.get("missing_copybooks") and not final["quality"]["missing_copybooks"]:
                    final["quality"]["missing_copybooks"] = raw["missing_copybooks"]

        if final is None:
            skipped.append({"name": name, "reason": "build_failed"})
            entries.append({"name": name, "path": f["path"], "source": None, "status": "build_failed",
                            "kind": None, "facts_file": None})
            continue

        common.write_json(os.path.join(cobol_dir, name + ".json"), final)
        finals[name] = final
        if diff:
            diffs[name] = diff
        if final["source"] == "proleap":
            n_proleap += 1
        else:
            n_text += 1
        entries.append({"name": name, "path": f["path"], "source": final["source"],
                        "status": final["quality"]["status"], "kind": final["kind"],
                        "facts_file": "cobol/%s.json" % name})

    for s in skipped:
        if s["reason"] == "skipped_encoding":
            entries.append({"name": s["name"], "path": None, "source": None, "status": "skipped_encoding",
                            "kind": None, "facts_file": None})

    report.write_index(out, entries, root)
    report.write_report(out, finals, diffs, {
        "codebase_root": root, "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "skipped": skipped})
    n_skipped = len(skipped)
    print("[facts] %d programs: %d proleap, %d text, %d skipped" % (
        len(finals) + n_skipped, n_proleap, n_text, n_skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
