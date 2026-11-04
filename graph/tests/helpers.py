"""Builders for synthetic facts (only the keys the graph builder reads)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from graph_lib import analysis, batch, model, names, online  # noqa: E402

UTILITIES = names.UTILITIES


def cobol(name, kind="cics_online", transfers=(), resources=(), files_io=(), copybooks=(), sql_includes=(),
          program_id=None):
    return {"name": name, "program_id": program_id or name, "path": name + ".cbl", "kind": kind,
            "flags": {"uses_cics": kind == "cics_online", "uses_db2": False, "uses_ims": False, "uses_mq": False},
            "metrics": {"lines": 10, "est_tokens_program": 5}, "source": "proleap",
            "files": [{"index": 0, "path": name + ".cbl"}], "transfers": list(transfers),
            "resources": list(resources), "files_io": list(files_io), "copybooks": list(copybooks),
            "sql_includes": list(sql_includes)}


def transfer(kind, values, how="literal", unresolved=False, target_text=None):
    if values:
        target = {"literal": values[0]}
    else:
        target = {"var": target_text or "X", "text": target_text or "X"}
    return {"kind": kind, "target": target, "resolved_targets": [{"value": v, "how": how} for v in values],
            "unresolved": unresolved, "paragraph": "P1", "loc": [0, 10], "commarea": None, "guards": []}


def resource(kind, values=(), op="read", mapset_values=(), unresolved=False):
    return {"kind": kind, "name": {"literal": values[0]} if values else None,
            "name_resolved": [{"value": v, "how": "literal"} for v in values],
            "mapset": None, "mapset_resolved": [{"value": v, "how": "literal"} for v in mapset_values],
            "op": op, "command": "X", "unresolved": unresolved, "paragraph": "P1", "loc": [0, 12], "extra": {}}


def csd_file(name, definitions):
    defs = []
    for d in definitions:
        x = {"type": d["type"], "name": d["name"], "line": 1, "program": None, "dsname": None, "queue_type": None,
             "attrs": {}}
        x.update(d)
        defs.append(x)
    return {"name": name, "path": name + ".csd", "definitions": defs}


def dd(name, dsn, mode_hint="read", member=None, generation=None, temp=False):
    return {"name": name, "dsn": dsn, "mode_hint": mode_hint, "member": member, "generation": generation,
            "temp": temp, "dummy": False, "sysout": False, "null_file": False, "inline": None, "disp": None,
            "unresolved_symbols": []}


def step(index, name, program, dds=(), invokes=None, utility=None, utility_data=None, kind="program"):
    if utility is None:
        utility = program in UTILITIES
    if invokes is None:
        invokes = [] if utility else [{"program": program, "via": "EXEC PGM"}]
    return {"index": index, "name": name, "kind": kind, "program": program, "proc": None, "proc_found": None,
            "utility": utility, "build": False, "cond": None, "if_context": [], "expanded_from": None, "line": 1,
            "dds": list(dds), "invokes": invokes, "utility_data": utility_data or {}}


def jcl_file(name, steps, procs_used=()):
    return {"name": name, "path": name + ".jcl", "kind": "job", "declared_name": name, "flat_steps": list(steps),
            "procs_used": list(procs_used), "unresolved_symbols": []}


def data(cobol=(), csd=(), jcl=(), proc=(), bms=(), ddl=(), ims=(), control=(), inventory=()):
    return {"root": "root", "inventory": list(inventory), "cobol": dict((c["name"], c) for c in cobol),
            "csd": list(csd), "jcl": list(jcl), "proc": list(proc), "bms": list(bms), "ddl": list(ddl),
            "ims": list(ims), "control": list(control)}


def build(d):
    """Run online + batch edge builders. Returns (graph, resolver)."""
    r = names.Resolver(d)
    g = model.Graph()
    online.add_online(g, r, d)
    batch.add_batch(g, r, d)
    return g, r


def has(g, type_, src, dst):
    return (type_, src, dst) in g.edges


def edge(g, type_, src, dst):
    return g.edges[(type_, src, dst)]
