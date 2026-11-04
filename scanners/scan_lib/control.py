"""Control card files (IDCAMS, SORT)."""
from . import common, utilities

_IDCAMS = {"REPRO", "DEFINE", "DELETE", "LISTCAT", "PRINT", "ALTER", "IMPORT", "EXPORT", "BLDINDEX", "VERIFY"}


def scan_file(path, rec, root):
    lines = common.split_lines(common.read_text(path))
    out = {"schema": "control-facts/1", "name": rec["name"], "path": rec["path"], "kind": "unknown",
           "warnings": []}
    logical = utilities.join_continued(lines, "-+")
    if any(t.split()[0].upper() in _IDCAMS for _, t in logical if t.split()):
        out["kind"] = "idcams"
        out["commands"] = utilities.idcams_parse(lines)
        return out
    statements = utilities.sort_parse(lines)
    if statements:
        out["kind"] = "sort"
        out["statements"] = statements
        return out
    out["head"] = [ln for ln in lines if ln.strip()][:5]
    return out
