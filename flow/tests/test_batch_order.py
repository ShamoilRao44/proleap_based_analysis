import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from flow_lib import batch_order  # noqa: E402


class G(object):
    def __init__(self):
        self.nodes = []
        self.edges = []
        self.stores = []

    def job(self, n):
        self.nodes.append({"id": "job:" + n, "type": "job", "name": n, "attrs": {}})
        self.cnt = getattr(self, "cnt", {})
        self.cnt[n] = 0

    def step(self, j, program=None):
        self.cnt[j] += 1
        sid = "step:%s#%d" % (j, self.cnt[j])
        self.nodes.append({"id": sid, "type": "step", "name": sid[5:], "attrs": {"job": j, "step_name": "S"}})
        self.edges.append({"type": "JOB_STEP", "source": "job:" + j, "target": sid, "access": None, "details": []})
        return sid

    def ds(self, n, temp=False):
        if not any(x["id"] == "dataset:" + n for x in self.nodes):
            self.nodes.append({"id": "dataset:" + n, "type": "dataset", "name": n, "attrs": {"temp": temp}})
        return "dataset:" + n

    def define(self, j, n, temp=False):
        self.edges.append({"type": "IDCAMS_DEFINE", "source": self.step(j), "target": self.ds(n, temp),
                           "access": "write", "details": []})

    def use(self, j, n, access="read"):
        self.edges.append({"type": "STEP_DATASET", "source": self.step(j), "target": self.ds(n),
                           "access": access, "details": []})

    def graph(self):
        return {"nodes": self.nodes, "edges": self.edges, "analysis": {"data_stores": self.stores}}


def base():
    g = G()
    for j in "ABCE":
        g.job(j)
    g.define("A", "D1")
    g.use("B", "D1")
    g.use("C", "D1")
    g.define("A", "D2")
    g.define("E", "D2")
    g.use("B", "D2")
    g.use("B", "D3")
    g.define("A", "TMP", temp=True)
    g.use("B", "TMP")
    return g


class BatchOrderTest(unittest.TestCase):

    def test_order_levels_multi_external_temp(self):
        b = batch_order.build_batch(base().graph())
        edges = dict(((e["from"], e["to"]), e["datasets"]) for e in b["order_edges"])
        self.assertEqual(edges, {("A", "B"): ["D1"], ("A", "C"): ["D1"]})
        lv = dict((j["job"], j["level"]) for j in b["jobs"])
        self.assertEqual(lv, {"A": 0, "B": 1, "C": 1, "E": 0})
        self.assertEqual(b["multi_definer"], [{"dataset": "D2", "definers": ["A", "E"], "users": ["B"]}])
        self.assertEqual(b["external_inputs"], [{"dataset": "D3", "users": ["B"]}])

    def test_online_prerequisites(self):
        g = base()
        g.stores = [{"dsn": "D1", "online_programs": [{"name": "P", "access": "read"}]},
                    {"dsn": "D2", "online_programs": [{"name": "P", "access": "read"}]},
                    {"dsn": "D4", "online_programs": [{"name": "P", "access": "read"}]},
                    {"dsn": "D1B", "online_programs": []}]
        op = batch_order.build_batch(g.graph())["online_prerequisites"]
        self.assertEqual(op["required_jobs"], [{"job": "A", "datasets": ["D1"]}])
        self.assertEqual(op["one_of"], [{"jobs": ["A", "E"], "datasets": ["D2"]}])
        self.assertEqual(op["external"], ["D4"])

    def test_cycle_does_not_hang(self):
        g = G()
        g.job("X")
        g.job("Y")
        g.define("X", "DX")
        g.use("Y", "DX")
        g.define("Y", "DY")
        g.use("X", "DY")
        b = batch_order.build_batch(g.graph())
        lv = dict((j["job"], j["level"]) for j in b["jobs"])
        self.assertEqual(lv["X"], lv["Y"])

    def test_job_record_fields(self):
        b = batch_order.build_batch(base().graph())
        a = [j for j in b["jobs"] if j["job"] == "A"][0]
        self.assertEqual(a["defines"], ["D1", "D2"])
        self.assertEqual([s["job"] for s in a["successors"]], ["B", "C"])
        bb = [j for j in b["jobs"] if j["job"] == "B"][0]
        self.assertEqual(bb["predecessors"], [{"job": "A", "datasets": ["D1"]}])


if __name__ == "__main__":
    unittest.main()
