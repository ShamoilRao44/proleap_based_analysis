"""Parsers for the inline control data of utility programs (IDCAMS, SORT, SDSF, TSO/DB2)."""
import re

from . import common


def _strip_block_comments(lines):
    out = []
    inside = False
    for ln in lines:
        res = []
        i = 0
        while i < len(ln):
            if inside:
                e = ln.find("*/", i)
                if e < 0:
                    i = len(ln)
                else:
                    inside = False
                    i = e + 2
            else:
                b = ln.find("/*", i)
                if b < 0:
                    res.append(ln[i:])
                    i = len(ln)
                else:
                    res.append(ln[i:b])
                    inside = True
                    i = b + 2
        out.append("".join(res))
    return out


def join_continued(lines, markers, keep=False):
    """Remove /* */ comments and join lines ending with a marker character.
    Returns [(first_line_index, text)]. With keep=True the marker character stays in the text."""
    lines = _strip_block_comments(lines)
    out = []
    cur = None
    start = 0
    for i, ln in enumerate(lines):
        t = ln.rstrip()
        if cur is None:
            if not t.strip():
                continue
            cur = ""
            start = i
        if t and t[-1] in markers:
            cur += (t if keep else t[:-1].rstrip()) + " "
            continue
        cur += t
        if cur.strip():
            out.append((start, cur.strip()))
        cur = None
    if cur is not None and cur.strip():
        out.append((start, cur.strip()))
    return out


# ---------------------------------------------------------------- IDCAMS

_IDCAMS_VERBS = {"DEFINE", "DELETE", "REPRO", "LISTCAT", "PRINT", "ALTER", "IMPORT", "EXPORT", "BLDINDEX",
                 "VERIFY", "EXAMINE"}
_OBJ_TYPES = r"(CLUSTER|GENERATIONDATAGROUP|GDG|NONVSAM|ALTERNATEINDEX|AIX|PATH|USERCATALOG|PAGESPACE)"
_SUBTYPE_MAP = {"GENERATIONDATAGROUP": "GDG", "ALTERNATEINDEX": "AIX"}


def _norm_sub(s):
    s = s.upper()
    return _SUBTYPE_MAP.get(s, s)


def _first(rx, text):
    m = re.search(rx, text, re.I)
    return m.group(1).upper() if m else None


def idcams_parse(lines):
    cmds = []
    for idx, text in join_continued(lines, "-+"):
        words = text.split()
        if not words:
            continue
        verb = words[0].upper()
        if verb not in _IDCAMS_VERBS:
            continue
        c = {"verb": verb, "subtype": None, "name": None, "names": [], "object_type": None, "infile": None,
             "outfile": None, "indataset": None, "outdataset": None, "attrs": {}, "text": common.cap(text, 300),
             "line": idx + 1}
        rest = text[len(words[0]):].strip()
        if verb == "DEFINE":
            if len(words) > 1:
                c["subtype"] = _norm_sub(words[1])
            c["names"] = [n.upper() for n in re.findall(r"(?i)\bNAME\s*\(\s*([^)\s]+)\s*\)", text)]
            c["name"] = c["names"][0] if c["names"] else None
            a = c["attrs"]
            m = re.search(r"(?i)\bKEYS\s*\(\s*(\d+)\s+(\d+)\s*\)", text)
            if m:
                a["KEYS"] = [int(m.group(1)), int(m.group(2))]
            m = re.search(r"(?i)\bRECORDSIZE\s*\(\s*(\d+)\s+(\d+)\s*\)", text)
            if m:
                a["RECORDSIZE"] = [int(m.group(1)), int(m.group(2))]
            m = re.search(r"(?i)\bLIMIT\s*\(\s*(\d+)\s*\)", text)
            if m:
                a["LIMIT"] = int(m.group(1))
            r = _first(r"\bRELATE\s*\(\s*([^)\s]+)", text)
            if r:
                a["RELATE"] = r
            m = re.search(r"(?i)(?<![A-Z0-9-])(INDEXED|NONINDEXED|NUMBERED|LINEAR)(?![A-Z0-9-])", text)
            if m:
                a["ORGANIZATION"] = m.group(1).upper()
        elif verb == "DELETE":
            after = rest
            if rest.startswith("("):
                depth = 0
                end = len(rest)
                for k, ch in enumerate(rest):
                    if ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            end = k
                            break
                c["names"] = [n.upper() for n in re.split(r"[\s,]+", rest[1:end].strip()) if n]
                after = rest[end + 1:]
            else:
                m = re.match(r"[^\s(]+", rest)
                if m:
                    c["names"] = [m.group(0).upper()]
                    after = rest[m.end():]
            c["name"] = c["names"][0] if c["names"] else None
            m = re.search(r"(?i)(?<![A-Z0-9-])" + _OBJ_TYPES + r"(?![A-Z0-9-])", after)
            if m:
                c["object_type"] = _norm_sub(m.group(1))
                c["subtype"] = c["object_type"]
        elif verb in ("REPRO", "PRINT"):
            c["infile"] = _first(r"\b(?:INFILE|IFILE)\s*\(\s*([^)\s]+)", text)
            c["outfile"] = _first(r"\b(?:OUTFILE|OFILE)\s*\(\s*([^)\s]+)", text)
            c["indataset"] = _first(r"\b(?:INDATASET|INDS)\s*\(\s*([^)\s]+)", text)
            c["outdataset"] = _first(r"\b(?:OUTDATASET|OUTDS)\s*\(\s*([^)\s]+)", text)
        else:
            nm = _first(r"\bENTRIES\s*\(\s*([^)\s]+)", text) or _first(r"\bLEVEL\s*\(\s*([^)\s]+)", text)
            if nm is None and verb in ("ALTER", "EXPORT", "IMPORT", "VERIFY"):
                m = re.match(r"[^\s(]+", rest)
                nm = m.group(0).upper() if m else None
            c["name"] = nm
        cmds.append(c)
    return cmds


# ---------------------------------------------------------------- SORT

_SORT_VERBS = {"SORT", "MERGE", "INCLUDE", "OMIT", "INREC", "OUTREC", "OUTFIL", "SUM", "OPTION", "MODS", "RECORD",
               "ALTSEQ", "END"}


def sort_parse(lines):
    lines = [ln for ln in _strip_block_comments(lines) if not ln.strip().startswith("*")]
    out = []
    for _, text in join_continued(lines, ",", keep=True):
        words = text.split()
        if not words or words[0].upper() not in _SORT_VERBS:
            continue
        verb = words[0].upper()
        fields = None
        if verb in ("SORT", "MERGE"):
            m = re.search(r"(?is)FIELDS\s*=\s*\((.*)\)", text)
            fields = m.group(1).strip() if m else None
        out.append({"verb": verb, "text": common.cap(text, 500), "fields": fields})
    return out


# ---------------------------------------------------------------- SDSF

_RES_TYPES = {"FIL": "FILE", "FILE": "FILE", "PROG": "PROGRAM", "PROGRAM": "PROGRAM", "TRAN": "TRANSACTION",
              "TRANSACTION": "TRANSACTION", "TDQ": "TDQUEUE", "TDQUEUE": "TDQUEUE"}
_ACTIONS = {"CLO": "CLOSE", "CLOSED": "CLOSE", "OPE": "OPEN", "OPEN": "OPEN", "ENA": "ENABLE", "ENABLED": "ENABLE",
            "DIS": "DISABLE", "DISABLED": "DISABLE", "NEW": "NEWCOPY", "NEWCOPY": "NEWCOPY"}


def sdsf_parse(lines):
    out = []
    for i, line in enumerate(lines):
        m = re.search(r"(?i)/F\s+(\w+)\s*,\s*'([^']*)'", line)
        if not m:
            continue
        c = re.search(r"(?i)CEMT\s+(SET|INQUIRE|PERFORM)\s+([A-Z]+)\s*\(\s*([^)]*?)\s*\)\s*([A-Z]*)", m.group(2))
        if not c:
            continue
        rt = c.group(2).upper()
        act = c.group(4).upper()
        out.append({"region": m.group(1).upper(), "verb": c.group(1).upper(),
                    "resource_type": _RES_TYPES.get(rt, rt), "resource": c.group(3).upper(),
                    "action": _ACTIONS.get(act, act) if act else None, "line": i + 1})
    return out


# ---------------------------------------------------------------- TSO / DB2

def tso_parse(lines):
    out = []
    subsystem = None
    for idx, text in join_continued(lines, "-"):
        m = re.search(r"(?i)\bDSN\s+SYSTEM\s*\(\s*(\w+)\s*\)", text)
        if m:
            subsystem = m.group(1).upper()
        m = re.search(r"(?i)\bRUN\s+PROGRAM\s*\(\s*(\w+)\s*\)", text)
        if m:
            plan = re.search(r"(?i)\bPLAN\s*\(\s*(\w+)", text)
            out.append({"program": m.group(1).upper(), "plan": plan.group(1).upper() if plan else None,
                        "subsystem": subsystem, "line": idx + 1})
    return out


def parm_invokes(program, parm):
    if program != "DFSRRC00" or not parm:
        return []
    p = parm.strip().strip("()").strip("'\"")
    items = [x.strip() for x in p.split(",")]
    if len(items) >= 2 and items[0].upper() in ("DLI", "BMP", "DBB"):
        return [{"program": items[1].upper(), "psb": items[2].upper() if len(items) > 2 and items[2] else None,
                 "via": "DFSRRC00 PARM"}]
    return []
