"""Cross-checks between scanner facts, inventory names and (optionally) COBOL facts."""


def _inline_csds(jcl_facts, proc_facts):
    """[(member, step name, definitions)] for every inline CSD found in steps."""
    out = []
    for f in jcl_facts:
        for s in f.get("flat_steps") or []:
            ic = s.get("utility_data", {}).get("inline_csd")
            if ic:
                out.append((f["name"], s["name"], ic["definitions"]))
    for f in proc_facts:
        for s in f.get("steps") or []:
            ic = s.get("utility_data", {}).get("inline_csd")
            if ic:
                out.append((f["name"], s["name"], ic["definitions"]))
    return out


def compute(data):
    """data: {"csd": [...], "jcl": [...], "proc": [...], "bms": [...], "ddl": [...], "source_names": set,
    "cobol": {name: facts} or {}}. Returns a dict C1..C9."""
    csd = data["csd"]
    jcl = data["jcl"]
    proc = data["proc"]
    bms = data["bms"]
    ddl = data["ddl"]
    src = data["source_names"]
    cobol = data["cobol"]
    inline = _inline_csds(jcl, proc)
    r = {}

    # C1
    # (a name defined twice in the same CSD is listed once)
    r["C1_files"] = sorted(set((f["name"], d["name"]) for f in csd for d in f["definitions"]
                               if d["type"] == "PROGRAM" and d["name"] not in src))
    r["C1_inline"] = sorted(set((m, s, d["name"]) for m, s, defs in inline for d in defs
                                if d["type"] == "PROGRAM" and d["name"] not in src))
    # C2
    c2 = []
    for f in csd:
        progs = set(d["name"] for d in f["definitions"] if d["type"] == "PROGRAM")
        for d in f["definitions"]:
            if d["type"] == "TRANSACTION" and d.get("program") and d["program"] not in progs:
                c2.append((f["name"], d["name"], d["program"]))
    r["C2"] = sorted(c2)
    # C3
    bms_names = set(m["name"] for f in bms for m in f["mapsets"] if m["name"])
    csd_maps_files = [(f["name"], d["name"]) for f in csd for d in f["definitions"] if d["type"] == "MAPSET"]
    csd_maps_inline = [(m, s, d["name"]) for m, s, defs in inline for d in defs if d["type"] == "MAPSET"]
    all_csd_maps = set(n for _, n in csd_maps_files) | set(n for _, _, n in csd_maps_inline)
    r["C3_a"] = sorted(set((f, n) for f, n in csd_maps_files if n not in bms_names))
    r["C3_b"] = sorted(set((m, s, n) for m, s, n in csd_maps_inline if n not in bms_names))
    r["C3_c"] = sorted((f["name"], m["name"]) for f in bms for m in f["mapsets"]
                       if m["name"] and m["name"] not in all_csd_maps)
    # C4 / C5
    c4 = set()
    c5 = set()
    for f in jcl:
        for s in f.get("flat_steps") or []:
            if s["kind"] == "program" and s["program"] and not s["utility"] and not s["build"] \
                    and s["program"] not in src:
                c4.add((f["name"], s["name"], s["program"]))
            for inv in s.get("invokes") or []:
                if inv["program"] not in src:
                    c4.add((f["name"], s["name"], inv["program"]))
            if s["kind"] == "proc" and s.get("proc_found") is False:
                c5.add((f["name"], s["name"], s["proc"]))
    r["C4"] = sorted(c4)
    r["C5"] = sorted(c5)
    # CSD file names (files and inline)
    csd_files = set(d["name"] for f in csd for d in f["definitions"] if d["type"] == "FILE")
    csd_files |= set(d["name"] for _, _, defs in inline for d in defs if d["type"] == "FILE")
    # tables
    tables = set()
    for f in ddl:
        for t in f["tables"]:
            tables.add(t["qualified"])
            tables.add(t["name"])
    for f in jcl + proc:
        for s in (f.get("flat_steps") or f.get("steps") or []):
            sql = s.get("utility_data", {}).get("inline_sql")
            if sql:
                for t in sql["tables"]:
                    tables.add(t["qualified"])
                    tables.add(t["name"])
    r["has_cobol"] = bool(cobol)
    if not cobol:
        return r
    # C6
    c6 = set()
    c8 = set()
    c9 = set()
    for name, cf in cobol.items():
        for res in cf.get("resources", []):
            if res["kind"] == "cics_file":
                for v in res["name_resolved"]:
                    if v["value"] not in csd_files:
                        c6.add((name, v["value"]))
            elif res["kind"] == "map":
                for v in res.get("mapset_resolved") or []:
                    if v["value"] not in bms_names and v["value"] not in all_csd_maps:
                        c8.add((name, v["value"]))
            elif res["kind"] == "db2_table":
                for v in res["name_resolved"]:
                    if v["value"] not in tables:
                        c9.add((name, v["value"]))
    r["C6"] = sorted(c6)
    r["C8"] = sorted(c8)
    r["C9"] = sorted(c9)
    # C7
    by_prog = {}
    for name, cf in cobol.items():
        by_prog[name] = cf
        if cf.get("program_id"):
            by_prog.setdefault(cf["program_id"], cf)
    c7_missing = []
    c7_extra = []
    for f in jcl:
        for s in f.get("flat_steps") or []:
            cf = by_prog.get(s["program"]) if s["kind"] == "program" and s["program"] else None
            if cf is None:
                continue
            expected = set(x["dd"] for x in cf.get("files_io", []) if x.get("dd"))
            present = set(d["name"] for d in s["dds"])
            missing = sorted(expected - present)
            extra = sorted(d["name"] for d in s["dds"]
                           if d["name"] not in expected and d["mode_hint"] not in ("library", "sysout", "dummy")
                           and not d["name"].startswith("SYS"))
            if missing:
                c7_missing.append((f["name"], s["name"], s["program"], missing))
            if extra:
                c7_extra.append((f["name"], s["name"], s["program"], extra))
    r["C7_missing"] = sorted(c7_missing)
    r["C7_extra"] = sorted(c7_extra)
    return r
