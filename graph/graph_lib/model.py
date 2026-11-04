"""Graph model: typed nodes and edges with merge rules."""
from . import access

STRENGTH = {
    "CALL": "hard", "LINK": "hard", "HANDLE_ABEND": "hard",
    "XCTL": "navigation", "RETURN_TRANSID": "navigation", "START_TRANSID": "navigation",
    "TRANSACTION_RUNS": "entry", "JOB_STEP": "entry", "STEP_RUNS": "entry", "STEP_PSB": "entry",
    "COPY": "build", "SQL_INCLUDE": "build", "USES_MAP": "build", "SYMBOLIC_MAP": "build",
    "PROGRAM_CICS_FILE": "data", "CICS_FILE_DATASET": "data", "PROGRAM_DATASET": "data", "STEP_DATASET": "data",
    "IDCAMS_DEFINE": "data", "IDCAMS_DELETE": "data", "DATASET_RELATE": "data", "PROGRAM_DB2_TABLE": "data",
    "PROGRAM_TS_QUEUE": "data", "PROGRAM_TD_QUEUE": "data", "PSB_DBD": "data", "PROGRAM_PSB": "data",
    "JOB_USES_PROC": "config", "STEP_CONTROL_CARD": "config", "CSD_DEFINES": "config",
    "JOB_CICS_COMMAND": "operational",
}


def node_id(type_, name):
    return type_ + ":" + name


class Graph(object):

    def __init__(self):
        self.nodes = {}
        self.edges = {}
        self._out = {}
        self._in = {}

    def add_node(self, type_, name, in_codebase=None, **attrs):
        nid = node_id(type_, name)
        n = self.nodes.get(nid)
        if n is None:
            n = {"id": nid, "type": type_, "name": name, "in_codebase": in_codebase, "attrs": {}}
            self.nodes[nid] = n
            self._out[nid] = []
            self._in[nid] = []
        else:
            a, b = n["in_codebase"], in_codebase
            if a is True or b is True:
                n["in_codebase"] = True
            elif a is False or b is False:
                n["in_codebase"] = False
            else:
                n["in_codebase"] = None
        for k, v in attrs.items():
            if v is None:
                continue
            old = n["attrs"].get(k)
            if isinstance(v, list):
                if isinstance(old, list):
                    for x in v:
                        if x not in old:
                            old.append(x)
                else:
                    n["attrs"][k] = list(v)
            else:
                n["attrs"][k] = v
        return n

    def add_edge(self, type_, source_id, target_id, access_=None, detail=None):
        if source_id not in self.nodes:
            raise KeyError(source_id)
        if target_id not in self.nodes:
            raise KeyError(target_id)
        key = (type_, source_id, target_id)
        e = self.edges.get(key)
        if e is None:
            e = {"id": None, "type": type_, "strength": STRENGTH[type_], "source": source_id,
                 "target": target_id, "access": access_, "count": 1,
                 "details": [detail] if detail else []}
            self.edges[key] = e
            self._out[source_id].append(key)
            self._in[target_id].append(key)
        else:
            e["count"] += 1
            e["access"] = access.combine(e["access"], access_)
            if detail is not None and len(e["details"]) < 50:
                e["details"].append(detail)
        return e

    def get(self, nid):
        return self.nodes.get(nid)

    def out_edges(self, nid, types=None):
        return [self.edges[k] for k in self._out.get(nid, []) if types is None or k[0] in types]

    def in_edges(self, nid, types=None):
        return [self.edges[k] for k in self._in.get(nid, []) if types is None or k[0] in types]

    def nodes_of(self, type_):
        return [n for n in self.nodes.values() if n["type"] == type_]

    def to_dict(self):
        nodes = [self.nodes[k] for k in sorted(self.nodes)]
        edges = []
        for i, key in enumerate(sorted(self.edges), 1):
            e = self.edges[key]
            e["id"] = "E%d" % i
            edges.append(e)
        return {"nodes": nodes, "edges": edges}
