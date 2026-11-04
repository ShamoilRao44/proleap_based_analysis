"""Resolution of program / transaction / resource names that are held in variables."""
import re

from . import layout

PROGRAM_RE = re.compile(r"^[A-Z0-9@#$][A-Z0-9@#$-]{0,7}$")
TRANSID_RE = re.compile(r"^[A-Z0-9@#$]{1,4}$")


def _index(ctx):
    """Build (once) the lookup tables used by resolve()."""
    if "_moves" in ctx:
        return
    moves = {}
    sets = []
    for s in ctx["statements"]:
        if s.get("type") == "move":
            for t in s.get("to") or []:
                moves.setdefault(t, []).append(s)
        elif s.get("type") == "set":
            sets.append(s)
    ctx["_moves"] = moves
    ctx["_sets"] = sets
    if "by_id" not in ctx:
        ctx["by_id"] = {it["id"]: it for it in ctx["items"]}


def _in_occurs(item, by_id):
    cur = item
    while cur is not None:
        if cur.get("occurs"):
            return True
        cur = by_id.get(cur["parent"]) if cur.get("parent") is not None else None
    return False


def _string_values(values):
    out = []
    for v in values or []:
        lv = layout.literal_value(v["from"])
        if lv["kind"] == "string":
            out.append(lv["value"].strip())
    return out


def _collect(var, ctx, depth, visited):
    """List of (value, how) before filtering."""
    _index(ctx)
    cands = []
    items = ctx["by_name"].get(var, [])
    by_id = ctx["by_id"]

    # 1. VALUE clause
    for it in items:
        if it["level"] != 88:
            for val in _string_values(it.get("values")):
                cands.append((val, "value_clause"))

    # 2. MOVE 'LIT' TO var
    for s in ctx["_moves"].get(var, []):
        if s.get("from_literal") is not None:
            lv = layout.literal_value(s["from_literal"])
            if lv["kind"] == "string":
                cands.append((lv["value"].strip(), "move_literal"))

    # 3. SET condition-name TO TRUE where the condition belongs to var
    for s in ctx["_sets"]:
        if str(s.get("value") or "").upper() != "TRUE":
            continue
        for cond in s.get("to") or []:
            for c in ctx["by_name"].get(cond, []):
                if c["level"] == 88 and c.get("parent") is not None and by_id[c["parent"]].get("name") == var:
                    for val in _string_values(c.get("values")):
                        cands.append((val, "set_condition"))

    # 4. VALUE tables
    for it in items:
        if it["level"] != 88 and _in_occurs(it, by_id):
            for val in layout.occurrence_values(ctx["items"], it["id"]):
                cands.append((val.strip(), "value_table"))

    # 5. MOVE other-var TO var
    if depth < 3:
        for s in ctx["_moves"].get(var, []):
            src = s.get("from_var")
            if src and src not in visited:
                for r in resolve(src, "name", ctx, _depth=depth + 1, _visited=visited | {var}, _raw=True):
                    cands.append((r["value"], "move_var:" + src))
    return cands


def resolve(var, kind, ctx, _depth=0, _visited=None, _raw=False):
    """Candidate values of a variable: list of {'value', 'how'}, de-duplicated by value."""
    visited = _visited if _visited is not None else {var}
    cands = _collect(var, ctx, _depth, visited)
    pattern = TRANSID_RE if kind == "transid" else PROGRAM_RE
    seen = set()
    out = []
    for value, how in cands:
        v = (value or "").upper().strip()
        if not v:
            continue
        if not _raw and not pattern.match(v):
            continue
        if v in seen:
            continue
        seen.add(v)
        out.append({"value": v, "how": how})
    return out


def resolve_option(opt, kind, ctx):
    """Resolve a CICS option value dict (literal / var / ...) to candidate values."""
    if not opt:
        return []
    pattern = TRANSID_RE if kind == "transid" else PROGRAM_RE
    if "literal" in opt:
        v = opt["literal"].upper().strip()
        return [{"value": v, "how": "literal"}] if v and pattern.match(v) else []
    if "var" in opt:
        return resolve(opt["var"], kind, ctx)
    return []
