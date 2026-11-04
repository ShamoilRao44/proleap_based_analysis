"""Edges from COBOL facts, CSD, and BMS."""
from . import access, common, names

HARD_KINDS = ("CALL", "LINK", "XCTL", "HANDLE_ABEND")
SKIP_TRANSFERS = ("GOBACK", "STOP_RUN", "EXIT_PROGRAM", "RETURN")


def _csd_defs(g, r, defining_id, defs):
    for d in defs:
        t = d["type"]
        name = d["name"]
        if t == "TRANSACTION":
            tid = g.add_node("transaction", name, True, program=d.get("program"), defined_in=[defining_id])["id"]
            g.add_edge("CSD_DEFINES", defining_id, tid, None, {"line": d.get("line")})
            if d.get("program"):
                g.add_edge("TRANSACTION_RUNS", tid, r.program(g, d["program"]), None, {"source": defining_id})
        elif t == "PROGRAM":
            pid = r.program(g, name)
            g.add_node("program", g.get(pid)["name"], None, csd_defined=True)
            g.add_edge("CSD_DEFINES", defining_id, pid, None, {"line": d.get("line")})
        elif t == "MAPSET":
            mid = r.mapset(g, name)
            g.add_node("mapset", name, None, csd_defined=True)
            g.add_edge("CSD_DEFINES", defining_id, mid, None, {"line": d.get("line")})
        elif t == "FILE":
            fid = r.cics_file(g, name)
            g.add_edge("CSD_DEFINES", defining_id, fid, None, {"line": d.get("line")})
            if d.get("dsname"):
                g.add_edge("CICS_FILE_DATASET", fid, r.dataset(g, d["dsname"], None, False), None,
                           {"source": defining_id})
        elif t == "TDQUEUE":
            attrs = d.get("attrs") or {}
            ddname = attrs.get("DDNAME")
            qid = g.add_node("td_queue", name, True, queue_type=d.get("queue_type"), ddname=ddname,
                             internal_reader=str(ddname or "").upper() == "INREADER")["id"]
            g.add_edge("CSD_DEFINES", defining_id, qid, None, {"line": d.get("line")})


def _ev(c, loc):
    files = c.get("files") or []
    f = files[loc[0]]["path"] if loc and loc[0] < len(files) else None
    return f, (loc[1] if loc else None)


def _target_text(t):
    tg = t.get("target") or {}
    return tg.get("text") or tg.get("var") or tg.get("literal")


def add_online(g, r, data):
    # 1. CSD definitions
    for f in data.get("csd", []):
        cid = g.add_node("csd", f["name"], True, path=f.get("path"))["id"]
        _csd_defs(g, r, cid, f["definitions"])
    for job, _step, defs in names.inline_csds(data):
        jf = [j for j in data["jcl"] if j["name"] == job][0]
        jid = g.add_node("job", job, True, path=jf.get("path"))["id"]
        _csd_defs(g, r, jid, defs)

    # 2. BMS
    for f in data.get("bms", []):
        for m in f.get("mapsets", []):
            if not m.get("name"):
                continue
            mid = r.mapset(g, m["name"])
            g.add_node("mapset", m["name"], None, maps=[mp["name"] for mp in m.get("maps", []) if mp.get("name")],
                       path=f.get("path"))
            if m.get("symbolic_copybook"):
                g.add_edge("SYMBOLIC_MAP", mid, r.copybook(g, common.member_of(m["symbolic_copybook"])))

    # 3. programs
    for name in sorted(data["cobol"]):
        c = data["cobol"][name]
        flags = c.get("flags") or {}
        pid = r.program(g, name)
        g.add_node("program", name, True, path=c.get("path"), kind=c.get("kind"), program_id=c.get("program_id"),
                   lines=(c.get("metrics") or {}).get("lines"),
                   est_tokens=(c.get("metrics") or {}).get("est_tokens_program"), source=c.get("source"),
                   uses_cics=bool(flags.get("uses_cics")), uses_db2=bool(flags.get("uses_db2")),
                   uses_ims=bool(flags.get("uses_ims")), uses_mq=bool(flags.get("uses_mq")))
        ims_calls = sum(1 for x in c.get("resources", []) if x["kind"] == "ims_call")
        mq_calls = sum(1 for x in c.get("resources", []) if x["kind"] == "mq_call")
        g.add_node("program", name, None, ims_calls=ims_calls, mq_calls=mq_calls)

        # 4. transfers
        for t in c.get("transfers", []):
            if t["kind"] in SKIP_TRANSFERS:
                continue
            file_, line = _ev(c, t.get("loc"))
            if t.get("unresolved"):
                r.unresolved.append({"kind": "dynamic_transfer", "program": name, "transfer_kind": t["kind"],
                                     "target_text": _target_text(t), "file": file_, "line": line})
                continue
            for rt in t.get("resolved_targets", []):
                v = rt["value"]
                if t["kind"] in ("CALL", "LINK", "XCTL", "HANDLE_ABEND"):
                    target = r.program(g, v)
                elif t["kind"] in ("RETURN_TRANSID", "START_TRANSID"):
                    target = r.transaction(g, v)
                else:
                    continue
                g.add_edge(t["kind"], pid, target, None,
                           {"how": rt.get("how"), "paragraph": t.get("paragraph"), "file": file_, "line": line,
                            "commarea": t.get("commarea"), "guards": (t.get("guards") or [])[:2]})

        # 5. resources
        for res in c.get("resources", []):
            kind = res["kind"]
            file_, line = _ev(c, res.get("loc"))
            if res.get("unresolved"):
                nm = res.get("name") or {}
                r.unresolved.append({"kind": "dynamic_resource", "program": name, "resource_kind": kind,
                                     "name_text": nm.get("text") or nm.get("var") or nm.get("literal"),
                                     "file": file_, "line": line})
            if kind == "cics_file":
                for v in res.get("name_resolved", []):
                    g.add_edge("PROGRAM_CICS_FILE", pid, r.cics_file(g, v["value"]), access.from_cics_op(res.get("op")),
                               {"op": res.get("op"), "command": res.get("command"),
                                "paragraph": res.get("paragraph"), "file": file_, "line": line})
            elif kind == "map":
                nm = res.get("name") or {}
                for v in res.get("mapset_resolved", []):
                    g.add_edge("USES_MAP", pid, r.mapset(g, v["value"]), None,
                               {"map": nm.get("literal") or nm.get("text"), "op": res.get("op"),
                                "paragraph": res.get("paragraph"), "file": file_, "line": line})
            elif kind == "db2_table":
                if res.get("op") == "declare":
                    continue
                for v in res.get("name_resolved", []):
                    g.add_edge("PROGRAM_DB2_TABLE", pid, r.table(g, v["value"]), access.from_sql_op(res.get("op")),
                               {"op": res.get("op"), "command": res.get("command"),
                                "paragraph": res.get("paragraph"), "file": file_, "line": line})
            elif kind in ("ts_queue", "td_queue"):
                etype = "PROGRAM_TS_QUEUE" if kind == "ts_queue" else "PROGRAM_TD_QUEUE"
                for v in res.get("name_resolved", []):
                    qid = g.add_node(kind, v["value"], None)["id"]
                    g.add_edge(etype, pid, qid, access.from_queue_op(res.get("op")),
                               {"op": res.get("op"), "paragraph": res.get("paragraph"), "file": file_,
                                "line": line})

        # 6. copybooks
        for e in c.get("copybooks", []):
            source = pid if not e.get("via") else r.copybook(g, e["via"])
            loc = e.get("loc")
            file_, line = _ev(c, loc)
            g.add_edge("COPY", source, r.copybook(g, e["name"]), None,
                       {"file": file_, "line": line, "depth": e.get("depth")})

        # 7. SQL includes
        for s in c.get("sql_includes", []):
            g.add_edge("SQL_INCLUDE", pid, r.copybook(g, s["name"]), None, {"line": (s.get("loc") or [0, None])[1]})
