"""Reader for EXEC SQL statements."""
import re

_TOKEN = r"[A-Z0-9_#@$.]+"
_FROM_RE = re.compile(
    r"\bFROM\s+(.+?)(?=\s+(?:WHERE|GROUP|ORDER|HAVING|UNION|FETCH|FOR|WITH|EXCEPT|INTERSECT|INTO)\b|\)|$)")
_JOIN_SPLIT = re.compile(
    r"\b(?:INNER\s+|LEFT\s+(?:OUTER\s+)?|RIGHT\s+(?:OUTER\s+)?|FULL\s+(?:OUTER\s+)?|CROSS\s+)?JOIN\b")
_JOIN_TABLE = re.compile(r"\bJOIN\s+(" + _TOKEN + ")")


def _from_tables(m):
    names = []
    for fm in _FROM_RE.finditer(m):
        for chunk in fm.group(1).split(","):
            for part in _JOIN_SPLIT.split(chunk):
                part = re.sub(r"\bON\b.*", "", part).strip()
                if not part or part.startswith("(") or part.startswith(":"):
                    continue
                tm = re.match(_TOKEN, part)
                if tm:
                    names.append(tm.group(0))
    for jm in _JOIN_TABLE.finditer(m):
        names.append(jm.group(1))
    return names


def _dedupe(tables):
    seen = set()
    out = []
    for t in tables:
        key = (t["name"], t["op"])
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _hosts(s):
    seen = []
    for h in re.findall(r":([A-Z0-9][A-Z0-9-]*)", s):
        if h not in seen:
            seen.append(h)
    return seen


def split_statements(exec_text):
    """ProLeap merges consecutive EXEC blocks into one statement. Split them on END-EXEC."""
    parts = re.split(r"(?i)\bEND-EXEC\b\s*\.?", exec_text or "")
    out = [p.strip() + " END-EXEC" for p in parts if p.strip()]
    return out or [exec_text or ""]


def parse(exec_text):
    """Parse an EXEC SQL statement."""
    t = re.sub(r"(?i)^\s*EXEC\s+SQL\b", "", exec_text)
    t = re.sub(r"(?i)\bEND-EXEC\s*\.?\s*$", "", t)
    t = re.sub(r"\s+", " ", t).upper().strip()
    m = re.sub(r"'(?:[^']|'')*'", "''", t)

    kind = "other"
    tables = []
    cursor = None
    include = None

    mm = re.match(r"^INCLUDE\s+(\S+)", m)
    if mm:
        kind = "include"
        include = mm.group(1).strip("'\".")
    elif re.match(r"^DECLARE\s+\S+\s+CURSOR", m):
        kind = "declare_cursor"
        cursor = re.match(r"^DECLARE\s+(\S+)", m).group(1)
        tables = [{"name": n, "op": "read"} for n in _from_tables(m)]
    elif re.match(r"^DECLARE\s+\S+\s+TABLE", m):
        kind = "declare_table"
        tables = [{"name": re.match(r"^DECLARE\s+(\S+)", m).group(1), "op": "declare"}]
    elif m.startswith("SELECT"):
        kind = "select"
        tables = [{"name": n, "op": "read"} for n in _from_tables(m)]
    elif re.match(r"^INSERT\s+INTO\s+\S+", m):
        kind = "insert"
        first = re.match(r"^INSERT\s+INTO\s+(" + _TOKEN + ")", m)
        if first:
            tables.append({"name": first.group(1), "op": "insert"})
        tables += [{"name": n, "op": "read"} for n in _from_tables(m)]
    elif re.match(r"^UPDATE\s+\S+", m):
        kind = "update"
        first = re.match(r"^UPDATE\s+(" + _TOKEN + ")", m)
        if first:
            tables.append({"name": first.group(1), "op": "update"})
        tables += [{"name": n, "op": "read"} for n in _from_tables(m)]
    elif re.match(r"^DELETE\s+FROM\s+\S+", m):
        kind = "delete"
        first = re.match(r"^DELETE\s+FROM\s+(" + _TOKEN + ")", m)
        if first:
            tables.append({"name": first.group(1), "op": "delete"})
        tables += [{"name": n, "op": "read"} for n in _from_tables(m)[1:]]
    elif re.match(r"^OPEN\s+\S+", m):
        kind = "open"
        cursor = re.match(r"^OPEN\s+(\S+)", m).group(1)
    elif re.match(r"^FETCH\b", m):
        kind = "fetch"
        fm = re.match(r"^FETCH\s+(?:NEXT\s+)?(?:FROM\s+)?(\S+)", m)
        cursor = fm.group(1) if fm else None
    elif re.match(r"^CLOSE\s+\S+", m):
        kind = "close"
        cursor = re.match(r"^CLOSE\s+(\S+)", m).group(1)
    elif m.startswith("WHENEVER"):
        kind = "whenever"
    elif m.startswith("COMMIT"):
        kind = "commit"
    elif m.startswith("ROLLBACK"):
        kind = "rollback"

    host_writes = []
    if kind in ("select", "fetch"):
        im = re.search(r"\bINTO\b", m)
        if im:
            seg = m[im.end():]
            fm = re.search(r"\bFROM\b", seg)
            if fm:
                seg = seg[:fm.start()]
            host_writes = _hosts(seg)
    host_reads = [h for h in _hosts(m) if h not in host_writes]

    return {"kind": kind, "tables": _dedupe(tables), "cursor": cursor, "include": include,
            "host_reads": host_reads, "host_writes": host_writes, "raw": exec_text}
