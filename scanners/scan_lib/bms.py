"""BMS mapset scanner."""
from . import common
from .asm_stmt import read_asm_statements


def _params(operands):
    d = {}
    for k, v in common.parse_params(operands):
        if k is not None and k not in d:
            d[k] = v
    return d


def _ints(value):
    if value is None:
        return None
    parts = common.sub_params(value)
    try:
        return [int(p) for p in parts]
    except ValueError:
        return None


def parse_lines(lines):
    mapsets = []
    warnings = []
    ms = None
    mp = None
    for st in read_asm_statements(lines):
        op = st["op"]
        if op == "DFHMSD":
            p = _params(st["operands"])
            if p.get("TYPE", "").upper() == "FINAL":
                ms = None
                mp = None
            else:
                ms = {"name": st["label"], "line": st["line"], "attrs": p, "maps": [], "symbolic_copybook": None}
                mapsets.append(ms)
                mp = None
        elif op == "DFHMDI":
            p = _params(st["operands"])
            if ms is None:
                ms = {"name": "", "line": st["line"], "attrs": {}, "maps": [], "symbolic_copybook": None}
                mapsets.append(ms)
                warnings.append("DFHMDI without DFHMSD")
            mp = {"name": st["label"], "line": st["line"], "size": _ints(p.get("SIZE")), "attrs": p, "fields": []}
            ms["maps"].append(mp)
        elif op == "DFHMDF":
            if mp is None:
                warnings.append("DFHMDF without DFHMDI")
                continue
            p = _params(st["operands"])
            attrb = [x.upper() for x in common.sub_params(p["ATTRB"])] if "ATTRB" in p else []
            name = st["label"] or None
            initial = common.unquote(p["INITIAL"]) if "INITIAL" in p else None
            length = None
            if "LENGTH" in p:
                try:
                    length = int(p["LENGTH"])
                except ValueError:
                    length = None
            if "UNPROT" in attrb:
                role = "input"
            elif name is not None:
                role = "output"
            elif initial is not None:
                role = "label"
            else:
                role = "filler"
            mp["fields"].append({
                "name": name, "line": st["line"], "pos": _ints(p.get("POS")), "length": length, "attrb": attrb,
                "initial": initial, "color": p["COLOR"].upper() if "COLOR" in p else None,
                "hilight": p["HILIGHT"].upper() if "HILIGHT" in p else None, "role": role, "attrs": p})
    for m in mapsets:
        for mp2 in m["maps"]:
            f = mp2["fields"]
            mp2["field_count"] = len(f)
            mp2["named_fields"] = sum(1 for x in f if x["name"])
            mp2["input_fields"] = sum(1 for x in f if x["role"] == "input")
            mp2["labels"] = sum(1 for x in f if x["role"] == "label")
    return {"mapsets": mapsets, "warnings": warnings}


def scan_file(path, rec, root, symbolic_copybooks):
    lines = common.split_lines(common.read_text(path))
    r = parse_lines(lines)
    for m in r["mapsets"]:
        m["symbolic_copybook"] = symbolic_copybooks.get(m["name"].upper())
    maps = sum(len(m["maps"]) for m in r["mapsets"])
    fields = sum(len(mp["fields"]) for m in r["mapsets"] for mp in m["maps"])
    return {"schema": "bms-facts/1", "name": rec["name"], "path": rec["path"], "mapsets": r["mapsets"],
            "summary": {"mapsets": len(r["mapsets"]), "maps": maps, "fields": fields},
            "warnings": r["warnings"]}
