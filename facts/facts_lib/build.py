"""Builds final facts (cobol-facts/1) from raw facts (parser or text)."""
import os
import re
from collections import Counter

from . import common, linemap, layout, cics, sql, dynamic, flow

DLI_CALLS = {"CBLTDLI", "AIBTDLI", "CEETDLI"}
MQ_CALLS = {"MQCONN", "MQCONNX", "MQOPEN", "MQPUT", "MQPUT1", "MQGET", "MQCLOSE", "MQDISC", "MQINQ",
            "MQSET", "MQBEGIN", "MQCMIT", "MQBACK"}
ABEND_CALLS = {"CEE3ABD", "ILBOABN0", "CEE3AB2"}
SPECIAL_REGISTERS = {"RETURN-CODE", "SORT-RETURN", "SORT-CONTROL", "TALLY", "WHEN-COMPILED", "LENGTH", "ADDRESS",
                     "DEBUG-ITEM", "LINAGE-COUNTER", "SHIFT-OUT", "SHIFT-IN", "XML-CODE", "JNIENVPTR"}
SECTION_KINDS = {"FILE": "file", "WORKING-STORAGE": "working-storage", "LOCAL-STORAGE": "local-storage",
                 "LINKAGE": "linkage"}


def _cap(s, n):
    return s if len(s) <= n else s[:n] + "..."


def _opt_out(o):
    """Option value dict -> output form."""
    if not o:
        return None
    if "literal" in o:
        return {"literal": o["literal"]}
    if "var" in o:
        return {"var": o["var"], "text": o["text"]}
    if "number" in o:
        return {"number": o["number"]}
    return {"flag": True}


def _region(raw, pline):
    div = raw.get("divisions") or {}
    secs = raw.get("data_sections") or []
    # a data section reaches up to the next section (or the procedure division): marker lines of
    # a missing copybook at the end of a section lie after the section's last token
    limit = (div.get("procedure") or [10 ** 9])[0]
    for i, sec in enumerate(secs):
        end = secs[i + 1]["start"] - 1 if i + 1 < len(secs) else limit - 1
        if sec["start"] <= pline <= max(end, sec["end"]):
            return SECTION_KINDS.get(sec["kind"], "other")
    for key in ("procedure", "environment", "identification"):
        r = div.get(key)
        if r and r[0] <= pline <= r[1]:
            return key
    return "unknown"


def _word_regex(names):
    names = [n for n in names if n]
    if not names:
        return None
    return re.compile(r"(?<![A-Z0-9-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![A-Z0-9-])")


def _combine_access(modes, ops):
    flags = set()
    for m in modes:
        flags.add({"INPUT": "read", "OUTPUT": "write", "EXTEND": "write", "I-O": "read_write"}.get(m, "read_write"))
    for o in ops:
        flags.add({"READ": "read", "START": "read", "WRITE": "write", "REWRITE": "read_write",
                   "DELETE": "read_write"}.get(o, "read_write"))
    if not flags:
        return "unknown"
    if flags == {"read"}:
        return "read"
    if flags == {"write"}:
        return "write"
    return "read_write"


def build(raw, pp_lines, ctx):
    """See STEP2_BUILD_PLAN.md section 6.8."""
    from . import textscan

    root = ctx["codebase_root"]
    fmt = raw.get("format") or "FIXED"
    orig = ctx["original_lines"]
    parser = raw.get("parser") or "proleap"

    # 1. line map
    if parser == "proleap":
        lm = linemap.build_linemap(pp_lines, raw["program_file"], fmt)
    else:
        lm = linemap.identity_linemap(raw["program_file"], len(orig))

    def L(pl):
        return linemap.loc(lm, pl)

    files = [{"index": f["index"], "path": common.relpath(f["path"], root), "name": f["name"], "kind": f["kind"]}
             for f in lm["files"]]

    # 2. copybooks
    events = lm["copies"] if parser == "proleap" else (raw.get("copy_events_direct") or [])
    copybooks = []
    for i, e in enumerate(events):
        via = None
        for j in range(i - 1, -1, -1):
            p = events[j]
            if p["enter_pline"] < e["enter_pline"] <= (p.get("exit_pline") or 10 ** 9):
                via = p["name"]
                break
        path = e.get("path")
        if path and os.path.isabs(path):
            path = common.relpath(path, root)
        copybooks.append({"name": e["name"], "path": path, "file_index": e.get("file_index"),
                          "loc": [e["parent_file"], e["line"]], "region": _region(raw, e["enter_pline"]),
                          "depth": e["depth"], "via": via, "missing": e["missing"], "exact": e["exact"],
                          "source": parser})

    # 3. data items
    items = layout.build_items(raw.get("data_items") or [])
    by_name = {}
    by_id = {}
    for it in items:
        it["loc"] = L(it.get("pline"))
        it["file_index"] = it["loc"][0]
        by_id[it["id"]] = it
        if it.get("name"):
            by_name.setdefault(it["name"], []).append(it)

    stmts = [dict(s) for s in raw.get("statements") or []]
    st_by_id = {s["id"]: s for s in stmts}
    ctxd = {"items": items, "by_name": by_name, "by_id": by_id, "statements": stmts}

    # 4. SQL includes (and host variables of data-division SQL)
    sql_includes = []
    data_sql_hosts = set()
    for d in raw.get("data_exec_sql") or []:
        q = sql.parse(d.get("exec_text") or "")
        data_sql_hosts.update(q["host_reads"])
        data_sql_hosts.update(q["host_writes"])
        if q["kind"] == "include":
            sql_includes.append({"name": q["include"], "loc": L(d.get("pline"))})
    data_sql_nonincl = any(sql.parse(d.get("exec_text") or "")["kind"] != "include"
                           for d in raw.get("data_exec_sql") or [])

    # 5. exec parsing
    labels = []
    resp_vars = set()
    for s in stmts:
        # ProLeap merges consecutive EXEC blocks into one statement: one entry per command
        if s["type"] == "execCics":
            s["_cics"] = []
            for text in cics.split_commands(s.get("exec_text") or ""):
                p = cics.parse(text)
                r = cics.interpret(p)
                s["_cics"].append((p, r))
                s["reads"] = sorted(set(s.get("reads") or []) | set(r["reads"]))
                s["writes"] = sorted(set(s.get("writes") or []) | set(r["writes"]))
                labels.extend(r["labels"])
                if "RESP" in p["options"] and p["options"]["RESP"].get("var"):
                    resp_vars.add(p["options"]["RESP"]["var"])
        elif s["type"] == "execSql":
            s["_sql"] = []
            for text in sql.split_statements(s.get("exec_text") or ""):
                q = sql.parse(text)
                s["_sql"].append(q)
                s["reads"] = sorted(set(s.get("reads") or []) | set(q["host_reads"]))
                s["writes"] = sorted(set(s.get("writes") or []) | set(q["host_writes"]))
                if q["kind"] == "include":
                    sql_includes.append({"name": q["include"], "loc": L(s["pline"])})

    paragraphs_raw = raw.get("paragraphs") or []
    sections_raw = raw.get("sections") or []
    reach = flow.reachability(paragraphs_raw, sections_raw, stmts, labels)

    # 7. transfers, resources, error handling
    transfers = []
    resources = []
    errors = []
    gcache = {}

    def guards_of(s):
        if s["id"] not in gcache:
            gcache[s["id"]] = flow.guards(s, st_by_id)
        return gcache[s["id"]]

    def base(s):
        return {"paragraph": s.get("paragraph"), "loc": L(s["pline"]), "guards": guards_of(s),
                "stmt_id": s["id"], "source": parser}

    def add_transfer(s, kind, target, resolved, commarea=None, length=None, using=None):
        t = {"id": "T%d" % (len(transfers) + 1), "kind": kind, "target": target, "resolved_targets": resolved,
             "unresolved": bool(target and "var" in target and not resolved), "commarea": commarea,
             "length": length, "using": using or []}
        t.update(base(s))
        transfers.append(t)

    def add_resource(b, kind, name, name_res, mapset, mapset_res, op, command, extra):
        unresolved = bool((name and "var" in name and not name_res) or
                          (mapset and "var" in mapset and not mapset_res))
        r = {"id": "R%d" % (len(resources) + 1), "kind": kind, "name": name, "name_resolved": name_res,
             "mapset": mapset, "mapset_resolved": mapset_res, "op": op, "command": command, "extra": extra,
             "unresolved": unresolved}
        r.update(b)
        resources.append(r)

    def add_error(kind, detail, b):
        errors.append({"id": "E%d" % (len(errors) + 1), "kind": kind, "detail": detail,
                       "paragraph": b.get("paragraph"), "loc": b["loc"]})

    for s in stmts:
        t = s["type"]
        b = base(s)
        if t == "call":
            lit = s.get("target_literal")
            using = s.get("using") or []
            if lit in DLI_CALLS:
                fn = None
                if using:
                    res = dynamic.resolve(using[0]["name"], "name", ctxd) if using[0].get("name") else []
                    fn = res[0]["value"] if res else using[0]["text"]
                add_resource(b, "ims_call", None, [], None, [], fn, lit,
                             {"pcb": using[1]["text"] if len(using) > 1 else None,
                              "io_area": using[2]["text"] if len(using) > 2 else None})
            elif lit in MQ_CALLS:
                add_resource(b, "mq_call", None, [], None, [], lit.lower(), lit,
                             {"object": using[1]["text"] if len(using) > 1 else None})
            else:
                if lit:
                    target = {"literal": lit}
                    resolved = [{"value": lit, "how": "literal"}]
                else:
                    v = s.get("target_var")
                    target = {"var": v, "text": s.get("target_text")}
                    resolved = dynamic.resolve(v, "program", ctxd) if v else []
                add_transfer(s, "CALL", target, resolved, using=[u["text"] for u in using])
                if lit in ABEND_CALLS:
                    add_error("ABEND", "CALL " + lit, b)
        elif t == "execCics":
            for p, r in s["_cics"]:
                for tr in r["transfers"]:
                    tk = "transid" if tr["kind"] in ("RETURN_TRANSID", "START_TRANSID") else "program"
                    resolved = dynamic.resolve_option(tr["target"], tk, ctxd)
                    add_transfer(s, tr["kind"], _opt_out(tr["target"]), resolved, tr["commarea"], tr["length"])
                for rs in r["resources"]:
                    add_resource(b, rs["kind"], _opt_out(rs["name"]),
                                 dynamic.resolve_option(rs["name"], "name", ctxd), _opt_out(rs["mapset"]),
                                 dynamic.resolve_option(rs["mapset"], "name", ctxd), rs["op"], rs["command"],
                                 rs["extra"])
                for er in r["error_handling"]:
                    add_error(er["kind"], er["detail"], b)
        elif t == "execSql":
            for q in s["_sql"]:
                for tb in q["tables"]:
                    add_resource(b, "db2_table", {"literal": tb["name"]},
                                 [{"value": tb["name"], "how": "literal"}], None, [], tb["op"], q["kind"],
                                 {"cursor": q["cursor"]})
                if q["kind"] == "whenever":
                    add_error("SQL_WHENEVER", _cap(s.get("exec_text") or "", 200), b)
        elif t == "execSqlIms":
            txt = re.sub(r"(?i)^EXEC\s+SQLIMS\s*", "", s.get("exec_text") or "")
            first = txt.split()[0].upper() if txt.split() else None
            add_resource(b, "ims_call", None, [], None, [], first, "EXEC SQLIMS", {"text": s.get("exec_text")})
        elif t == "goback":
            add_transfer(s, "GOBACK", None, [])
        elif t == "stop" and s.get("run"):
            add_transfer(s, "STOP_RUN", None, [])
        elif t == "exit" and s.get("program"):
            add_transfer(s, "EXIT_PROGRAM", None, [])

    # EXEC DLI blocks (never parsed by ProLeap)
    para_locs = [(p["name"], L(p["start"]), L(p["end"])) for p in paragraphs_raw]
    for blk in textscan.scan_exec_dli(orig, fmt):
        p = cics.parse(re.sub(r"(?i)\bDLI\b", "CICS", blk["text"], count=1))
        seg = p["options"].get("SEGMENT")
        pcb = p["options"].get("PCB")
        para = None
        for name, st, en in para_locs:
            if st[0] == 0 and en[0] == 0 and st[1] <= blk["line"] <= en[1]:
                para = name
                break
        add_resource({"paragraph": para, "loc": [0, blk["line"]], "guards": [], "stmt_id": None, "source": parser},
                     "ims_call", None, [], None, [], p["command"], "EXEC DLI",
                     {"segment": (seg or {}).get("literal") or (seg or {}).get("text"),
                      "pcb": (pcb or {}).get("literal") or (pcb or {}).get("text")})

    # 8. batch files
    selects = raw.get("selects") or []
    files_io = []
    for sel in selects:
        fname = sel["file"]
        dd = re.sub(r"^(UT-S-|UR-S-|DA-S-|S-|AS-)", "", sel.get("assign") or "")
        records = [it["name"] for it in items if it["level"] == 1 and it.get("fd") == fname]
        modes = set()
        ops = set()
        for s in stmts:
            if s["type"] == "open":
                for m in s.get("modes") or []:
                    if fname in m["files"]:
                        modes.add(m["mode"])
            elif s["type"] in ("read", "start", "delete") and s.get("file") == fname:
                ops.add(s["type"].upper())
            elif s["type"] in ("write", "rewrite") and s.get("record") in records:
                ops.add(s["type"].upper())
        summary = _combine_access(modes, ops)
        files_io.append({"select": fname, "dd": dd, "assign_is_literal": sel.get("assign_is_literal"),
                         "organization": sel.get("organization"), "access": sel.get("access"),
                         "record_key": sel.get("record_key"), "file_status": sel.get("file_status"),
                         "records": records, "open_modes": sorted(modes), "ops": sorted(ops),
                         "access_summary": summary})
        add_resource({"paragraph": None, "loc": L(sel.get("pline")), "guards": [], "stmt_id": None,
                      "source": parser}, "batch_file", {"literal": dd}, [{"value": dd, "how": "literal"}],
                     None, [], summary, "SELECT", {"select": fname})

    # 9. decisions
    decisions = []
    for s in stmts:
        if s["type"] not in ("if", "evaluate", "search"):
            continue
        d = {"id": "D%d" % (len(decisions) + 1), "kind": s["type"], "paragraph": s.get("paragraph"),
             "loc": L(s["pline"]), "end": L(s["pline_end"]), "depth": flow.depth_of(s, st_by_id),
             "stmt_id": s["id"]}
        if s["type"] == "if":
            d["condition"] = s.get("condition")
        elif s["type"] == "evaluate":
            d["subjects"] = s.get("subjects")
            d["whens"] = [{"loc": L(w["pline"]), "conditions": w["conditions"]} for w in s.get("whens") or []]
            d["has_other"] = s.get("has_other")
        else:
            d["table"] = s.get("table")
            d["whens"] = [{"loc": L(w["pline"]), "condition": w["condition"]} for w in s.get("whens") or []]
        decisions.append(d)

    # 10. error handling derived from decisions
    fs_vars = set(sel["file_status"] for sel in selects if sel.get("file_status"))
    fs_names = set(fs_vars)
    for it in items:
        if it["level"] == 88 and it.get("parent") is not None and by_id[it["parent"]].get("name") in fs_vars:
            fs_names.add(it["name"])
    checks = [("FILE_STATUS_CHECK", _word_regex(sorted(fs_names))),
              ("SQLCODE_CHECK", _word_regex(["SQLCODE", "SQLSTATE"])),
              ("RESP_EVAL", _word_regex(sorted(set(["EIBRESP"]) | resp_vars)))]
    for d in decisions:
        if d["kind"] == "if":
            text = d.get("condition") or ""
        elif d["kind"] == "evaluate":
            text = " ".join(d.get("subjects") or []) + " " + " ".join(
                c for w in d["whens"] for c in w["conditions"])
        else:
            text = " ".join(w["condition"] for w in d["whens"])
        up = text.upper()
        for kind, rx in checks:
            if rx is not None and rx.search(up):
                add_error(kind, _cap(text, 200), {"paragraph": d["paragraph"], "loc": d["loc"]})

    # 6. procedure (paragraphs / sections)
    by_par = {}
    for s in stmts:
        if s.get("paragraph"):
            by_par.setdefault(s["paragraph"], []).append(s)
    performed_by = {}
    paragraphs = []
    for p in paragraphs_raw:
        pst = by_par.get(p["name"], [])
        performs = set()
        for s in pst:
            if s["type"] == "perform" and s.get("target"):
                for tgt in flow.resolve_targets(s["target"], s.get("thru"), paragraphs_raw, sections_raw):
                    performs.add(tgt)
                    performed_by.setdefault(tgt, set()).add(p["name"])
        start, end = L(p["start"]), L(p["end"])
        if start[0] == 0 and end[0] == 0:
            chars = 0
            for k in range(start[1], end[1] + 1):
                if 1 <= k <= len(orig):
                    chars += len(common.source_area(orig[k - 1], fmt)[1].rstrip())
        else:
            chars = sum(len(pp_lines[k - 1].strip()) for k in range(p["start"], p["end"] + 1)
                        if 1 <= k <= len(pp_lines))
        rd = set()
        wr = set()
        for s in pst:
            rd.update(s.get("reads") or [])
            wr.update(s.get("writes") or [])
        paragraphs.append({
            "name": p["name"], "section": p.get("section"), "declaratives": p.get("declaratives"),
            "start": start, "end": end, "statements": len(pst), "complexity": flow.complexity(pst),
            "est_tokens": common.est_tokens(chars), "reachable": p["name"] in reach,
            "reads": sorted(rd), "writes": sorted(wr), "performs": sorted(performs), "performed_by": [],
            "transfers": [t["id"] for t in transfers if t["paragraph"] == p["name"]],
            "resources": [r["id"] for r in resources if r["paragraph"] == p["name"]],
            "outline": flow.outline(pst, st_by_id, lm)})
    for p in paragraphs:
        p["performed_by"] = sorted(performed_by.get(p["name"], set()))
    sections = [{"name": s["name"], "start": L(s["start"]), "end": L(s["end"]),
                 "declaratives": s.get("declaratives"),
                 "paragraphs": [p["name"] for p in paragraphs_raw if p.get("section") == s["name"]]}
                for s in sections_raw]
    dead = [p["name"] for p in paragraphs if not p["reachable"]]

    # 11. unresolved names
    known = set()
    for it in items:
        if it.get("name"):
            known.add(it["name"])
        if it.get("occurs"):
            known.update(it["occurs"].get("indexed_by") or [])
    known.update(sel["file"] for sel in selects)
    known.update(fd["file"] for fd in raw.get("fds") or [])
    known.update(p["name"] for p in paragraphs_raw)
    known.update(s["name"] for s in sections_raw)
    known.update(SPECIAL_REGISTERS)
    # ProLeap reads DFHRESP(NORMAL) / DFHVALUE(ERASE) as a table call: the argument is not a data name
    for s in stmts:
        texts = [s.get("text") or "", s.get("condition") or ""] + list(s.get("subjects") or [])
        for w in s.get("whens") or []:
            texts.extend(w.get("conditions") or [w.get("condition") or ""])
        for tx in texts:
            known.update(re.findall(r"DFH(?:RESP|VALUE)\s*\(\s*([A-Z0-9-]+)\s*\)", tx.upper()))
    counts = {}
    first_loc = {}
    for s in stmts:
        for n in set(s.get("reads") or []) | set(s.get("writes") or []):
            if n in known or n.startswith(("EIB", "DFH", "SQL")):
                continue
            counts[n] = counts.get(n, 0) + 1
            first_loc.setdefault(n, L(s["pline"]))
    unresolved_names = [{"name": n, "count": counts[n], "first_loc": first_loc[n]} for n in sorted(counts)]

    # 12. usage
    refd = set(data_sql_hosts)
    reads_all = set()
    writes_all = set()
    for s in stmts:
        reads_all.update(s.get("reads") or [])
        writes_all.update(s.get("writes") or [])
        for u in s.get("using") or []:
            if isinstance(u, dict) and u.get("name"):
                refd.add(u["name"])
        if s.get("target_var"):
            refd.add(s["target_var"])
    refd |= reads_all | writes_all
    refd.update(raw.get("procedure_using") or [])
    for sel in selects:
        refd.update(x for x in (sel.get("record_key"), sel.get("file_status")) if x)
    for it in items:
        if it.get("occurs") and it["occurs"].get("depending"):
            refd.add(it["occurs"]["depending"])
    for t in transfers:
        if t.get("commarea"):
            refd.add(t["commarea"])
    for r in resources:
        if r["extra"] and r["extra"].get("ridfld"):
            refd.add(r["extra"]["ridfld"])

    def ancestors(it):
        out = []
        cur = it
        while cur.get("parent") is not None and cur["level"] != 88:
            cur = by_id[cur["parent"]]
            out.append(cur)
        return out

    def descendants(it):
        out = []
        todo = list(it["children"])
        while todo:
            c = by_id[todo.pop()]
            out.append(c)
            todo.extend(c["children"])
        return out

    marked = set()
    for it in items:
        if it.get("name") in refd:
            marked.add(it["id"])
            if it["level"] == 88 and it.get("parent") is not None:
                marked.add(it["parent"])
    used = set(marked)
    for mid in list(marked):
        m = by_id[mid]
        used.update(a["id"] for a in ancestors(m))
        used.update(d["id"] for d in descendants(m))
    unused = []
    write_only = []
    for it in items:
        if it["file_index"] != 0 or it["level"] in (88, 66) or not it.get("name") or it["name"] == "FILLER":
            continue
        if it["id"] not in used and len(unused) < 500:
            unused.append(it["name"])
        if it["name"] in writes_all and it["name"] not in reads_all and len(write_only) < 500:
            near = [a["name"] for a in ancestors(it)] + [d["name"] for d in descendants(it)] + it["conditions"]
            if not any(n in reads_all for n in near if n):
                write_only.append(it["name"])

    # 13. interface
    linkage_records = [it for it in items if it["level"] == 1 and it.get("section") == "LINKAGE"]
    commarea = None
    for it in linkage_records:
        if it["name"] == "DFHCOMMAREA":
            commarea = {"name": "DFHCOMMAREA", "size": it["total_size"]}
    linkage_layout = []
    for rec in linkage_records:
        rows = [{"name": it.get("name"), "level": it["level"], "offset": it["offset"], "size": it["size"],
                 "pic": it.get("pic"), "usage": it.get("usage")}
                for it in items if it["record"] == rec["id"]][:300]
        linkage_layout.append({"record": rec["name"], "items": rows})
    interface = {"procedure_using": raw.get("procedure_using") or [],
                 "linkage_records": [it["name"] for it in linkage_records], "commarea": commarea,
                 "linkage_layout": linkage_layout}

    # 14. kind and flags
    flags = {"uses_cics": any(s["type"] == "execCics" for s in stmts),
             "uses_db2": any(s["type"] == "execSql" for s in stmts) or data_sql_nonincl,
             "uses_ims": any(r["kind"] == "ims_call" for r in resources),
             "uses_mq": any(r["kind"] == "mq_call" for r in resources),
             "uses_files": bool(selects) or any(r["kind"] == "cics_file" for r in resources)}
    if flags["uses_cics"]:
        kind = "cics_online"
    elif interface["procedure_using"]:
        kind = "batch_subroutine"
    else:
        kind = "batch_main"

    # 15. metrics
    code = comment = blank = chars = 0
    for line in orig:
        ind, content = common.source_area(line, fmt)
        chars += len(content.rstrip())
        if common.is_comment(ind, content):
            comment += 1
        elif content.strip() == "":
            blank += 1
        else:
            code += 1
    cmd_counts = Counter(p["command"] for s in stmts if s["type"] == "execCics" for p, _ in s["_cics"])
    metrics = {"lines": len(orig), "code_lines": code, "comment_lines": comment, "blank_lines": blank,
               "statements": len(stmts), "paragraphs": len(paragraphs),
               "complexity": sum(p["complexity"] for p in paragraphs), "est_tokens_program": common.est_tokens(chars),
               "est_tokens_expanded": common.est_tokens(sum(len(l.strip()) for l in pp_lines)),
               "cics_commands": dict(sorted(cmd_counts.items())),
               "statement_types": dict(sorted(Counter(s["type"] for s in stmts).items()))}

    # 16. quality
    quality = {"status": raw.get("status"), "parser": parser, "syntax_error_count": raw.get("syntax_error_count", 0),
               "syntax_error_samples": [{"loc": L(e["pline"]), "msg": e["msg"]}
                                        for e in (raw.get("syntax_errors") or [])[:20]],
               "line_map_exact_ratio": lm["exact_ratio"], "missing_copybooks": raw.get("missing_copybooks") or [],
               "fallback_reason": None, "parse_ms": raw.get("parse_ms")}

    out_items = []
    for it in items:
        vals = None
        if it.get("values"):
            vals = [dict(v, **layout.literal_value(v["from"])) for v in it["values"]]
        out_items.append({
            "id": it["id"], "level": it["level"], "name": it.get("name"), "parent": it["parent"],
            "record": it["record"], "children": it["children"], "conditions": it["conditions"],
            "section": it.get("section"), "fd": it.get("fd"), "pic": it.get("pic"), "usage": it.get("usage"),
            "effective_usage": it["effective_usage"], "values": vals, "occurs": it.get("occurs"),
            "redefines": it.get("redefines"), "redefines_id": it["redefines_id"], "size": it["size"],
            "occurs_count": it["occurs_count"], "total_size": it["total_size"], "offset": it["offset"],
            "is_group": it["is_group"], "size_unknown": it["size_unknown"], "loc": it["loc"],
            "file_index": it["file_index"]})

    ids = raw.get("program_ids") or []
    rec = ctx.get("inventory_record") or {}
    return {
        "schema": "cobol-facts/1", "name": raw.get("name"),
        "path": rec.get("path") or common.relpath(raw["program_file"], root),
        "program_id": ids[0] if ids else None, "source": parser, "quality": quality, "files": files,
        "metrics": metrics, "kind": kind, "flags": flags, "interface": interface, "copybooks": copybooks,
        "sql_includes": sql_includes, "data_items": out_items, "files_io": files_io,
        "procedure": {"sections": sections, "paragraphs": paragraphs}, "dead_paragraphs": dead,
        "decisions": decisions, "transfers": transfers, "resources": resources, "error_handling": errors,
        "unresolved_names": unresolved_names, "unused_data": unused, "write_only_data": write_only}
