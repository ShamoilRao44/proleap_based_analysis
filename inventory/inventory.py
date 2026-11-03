#!/usr/bin/env python3
"""
inventory.py - step 1 of the modularization pipeline: classify every file of a mainframe codebase.

Files are classified by content, not by extension (mainframe exports often have no or misleading
extensions). For each file the inventory records its type, the name it declares (PROGRAM-ID,
JOB / PROC name, mapset, DBD / PSB name), encoding, COBOL source format, size and hash.

Only the Python standard library is used (Python 3.8+).

Usage:
  python3 inventory.py <codebase_root> --out <analysis_dir>

Output (in <analysis_dir>):
  inventory.json        machine-readable inventory, input for the next pipeline steps
  inventory_report.md   human-readable summary: counts per type, duplicates, name mismatches,
                        unclassified and low-confidence files

Exit codes: 0 ok, 1 bad arguments
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
from collections import Counter, OrderedDict

SCHEMA_VERSION = "1.0"

# bytes read for classification; hash and line count always use the whole file
HEAD_BYTES = 256 * 1024

SKIP_DIRS = {".git", ".svn", ".hg", "node_modules", "target", "__pycache__", ".idea", ".vscode"}

# ---------------------------------------------------------------------------
# File types
# ---------------------------------------------------------------------------

COBOL_PROGRAM = "cobol_program"
COPYBOOK = "copybook"
DCLGEN = "dclgen"
BMS = "bms"
JCL = "jcl"
PROC = "proc"
CSD = "csd"
DDL = "ddl"
IMS_DBD = "ims_dbd"
IMS_PSB = "ims_psb"
ASSEMBLER = "assembler"
ASM_MACRO = "asm_macro"
CONTROL_CARD = "control_card"
DATA = "data"
BINARY = "binary"
EMPTY = "empty"
DOCUMENT = "document"
OTHER_SOURCE = "other_source"
UNKNOWN = "unknown"

# types that belong to the mainframe application (others are ignored by later steps)
MAINFRAME_TYPES = [COBOL_PROGRAM, COPYBOOK, DCLGEN, BMS, JCL, PROC, CSD, DDL, IMS_DBD, IMS_PSB,
                   ASSEMBLER, ASM_MACRO, CONTROL_CARD]

# extension hints: only used when the content is not conclusive, and to report mismatches
EXTENSION_HINTS = {
    "cbl": COBOL_PROGRAM, "cob": COBOL_PROGRAM, "cobol": COBOL_PROGRAM,
    "cpy": COPYBOOK, "copy": COPYBOOK, "cpb": COPYBOOK,
    "dcl": DCLGEN, "dclgen": DCLGEN,
    "bms": BMS,
    "jcl": JCL, "job": JCL,
    "prc": PROC, "proc": PROC,
    "csd": CSD,
    "ddl": DDL, "sql": DDL,
    "dbd": IMS_DBD, "psb": IMS_PSB,
    "asm": ASSEMBLER, "assemble": ASSEMBLER, "mac": ASM_MACRO,
    "ctl": CONTROL_CARD, "ctc": CONTROL_CARD,
}

DOCUMENT_EXTENSIONS = {"md", "txt", "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "html", "htm",
                       "drawio", "png", "jpg", "jpeg", "gif", "svg", "bmp", "ico", "rst", "csv"}

OTHER_SOURCE_EXTENSIONS = {"java", "js", "jsx", "ts", "tsx", "py", "sh", "bat", "ps1", "xml", "json",
                           "yml", "yaml", "properties", "scss", "css", "gradle", "kt", "groovy", "c",
                           "h", "cpp", "rexx", "rex", "clist", "pli", "pl1", "map", "project", "prefs",
                           "gitignore", "gitkeep", "lock", "toml", "ini", "cfg", "conf", "mf", "license"}

# ---------------------------------------------------------------------------
# Content patterns (applied to upper-cased text)
# ---------------------------------------------------------------------------

RE_JCL_JOB = re.compile(r"^//([A-Z0-9@#$]{1,8})\s+JOB\b", re.M)
RE_JCL_PROC = re.compile(r"^//([A-Z0-9@#$]{1,8})\s+PROC\b", re.M)
RE_JCL_ANY = re.compile(r"^//[A-Z0-9@#$]*\s+(EXEC|DD)\b", re.M)
RE_CSD_DEFINE = re.compile(r"^\s*DEFINE\s+(TRANSACTION|PROGRAM|FILE|MAPSET|TRANSCLASS|TDQUEUE|"
                           r"LIBRARY|DB2CONN|DB2ENTRY|URIMAP|PIPELINE|WEBSERVICE)\s*\(", re.M)
RE_BMS = re.compile(r"^([A-Z0-9@#$]{1,8})?\s+DFHMSD\b", re.M)
RE_DBD = re.compile(r"^\S*\s+DBD\s+NAME=([A-Z0-9@#$]+)", re.M)
RE_PSB = re.compile(r"\bPSBGEN\b.*?PSBNAME=([A-Z0-9@#$]+)|^\S*\s+PCB\s+TYPE=", re.M)
RE_DDL = re.compile(r"^\s*CREATE\s+(TABLE|(UNIQUE\s+)?INDEX|VIEW|TABLESPACE|DATABASE|SYNONYM|ALIAS|"
                    r"STOGROUP|PROCEDURE|TRIGGER)\b", re.M)
RE_DCLGEN = re.compile(r"EXEC\s+SQL\s+DECLARE\s+([A-Z0-9_.\"]+)\s+TABLE", re.S)
RE_ASM_CSECT = re.compile(r"^([A-Z0-9@#$]{1,8})\s+(CSECT|RSECT|START)\b", re.M)
RE_ASM_MACRO = re.compile(r"^\s+MACRO\s*$", re.M)
RE_ASM_INSTR = re.compile(r"^\S*\s+(USING|STM|LM|BALR|BR|LA|L|ST|MVC|DS|DC|EQU|DROP|LTORG)\s", re.M)
RE_CONTROL_CARD = re.compile(r"^\s*(REPRO|DEFINE\s+(CLUSTER|AIX|PATH|GDG|ALTERNATEINDEX)|DELETE\s+\S|"
                             r"SORT\s+FIELDS|MERGE\s+FIELDS|INCLUDE\s+COND|OUTREC|INREC|SUM\s+FIELDS|"
                             r"BLDINDEX|LISTCAT|PRINT\s+INFILE|ALTER\s+\S|VERIFY\s+(DATASET|FILE)|"
                             r"OPTION\s+COPY|DSN\s+SYSTEM|RUN\s+PROGRAM|BIND\s+(PLAN|PACKAGE))\b", re.M)

# applied to the COBOL code area only (see code_area)
RE_PROGRAM_ID = re.compile(r"\bPROGRAM-ID\s*\.?\s*['\"]?([A-Z0-9][A-Z0-9\-_#@$]*)", re.M)
RE_ID_DIVISION = re.compile(r"\b(IDENTIFICATION|ID)\s+DIVISION\b")
RE_COBOL_DATA_LINE = re.compile(r"^\s*(0?[1-9]|[1-4][0-9]|66|77|88)\s+([A-Z0-9][A-Z0-9\-_]*|FILLER)(\s|\.|$)")
RE_COBOL_PROC_LINE = re.compile(r"^\s*(MOVE|PERFORM|IF|ELSE|END-IF|EVALUATE|WHEN|END-EVALUATE|COMPUTE|ADD|"
                                r"SUBTRACT|MULTIPLY|DIVIDE|DISPLAY|CALL|GO\s+TO|EXEC\s+(CICS|SQL|DLI)|"
                                r"END-EXEC|INITIALIZE|SET|STRING|UNSTRING|INSPECT|READ|WRITE|REWRITE|"
                                r"OPEN|CLOSE|COPY|CONTINUE|EXIT|STOP\s+RUN|GOBACK)\b")
RE_COBOL_CONTINUATION = re.compile(r"^\s*(PIC|PICTURE|VALUE|VALUES|USAGE|COMP|OCCURS|REDEFINES|"
                                   r"INDEXED|ASCENDING|DESCENDING|DEPENDING|TO|THRU|THROUGH|"
                                   r"'|\"|[A-Z0-9\-]+\s*(\.|,)?$)")

FIXED_INDICATORS = set(" *-/DdC$")

# BMS symbolic map copybooks: every field has a length subfield 'xxxL COMP PIC S9(4)'
RE_SYMBOLIC_MAP_LENGTH = re.compile(r"\b[A-Z0-9\-]+L\s+(COMP(-5)?|BINARY)\s+PIC(TURE)?\s+S9\(4\)|"
                                    r"\b[A-Z0-9\-]+L\s+PIC(TURE)?\s+S9\(4\)\s+(COMP(-5)?|BINARY)")

EBCDIC_PRINTABLE = set([0x40] + list(range(0x4a, 0x51)) + list(range(0x5a, 0x62)) + list(range(0x6a, 0x70))
                       + list(range(0x79, 0x80)) + list(range(0x81, 0x8a)) + list(range(0x91, 0x9a))
                       + list(range(0xa1, 0xaa)) + list(range(0xc0, 0xca)) + list(range(0xd0, 0xda))
                       + list(range(0xe0, 0xea)) + list(range(0xf0, 0xfa)))

# documentation files without extension
DOCUMENT_NAMES = {"LICENSE", "LICENCE", "NOTICE", "README", "CHANGELOG", "CONTRIBUTING", "AUTHORS", "COPYING"}

# member name spaces: names only collide within the same library kind
NAMESPACES = {
    COBOL_PROGRAM: "program", ASSEMBLER: "program",
    COPYBOOK: "copy", DCLGEN: "copy",
    BMS: "mapset", JCL: "jcl", PROC: "proc", CSD: "csd", DDL: "ddl",
    IMS_DBD: "dbd", IMS_PSB: "psb", ASM_MACRO: "macro", CONTROL_CARD: "control",
}

# ---------------------------------------------------------------------------
# Reading and decoding
# ---------------------------------------------------------------------------


def detect_encoding(raw):
    """Return ('binary' | 'ebcdic' | 'utf-8' | 'latin-1' | 'ascii', decoded text or None)."""
    if not raw:
        return "ascii", ""

    sample = raw[:65536]

    # EBCDIC text: nearly all bytes are EBCDIC printable characters (space 0x40, letters 0x81-0xE9,
    # digits 0xF0-0xF9). EBCDIC letters and digits are all >= 0x81, so a large share of high bytes
    # separates it from ASCII text (whose bytes in 0x40-0x7E are also EBCDIC printable). Space-padded
    # EBCDIC records have fewer high bytes, but they also have no ASCII line breaks
    ebcdic_printable = sum(1 for b in sample if b in EBCDIC_PRINTABLE)
    high = sum(1 for b in sample if b >= 0x80)
    no_newlines = b"\n" not in sample
    if ebcdic_printable > len(sample) * 0.9 and (high > len(sample) * 0.3 or (no_newlines and high > len(sample) * 0.1)):
        return "ebcdic", raw.decode("cp037")

    nul = sample.count(b"\x00")
    control = sum(1 for b in sample if b < 0x20 and b not in (0x09, 0x0a, 0x0c, 0x0d))
    if nul > 0 or control > len(sample) * 0.05:
        return "binary", None

    try:
        text = raw.decode("utf-8")
        return ("ascii" if all(b < 0x80 for b in sample) else "utf-8"), text
    except UnicodeDecodeError:
        return "latin-1", raw.decode("latin-1")


def code_area(lines, source_format):
    """COBOL code part of each non-comment line (columns 8-72 for fixed format)."""
    result = []

    for line in lines:
        if source_format == "fixed":
            if len(line) < 7 or line[6] in "*/":
                continue
            result.append(line[7:72])
        else:
            stripped = line.lstrip()
            if stripped.startswith("*>") or stripped.startswith("*"):
                continue
            result.append(line)

    return result


def detect_cobol_format(lines):
    """
    'fixed' when most lines follow the fixed layout: columns 1-6 sequence area (digits, blanks or a
    short label), column 7 indicator, code from column 8; otherwise 'free'.
    """
    candidates = [l for l in lines if l.strip()]

    if not candidates:
        return "unknown"

    fixed = 0
    for line in candidates:
        if len(line) < 7:
            # short lines are only valid in fixed format when blank in the code area
            fixed += 1 if not line[:6].strip() or line[:6].strip().isdigit() else 0
            continue

        sequence, indicator = line[:6], line[6]
        sequence_ok = sequence.strip() == "" or sequence.strip().isdigit() or sequence == sequence.upper()
        code_starts_late = line[:7].strip() == "" or sequence.strip().isdigit() or indicator in "*/-"
        if indicator in FIXED_INDICATORS and sequence_ok and code_starts_late:
            fixed += 1

    return "fixed" if fixed >= len(candidates) * 0.9 else "free"


def cobol_line_ratio(code_lines):
    """Fraction of non-blank code lines that look like COBOL data or procedure lines."""
    lines = [l.upper() for l in code_lines if l.strip()]

    if not lines:
        return 0.0, 0

    hits = 0
    for line in lines:
        if RE_COBOL_DATA_LINE.match(line) or RE_COBOL_PROC_LINE.match(line) or RE_COBOL_CONTINUATION.match(line):
            hits += 1

    return hits / len(lines), len(lines)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def classify(text, extension):
    """
    Return (type, declared_name, confidence, reason, source_format).
    Order matters: the most specific signatures are tested first.
    """
    upper = text.upper()
    lines = text.splitlines()
    ext_hint = EXTENSION_HINTS.get(extension)

    # JCL / PROC
    job = RE_JCL_JOB.search(upper)
    if job:
        return JCL, job.group(1), "high", "JOB card", None

    proc = RE_JCL_PROC.search(upper)
    if proc:
        return PROC, proc.group(1), "high", "PROC statement", None

    jcl_statements = len(RE_JCL_ANY.findall(upper))
    if jcl_statements >= 2:
        # JCL fragments without JOB / PROC card (INCLUDE members, instream fragments)
        return PROC, None, "medium", "JCL EXEC/DD statements without JOB or PROC card", None

    # CICS CSD definitions
    csd_defines = len(RE_CSD_DEFINE.findall(upper))
    if csd_defines >= 1 and "DFHMSD" not in upper and "PROGRAM-ID" not in upper:
        return CSD, None, "high" if csd_defines >= 3 else "medium", "{} CICS DEFINE statements".format(csd_defines), None

    # BMS mapset
    bms = RE_BMS.search(upper)
    if bms:
        return BMS, bms.group(1), "high", "DFHMSD macro", None

    # IMS
    dbd = RE_DBD.search(upper)
    if dbd:
        return IMS_DBD, dbd.group(1), "high", "DBD NAME=", None

    psb = RE_PSB.search(upper)
    if psb:
        name_match = re.search(r"PSBNAME=([A-Z0-9@#$]+)", upper)
        return IMS_PSB, name_match.group(1) if name_match else None, "high", "PSBGEN / PCB macros", None

    # COBOL program / copybook / DCLGEN
    source_format = detect_cobol_format(lines)
    code = code_area(lines, source_format if source_format != "unknown" else "free")
    code_upper = "\n".join(code).upper()

    program_id = RE_PROGRAM_ID.search(code_upper)
    if program_id and RE_ID_DIVISION.search(code_upper):
        return COBOL_PROGRAM, program_id.group(1), "high", "IDENTIFICATION DIVISION + PROGRAM-ID", source_format
    if program_id:
        return COBOL_PROGRAM, program_id.group(1), "medium", "PROGRAM-ID without IDENTIFICATION DIVISION", source_format

    dclgen = RE_DCLGEN.search(code_upper)
    if dclgen:
        return DCLGEN, dclgen.group(1).replace('"', ""), "high", "EXEC SQL DECLARE ... TABLE", source_format

    # DDL (after DCLGEN: a DCLGEN never contains CREATE, DDL never has COBOL layout)
    if RE_DDL.search(upper):
        return DDL, None, "high", "CREATE statement", None

    # assembler (before copybook: assembler lines can look like COBOL continuation lines)
    csect = RE_ASM_CSECT.search(upper)
    if RE_ASM_MACRO.search(upper):
        return ASM_MACRO, None, "high", "MACRO statement", None
    if csect:
        return ASSEMBLER, csect.group(1), "high", "CSECT", None
    if len(RE_ASM_INSTR.findall(upper)) >= 5:
        return ASSEMBLER, None, "medium", "assembler instructions", None

    ratio, code_line_count = cobol_line_ratio(code)
    if code_line_count >= 1 and ratio >= 0.6 and (source_format == "fixed" or ext_hint == COPYBOOK):
        has_data = any(RE_COBOL_DATA_LINE.match(l.upper()) for l in code)
        kind = "data definitions" if has_data else "procedure code"
        confidence = "high" if ratio >= 0.85 and code_line_count >= 2 else "medium"
        return COPYBOOK, None, confidence, "COBOL {} ({:.0%} COBOL lines)".format(kind, ratio), source_format

    # utility control statements (IDCAMS, SORT, DSNTEP2 ...)
    if RE_CONTROL_CARD.search(upper):
        return CONTROL_CARD, None, "medium", "utility control statements", None

    return None, None, None, None, None


def classify_file(path, extension):
    name = os.path.basename(path)

    with open(path, "rb") as f:
        raw = f.read()

    encoding, text = detect_encoding(raw)
    info = {
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encoding": encoding,
        "lines": raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0) if encoding != "ebcdic" else None,
    }

    if not raw:
        return dict(info, type=EMPTY, declared_name=None, confidence="high", reason="empty file")

    if text is None:
        if extension in DOCUMENT_EXTENSIONS:
            return dict(info, type=DOCUMENT, declared_name=None, confidence="high", reason="binary document")
        return dict(info, type=BINARY if encoding == "binary" else DATA, declared_name=None,
                    confidence="high", reason="binary content")

    # documentation is recognised by name first: it may quote JCL, CSD or COBOL as examples.
    # .txt is excluded because mainframe members and test data are often exported as .txt
    if (extension in DOCUMENT_EXTENSIONS and extension != "txt") or (not extension and member_name(name) in DOCUMENT_NAMES):
        return dict(info, type=DOCUMENT, declared_name=None, confidence="high", reason="document")

    if encoding == "ebcdic":
        # EBCDIC data sets have no line breaks; only classify as source if it really looks like one
        text_for_classify = text
    else:
        text_for_classify = text[:HEAD_BYTES]

    file_type, declared, confidence, reason, source_format = classify(text_for_classify, extension)

    if file_type is None:
        if encoding == "ebcdic":
            file_type, confidence, reason = DATA, "high", "EBCDIC data"
        elif looks_like_fixed_records(text_for_classify):
            file_type, confidence, reason = DATA, "medium", "fixed-length records"
        elif extension in DOCUMENT_EXTENSIONS:
            file_type, confidence, reason = DOCUMENT, "high", "document extension"
        elif extension in OTHER_SOURCE_EXTENSIONS:
            file_type, confidence, reason = OTHER_SOURCE, "high", "non-mainframe source extension"
        elif extension in EXTENSION_HINTS:
            file_type, confidence, reason = EXTENSION_HINTS[extension], "low", "extension only, content not recognised"
        else:
            file_type, confidence, reason = UNKNOWN, "low", "not recognised"

    result = dict(info, type=file_type, declared_name=declared, confidence=confidence, reason=reason)

    if source_format and file_type in (COBOL_PROGRAM, COPYBOOK, DCLGEN):
        result["source_format"] = source_format

    if file_type == COPYBOOK:
        if len(RE_SYMBOLIC_MAP_LENGTH.findall(text_for_classify.upper())) >= 2:
            result["subtype"] = "bms_symbolic_map"
        else:
            result["subtype"] = "data" if "data definitions" in reason else "procedure"

    hint = EXTENSION_HINTS.get(extension)
    if hint and hint != file_type and file_type in MAINFRAME_TYPES:
        result["extension_mismatch"] = "extension suggests {}".format(hint)

    return result


def looks_like_fixed_records(text):
    """
    Text data files: lines of (nearly) equal length. Either almost all lines have the same length
    (padded records), or most do and the content is digit-heavy (numeric records).
    """
    lines = [l for l in text.splitlines()[:200] if l.strip()]
    if len(lines) < 3:
        return False
    lengths = Counter(len(l.rstrip("\r")) for l in lines)
    most_common_share = lengths.most_common(1)[0][1] / len(lines)
    digits = sum(c.isdigit() for l in lines for c in l) / max(1, sum(len(l) for l in lines))
    return most_common_share >= 0.9 or (most_common_share >= 0.6 and digits >= 0.2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def member_name(filename):
    """Logical member name: upper case, without extension (PDS member style)."""
    stem, _ = os.path.splitext(filename)
    return (stem or filename).upper()


def file_extension(filename):
    _, ext = os.path.splitext(filename)
    return ext[1:].lower() if ext else (filename[1:].lower() if filename.startswith(".") else "")


def build_inventory(root, out_dir):
    root = os.path.abspath(root)
    out_abs = os.path.normcase(os.path.abspath(out_dir))
    files = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in SKIP_DIRS and os.path.normcase(os.path.abspath(os.path.join(dirpath, d))) != out_abs
        )

        for filename in sorted(filenames):
            path = os.path.join(dirpath, filename)
            relative = os.path.relpath(path, root).replace(os.sep, "/")
            extension = file_extension(filename)

            try:
                info = classify_file(path, extension)
            except OSError as e:
                info = {"type": UNKNOWN, "confidence": "low", "reason": "unreadable: {}".format(e)}

            record = OrderedDict()
            record["path"] = relative
            record["name"] = member_name(filename)
            record.update(info)
            files.append(record)

    return files


def find_duplicates(files):
    """
    Members with the same name (case-insensitive, extension ignored) in the same name space.
    Names in different libraries do not collide: a BMS mapset and its symbolic map copybook, or a
    JCL member and a PROC, normally share a name.
    """
    by_name = {}
    for f in files:
        namespace = NAMESPACES.get(f["type"])
        if namespace:
            by_name.setdefault((namespace, f["name"]), []).append(f)

    return OrderedDict(
        ("{}:{}".format(namespace, name), [{"path": f["path"], "type": f["type"]} for f in group])
        for (namespace, name), group in sorted(by_name.items()) if len(group) > 1
    )


def find_name_mismatches(files):
    """Files whose declared name (PROGRAM-ID, JOB, PROC, mapset ...) differs from the member name."""
    result = []
    for f in files:
        declared = f.get("declared_name")
        if declared and f["type"] in (COBOL_PROGRAM, JCL, PROC, BMS, IMS_DBD, IMS_PSB, ASSEMBLER):
            if declared.upper() != f["name"]:
                result.append({"path": f["path"], "type": f["type"], "member_name": f["name"],
                               "declared_name": declared})
    return result


def write_report(path, inventory):
    summary = inventory["summary"]
    lines = []
    lines.append("# Inventory: {}".format(inventory["meta"]["codebase_root"]))
    lines.append("")
    lines.append("Generated {} — {} files.".format(inventory["meta"]["generated"], summary["total_files"]))
    lines.append("")
    lines.append("## Files per type")
    lines.append("")
    lines.append("| Type | Files | Lines |")
    lines.append("|---|---:|---:|")
    for file_type, count in summary["by_type"].items():
        lines.append("| {} | {} | {} |".format(file_type, count, summary["lines_by_type"].get(file_type, "")))

    lines.append("")
    lines.append("## COBOL source formats")
    lines.append("")
    for fmt, count in summary["cobol_formats"].items():
        lines.append("- {}: {}".format(fmt, count))

    def section(title, rows, header, render):
        lines.append("")
        lines.append("## {} ({})".format(title, len(rows)))
        lines.append("")
        if not rows:
            lines.append("None.")
            return
        lines.append(header)
        lines.append("|" + "|".join("---" for _ in header.strip("|").split("|")) + "|")
        for row in rows:
            lines.append(render(row))

    section("Duplicate member names", list(inventory["duplicates"].items()),
            "| Name | Files |",
            lambda r: "| {} | {} |".format(r[0], "<br>".join("{} ({})".format(f["path"], f["type"]) for f in r[1])))

    section("Declared name differs from member name", inventory["name_mismatches"],
            "| File | Type | Member name | Declared name |",
            lambda r: "| {} | {} | {} | {} |".format(r["path"], r["type"], r["member_name"], r["declared_name"]))

    mismatched_ext = [f for f in inventory["files"] if f.get("extension_mismatch")]
    section("Extension does not match content", mismatched_ext,
            "| File | Classified as | Note |",
            lambda f: "| {} | {} | {} |".format(f["path"], f["type"], f["extension_mismatch"]))

    review = [f for f in inventory["files"]
              if f["confidence"] in ("low", "medium") and f["type"] not in (DOCUMENT, OTHER_SOURCE, BINARY, DATA)]
    section("To review: low / medium confidence", review,
            "| File | Type | Confidence | Reason |",
            lambda f: "| {} | {} | {} | {} |".format(f["path"], f["type"], f["confidence"], f["reason"]))

    with open(path, "w", encoding="utf-8") as out:
        out.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Classify every file of a mainframe codebase (step 1).")
    parser.add_argument("codebase_root", help="root folder of the codebase")
    parser.add_argument("--out", required=True, help="analysis output folder (created if missing)")
    args = parser.parse_args()

    if not os.path.isdir(args.codebase_root):
        print("Codebase folder not found: {}".format(args.codebase_root), file=sys.stderr)
        return 1

    os.makedirs(args.out, exist_ok=True)
    print("Scanning {} ...".format(os.path.abspath(args.codebase_root)))
    files = build_inventory(args.codebase_root, args.out)

    by_type = Counter(f["type"] for f in files)
    lines_by_type = Counter()
    for f in files:
        lines_by_type[f["type"]] += f.get("lines") or 0
    ordered_types = [t for t in MAINFRAME_TYPES if t in by_type] + sorted(t for t in by_type if t not in MAINFRAME_TYPES)

    inventory = OrderedDict()
    inventory["meta"] = OrderedDict([
        ("schema_version", SCHEMA_VERSION),
        ("tool", "inventory.py"),
        ("codebase_root", os.path.abspath(args.codebase_root)),
        ("generated", datetime.datetime.now().isoformat(timespec="seconds")),
    ])
    inventory["summary"] = OrderedDict([
        ("total_files", len(files)),
        ("by_type", OrderedDict((t, by_type[t]) for t in ordered_types)),
        ("lines_by_type", OrderedDict((t, lines_by_type[t]) for t in ordered_types)),
        ("cobol_formats", dict(Counter(f.get("source_format", "n/a") for f in files
                                       if f["type"] in (COBOL_PROGRAM, COPYBOOK, DCLGEN)))),
    ])
    inventory["duplicates"] = find_duplicates(files)
    inventory["name_mismatches"] = find_name_mismatches(files)
    inventory["files"] = files

    json_path = os.path.join(args.out, "inventory.json")
    with open(json_path, "w", encoding="utf-8") as out:
        json.dump(inventory, out, indent=2)

    report_path = os.path.join(args.out, "inventory_report.md")
    write_report(report_path, inventory)

    print("\nFiles: {}".format(len(files)))
    for t in ordered_types:
        print("  {:<14} {:>6}".format(t, by_type[t]))
    print("\nDuplicate member names : {}".format(len(inventory["duplicates"])))
    print("Name mismatches        : {}".format(len(inventory["name_mismatches"])))
    print("\nWritten:\n  {}\n  {}".format(json_path, report_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
