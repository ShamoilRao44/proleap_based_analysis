"""Edges from JCL, PROC, control cards, IDCAMS and IMS."""
import re

from . import access, names


def _cobol_by_program(data):
    out = {}
    for name, cf in data["cobol"].items():
        out[name.upper()] = cf
        if cf.get("program_id"):
            out.setdefault(cf["program_id"].upper(), cf)
    return out


def add_batch(g, r, data):
    cbp = _cobol_by_program(data)

    # 1. proc and control card nodes
    for p in data.get("proc", []):
        g.add_node("proc", p["name"], True, path=p.get("path"), declared_name=p.get("declared_name"))
    for k in data.get("control", []):
        g.add_node("control_card", k["name"], True, path=k.get("path"), kind=k.get("kind"))

    # 2. jobs
    for j in data.get("jcl", []):
        if j.get("kind") not in ("job", "fragment"):
            continue
        jid = g.add_node("job", j["name"], True, path=j.get("path"), declared_name=j.get("declared_name"),
                         kind=j.get("kind"))["id"]
        for u in j.get("procs_used") or []:
            if u.get("found"):
                pf = r.procs.get(u["name"])
                if pf is not None:
                    pid = g.add_node("proc", pf["name"], True)["id"]
                    g.add_edge("JOB_USES_PROC", jid, pid)
        if j.get("unresolved_symbols"):
            r.unresolved.append({"kind": "unresolved_symbols", "job": j["name"],
                                 "names": list(j["unresolved_symbols"])})
        for s in j.get("flat_steps") or []:
            sid = g.add_node("step", "%s#%s" % (j["name"], s["index"]), True, job=j["name"], step_name=s["name"],
                             index=s["index"], program=s.get("program"), kind=s.get("kind"),
                             expanded_from=s.get("expanded_from"), cond=s.get("cond"),
                             if_context=list(s.get("if_context") or []), utility=bool(s.get("utility")),
                             line=s.get("line"))["id"]
            g.add_edge("JOB_STEP", jid, sid, None, {"index": s["index"]})
            if s.get("kind") == "proc" and s.get("proc_found") is False:
                r.unresolved.append({"kind": "proc_not_found", "job": j["name"], "step": s["name"],
                                     "proc": s.get("proc")})
            program = s.get("program") if s.get("kind") == "program" else None
            if program:
                g.add_edge("STEP_RUNS", sid, r.program(g, program))
            for inv in s.get("invokes") or []:
                if inv.get("program") and inv["program"] != program:
                    pid = r.program(g, inv["program"])
                    g.add_edge("STEP_RUNS", sid, pid, None, {"via": inv.get("via"), "plan": inv.get("plan")})
                if inv.get("psb"):
                    psb = g.add_node("psb", inv["psb"], None)["id"]
                    g.add_edge("STEP_PSB", sid, psb)
                    g.add_edge("PROGRAM_PSB", r.program(g, inv["program"]), psb)

            # DDs
            files_io = []
            cf = cbp.get(program) if program else None
            if cf is not None:
                files_io = cf.get("files_io") or []
            for d in s.get("dds") or []:
                if (not d.get("dsn") or d.get("dummy") or d.get("sysout") or d.get("null_file")
                        or d.get("inline") is not None or d.get("mode_hint") == "library"):
                    continue
                dsid = r.dataset(g, d["dsn"], j["name"], d.get("temp"))
                if d.get("generation") is not None:
                    g.add_node("dataset", g.get(dsid)["name"], None, gdg=True)
                a = access.dd_access(s, d, cbp)
                disp = d.get("disp") or {}
                g.add_edge("STEP_DATASET", sid, dsid, a,
                           {"dd": d["name"], "member": d.get("member"), "generation": d.get("generation"),
                            "disp": disp.get("raw"), "mode_hint": d.get("mode_hint")})
                if d.get("member") and d["member"].upper() in r.control_cards:
                    kid = g.add_node("control_card", r.control_cards[d["member"].upper()]["name"], True)["id"]
                    g.add_edge("STEP_CONTROL_CARD", sid, kid, None, {"dd": d["name"], "dsn": d["dsn"]})
                for fio in files_io:
                    if fio.get("dd") == d["name"]:
                        g.add_edge("PROGRAM_DATASET", r.program(g, program), dsid,
                                   fio.get("access_summary") or "unknown",
                                   {"job": j["name"], "step": s["name"], "dd": d["name"]})
            if cf is not None:
                present = set(d["name"] for d in s.get("dds") or [])
                for fio in files_io:
                    if fio.get("dd") and fio["dd"] not in present:
                        r.unresolved.append({"kind": "dd_missing", "job": j["name"], "step": s["name"],
                                             "program": program, "dd": fio["dd"]})

            ud = s.get("utility_data") or {}
            # IDCAMS commands
            for c in ud.get("idcams_commands") or []:
                verb = c.get("verb")
                if verb == "DEFINE" and c.get("name"):
                    dsid = r.dataset(g, c["name"], j["name"], c["name"].startswith("&&"))
                    g.add_edge("IDCAMS_DEFINE", sid, dsid, "write", {"subtype": c.get("subtype"), "line": c.get("line")})
                    if c.get("subtype") == "GDG":
                        g.add_node("dataset", g.get(dsid)["name"], None, gdg=True)
                    rel = (c.get("attrs") or {}).get("RELATE")
                    if rel:
                        g.add_edge("DATASET_RELATE", dsid, r.dataset(g, rel, j["name"], False), None, {"kind": "AIX"})
                    if c.get("subtype") == "PATH":
                        m = re.search(r"(?i)PATHENTRY\s*\(\s*([^)\s]+)", c.get("text") or "")
                        if m:
                            g.add_edge("DATASET_RELATE", dsid, r.dataset(g, m.group(1).upper(), j["name"], False),
                                       None, {"kind": "PATH"})
                elif verb == "DELETE":
                    for n in c.get("names") or []:
                        dsid = r.dataset(g, n, j["name"], n.startswith("&&"))
                        g.add_edge("IDCAMS_DELETE", sid, dsid, "delete",
                                   {"object_type": c.get("object_type"), "line": c.get("line")})
                elif verb in ("REPRO", "PRINT"):
                    if c.get("indataset"):
                        g.add_edge("STEP_DATASET", sid, r.dataset(g, c["indataset"], j["name"], False), "read",
                                   {"dd": None, "via": "IDCAMS " + verb})
                    if verb == "REPRO" and c.get("outdataset"):
                        g.add_edge("STEP_DATASET", sid, r.dataset(g, c["outdataset"], j["name"], False), "write",
                                   {"dd": None, "via": "IDCAMS " + verb})
            # SDSF commands
            for c in ud.get("sdsf_commands") or []:
                if c.get("resource_type") == "FILE":
                    g.add_edge("JOB_CICS_COMMAND", jid, r.cics_file(g, c["resource"]), None,
                               {"action": c.get("action"), "region": c.get("region"), "step": s["name"]})

    # 3. IMS
    dbd_names = set()
    for f in data.get("ims", []):
        if f.get("kind") == "dbd" and f.get("declared_name"):
            dbd_names.add(f["declared_name"])
            g.add_node("ims_db", f["declared_name"], True, path=f.get("path"))
    for f in data.get("ims", []):
        if f.get("kind") != "psb" or not f.get("declared_name"):
            continue
        pid = g.add_node("psb", f["declared_name"], True, path=f.get("path"))["id"]
        for pcb in ((f.get("psb") or {}).get("pcbs") or []):
            if pcb.get("dbdname"):
                dbd = pcb["dbdname"].upper()
                did = g.add_node("ims_db", dbd, dbd in dbd_names)["id"]
                g.add_edge("PSB_DBD", pid, did, "read_write" if pcb.get("access_hint") == "update" else "read",
                           {"procopt": pcb.get("procopt"), "pcb": pcb.get("index")})

    # 4. tables
    for f in data.get("ddl", []):
        for t in f.get("tables", []):
            r.table(g, t["qualified"])
            g.add_node("db2_table", t["qualified"], None, defined_in=[f.get("path")])
    for j, tables in names.inline_tables(data):
        for t in tables:
            r.table(g, t["qualified"])
            g.add_node("db2_table", t["qualified"], None, defined_in=["%s (inline SQL)" % j.get("path")])
