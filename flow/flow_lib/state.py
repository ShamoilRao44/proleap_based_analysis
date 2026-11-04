"""State records, cells (storage identity), statement effects, producers and consumers."""
import collections

from . import common

RECORD_TRANSFERS = ("XCTL", "LINK", "RETURN_TRANSID", "START_TRANSID")
SKIP_TYPES = ("execCics", "goback", "stop", "exit", "goTo", "open", "close")


def senders_map(graph):
    """program name -> set of programs that transfer to it directly (XCTL, LINK or via a transaction)."""
    tx_runs = collections.defaultdict(set)
    for e in graph["edges"]:
        if e["type"] == "TRANSACTION_RUNS":
            tx_runs[e["source"]].add(common.strip_prefix(e["target"]))
    out = collections.defaultdict(set)
    for e in graph["edges"]:
        t = e["type"]
        if not e["source"].startswith("program:"):
            continue
        a = common.strip_prefix(e["source"])
        if t in ("XCTL", "LINK") and e["target"].startswith("program:"):
            b = common.strip_prefix(e["target"])
            if a != b:
                out[b].add(a)
        elif t in ("RETURN_TRANSID", "START_TRANSID"):
            for b in tx_runs.get(e["target"], ()):
                if a != b:
                    out[b].add(a)
    return out


def find_records(final):
    """Level-01 items passed as COMMAREA by the transfers of a program. -> (items, warnings)"""
    names = set()
    for t in final.get("transfers", []):
        if t["kind"] in RECORD_TRANSFERS and t.get("commarea"):
            names.add(t["commarea"])
    items = []
    warnings = []
    for n in sorted(names):
        it = next((i for i in final["data_items"] if i["level"] == 1 and i["name"] == n), None)
        if it is None:
            warnings.append("state record %s not defined in %s" % (n, final["name"]))
        else:
            items.append(it)
    return items, warnings


def _leaves_below(item, byid):
    out = []
    stack = [item]
    while stack:
        i = stack.pop()
        if i["children"]:
            for c in reversed(i["children"]):
                stack.append(byid[c])
        elif i["level"] not in (66, 88):
            out.append(i)
    return out


def _eligible(i):
    return bool(i.get("name")) and i["name"] != "FILLER" and (i.get("total_size") or 0) > 0 \
        and i.get("offset") is not None


def build_tables(final, rec_items):
    """Name tables of one program: leaves, 88-level names, groups."""
    items = final["data_items"]
    byid = dict((i["id"], i) for i in items)
    leaves = {}
    rec_of = {}
    cond_to_leaf = {}
    group_leaves = {}
    for R in rec_items:
        for i in items:
            if i["record"] != R["id"] or i["level"] in (66, 88):
                continue
            if not i["children"]:
                if _eligible(i):
                    if i["name"] not in leaves:
                        leaves[i["name"]] = i
                        rec_of[i["name"]] = R["name"]
                    for c in i.get("conditions") or []:
                        cond_to_leaf.setdefault(c, i["name"])
            else:
                names = [x["name"] for x in _leaves_below(i, byid) if _eligible(x)]
                group_leaves.setdefault(i["name"], names)
    return {"leaves": leaves, "rec_of": rec_of, "cond_to_leaf": cond_to_leaf, "group_leaves": group_leaves}


def cell_id(record, offset, size):
    return "%s@%d+%d" % (record, offset, size)


def _evidence(s):
    return {"stmt": s["id"], "paragraph": s.get("paragraph"), "text": (s.get("text") or "")[:80]}


def _add_ev(lst, ev):
    if len(lst) < 3:
        lst.append(ev)


def program_effects(raw, tables, leaf_cell):
    """-> (reads {cell: [ev]}, writes {cell: {kind: [ev]}}, copies [stmt ids])"""
    leaves = tables["leaves"]
    cond = tables["cond_to_leaf"]
    groups = tables["group_leaves"]

    def resolve(name):
        if name in leaves:
            return [name]
        if name in cond:
            return [cond[name]]
        if name in groups:
            return list(groups[name])
        return []

    reads = collections.defaultdict(list)
    writes = collections.defaultdict(lambda: collections.defaultdict(list))
    copies = []
    for s in raw.get("statements", []):
        t = s["type"]
        if t in SKIP_TYPES:
            continue
        fv = s.get("from_var")
        if t == "move":
            to = s.get("to") or []
            if (fv is not None and any(n in groups for n in to)) or (fv is not None and fv in groups):
                copies.append(s["id"])
                continue
        names = list(s.get("reads") or [])
        texts = []
        if t == "if":
            texts.append(s.get("condition") or "")
        elif t == "evaluate":
            texts.extend(s.get("subjects") or [])
            for w in s.get("whens") or []:
                texts.extend(w.get("conditions") or [])
                if w.get("condition"):
                    texts.append(w["condition"])
        elif t == "search":
            for w in s.get("whens") or []:
                if w.get("condition"):
                    texts.append(w["condition"])
        elif t == "perform":
            if s.get("until"):
                texts.append(s["until"])
        for text in texts:
            for tok in common.tokens(text):
                if tok in cond:
                    names.append(tok)
        ev = _evidence(s)
        for n in names:
            for leaf in resolve(n):
                _add_ev(reads[leaf_cell[leaf]], ev)
        if t == "initialize":
            kind = "reset"
        elif t == "set" or (t == "move" and s.get("from_literal") is not None):
            kind = "constant"
        elif t == "move" and fv in leaves:
            kind = "copy"
        else:
            kind = "origin"
        for n in s.get("writes") or []:
            for leaf in resolve(n):
                _add_ev(writes[leaf_cell[leaf]][kind], ev)
    return reads, writes, copies


def build_state(data):
    graph = data["graph"]
    senders = senders_map(graph)
    warnings = []
    cells = {}
    alias = collections.defaultdict(set)
    progs = {}
    record_programs = collections.defaultdict(set)
    record_size = collections.defaultdict(int)

    for P in data["online"]:
        final = data["final"][P]
        recs, w = find_records(final)
        warnings.extend(w)
        if not recs:
            continue
        tables = build_tables(final, recs)
        leaf_cell = {}
        files = final.get("files") or []
        for name, item in sorted(tables["leaves"].items()):
            rec = tables["rec_of"][name]
            key = (rec, item["offset"], item["total_size"])
            leaf_cell[name] = key
            alias[(rec, name)].add((item["offset"], item["total_size"]))
            c = cells.setdefault(key, {"record": rec, "offset": item["offset"], "size": item["total_size"],
                                       "names": set(), "shared": False, "defined_in": {}})
            c["names"].add(name)
            fi = item.get("file_index") or 0
            if fi != 0:
                c["shared"] = True
            src = files[fi]["name"] if fi < len(files) else "program"
            c["defined_in"][(P, name)] = src if fi != 0 else "program"
        for R in recs:
            record_programs[R["name"]].add(P)
            record_size[R["name"]] = max(record_size[R["name"]], R.get("total_size") or 0)
        progs[P] = {"records": [R["name"] for R in recs], "tables": tables, "leaf_cell": leaf_cell}

    for (rec, name), spans in sorted(alias.items()):
        if len(spans) > 1:
            warnings.append("alias_mismatch %s" % name)

    ids = dict((k, cell_id(*k)) for k in cells)

    # partial overlaps between cells of different programs
    by_record = collections.defaultdict(list)
    for k in cells:
        by_record[k[0]].append(k)
    overlaps = []
    for rec, keys in by_record.items():
        keys.sort(key=lambda k: (k[1], k[2]))
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                if b[1] >= a[1] + a[2]:
                    break
                pa = set(p for p, _ in cells[a]["defined_in"])
                pb = set(p for p, _ in cells[b]["defined_in"])
                if any(x != y for x in pa for y in pb):
                    overlaps.append("partial_overlap %s<->%s" % (ids[a], ids[b]))
    warnings.extend(sorted(overlaps)[:50])
    if len(overlaps) > 50:
        warnings.append("%d more partial_overlap warnings" % (len(overlaps) - 50))

    # effects
    for P, info in progs.items():
        raw = data["raw"].get(P)
        info["analysed"] = raw is not None
        if raw is None:
            info.update({"reads": {}, "writes": {}, "copies": []})
            continue
        r, w, copies = program_effects(raw, info["tables"], info["leaf_cell"])
        info["reads"] = dict((ids[k], v) for k, v in r.items())
        info["writes"] = dict((ids[k], dict((kind, ev) for kind, ev in kinds.items())) for k, kinds in w.items())
        info["copies"] = sorted(copies)

    cell_out = {}
    for k, c in cells.items():
        cell_out[ids[k]] = {"id": ids[k], "record": c["record"], "offset": c["offset"], "size": c["size"],
                            "names": sorted(c["names"]), "shared": c["shared"],
                            "defined_in": [{"program": p, "name": n, "source": s}
                                           for (p, n), s in sorted(c["defined_in"].items())],
                            "origin_producers": set(), "constant_writers": set(), "reset_by": set(),
                            "copy_writers": set(), "consumers": set()}
    kind_key = {"origin": "origin_producers", "constant": "constant_writers", "reset": "reset_by",
                "copy": "copy_writers"}
    for P, info in progs.items():
        for cid, kinds in info["writes"].items():
            for kind in kinds:
                cell_out[cid][kind_key[kind]].add(P)
        for cid in info["reads"]:
            cell_out[cid]["consumers"].add(P)
    for c in cell_out.values():
        for key in ("origin_producers", "constant_writers", "reset_by", "copy_writers", "consumers"):
            c[key] = sorted(c[key])
        c["single_origin"] = len(c["origin_producers"]) == 1

    programs = {}
    for P in sorted(progs):
        info = progs[P]
        written = set(info["writes"])
        requires = sorted(cid for cid in info["reads"] if cid not in written)
        provides = sorted(cid for cid, kinds in info["writes"].items() if "origin" in kinds)
        requirements = []
        for cid in requires:
            c = cell_out[cid]
            if c["shared"]:
                producers = [p for p in c["origin_producers"] if p != P]
            else:
                producers = [p for p in c["origin_producers"] if p in senders.get(P, ())]
            requirements.append({"cell": cid, "kind": "shared" if c["shared"] else "local",
                                 "producers": producers,
                                 "status": "produced" if producers else "unproduced"})
        programs[P] = {"records": info["records"], "requires": requires, "provides": provides,
                       "requirements": requirements,
                       "reads": dict(sorted(info["reads"].items())),
                       "writes": dict((cid, dict(sorted(kinds.items())))
                                      for cid, kinds in sorted(info["writes"].items())),
                       "copies": info["copies"], "analysed": info["analysed"]}

    records = [{"name": n, "programs": sorted(ps), "size": record_size[n]}
               for n, ps in sorted(record_programs.items())]
    return {"schema": "state-deps/1", "records": records,
            "cells": [cell_out[k] for k in sorted(cell_out)], "programs": programs, "warnings": warnings}
