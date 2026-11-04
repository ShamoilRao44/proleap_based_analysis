"""Builders for synthetic facts (only the keys the flow analysis reads) and the SHOP mini application."""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from flow_lib import entry, process, state  # noqa: E402


def item(id_, name, level, offset, size, record, parent=None, children=(), conditions=(), file_index=0,
         values=None):
    return {"id": id_, "level": level, "name": name, "parent": parent, "record": record,
            "children": list(children), "conditions": list(conditions), "offset": offset, "size": size,
            "total_size": size, "is_group": bool(children), "values": values, "file_index": file_index,
            "loc": [file_index, 1]}


def final(name, items, transfers=(), decisions=(), kind="cics_online"):
    return {"name": name, "kind": kind, "path": name + ".cbl",
            "files": [{"index": 0, "path": name + ".cbl", "name": name},
                      {"index": 1, "path": "COMM.cpy", "name": "COMM"}],
            "data_items": list(items), "transfers": list(transfers), "decisions": list(decisions),
            "resources": [], "procedure": {"paragraphs": []}}


def xfer(stmt_id, kind, values, var=None, commarea="COMM"):
    target = {"var": var, "text": var} if var else {"literal": values[0]}
    return {"kind": kind, "stmt_id": stmt_id, "target": target,
            "resolved_targets": [{"value": v, "how": "literal"} for v in values], "commarea": commarea,
            "paragraph": "P", "loc": [0, 1]}


def stmt(id_, type_, paragraph, parent=None, branch=None, **kw):
    s = {"id": id_, "type": type_, "paragraph": paragraph, "parent": parent, "branch": branch, "pline": id_,
         "text": kw.pop("text", type_), "reads": [], "writes": []}
    s.update(kw)
    return s


def rawf(name, paragraphs, statements):
    return {"name": name, "paragraphs": [{"name": p, "declaratives": False} for p in paragraphs],
            "statements": list(statements)}


def graph(transactions=None, edges=()):
    nodes = {}
    out_edges = []

    def node(nid):
        nodes.setdefault(nid, {"id": nid, "type": nid.split(":")[0], "name": nid.split(":")[1], "attrs": {}})

    for t, prog in sorted((transactions or {}).items()):
        node("transaction:" + t)
        node("program:" + prog)
        out_edges.append({"type": "TRANSACTION_RUNS", "source": "transaction:" + t, "target": "program:" + prog,
                          "access": None, "details": []})
    for typ, a, b in edges:
        node("program:" + a)
        node("program:" + b)
        out_edges.append({"type": typ, "source": "program:" + a, "target": "program:" + b, "access": None,
                          "details": [{"how": "literal", "guards": []}]})
    return {"codebase_root": "root", "nodes": list(nodes.values()), "edges": out_edges,
            "analysis": {"data_stores": []}}


def shop_items(local_name=None):
    its = [item(1, "COMM", 1, 0, 48, 1, children=[2, 3, 4] + ([5] if local_name else []), file_index=1),
           item(2, "USER-ID", 5, 0, 8, 1, parent=1, file_index=1),
           item(3, "USER-TYPE", 5, 8, 1, 1, parent=1, conditions=["IS-ADMIN"], file_index=1),
           item(4, "PAD", 5, 9, 31, 1, parent=1, file_index=1)]
    if local_name:
        its.append(item(5, local_name, 5, 40, 8, 1, parent=1, file_index=0))
    return its


XCTL_TEXT = "EXEC CICS XCTL PROGRAM('X') END-EXEC"


def shop_programs():
    """-> (finals, raws) of the five programs of SHOP."""
    finals = {}
    raws = {}
    finals["SIGN"] = final("SIGN", shop_items(), [xfer(5, "XCTL", ["MENU"])])
    raws["SIGN"] = rawf("SIGN", ["MAIN"], [
        stmt(1, "if", "MAIN", condition="EIBCALEN = 0"),
        stmt(2, "execCics", "MAIN", 1, "then", exec_text="EXEC CICS SEND MAP('M') MAPSET('S') END-EXEC"),
        stmt(3, "move", "MAIN", 1, "else", from_var="UID-IN", to=["USER-ID"], writes=["USER-ID"]),
        stmt(4, "move", "MAIN", 1, "else", from_var="UTYPE-IN", to=["USER-TYPE"], writes=["USER-TYPE"]),
        stmt(5, "execCics", "MAIN", 1, "else", exec_text=XCTL_TEXT)])
    finals["MENU"] = final("MENU", shop_items(), [xfer(5, "XCTL", ["SIGN", "LIST"], var="TARGET")])
    raws["MENU"] = rawf("MENU", ["MAIN", "BACK"], [
        stmt(1, "if", "MAIN", condition="EIBCALEN = 0"),
        stmt(2, "move", "MAIN", 1, "then", from_literal="'SIGN'", to=["TARGET"], writes=["TARGET"]),
        stmt(3, "perform", "MAIN", 1, "then", target="BACK", thru=None, inline=False),
        stmt(4, "if", "MAIN", 1, "else", condition="IS-ADMIN"),
        stmt(5, "execCics", "BACK", exec_text="EXEC CICS XCTL PROGRAM(TARGET) END-EXEC")])
    finals["LIST"] = final("LIST", shop_items("LIST-SEL"), [xfer(2, "XCTL", ["DETAIL"])])
    raws["LIST"] = rawf("LIST", ["MAIN"], [
        stmt(1, "move", "MAIN", from_var="ROW-IN", to=["LIST-SEL"], writes=["LIST-SEL"]),
        stmt(2, "execCics", "MAIN", exec_text=XCTL_TEXT)])
    finals["DETAIL"] = final("DETAIL", shop_items("DET-SEL"), [xfer(2, "XCTL", ["MENU"])])
    raws["DETAIL"] = rawf("DETAIL", ["MAIN"], [
        stmt(1, "move", "MAIN", from_var="DET-SEL", to=["WS-X"], reads=["DET-SEL"], writes=["WS-X"]),
        stmt(2, "execCics", "MAIN", exec_text=XCTL_TEXT)])
    card_items = shop_items() + [item(6, "LIT-MENU", 77, 0, 8, 6,
                                      values=[{"from": "'MENU'", "kind": "string", "value": "MENU"}])]
    finals["CARD"] = final("CARD", card_items, [xfer(3, "XCTL", ["MENU"])])
    raws["CARD"] = rawf("CARD", ["MAIN"], [
        stmt(1, "if", "MAIN", condition="EIBCALEN = 0 OR FROM-PGM = LIT-MENU"),
        stmt(2, "initialize", "MAIN", 1, "then", writes=["USER-TYPE"]),
        stmt(3, "execCics", "MAIN", exec_text=XCTL_TEXT)])
    return finals, raws


SHOP_TRANSACTIONS = {"T-SIGN": "SIGN", "T-MENU": "MENU", "T-LIST": "LIST", "T-CARD": "CARD"}
SHOP_EDGES = [("XCTL", "MENU", "SIGN"), ("XCTL", "MENU", "LIST"), ("XCTL", "LIST", "DETAIL"),
              ("XCTL", "SIGN", "MENU")]


def assemble(finals, raws, transactions=None, edges=None):
    g = graph(SHOP_TRANSACTIONS if transactions is None else transactions,
              SHOP_EDGES if edges is None else edges)
    return {"root": "root", "final": finals, "raw": raws, "graph": g,
            "online": sorted(n for n, d in finals.items() if d["kind"] == "cics_online"), "warnings": []}


def shop_data(transactions=None, edges=None):
    finals, raws = shop_programs()
    return assemble(finals, raws, transactions, edges)


def shop_entries(data):
    known = set(data["final"])
    return dict((n, entry.first_entry(data["final"][n], data["raw"].get(n), known)) for n in data["online"])


def shop_process(data=None):
    data = data or shop_data()
    st = state.build_state(data)
    entries = shop_entries(data)
    return data, st, entries, process.build_process(data, st, entries)


def clone(x):
    return copy.deepcopy(x)
