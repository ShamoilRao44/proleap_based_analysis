"""CICS CSD (DFHCSDUP input) scanner."""
import re

from . import common

KEYWORDS = {"DEFINE", "DELETE", "ADD", "ALTER", "COPY", "APPEND", "REMOVE", "LIST", "INSTALL", "MOVE", "RENAME",
            "CHECK", "UPGRADE", "USERDEFINE", "EXTRACT", "INITIALIZE", "PRINT", "SCAN", "SERVICE", "VERIFY"}

_START_RE = re.compile(r"^\s*([A-Za-z]+)(?=\s|$)(.*)$")
_DEFINE_RE = re.compile(r"(?i)^DEFINE\s+([A-Z0-9]+)\s*\(\s*([^)]*?)\s*\)(.*)$")


def _is_string_arg(arg):
    a = arg.strip()
    return len(a) >= 2 and a[0] in ("'", '"') and a[-1] == a[0]


def _attrs(rest):
    attrs = {}
    for word, arg in common.paren_args(rest):
        if word in attrs:
            continue
        if arg is None:
            attrs[word] = True
        elif _is_string_arg(arg):
            attrs[word] = common.unquote(arg)
        else:
            attrs[word] = arg.strip()
    return attrs


def _definition(m, attrs, line, end_line):
    d = {"type": m.group(1).upper(), "name": m.group(2).upper(), "group": None, "description": None,
         "line": line, "end_line": end_line, "attrs": attrs}
    g = attrs.get("GROUP")
    d["group"] = g if isinstance(g, str) else None
    ds = attrs.get("DESCRIPTION")
    d["description"] = ds if isinstance(ds, str) else None
    t = d["type"]
    if t == "TRANSACTION":
        p = attrs.get("PROGRAM")
        d["program"] = p.upper() if isinstance(p, str) else None
    elif t == "PROGRAM":
        d["language"] = attrs.get("LANGUAGE")
        d["transid"] = attrs.get("TRANSID")
    elif t == "FILE":
        p = attrs.get("DSNAME")
        d["dsname"] = p.upper() if isinstance(p, str) else None
    elif t == "LIBRARY":
        names = []
        for i in range(1, 17):
            v = attrs.get("DSNAME%02d" % i)
            if isinstance(v, str):
                names.append(v.upper())
        d["dsnames"] = names
    elif t == "TDQUEUE":
        d["queue_type"] = attrs.get("TYPE")
    return d


def parse_lines(lines, first_line=1):
    definitions = []
    commands = []
    stmts = []
    cur = None
    for idx, raw in enumerate(lines):
        line = raw.rstrip()
        s = line.strip()
        if not s or s.startswith("*"):
            continue
        no = idx + first_line
        m = _START_RE.match(line)
        if m and m.group(1).upper() in KEYWORDS and not re.match(r"\s*\(", m.group(2)):
            cur = {"line": no, "end_line": no, "parts": [s]}
            stmts.append(cur)
        elif cur is not None:
            cur["parts"].append(s)
            cur["end_line"] = no
    for st in stmts:
        text = " ".join(st["parts"])
        dm = _DEFINE_RE.match(text)
        if dm:
            definitions.append(_definition(dm, _attrs(dm.group(3)), st["line"], st["end_line"]))
        else:
            verb = text.split(None, 1)[0].upper()
            commands.append({"verb": verb, "text": common.cap(text, 200), "line": st["line"]})
    return {"definitions": definitions, "commands": commands}


def summarize(definitions):
    by_type = {}
    groups = set()
    for d in definitions:
        by_type[d["type"]] = by_type.get(d["type"], 0) + 1
        if d["group"]:
            groups.add(d["group"])
    return {"by_type": dict(sorted(by_type.items())), "groups": sorted(groups)}


def scan_file(path, rec, root):
    lines = common.split_lines(common.read_text(path))
    r = parse_lines(lines)
    return {"schema": "csd-facts/1", "name": rec["name"], "path": rec["path"], "source": "file",
            "definitions": r["definitions"], "commands": r["commands"],
            "summary": summarize(r["definitions"]), "warnings": []}
