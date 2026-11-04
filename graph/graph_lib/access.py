"""Access rules: how a program or step uses a data store."""

SORT_PROGRAMS = ("SORT", "ICEMAN", "DFSORT", "SYNCSORT")


def combine(a, b):
    if a is None:
        return b
    if b is None:
        return a
    if a == b:
        return a
    s = set([a, b])
    if "unknown" in s:
        return b if a == "unknown" else a
    if "read_write" in s:
        return "read_write"
    if s == set(["read", "write"]):
        return "read_write"
    if s == set(["delete", "read"]):
        return "read_write"
    if s == set(["delete", "write"]):
        return "write"
    return "unknown"


def from_cics_op(op):
    if op in ("read", "browse", "unlock"):
        return "read"
    if op == "write":
        return "write"
    if op in ("update", "read_update", "delete"):
        return "read_write"
    return "unknown"


def from_sql_op(op):
    if op == "read":
        return "read"
    if op == "insert":
        return "write"
    if op in ("update", "delete"):
        return "read_write"
    if op == "declare":
        return None
    return "unknown"


def from_queue_op(op):
    if op == "read":
        return "read"
    if op == "write":
        return "write"
    if op == "delete":
        return "delete"
    return "unknown"


def from_mode_hint(m):
    if m in ("create", "append"):
        return "write"
    if m == "read":
        return "read"
    if m == "old":
        return "read_write"
    if m == "delete":
        return "delete"
    return "unknown"


def dd_access(step, dd, cobol_by_program):
    """Access of one DD of a flat step (rules 1 to 5 of the plan)."""
    name = dd["name"]
    prog = step.get("program")
    cf = cobol_by_program.get(prog) if prog else None
    if cf is not None:
        for f in cf.get("files_io") or []:
            if f.get("dd") == name:
                return f.get("access_summary") or "unknown"
    ud = step.get("utility_data") or {}
    if prog == "IDCAMS":
        is_in = is_out = False
        for c in ud.get("idcams_commands") or []:
            if c.get("verb") in ("REPRO", "PRINT"):
                if c.get("infile") == name:
                    is_in = True
                if c.get("outfile") == name:
                    is_out = True
        if is_in and is_out:
            return "read_write"
        if is_in:
            return "read"
        if is_out:
            return "write"
    if prog in SORT_PROGRAMS:
        if name.startswith("SORTIN"):
            return "read"
        if name == "SORTOUT" or name.startswith("SORTOF"):
            return "write"
    if prog == "IEBGENER":
        if name == "SYSUT1":
            return "read"
        if name == "SYSUT2":
            return "write"
    return from_mode_hint(dd.get("mode_hint"))
