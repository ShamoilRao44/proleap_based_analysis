"""IMS DBD / PSB scanner."""
import re

from . import common
from .asm_stmt import read_asm_statements


def _params(operands):
    d = {}
    for k, v in common.parse_params(operands):
        if k is not None and k not in d:
            d[k] = v
    return d


def _parent(value):
    if value is None:
        return None
    v = value.strip()
    if v == "0":
        return None
    m = re.search(r"[A-Za-z0-9#@$]+", v.replace("(", " ").replace(")", " ").replace(",", " "))
    if not m or m.group(0) == "0":
        return None
    return m.group(0).upper()


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_lines(lines):
    dbd = None
    psb = None
    pcbs = []
    warnings = []
    last_seg = None
    for st in read_asm_statements(lines):
        op = st["op"]
        p = _params(st["operands"])
        if op == "DBD":
            dbd = {"name": p.get("NAME", "").upper(),
                   "access": [x.upper() for x in common.sub_params(p["ACCESS"])] if "ACCESS" in p else [],
                   "line": st["line"], "datasets": [], "segments": []}
        elif op == "DATASET":
            if dbd is None:
                warnings.append("DATASET before DBD")
                continue
            dbd["datasets"].append({"label": st["label"] or None, "dd1": p.get("DD1"), "dd2": p.get("DD2"),
                                    "size": p.get("SIZE"), "line": st["line"]})
        elif op == "SEGM":
            if dbd is None:
                warnings.append("SEGM before DBD")
                continue
            last_seg = {"name": p.get("NAME", "").upper(), "parent": _parent(p.get("PARENT")),
                        "bytes": _int(p.get("BYTES")), "rules": p.get("RULES"), "pointer": p.get("POINTER"),
                        "line": st["line"], "fields": [], "lchild": []}
            dbd["segments"].append(last_seg)
        elif op == "FIELD":
            if dbd is None or last_seg is None:
                warnings.append("FIELD before DBD")
                continue
            nm = p.get("NAME", "")
            items = common.sub_params(nm)
            fld = {"name": items[0].upper() if items else "",
                   "seq": len(items) > 1 and items[1].upper() == "SEQ",
                   "unique": len(items) > 2 and items[2].upper() == "U",
                   "start": _int(p.get("START")), "bytes": _int(p.get("BYTES")), "type": p.get("TYPE"),
                   "line": st["line"]}
            last_seg["fields"].append(fld)
        elif op == "LCHILD":
            if dbd is None or last_seg is None:
                warnings.append("LCHILD before DBD")
                continue
            items = common.sub_params(p.get("NAME", ""))
            last_seg["lchild"].append({"segment": items[0].upper() if items else "",
                                       "dbd": items[1].upper() if len(items) > 1 else None,
                                       "pointer": p.get("POINTER"), "line": st["line"]})
        elif op == "PCB":
            procopt = p.get("PROCOPT")
            hint = None
            if procopt:
                hint = "update" if re.search(r"[AIRD]", procopt.upper()) else "read"
            pcbs.append({"index": len(pcbs) + 1, "label": st["label"] or None,
                         "type": (p.get("TYPE") or "").upper() or None, "dbdname": p.get("DBDNAME"),
                         "procopt": procopt, "keylen": _int(p.get("KEYLEN")), "access_hint": hint,
                         "line": st["line"], "segments": []})
        elif op == "SENSEG":
            if not pcbs:
                warnings.append("SENSEG before PCB")
                continue
            pcbs[-1]["segments"].append({"name": p.get("NAME", "").upper(), "parent": _parent(p.get("PARENT")),
                                         "procopt": p.get("PROCOPT")})
        elif op == "PSBGEN":
            psb = {"name": p.get("PSBNAME", "").upper(), "lang": p.get("LANG"), "cmpat": p.get("CMPAT"),
                   "line": st["line"], "pcbs": pcbs}
    if psb is None and pcbs:
        psb = {"name": None, "lang": None, "cmpat": None, "line": None, "pcbs": pcbs}
    return {"dbd": dbd, "psb": psb, "warnings": warnings}


def scan_file(path, rec, root):
    lines = common.split_lines(common.read_text(path))
    r = parse_lines(lines)
    if r["psb"] is not None and r["psb"]["name"] is None:
        r["psb"]["name"] = rec["name"]
    kind = "dbd" if r["dbd"] is not None else "psb"
    declared = r["dbd"]["name"] if r["dbd"] is not None else (r["psb"]["name"] if r["psb"] else None)
    return {"schema": "ims-facts/1", "name": rec["name"], "path": rec["path"], "kind": kind,
            "declared_name": declared, "dbd": r["dbd"], "psb": r["psb"], "warnings": r["warnings"]}
