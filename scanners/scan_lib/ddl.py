"""DDL, DCLGEN and inline SQL scanner."""
import re

from . import common

_NAME = r"[A-Za-z0-9_#@$.\"]+"


def strip_comments(text):
    out = []
    i = 0
    n = len(text)
    quote = None
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
        elif ch == "/" and text[i:i + 2] == "/*":
            end = text.find("*/", i + 2)
            if end < 0:
                end = n - 2
            out.append("\n" * text.count("\n", i, end + 2))
            i = end + 2
        elif ch == "-" and text[i:i + 2] == "--":
            while i < n and text[i] != "\n":
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def split_statements(text):
    """[(statement_text, first_line)] split at ';' outside quotes. Lines are 1-based within text."""
    result = []
    cur = []
    quote = None
    start_pos = 0
    for i, ch in enumerate(text):
        if quote:
            cur.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            cur.append(ch)
        elif ch == ";":
            _flush(text, cur, start_pos, result)
            cur = []
            start_pos = i + 1
        else:
            cur.append(ch)
    _flush(text, cur, start_pos, result)
    return result


def _flush(text, cur, start_pos, result):
    piece = "".join(cur)
    if not piece.strip():
        return
    lead = len(piece) - len(piece.lstrip())
    line = 1 + text.count("\n", 0, start_pos + lead)
    result.append((piece.strip(), line))


def norm_name(tok):
    """-> (schema, name, qualified)"""
    q = tok.replace('"', "").strip().upper()
    if "." in q:
        schema, name = q.rsplit(".", 1)
    else:
        schema, name = None, q
    return schema, name, q


def _match_paren(s, open_idx):
    depth = 0
    quote = None
    for i in range(open_idx, len(s)):
        ch = s[i]
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


_CONSTRAINT_RE = re.compile(r"(?i)^(CONSTRAINT\s+\S+\s+)?(PRIMARY\s+KEY|FOREIGN\s+KEY|UNIQUE|CHECK)\b")
_TYPE_RE = re.compile(r"(?i)^(LONG\s+VARCHAR|DOUBLE\s+PRECISION|[A-Z]+)(?:\s*\(\s*(\d+)\s*(?:,\s*(\d+))?\s*\))?")


def _cols(text):
    return [c.strip().replace('"', "").upper() for c in common.split_top(text) if c.strip()]


def parse_columns(body):
    columns = []
    pk = []
    fks = []
    uniq = []
    for item in common.split_top(body):
        item = item.strip()
        if not item:
            continue
        cm = _CONSTRAINT_RE.match(item)
        if cm:
            kind = re.sub(r"\s+", " ", cm.group(2).upper())
            if kind == "PRIMARY KEY":
                m = re.search(r"(?i)PRIMARY\s+KEY\s*\((.*)\)", item)
                if m:
                    pk = _cols(m.group(1))
            elif kind == "FOREIGN KEY":
                m = re.search(r"(?i)FOREIGN\s+KEY\s*(?:\S+\s*)?\(([^)]*)\)\s*REFERENCES\s+(" + _NAME +
                              r")\s*(?:\(([^)]*)\))?", item)
                if m:
                    fks.append({"columns": _cols(m.group(1)), "ref_table": norm_name(m.group(2))[2],
                                "ref_columns": _cols(m.group(3)) if m.group(3) else []})
            elif kind == "UNIQUE":
                m = re.search(r"(?i)UNIQUE\s*\(([^)]*)\)", item)
                if m:
                    uniq.append(_cols(m.group(1)))
            continue
        parts = item.split(None, 1)
        name = parts[0].replace('"', "").upper()
        rest = parts[1] if len(parts) > 1 else ""
        tm = _TYPE_RE.match(rest)
        ctype = re.sub(r"\s+", " ", tm.group(1).upper()) if tm else None
        length = int(tm.group(2)) if tm and tm.group(2) else None
        scale = int(tm.group(3)) if tm and tm.group(3) else None
        up = rest.upper()
        columns.append({"name": name, "type": ctype, "length": length, "scale": scale,
                        "nullable": "NOT NULL" not in up, "default": "DEFAULT" in up})
        if re.search(r"\bPRIMARY\s+KEY\b", up):
            pk.append(name)
    return columns, pk, fks, uniq


def _table(name_tok, body, tail, line):
    schema, name, qualified = norm_name(name_tok)
    columns, pk, fks, uniq = parse_columns(body)
    ts = re.search(r"(?i)\bIN\s+([A-Z0-9_.]+)", tail or "")
    return {"schema": schema, "name": name, "qualified": qualified, "columns": columns, "primary_key": pk,
            "foreign_keys": fks, "unique": uniq, "tablespace": ts.group(1).upper() if ts else None,
            "line": line, "host_structure": None}


def _empty_body():
    return {"tables": [], "indexes": [], "views": [], "other": [], "alters": [], "drops": [], "dml": []}


def _from_tables(u):
    names = []
    for m in re.finditer(r"\b(?:FROM|JOIN)\s+(" + _NAME + ")", u):
        n = norm_name(m.group(1))[2]
        if n not in names:
            names.append(n)
    return names


def parse_sql(text, first_line=1):
    body = _empty_body()
    off = first_line - 1
    for stmt, ln in split_statements(text):
        line = ln + off
        s = re.sub(r"\s+", " ", stmt).strip()
        u = s.upper()
        m = re.match(r"(?i)^CREATE\s+(?:GLOBAL\s+TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(" + _NAME +
                     r")\s*\(", s)
        if m:
            open_idx = m.end() - 1
            close = _match_paren(s, open_idx)
            if close < 0:
                close = len(s)
            body["tables"].append(_table(m.group(1), s[open_idx + 1:close], s[close + 1:], line))
            continue
        m = re.match(r"(?i)^CREATE\s+(UNIQUE\s+)?INDEX\s+(" + _NAME + r")\s+ON\s+(" + _NAME + r")\s*\((.*?)\)", s)
        if m:
            cols = []
            for c in common.split_top(m.group(4)):
                c = c.strip()
                if not c:
                    continue
                parts = c.split()
                order = parts[1].upper() if len(parts) > 1 and parts[1].upper() in ("ASC", "DESC") else "ASC"
                cols.append({"name": parts[0].replace('"', "").upper(), "order": order})
            body["indexes"].append({"name": norm_name(m.group(2))[2], "table": norm_name(m.group(3))[2],
                                    "unique": bool(m.group(1)), "columns": cols, "line": line})
            continue
        m = re.match(r"(?i)^CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(" + _NAME + ")", s)
        if m:
            am = re.search(r"\bAS\b(.*)$", u)
            body["views"].append({"name": norm_name(m.group(1))[2],
                                  "tables": _from_tables(am.group(1)) if am else [], "line": line})
            continue
        m = re.match(r"(?i)^CREATE\s+(?:LARGE\s+)?(DATABASE|TABLESPACE|STOGROUP|SCHEMA|ALIAS|SYNONYM|SEQUENCE|"
                     r"TYPE)\s+(" + _NAME + ")", s)
        if m:
            body["other"].append({"kind": m.group(1).upper(), "name": norm_name(m.group(2))[2], "line": line})
            continue
        m = re.match(r"(?i)^ALTER\s+TABLE\s+(" + _NAME + ")", s)
        if m:
            body["alters"].append({"table": norm_name(m.group(1))[2], "text": common.cap(s, 200), "line": line})
            continue
        m = re.match(r"(?i)^DROP\s+([A-Z]+)\s+(" + _NAME + ")", s)
        if m:
            body["drops"].append({"kind": m.group(1).upper(), "name": norm_name(m.group(2))[2], "line": line})
            continue
        m = re.match(r"(?i)^INSERT\s+INTO\s+(" + _NAME + ")", s)
        if m:
            t = [{"name": norm_name(m.group(1))[2], "op": "insert"}]
            t += [{"name": n, "op": "read"} for n in _from_tables(u)]
            body["dml"].append({"kind": "insert", "tables": t, "line": line})
            continue
        m = re.match(r"(?i)^UPDATE\s+(" + _NAME + ")", s)
        if m:
            t = [{"name": norm_name(m.group(1))[2], "op": "update"}]
            t += [{"name": n, "op": "read"} for n in _from_tables(u)]
            body["dml"].append({"kind": "update", "tables": t, "line": line})
            continue
        m = re.match(r"(?i)^DELETE\s+FROM\s+(" + _NAME + ")", s)
        if m:
            t = [{"name": norm_name(m.group(1))[2], "op": "delete"}]
            t += [{"name": n, "op": "read"} for n in _from_tables(u)[1:]]
            body["dml"].append({"kind": "delete", "tables": t, "line": line})
            continue
        if re.match(r"(?i)^SELECT\b", s):
            body["dml"].append({"kind": "select", "tables": [{"name": n, "op": "read"} for n in _from_tables(u)],
                                "line": line})
    return body


def parse_dclgen(lines):
    body = _empty_body()
    warnings = []
    code = []
    for i, line in enumerate(lines):
        ind = line[6:7]
        content = line[7:72]
        if ind in ("*", "/") or not content.strip():
            continue
        code.append((i + 1, content))
    joined = "\n".join(c for _, c in code)
    m = re.search(r"(?is)EXEC\s+SQL\s+DECLARE\s+(\S+)\s+TABLE\s*\((.*)\)\s*END-EXEC", joined)
    if not m:
        warnings.append("no DECLARE TABLE found")
        body["warnings"] = warnings
        return body
    line_no = next((n for n, c in code if "DECLARE" in c.upper()), 1)
    table = _table(m.group(1), m.group(2), "", line_no)
    end_idx = next((k for k, (_, c) in enumerate(code) if "END-EXEC" in c.upper()), len(code) - 1)
    fields = []
    sname = None
    for _, c in code[end_idx + 1:]:
        fm = re.match(r"^\s*(\d{2})\s+([A-Z0-9-]+)\s*(.*?)\.\s*$", c.upper())
        if not fm:
            continue
        rest = fm.group(3)
        pm = re.search(r"\bPIC(?:TURE)?\s+(\S+)", rest)
        um = re.search(r"\b(COMP(?:UTATIONAL)?(?:-[1-5])?|BINARY|PACKED-DECIMAL)\b", rest)
        level = int(fm.group(1))
        fields.append({"level": level, "name": fm.group(2), "pic": pm.group(1) if pm else None,
                       "usage": um.group(1) if um else None})
        if sname is None and level == 1:
            sname = fm.group(2)
    table["host_structure"] = {"name": sname, "fields": fields}
    for col in table["columns"]:
        want = col["name"].replace("_", "-")
        col["host_var"] = next((f["name"] for f in fields if f["name"] == want and f["level"] != 49), None)
    body["tables"].append(table)
    body["warnings"] = warnings
    return body


def scan_file(path, rec, root):
    lines = common.split_lines(common.read_text(path))
    if rec.get("type") == "dclgen":
        kind = "dclgen"
        body = parse_dclgen(lines)
        warnings = body.pop("warnings", [])
    else:
        kind = "ddl"
        body = parse_sql(strip_comments("\n".join(lines)))
        warnings = []
    out = {"schema": "ddl-facts/1", "name": rec["name"], "path": rec["path"], "kind": kind}
    out.update(body)
    out["summary"] = {"tables": len(body["tables"]), "indexes": len(body["indexes"]), "views": len(body["views"])}
    out["warnings"] = warnings
    return out
