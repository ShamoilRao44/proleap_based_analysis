#!/usr/bin/env python3
"""
fetch_copybooks.py - collect the copybooks a COBOL program needs, from a large source tree.

Given one isolated COBOL program file and the root of the full codebase, this script:
  1. finds every COPY statement in the program,
  2. looks the copybook names up (case-insensitively) anywhere under the codebase root,
  3. copies the matches into <directory of the program>/copybooks/ (flat, no subfolders),
  4. repeats on the copybooks it just copied (nested COPY), but only for names not
     already handled, until no new names appear,
  5. reports which copybooks could not be found.

Only the Python standard library is used (Python 3.8+).

Usage:
  python fetch_copybooks.py <program_file> <codebase_root> [options]

Examples:
  python fetch_copybooks.py /work/isolated/CUCO003 /data/codebase
  python fetch_copybooks.py /work/isolated/CUCO003 /data/codebase --stub-missing
  python fetch_copybooks.py /work/isolated/PGM1.cbl /data/codebase --format free

Exit codes:
  0  all copybooks found
  1  invalid arguments / input
  2  finished, but some copybooks could not be found
"""

import argparse
import json
import os
import re
import shutil
import sys
from collections import OrderedDict

# ---------------------------------------------------------------------------
# COBOL source reading
# ---------------------------------------------------------------------------

# characters allowed in a COBOL word / PDS member name
NAME_CHARS = r"A-Za-z0-9\-_#@$"

# COPY must be a standalone word: not part of e.g. WS-COPY-FLAG
COPY_PATTERN = re.compile(
    r"(?<![" + NAME_CHARS + r"])COPY\s+"
    r"(?:\"(?P<dq>[^\"]+)\"|'(?P<sq>[^']+)'|(?P<word>[" + NAME_CHARS + r"]+))"
    r"(?:\s+(?:OF|IN)\s+(?:\"(?P<libdq>[^\"]+)\"|'(?P<libsq>[^']+)'|(?P<libword>[" + NAME_CHARS + r"]+)))?",
    re.IGNORECASE,
)

LITERAL_PATTERN = re.compile(r"'[^']*'|\"[^\"]*\"")

COMMENT_INDICATORS = ("*", "/")


def read_text(path):
    """Read a source file without failing on odd bytes (mainframe transfers often contain them)."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def extract_code(text, source_format):
    """
    Return the code part of a COBOL source as one string, with comment lines removed.

    fixed    : columns 1-6 sequence area, column 7 indicator, code in columns 8-72
    variable : like fixed, but code runs from column 8 to end of line
    free     : whole line is code, '*>' starts a comment
    Floating comments ('*>') are stripped in every format.
    Each returned line keeps its original line number (as a list of (lineno, code)).
    """
    result = []

    for lineno, line in enumerate(text.splitlines(), start=1):
        line = line.rstrip("\r\n")

        if source_format == "free":
            code = line
        else:
            if len(line) < 7:
                continue

            indicator = line[6]

            if indicator in COMMENT_INDICATORS:
                continue

            code = line[7:72] if source_format == "fixed" else line[7:]

        comment_start = find_floating_comment(code)

        if comment_start >= 0:
            code = code[:comment_start]

        if code.strip():
            result.append((lineno, code))

    return result


def find_floating_comment(code):
    """Position of a '*>' that is not inside a literal, or -1."""
    in_quote = None

    for i, ch in enumerate(code):
        if in_quote:
            if ch == in_quote:
                in_quote = None
        elif ch in ("'", '"'):
            in_quote = ch
        elif ch == "*" and code[i + 1:i + 2] == ">":
            return i

    return -1


def find_copy_statements(text, source_format):
    """
    Find COPY statements in a COBOL source.

    Returns a list of dicts: {name, library, line}.
    COPY statements may span lines, so the code lines are joined before matching;
    a COPY keyword that sits inside a string literal (e.g. DISPLAY 'COPY X') is ignored.
    """
    lines = extract_code(text, source_format)

    # join lines, remembering where each line starts so matches map back to line numbers
    joined_parts = []
    line_starts = []
    offset = 0

    for lineno, code in lines:
        line_starts.append((offset, lineno))
        joined_parts.append(code)
        offset += len(code) + 1

    joined = " ".join(joined_parts)
    literal_spans = [m.span() for m in LITERAL_PATTERN.finditer(joined)]

    def inside_literal(pos):
        for start, end in literal_spans:
            if start <= pos < end:
                return True
            if start > pos:
                break
        return False

    def line_of(pos):
        result = None
        for start, lineno in line_starts:
            if start > pos:
                break
            result = lineno
        return result

    copies = []

    for m in COPY_PATTERN.finditer(joined):
        if inside_literal(m.start()):
            continue

        name = m.group("dq") or m.group("sq") or m.group("word")
        library = m.group("libdq") or m.group("libsq") or m.group("libword")

        copies.append({
            "name": name.strip(),
            "library": library.strip() if library else None,
            "line": line_of(m.start()),
        })

    return copies


# ---------------------------------------------------------------------------
# Codebase index and lookup
# ---------------------------------------------------------------------------

def name_key(name):
    """Case-insensitive lookup key: file name without directory and without extension."""
    base = os.path.basename(name.replace("\\", "/"))
    stem, _ = os.path.splitext(base)
    return (stem or base).upper()


def build_index(codebase_root, exclude_dirs):
    """Map NAME (upper case, no extension) -> list of file paths, for every file under the root."""
    index = {}
    exclude = {os.path.normcase(os.path.abspath(d)) for d in exclude_dirs}
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(codebase_root):
        # do not descend into our own output folder if it lies inside the codebase
        dirnames[:] = [
            d for d in dirnames
            if os.path.normcase(os.path.abspath(os.path.join(dirpath, d))) not in exclude
        ]

        for filename in filenames:
            path = os.path.join(dirpath, filename)
            index.setdefault(name_key(filename), []).append(path)
            file_count += 1

    return index, file_count


def choose_candidate(candidates, library, program_path):
    """
    Pick one file among several with the same copybook name.
    Preference: a file whose folder path contains the OF/IN library name, then a file without
    extension, then the first in sorted order. The program file itself is never chosen.
    """
    program_abs = os.path.normcase(os.path.abspath(program_path))
    candidates = sorted(c for c in candidates if os.path.normcase(os.path.abspath(c)) != program_abs)

    if not candidates:
        return None

    if library:
        lib = library.upper()
        for c in candidates:
            folders = [p.upper() for p in os.path.normpath(os.path.dirname(c)).split(os.sep)]
            if lib in folders:
                return c

    for c in candidates:
        if not os.path.splitext(os.path.basename(c))[1]:
            return c

    return candidates[0]


# ---------------------------------------------------------------------------
# Main resolution loop
# ---------------------------------------------------------------------------

def fetch_copybooks(program_path, codebase_root, source_format, stub_missing):
    program_dir = os.path.dirname(os.path.abspath(program_path))
    copybook_dir = os.path.join(program_dir, "copybooks")
    os.makedirs(copybook_dir, exist_ok=True)

    print("Indexing files under {} ...".format(codebase_root))
    index, file_count = build_index(codebase_root, exclude_dirs=[copybook_dir])
    print("Indexed {} files ({} distinct names).".format(file_count, len(index)))

    # NAME -> record; insertion order = discovery order
    found = OrderedDict()
    missing = OrderedDict()
    duplicates = OrderedDict()

    # first iteration: COPY statements of the program itself
    current_sources = [(program_path, os.path.basename(program_path))]
    iteration = 0

    while current_sources:
        iteration += 1
        next_sources = []
        print("\nIteration {}: scanning {} file(s)".format(iteration, len(current_sources)))

        for source_path, source_label in current_sources:
            for copy in find_copy_statements(read_text(source_path), source_format):
                key = name_key(copy["name"])
                reference = {"from": source_label, "line": copy["line"]}

                # already handled in this or an earlier iteration: only record the extra reference
                if key in found:
                    found[key]["referenced_by"].append(reference)
                    continue
                if key in missing:
                    missing[key]["referenced_by"].append(reference)
                    continue

                candidates = index.get(key, [])
                chosen = choose_candidate(candidates, copy["library"], program_path)

                if chosen is None:
                    missing[key] = {"name": key, "library": copy["library"], "referenced_by": [reference]}
                    print("  MISSING  {:<20} (from {} line {})".format(key, source_label, copy["line"]))
                    continue

                destination = os.path.join(copybook_dir, os.path.basename(chosen))
                shutil.copyfile(chosen, destination)

                found[key] = {
                    "name": key,
                    "library": copy["library"],
                    "source": chosen,
                    "copied_to": destination,
                    "iteration": iteration,
                    "referenced_by": [reference],
                }
                print("  found    {:<20} <- {}".format(key, chosen))

                if len(candidates) > 1:
                    duplicates[key] = {"chosen": chosen, "candidates": sorted(candidates)}

                # scan this copybook in the next iteration
                next_sources.append((destination, os.path.basename(destination)))

        current_sources = next_sources

    stubs = []
    if stub_missing:
        for key in missing:
            stub_path = os.path.join(copybook_dir, key)
            if not os.path.exists(stub_path):
                open(stub_path, "w").close()
                stubs.append(stub_path)

    return {
        "program": os.path.abspath(program_path),
        "codebase_root": os.path.abspath(codebase_root),
        "copybook_dir": copybook_dir,
        "format": source_format,
        "iterations": iteration,
        "found": list(found.values()),
        "missing": list(missing.values()),
        "duplicates": duplicates,
        "stubs_created": stubs,
        "extensions_copied": sorted({os.path.splitext(r["copied_to"])[1] for r in found.values()}),
    }


def write_reports(report):
    program_dir = os.path.dirname(report["program"])

    json_path = os.path.join(program_dir, "copybook_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    missing_path = os.path.join(program_dir, "missing_copybooks.txt")
    with open(missing_path, "w", encoding="utf-8") as f:
        for record in report["missing"]:
            refs = ", ".join("{} line {}".format(r["from"], r["line"]) for r in record["referenced_by"])
            f.write("{}\t{}\n".format(record["name"], refs))

    return json_path, missing_path


def print_summary(report, json_path, missing_path):
    print("\n" + "=" * 70)
    print("Program          : {}".format(report["program"]))
    print("Copybook folder  : {}".format(report["copybook_dir"]))
    print("Iterations       : {}".format(report["iterations"]))
    print("Copybooks found  : {}".format(len(report["found"])))
    print("Copybooks missing: {}".format(len(report["missing"])))

    if report["extensions_copied"]:
        shown = ", ".join("'{}'".format(e) if e else "(none)" for e in report["extensions_copied"])
        print("File extensions  : {}  (configure these as copybook extensions in the parser)".format(shown))

    if report["duplicates"]:
        print("\nSame name found in several places (first choice was copied, check these):")
        for key, dup in report["duplicates"].items():
            print("  {}".format(key))
            for c in dup["candidates"]:
                print("    {} {}".format("*" if c == dup["chosen"] else " ", c))

    if report["missing"]:
        print("\nCopybooks NOT found:")
        for record in report["missing"]:
            refs = ", ".join("{} line {}".format(r["from"], r["line"]) for r in record["referenced_by"])
            print("  {:<20} referenced by {}".format(record["name"], refs))
        if report["stubs_created"]:
            print("\nEmpty stub files were created for the missing copybooks.")

    print("\nReport           : {}".format(json_path))
    print("Missing list     : {}".format(missing_path))


def main():
    parser = argparse.ArgumentParser(
        description="Copy the copybooks a COBOL program needs (recursively) into <program dir>/copybooks.")
    parser.add_argument("program", help="the isolated COBOL program file")
    parser.add_argument("codebase_root", help="root folder of the full codebase to search")
    parser.add_argument("--format", choices=["fixed", "variable", "free"], default="fixed",
                        help="source format (default: fixed = code in columns 8-72)")
    parser.add_argument("--stub-missing", action="store_true",
                        help="create empty files for copybooks that cannot be found, so parsing can proceed")
    args = parser.parse_args()

    if not os.path.isfile(args.program):
        print("Program file not found: {}".format(args.program), file=sys.stderr)
        return 1
    if not os.path.isdir(args.codebase_root):
        print("Codebase folder not found: {}".format(args.codebase_root), file=sys.stderr)
        return 1

    report = fetch_copybooks(args.program, args.codebase_root, args.format, args.stub_missing)
    json_path, missing_path = write_reports(report)
    print_summary(report, json_path, missing_path)

    return 2 if report["missing"] else 0


if __name__ == "__main__":
    sys.exit(main())
