import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from graph_lib import analysis  # noqa: E402
from tests.helpers import build, cobol, csd_file, data, dd, jcl_file, resource, step, transfer  # noqa: E402


def scenario():
    csd = csd_file("CSD", [{"type": "TRANSACTION", "name": "T", "program": "A"}])
    a = cobol("A", transfers=[transfer("XCTL", ["B"])])
    b = cobol("B", transfers=[transfer("XCTL", ["A"])])
    c = cobol("C", kind="batch_main", transfers=[transfer("CALL", ["D"])])
    d = cobol("D", kind="batch_subroutine")
    e = cobol("E", kind="batch_main")
    j = jcl_file("J", [step(1, "S1", "C")])
    return data(cobol=[a, b, c, d, e], csd=[csd], jcl=[j])


class AnalysisTest(unittest.TestCase):

    def test_roles_cycles(self):
        g, r = build(scenario())
        ana, entries = analysis.run(g, r, scenario())
        roles = dict((n["name"], n["attrs"]["role"]) for n in g.nodes_of("program"))
        self.assertEqual((roles["A"], roles["B"]), ("online", "online"))
        self.assertEqual((roles["C"], roles["D"]), ("batch", "batch"))
        self.assertEqual(roles["E"], "unreached")
        self.assertEqual(ana["candidates"], ["E"])
        self.assertEqual(ana["orphans"], ["E"])
        self.assertEqual(ana["sccs_navigation"], [["A", "B"]])
        self.assertEqual(ana["sccs_hard"], [])
        self.assertIn({"type": "transaction", "id": "transaction:T", "program": "A"}, entries)
        self.assertIn({"type": "job", "id": "job:J", "programs": ["C"]}, entries)
        self.assertIn({"type": "candidate_program", "id": "program:E", "reason": "no caller, no transaction, no job"},
                      entries)

    def test_return_transid_composition(self):
        csd = csd_file("CSD", [{"type": "TRANSACTION", "name": "T2", "program": "B"}])
        a = cobol("A", transfers=[transfer("RETURN_TRANSID", ["T2"])])
        b = cobol("B", transfers=[transfer("XCTL", ["A"])])
        d = data(cobol=[a, b], csd=[csd])
        g, r = build(d)
        ana, _ = analysis.run(g, r, d)
        self.assertEqual(ana["sccs_navigation"], [["A", "B"]])

    def test_shared_data_store(self):
        csd = csd_file("CSD", [{"type": "FILE", "name": "F", "dsname": "AWS.D"}])
        p1 = cobol("P1", resources=[resource("cics_file", ["F"], "read")])
        s = step(1, "S1", "SORT", dds=[dd("SORTIN", "AWS.D", "old")])
        d = data(cobol=[p1], csd=[csd], jcl=[jcl_file("J", [s])])
        g, r = build(d)
        ana, _ = analysis.run(g, r, d)
        store = [x for x in ana["data_stores"] if x["dsn"] == "AWS.D"][0]
        self.assertTrue(store["shared"])
        self.assertEqual(store["cics_files"], ["F"])
        self.assertEqual(store["online_programs"], [{"name": "P1", "access": "read"}])
        self.assertEqual(store["batch_steps"], [{"name": "J:S1", "access": "read"}])

    def test_tarjan_no_recursion_limit(self):
        n = 1000
        nodes = ["n%d" % i for i in range(n)]
        adj = dict((nodes[i], set([nodes[i + 1]])) for i in range(n - 1))
        comps = analysis.tarjan(nodes, adj)
        self.assertEqual(len(comps), n)
        adj[nodes[-1]] = set([nodes[0]])
        comps = analysis.tarjan(nodes, adj)
        self.assertEqual(len(comps), 1)
        self.assertEqual(len(comps[0]), n)

    def test_entry_points(self):
        d = scenario()
        g, r = build(d)
        analysis.run(g, r, d)
        doc = analysis.entry_points_doc(g, r, "root")
        by = dict((e["name"], e) for e in doc["entry_points"])
        self.assertEqual(by["A"]["entry_type"], "cics_transaction")
        self.assertEqual(by["A"]["confidence"], "confirmed")
        self.assertEqual(by["A"]["nav_callers"], ["B"])
        self.assertEqual(by["C"]["entry_type"], "jcl_job")
        self.assertEqual(by["C"]["jobs"], [{"job": "J", "step": "S1"}])
        self.assertEqual(by["E"]["entry_type"], "candidate")
        self.assertEqual(by["E"]["confidence"], "heuristic")
        others = dict((e["name"], e) for e in doc["not_entry_points"])
        self.assertEqual(sorted(others), ["B", "D"])
        self.assertEqual(others["B"]["reason"], "navigation target")
        self.assertEqual(others["B"]["nav_callers"], ["A"])
        self.assertEqual(others["D"]["reason"], "called")
        self.assertEqual(others["D"]["hard_callers"], ["C"])
        self.assertEqual(doc["summary"]["entry_points"], 3)
        self.assertEqual(doc["summary"]["not_entry_points"], 2)

    def test_entry_point_also_called(self):
        d = scenario()
        d["jcl"][0]["flat_steps"].append(step(2, "S2", "D"))
        g, r = build(d)
        analysis.run(g, r, d)
        doc = analysis.entry_points_doc(g, r, "root")
        by = dict((e["name"], e) for e in doc["entry_points"])
        self.assertEqual(by["D"]["entry_type"], "jcl_job")
        self.assertTrue(by["D"]["also_called"])
        self.assertEqual(by["D"]["hard_callers"], ["C"])
        self.assertEqual(by["D"]["notes"], ["also called by other programs"])

    def test_candidate_dynamic_note(self):
        a = cobol("A", kind="batch_main", transfers=[transfer("CALL", [], unresolved=True, target_text="WS-PGM")])
        d = data(cobol=[a])
        g, r = build(d)
        analysis.run(g, r, d)
        doc = analysis.entry_points_doc(g, r, "root")
        self.assertEqual(doc["summary"]["unresolved_dynamic_calls"], 1)
        self.assertEqual(len(doc["entry_points"][0]["notes"]), 2)


if __name__ == "__main__":
    unittest.main()
