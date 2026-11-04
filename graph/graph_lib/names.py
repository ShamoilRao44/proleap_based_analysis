"""Name resolution: finds or creates the graph node for a program, copybook, mapset, ..."""
from . import common

SYSTEM_PREFIXES = ("CEE", "DFH", "DSN", "IGZ", "ILBO", "IEF", "IKJ", "CSQ")
SYSTEM_NAMES = set(["CBLTDLI", "AIBTDLI", "CEETDLI", "SQLCA", "SQLDA", "MQCONN", "MQCONNX", "MQOPEN", "MQPUT",
                    "MQPUT1", "MQGET", "MQCLOSE", "MQDISC", "MQINQ", "MQSET", "MQBEGIN", "MQCMIT", "MQBACK"])
UTILITIES = set(["IDCAMS", "SORT", "ICEMAN", "DFSORT", "SYNCSORT", "IEBGENER", "IEBCOPY", "IEFBR14", "IKJEFT01",
                 "IKJEFT1A", "IKJEFT1B", "DFHCSDUP", "DSNTEP2", "DSNTEP4", "DSNUTILB", "SDSF", "IEBCOMPR",
                 "IEBUPDTE", "IEHLIST", "IEHPROGM", "ADRDSSU", "FTP", "DFSRRC00", "IRXJCL"])


def inline_csds(data):
    """[(defining job member, step name, definitions)] for inline CSDs of JCL steps."""
    out = []
    for j in data.get("jcl", []):
        for s in j.get("flat_steps") or []:
            ic = (s.get("utility_data") or {}).get("inline_csd")
            if ic:
                out.append((j["name"], s["name"], ic["definitions"]))
    return out


def inline_tables(data):
    """[(jcl facts, tables)] for inline SQL of JCL steps."""
    out = []
    for j in data.get("jcl", []):
        for s in j.get("flat_steps") or []:
            sql = (s.get("utility_data") or {}).get("inline_sql")
            if sql and sql.get("tables"):
                out.append((j, sql["tables"]))
    return out


class Resolver(object):

    def __init__(self, data):
        self.data = data
        self.unresolved = []
        self.program_index = {}
        for name, cf in data["cobol"].items():
            self.program_index[name.upper()] = name
            if cf.get("program_id"):
                self.program_index.setdefault(cf["program_id"].upper(), name)
        self.copybook_index = {}
        for rec in data.get("inventory", []):
            t = rec.get("type")
            if t in ("assembler",):
                self.program_index.setdefault(rec["name"].upper(), rec["name"])
                if rec.get("declared_name"):
                    self.program_index.setdefault(rec["declared_name"].upper(), rec["name"])
            elif t in ("copybook", "dclgen"):
                self.copybook_index.setdefault(rec["name"].upper(), rec)
        self.bms_index = {}
        for f in data.get("bms", []):
            for m in f.get("mapsets", []):
                if m.get("name"):
                    self.bms_index.setdefault(m["name"].upper(), f["name"])
        self.csd_files = {}
        self.transactions = {}
        for f in data.get("csd", []):
            self._index_defs(f["definitions"], "csd:" + f["name"])
        for job, _step, defs in inline_csds(data):
            self._index_defs(defs, "job:" + job)
        self.tables = {}
        for f in data.get("ddl", []):
            for t in f.get("tables", []):
                self._index_table(t)
        for _j, tables in inline_tables(data):
            for t in tables:
                self._index_table(t)
        self.control_cards = {}
        for f in data.get("control", []):
            self.control_cards.setdefault(f["name"].upper(), f)
        self.procs = {}
        for f in data.get("proc", []):
            self.procs.setdefault(f["name"].upper(), f)
        for f in data.get("proc", []):
            if f.get("declared_name"):
                self.procs.setdefault(f["declared_name"].upper(), f)

    def _index_defs(self, defs, defined_in):
        for d in defs:
            if d["type"] == "FILE":
                lst = self.csd_files.setdefault(d["name"], [])
                if d.get("dsname") and d["dsname"] not in lst:
                    lst.append(d["dsname"])
            elif d["type"] == "TRANSACTION":
                t = self.transactions.setdefault(d["name"], {"program": d.get("program"), "defined_in": []})
                if defined_in not in t["defined_in"]:
                    t["defined_in"].append(defined_in)

    def _index_table(self, t):
        self.tables.setdefault(t["qualified"].upper(), t["qualified"])
        self.tables.setdefault(t["name"].upper(), t["qualified"])

    # ------------------------------------------------------------ helpers

    def is_system(self, name):
        if name in SYSTEM_NAMES:
            return True
        return name.startswith(SYSTEM_PREFIXES) and name not in self.program_index

    def program(self, g, name):
        member = self.program_index.get(name, name)
        n = g.add_node("program", member, name in self.program_index, system=self.is_system(name),
                       utility=name in UTILITIES)
        return n["id"]

    def copybook(self, g, name):
        rec = self.copybook_index.get(name)
        kind = "dclgen" if rec and rec.get("type") == "dclgen" else "copybook"
        n = g.add_node("copybook", name, name in self.copybook_index,
                       path=rec["path"] if rec else None, subtype=rec.get("subtype") if rec else None,
                       kind=kind, system=self.is_system(name) or name.startswith("DFH"))
        return n["id"]

    def mapset(self, g, name):
        n = g.add_node("mapset", name, name in self.bms_index, bms=self.bms_index.get(name))
        return n["id"]

    def transaction(self, g, name):
        n = g.add_node("transaction", name, name in self.transactions)
        return n["id"]

    def cics_file(self, g, name):
        n = g.add_node("cics_file", name, name in self.csd_files, dsnames=list(self.csd_files.get(name, [])))
        return n["id"]

    def table(self, g, name):
        canonical = self.tables.get(name, name)
        n = g.add_node("db2_table", canonical, name in self.tables)
        return n["id"]

    def dataset(self, g, dsn, job_member, temp):
        name = "%s@%s" % (dsn, job_member) if temp else dsn
        n = g.add_node("dataset", name, None, temp=bool(temp), unresolved=("&" in dsn and not temp))
        return n["id"]

    def member_of_path(self, path):
        return common.member_of(path)
