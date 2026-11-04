"""JCL and PROC scanner: cards, symbols, DDs, steps, utility data and PROC expansion."""
import copy
import re

from . import common, csd, ddl, utilities

UTILITIES = {"IDCAMS", "SORT", "ICEMAN", "DFSORT", "SYNCSORT", "IEBGENER", "IEBCOPY", "IEFBR14", "IKJEFT01",
             "IKJEFT1A", "IKJEFT1B", "DFHCSDUP", "DSNTEP2", "DSNTEP4", "DSNUTILB", "SDSF", "IEBCOMPR",
             "IEBUPDTE", "IEHLIST", "IEHPROGM", "ADRDSSU", "FTP", "DFSRRC00", "IRXJCL"}
BUILD_PROGRAMS = {"IGYCRCTL", "ASMA90", "ASMA90X", "IEWL", "HEWL", "IEWBLINK", "DSNHPC", "DFHECP1$", "DFHEAP1$",
                  "DFHEBRZP", "DFHYITVL", "CCNDRVR", "EDCCOMP"}
LIBRARY_DDS = {"STEPLIB", "JOBLIB", "SYSLIB", "DFHRPL", "STEPCAT", "JOBCAT"}
SYSTEM_SYMBOLS = {"SYSUID", "SYSJOBNAME", "SYSNAME", "SYSPLEX", "SYSCLONE", "SYSJOBID", "LYR", "LMON", "LDAY",
                  "LHR", "LMIN", "LSEC", "YR4", "YR2", "MON", "DAY", "HR", "MIN", "SEC", "HRS", "JDAY"}
SORT_PROGRAMS = {"SORT", "ICEMAN", "DFSORT", "SYNCSORT"}
TSO_PROGRAMS = {"IKJEFT01", "IKJEFT1A", "IKJEFT1B"}
IF_FAMILY = {"IF", "ELSE", "ENDIF", "THEN"}
EXEC_NON_SYMBOLIC = {"PGM", "PROC", "PARM", "COND", "REGION", "TIME", "ACCT", "DYNAMNBR", "PERFORM", "ADDRSPC",
                     "CCSID", "RD"}

_SYM_RE = re.compile(r"(?<!&)&(?!&)([A-Za-z#@$][A-Za-z0-9#@$]*)\.?")


# ---------------------------------------------------------------- symbols

def _unresolved(text, symbols):
    out = []
    for m in _SYM_RE.finditer(text):
        name = m.group(1).upper()
        if name not in symbols and name not in SYSTEM_SYMBOLS and name not in out:
            out.append(name)
    return out


def subst(text, symbols):
    """-> (new_text, unresolved_names)"""
    cur = text
    for _ in range(3):
        changed = [False]

        def rep(m):
            name = m.group(1).upper()
            if name in symbols:
                changed[0] = True
                return str(symbols[name])
            return m.group(0)
        new = _SYM_RE.sub(rep, cur)
        if not changed[0]:
            break
        cur = new
    return cur, _unresolved(cur, symbols)


# ---------------------------------------------------------------- cards

def _new_card(no, name, op, operands):
    return {"line": no, "end_line": no, "name": name, "op": op, "operands": operands, "inline": None}


def read_cards(lines):
    cards = []
    n = len(lines)
    i = 0
    while i < n:
        raw = lines[i].rstrip("\r\n")
        no = i + 1
        i += 1
        if raw.startswith("//*"):
            continue
        if raw.startswith("//"):
            text = raw[:71]
            if text.strip() == "//":
                cards.append(_new_card(no, "", "", ""))
                continue
            m = re.match(r"^//(\S*)\s+(\S+)(?:\s+(.*))?$", text)
            if not m:
                continue
            name = m.group(1).upper()
            op = m.group(2).upper()
            rest = (m.group(3) or "").strip()
            if op in IF_FAMILY:
                card = _new_card(no, name, op, rest)
                cards.append(card)
                continue
            operands = common.take_operand_field(rest)
            card = _new_card(no, name, op, operands)
            is_open = operands.endswith(",")
            j = i
            while is_open:
                while j < n and lines[j].startswith("//*"):
                    j += 1
                if j < n and lines[j].startswith("//") and lines[j][2:3] == " " and lines[j][:71].strip() != "//":
                    piece = common.take_operand_field(lines[j][:71][2:].lstrip())
                    card["operands"] += piece
                    card["end_line"] = j + 1
                    is_open = piece.endswith(",")
                    j += 1
                else:
                    break
            i = j
            cards.append(card)
            if op == "DD":
                params = common.parse_params(card["operands"])
                items = [v.upper() for k, v in params if k is None]
                if "*" in items or "DATA" in items:
                    dlm = None
                    for k, v in params:
                        if k == "DLM":
                            dlm = common.unquote(v)
                    data = []
                    while i < n:
                        ln = lines[i]
                        if dlm:
                            if ln.startswith(dlm):
                                i += 1
                                break
                        else:
                            if ln.startswith("/*"):
                                i += 1
                                break
                            if ln.startswith("//"):
                                break
                        data.append((i + 1, ln.rstrip("\r\n")[:80]))
                        i += 1
                    card["inline"] = {"lines": data, "dlm": dlm}
            continue
        if raw.startswith("/*"):
            cards.append(_new_card(no, "", "DELIM", ""))
    return cards


# ---------------------------------------------------------------- DD

def _mode_hint(dd):
    if dd["dummy"]:
        dd["mode_hint"] = "dummy"
    elif dd["sysout"]:
        dd["mode_hint"] = "sysout"
    elif dd["inline"] is not None:
        dd["mode_hint"] = "inline"
    elif dd["name"] in LIBRARY_DDS:
        dd["mode_hint"] = "library"
    else:
        disp = dd["disp"] or {}
        status = disp.get("status")
        if disp.get("normal") == "DELETE":
            dd["mode_hint"] = "delete"
        elif status == "NEW":
            dd["mode_hint"] = "create"
        elif status == "MOD":
            dd["mode_hint"] = "append"
        elif status == "SHR":
            dd["mode_hint"] = "read"
        elif status == "OLD":
            dd["mode_hint"] = "old"
        else:
            dd["mode_hint"] = "unknown"


def apply_dsn(dd, symbols):
    """Recompute the dataset related fields of a DD from dsn_raw with the given symbols."""
    raw = dd["dsn_raw"]
    dd["dsn"] = None
    dd["member"] = None
    dd["generation"] = None
    dd["temp"] = False
    dd["null_file"] = False
    dd["referback"] = None
    dd["unresolved_symbols"] = []
    if raw is not None:
        txt, unres = subst(raw, symbols)
        dd["unresolved_symbols"] = unres
        txt = txt.strip().upper()
        if txt.startswith("*."):
            dd["referback"] = txt[2:]
        else:
            m = re.match(r"^(.+)\(([^)]+)\)$", txt)
            if m:
                inner = m.group(2).strip()
                if re.match(r"^[+-]?\d+$", inner):
                    dd["generation"] = inner
                else:
                    dd["member"] = inner.upper()
                txt = m.group(1)
            dd["dsn"] = txt
            dd["temp"] = txt.startswith("&&")
            dd["null_file"] = txt == "NULLFILE"
    _mode_hint(dd)


def make_dd(card, name, symbols):
    params = common.parse_params(card["operands"])
    kv = {}
    pos = []
    for k, v in params:
        if k is None:
            pos.append(v)
        elif k not in kv:
            kv[k] = v
    dd = {"name": name, "line": card["line"], "concat": False, "dsn_raw": None, "dsn": None, "member": None,
          "generation": None, "temp": False, "null_file": False, "referback": None, "disp": None,
          "sysout": "SYSOUT" in kv, "dummy": any(p.upper() == "DUMMY" for p in pos), "inline": None,
          "mode_hint": "unknown", "dcb": None, "unit": kv.get("UNIT"), "ddname_ref": kv.get("DDNAME"),
          "override_of": None, "added_by_override": False, "unresolved_symbols": []}
    raw = kv.get("DSN") or kv.get("DSNAME")
    dd["dsn_raw"] = common.unquote(raw) if raw else None
    if "DISP" in kv:
        pieces = common.sub_params(kv["DISP"])
        dd["disp"] = {"raw": kv["DISP"],
                      "status": pieces[0].upper() if pieces and pieces[0] else None,
                      "normal": pieces[1].upper() if len(pieces) > 1 and pieces[1] else None,
                      "abnormal": pieces[2].upper() if len(pieces) > 2 and pieces[2] else None}
    if "DCB" in kv:
        dcb = {"lrecl": None, "recfm": None, "blksize": None, "dsorg": None, "ref": None}
        for piece in common.sub_params(kv["DCB"]):
            if piece.startswith("*."):
                dcb["ref"] = piece
                continue
            if "=" in piece:
                k, v = piece.split("=", 1)
                k = k.strip().upper()
                v = v.strip()
                if k in ("LRECL", "BLKSIZE"):
                    try:
                        dcb[k.lower()] = int(v)
                    except ValueError:
                        dcb[k.lower()] = None
                elif k in ("RECFM", "DSORG"):
                    dcb[k.lower()] = v.upper()
        dd["dcb"] = dcb
    if card["inline"] is not None:
        items = [p.upper() for p in pos]
        dd["inline"] = {"kind": "DATA" if "DATA" in items else "*", "lines": len(card["inline"]["lines"]),
                        "dlm": card["inline"]["dlm"], "symbols": kv.get("SYMBOLS")}
        dd["_data"] = card["inline"]["lines"]
    apply_dsn(dd, symbols)
    return dd


# ---------------------------------------------------------------- steps

def _new_step(index, name, line, job):
    return {"index": index, "name": name, "line": line, "job": job, "kind": "program", "program": None,
            "proc": None, "parm": None, "cond": None, "region": None, "params": {}, "if_context": [],
            "utility": False, "build": False, "dds": [], "overrides": [], "invokes": [], "utility_data": {},
            "proc_found": None, "expanded": None, "expanded_from": None, "via_step": None, "warnings": [],
            "program_raw": None, "parm_raw": None}


def make_step(card, index, job, symbols, if_stack):
    params = common.parse_params(card["operands"])
    kv = {}
    pos = []
    for k, v in params:
        if k is None:
            pos.append(v)
        elif k not in kv:
            kv[k] = v
    s = _new_step(index, card["name"], card["line"], job)
    if "PGM" in kv:
        s["kind"] = "program"
        s["program_raw"] = kv["PGM"]
        s["program"] = subst(kv["PGM"], symbols)[0].strip().upper()
    elif "PROC" in kv:
        s["kind"] = "proc"
        s["proc"] = subst(kv["PROC"], symbols)[0].strip().upper()
    elif pos:
        s["kind"] = "proc"
        s["proc"] = pos[0].strip().upper()
    else:
        s["warnings"].append("EXEC without PGM or PROC")
    if "PARM" in kv:
        s["parm_raw"] = common.unquote(kv["PARM"])
        s["parm"] = subst(s["parm_raw"], symbols)[0]
    s["cond"] = kv.get("COND")
    s["region"] = kv.get("REGION")
    for k, v in kv.items():
        if k not in EXEC_NON_SYMBOLIC:
            s["params"][k] = common.unquote(v)
    s["if_context"] = list(if_stack)
    s["utility"] = s["program"] in UTILITIES if s["program"] else False
    s["build"] = s["program"] in BUILD_PROGRAMS if s["program"] else False
    return s


def compute_invokes(step):
    inv = []
    prog = step["program"]
    if step["kind"] == "program" and prog and not step["utility"] and not step["build"]:
        inv.append({"program": prog, "via": "EXEC PGM"})
    inv += utilities.parm_invokes(prog, step["parm"]) if prog else []
    for r in step["utility_data"].get("tso_runs", []):
        inv.append({"program": r["program"], "plan": r["plan"], "via": "SYSTSIN RUN PROGRAM"})
    return inv


def finalize_step(step, symbols):
    """Parse the inline control data of the utility steps."""
    prog = step["program"]
    step["utility"] = prog in UTILITIES if prog else False
    step["build"] = prog in BUILD_PROGRAMS if prog else False
    data = step["utility_data"]
    if step["kind"] == "program" and prog:
        for dd in step["dds"]:
            raw = dd.get("_data")
            if raw is None:
                continue
            first = raw[0][0] if raw else 1
            texts = [t for _, t in raw]
            name = dd["name"]
            if prog == "IDCAMS" and name == "SYSIN":
                cmds = utilities.idcams_parse(texts)
                for c in cmds:
                    c["line"] = first + c["line"] - 1
                data["idcams_commands"] = cmds
            elif prog in SORT_PROGRAMS and name == "SYSIN":
                data["sort_statements"] = utilities.sort_parse(texts)
            elif prog == "SDSF" and name == "ISFIN":
                cmds = utilities.sdsf_parse(texts)
                for c in cmds:
                    c["line"] = first + c["line"] - 1
                data["sdsf_commands"] = cmds
            elif prog == "DFHCSDUP" and name == "SYSIN":
                if dd["inline"] and dd["inline"]["symbols"] is not None:
                    texts = [subst(t, symbols)[0] for t in texts]
                r = csd.parse_lines(texts, first_line=first)
                data["inline_csd"] = {"definitions": r["definitions"], "commands": r["commands"]}
            elif prog in TSO_PROGRAMS and name == "SYSTSIN":
                runs = utilities.tso_parse(texts)
                for r in runs:
                    r["line"] = first + r["line"] - 1
                data["tso_runs"] = runs
            if (prog in TSO_PROGRAMS or prog in ("DSNTEP2", "DSNTEP4")) and name == "SYSIN":
                body = ddl.parse_sql(ddl.strip_comments("\n".join(texts)), first_line=first)
                data["inline_sql"] = {k: body[k] for k in ("tables", "indexes", "views", "other", "alters",
                                                          "drops", "dml")}
    for dd in step["dds"] + step["overrides"]:
        dd.pop("_data", None)
    step["invokes"] = compute_invokes(step)


# ---------------------------------------------------------------- parse_member

def _new_state():
    return {"jobs": [], "symbols": {}, "defaults": {}, "jcllib": [], "includes": [], "instream": {}, "steps": [],
            "job_dds": [], "warnings": [], "declared_name": None, "has_job": False, "has_proc": False,
            "cur_job": None, "cur_step": None, "if_stack": [], "proc_stack": None, "counter": 0,
            "names_seen": set()}


def _scope(st):
    sym = dict(st["symbols"])
    if st["proc_stack"] is not None:
        sym.update(st["proc_stack"]["defaults"])
    elif st["has_proc"] and not st["has_job"]:
        sym.update(st["defaults"])
    return sym


def _finalize_current(st):
    if st["cur_step"] is not None:
        finalize_step(st["cur_step"], _scope(st))
        st["cur_step"] = None


def _if_condition(text):
    ms = list(re.finditer(r"(?i)\sTHEN\b", text))
    cond = text[:ms[-1].start()] if ms else text
    return common.cap(cond.strip(), 200)


def _process_cards(cards, st, ctx, depth, only_symbols=False):
    for card in cards:
        op = card["op"]
        if only_symbols and op not in ("SET", "INCLUDE"):
            continue
        if op == "SET":
            for k, v in common.parse_params(card["operands"]):
                if k is not None:
                    st["symbols"][k] = subst(common.unquote(v), _scope(st))[0]
        elif op == "INCLUDE":
            kv = dict((k, v) for k, v in common.parse_params(card["operands"]) if k)
            member = common.unquote(kv.get("MEMBER", "")).upper()
            lines = ctx["members"].get(member)
            st["includes"].append({"member": member, "found": lines is not None})
            if lines is not None and depth < 3:
                _process_cards(read_cards(lines), st, ctx, depth + 1, only_symbols=True)
        elif only_symbols:
            continue
        elif op == "JOB":
            _finalize_current(st)
            params = common.parse_params(card["operands"])
            kv = dict((k, v) for k, v in params if k)
            pos = [common.unquote(v) for k, v in params if k is None]
            job = {"name": card["name"], "line": card["line"], "class": kv.get("CLASS"),
                   "msgclass": kv.get("MSGCLASS"), "notify": kv.get("NOTIFY"),
                   "programmer": pos[1] if len(pos) > 1 else None, "accounting": pos[0] if pos else None}
            st["jobs"].append(job)
            st["has_job"] = True
            st["cur_job"] = card["name"]
            st["names_seen"] = set()
        elif op == "PROC":
            _finalize_current(st)
            defaults = {}
            for k, v in common.parse_params(card["operands"]):
                if k is not None:
                    defaults[k] = common.unquote(v)
            if st["has_job"]:
                st["proc_stack"] = {"name": card["name"], "defaults": defaults, "steps": [], "counter": 0}
            else:
                st["has_proc"] = True
                st["defaults"] = defaults
                st["declared_name"] = card["name"]
        elif op == "PEND":
            _finalize_current(st)
            if st["proc_stack"] is not None:
                ps = st["proc_stack"]
                st["instream"][ps["name"]] = {"kind": "proc", "defaults": ps["defaults"], "steps": ps["steps"],
                                              "declared_name": ps["name"]}
                st["proc_stack"] = None
        elif op == "JCLLIB":
            kv = dict((k, v) for k, v in common.parse_params(card["operands"]) if k)
            if "ORDER" in kv:
                st["jcllib"] = [common.unquote(x).upper() for x in common.sub_params(kv["ORDER"])]
        elif op == "IF":
            st["if_stack"].append(_if_condition(card["operands"]))
        elif op == "ELSE":
            if st["if_stack"]:
                st["if_stack"][-1] = "NOT (" + st["if_stack"][-1] + ")"
        elif op == "ENDIF":
            if st["if_stack"]:
                st["if_stack"].pop()
        elif op == "EXEC":
            _finalize_current(st)
            ps = st["proc_stack"]
            if ps is not None:
                ps["counter"] += 1
                index = ps["counter"]
            else:
                st["counter"] += 1
                index = st["counter"]
            step = make_step(card, index, st["cur_job"], _scope(st), st["if_stack"])
            if ps is None and step["name"]:
                if step["name"] in st["names_seen"]:
                    msg = "duplicate step name %s" % step["name"]
                    step["warnings"].append(msg)
                    st["warnings"].append(msg)
                st["names_seen"].add(step["name"])
            (ps["steps"] if ps is not None else st["steps"]).append(step)
            st["cur_step"] = step
        elif op == "DD":
            cur = st["cur_step"]
            name = card["name"]
            concat = False
            if not name:
                concat = True
                if cur is not None and cur["dds"]:
                    name = cur["dds"][-1]["name"]
            dd = make_dd(card, name, _scope(st))
            dd["concat"] = concat
            if "." in name and cur is not None and cur["kind"] == "proc":
                dd["override_of"] = {"proc_step": name.split(".")[0], "dd": name.rsplit(".", 1)[1]}
                dd["name"] = name.rsplit(".", 1)[1]
                _mode_hint(dd)
                cur["overrides"].append(dd)
            elif cur is None:
                st["job_dds"].append(dd)
            else:
                cur["dds"].append(dd)


def parse_member(lines, name, ctx, _depth=0):
    if ctx is None:
        ctx = {"procs": {}, "members": {}}
    st = _new_state()
    _process_cards(read_cards(lines), st, ctx, 0)
    _finalize_current(st)
    if st["has_job"]:
        kind = "job"
    elif st["has_proc"]:
        kind = "proc"
    else:
        kind = "fragment"
    declared = st["jobs"][0]["name"] if st["jobs"] else st["declared_name"]
    return {"kind": kind, "name": name, "jobs": st["jobs"], "symbols": st["symbols"], "defaults": st["defaults"],
            "jcllib": st["jcllib"], "includes": st["includes"], "instream_procs": st["instream"],
            "steps": st["steps"], "job_dds": st["job_dds"], "warnings": st["warnings"],
            "declared_name": declared}


# ---------------------------------------------------------------- expansion

def _rederive(step, syms):
    """Recompute program-dependent fields of an expanded step with the given symbols."""
    if step["kind"] == "program":
        if step.get("program_raw"):
            step["program"] = subst(step["program_raw"], syms)[0].strip().upper()
        if step.get("parm_raw") is not None:
            step["parm"] = subst(step["parm_raw"], syms)[0]
        prog = step["program"]
        step["utility"] = prog in UTILITIES if prog else False
        step["build"] = prog in BUILD_PROGRAMS if prog else False
        step["invokes"] = compute_invokes(step)
    for dd in step["dds"]:
        apply_dsn(dd, syms)


def expand_step(s, ctx, job_symbols, instream, depth, stack, used):
    """Return the list of flat steps for a step (the step itself for non-proc steps)."""
    if s["kind"] != "proc":
        return [copy.deepcopy(s)]
    proc_name = s["proc"]
    raw = (instream or {}).get(proc_name) or ctx["procs"].get(proc_name)
    used.append({"name": proc_name, "found": raw is not None})
    if raw is None:
        s["proc_found"] = False
        s["expanded"] = None
        return [copy.deepcopy(s)]
    s["proc_found"] = True
    if proc_name in stack or depth >= 3:
        s["warnings"].append("recursive proc %s" % proc_name)
        s["expanded"] = None
        return [copy.deepcopy(s)]
    syms = dict(job_symbols)
    syms.update(raw.get("defaults") or {})
    params = dict((k.upper(), subst(v, job_symbols)[0]) for k, v in s["params"].items())
    syms.update(params)
    ov_syms = dict(job_symbols)
    ov_syms.update(params)
    out = []
    for ps in raw["steps"]:
        ps2 = copy.deepcopy(ps)
        orig_name = ps["name"]
        ps2["name"] = s["name"] + "." + orig_name
        ps2["expanded_from"] = proc_name
        ps2["via_step"] = s["name"]
        ps2["job"] = s["job"]
        ps2["if_context"] = list(s["if_context"]) + list(ps["if_context"])
        _rederive(ps2, syms)
        for ov in s["overrides"]:
            if ov["override_of"]["proc_step"].upper() != orig_name.upper():
                continue
            ovc = copy.deepcopy(ov)
            apply_dsn(ovc, ov_syms)
            for k, existing in enumerate(ps2["dds"]):
                if existing["name"].upper() == ovc["name"].upper():
                    ps2["dds"][k] = ovc
                    break
            else:
                ovc["added_by_override"] = True
                ps2["dds"].append(ovc)
        if ps2["kind"] == "proc":
            out.extend(expand_step(ps2, ctx, syms, instream, depth + 1, stack + [proc_name], used))
        else:
            out.append(ps2)
    s["expanded"] = out
    return [copy.deepcopy(x) for x in out]


def _resolve_referbacks(flat):
    for i, st in enumerate(flat):
        for dd in st["dds"]:
            ref = dd.get("referback")
            if not ref:
                continue
            step_ref, _, dd_name = ref.rpartition(".")
            found = None
            # *.ddname (no step name) refers to an earlier DD of the same step
            candidates = [st] if not step_ref else [
                prev for prev in flat[:i]
                if prev["name"].upper() == step_ref or prev["name"].upper().endswith("." + step_ref)]
            for prev in candidates:
                for pdd in prev["dds"]:
                    if pdd is not dd and pdd["name"].upper() == dd_name and pdd["dsn"]:
                        found = pdd
            if found is not None:
                dd["dsn"] = found["dsn"]
                dd["member"] = found["member"]
                dd["generation"] = found["generation"]
                dd["referback_resolved"] = True
            else:
                dd["referback_resolved"] = False


def _dedupe_used(used):
    seen = set()
    out = []
    for u in used:
        if u["name"] not in seen:
            seen.add(u["name"])
            out.append(u)
    return out


def build_facts(raw, rec, ctx):
    """Final facts for a parsed member."""
    kind = raw["kind"]
    steps = raw["steps"]
    out = {"schema": "jcl-facts/1", "name": rec["name"], "path": rec["path"], "kind": kind,
           "declared_name": raw["declared_name"], "jobs": raw["jobs"], "symbols": raw["symbols"],
           "jcllib": raw["jcllib"], "includes": raw["includes"],
           "instream_procs": sorted(raw["instream_procs"].keys())}
    if kind == "proc":
        out["defaults"] = raw["defaults"]
    used = []
    if kind == "proc":
        flat = None
        for s in steps:
            if s["kind"] == "proc":
                found = s["proc"] in raw["instream_procs"] or s["proc"] in ctx["procs"]
                s["proc_found"] = found
                used.append({"name": s["proc"], "found": found})
        dds = [dd for s in steps for dd in s["dds"]]
        programs = set()
        for s in steps:
            if s["kind"] == "program" and s["program"] and not s["utility"] and not s["build"]:
                programs.add(s["program"])
            for inv in s["invokes"]:
                programs.add(inv["program"])
        utils = sorted(set(s["program"] for s in steps if s["kind"] == "program" and s["utility"]))
        datasets = []
        unresolved = []
    else:
        job_symbols = dict(raw["symbols"])
        flat = []
        for s in steps:
            flat.extend(expand_step(s, ctx, job_symbols, raw["instream_procs"], 0, [], used))
        for k, f in enumerate(flat, 1):
            f["index"] = k
        _resolve_referbacks(flat)
        dds = [dd for f in flat for dd in f["dds"]]
        programs = set()
        for f in flat:
            if f["kind"] == "program" and f["program"] and not f["utility"] and not f["build"]:
                programs.add(f["program"])
            for inv in f["invokes"]:
                programs.add(inv["program"])
        utils = sorted(set(f["program"] for f in flat if f["kind"] == "program" and f["utility"]))
        unresolved = sorted(set(n for dd in dds for n in dd["unresolved_symbols"]))
        ds = {}
        for f in flat:
            for dd in f["dds"] + []:
                _add_dataset(ds, dd, f["name"])
        for dd in raw["job_dds"]:
            _add_dataset(ds, dd, None)
        datasets = [ds[k] for k in sorted(ds.keys(), key=lambda x: (x[0], x[1] or ""))]
    out["steps"] = steps
    out["flat_steps"] = flat
    out["job_dds"] = raw["job_dds"]
    out["programs_run"] = sorted(programs)
    out["procs_used"] = _dedupe_used(used)
    out["utilities_used"] = utils
    out["datasets"] = datasets
    out["unresolved_symbols"] = unresolved
    out["summary"] = {"steps": len(steps), "flat_steps": len(flat) if flat is not None else 0, "dds": len(dds)}
    out["warnings"] = raw["warnings"]
    return out


def _add_dataset(ds, dd, step_name):
    if not dd["dsn"] or dd["temp"] or dd["null_file"] or dd["dummy"] or dd["sysout"]:
        return
    key = (dd["dsn"], dd["generation"])
    entry = ds.setdefault(key, {"dsn": dd["dsn"], "generation": dd["generation"], "refs": []})
    entry["refs"].append({"step": step_name, "dd": dd["name"], "member": dd["member"],
                          "mode_hint": dd["mode_hint"], "disp": dd["disp"]["raw"] if dd["disp"] else None})


def scan_file(path, rec, root, ctx):
    lines = common.split_lines(common.read_text(path))
    raw = parse_member(lines, rec["name"], ctx)
    return build_facts(raw, rec, ctx)
