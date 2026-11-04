import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from flow_lib import process  # noqa: E402
from tests.helpers import shop_data, shop_process  # noqa: E402


def entry_stub(outcome="none"):
    return {"found": False, "paragraph": None, "statement_id": None, "loc": None, "condition": None,
            "outcome": outcome, "handoff_targets": [], "path_resolved": True, "events": [],
            "expected_callers": []}


class ProcessTest(unittest.TestCase):

    def test_classification_and_roots(self):
        _d, _s, _e, p = shop_process()
        P = p["programs"]
        self.assertEqual(P["SIGN"]["classification"], "starter")
        self.assertEqual(P["SIGN"]["certainty"], "certain")
        self.assertEqual(P["SIGN"]["dependents"], ["MENU"])
        self.assertEqual(p["roots"], ["SIGN"])
        self.assertEqual(P["MENU"]["classification"], "needs_prior")
        self.assertEqual([(x["program"], x["kind"]) for x in P["MENU"]["prerequisites"]],
                         [("SIGN", "handoff"), ("SIGN", "state")])
        self.assertEqual(P["DETAIL"]["classification"], "needs_prior")
        self.assertEqual([(x["program"], x["kind"]) for x in P["DETAIL"]["prerequisites"]], [("LIST", "state")])
        self.assertEqual(P["CARD"]["classification"], "expects_caller")
        self.assertEqual([(x["program"], x["kind"]) for x in P["CARD"]["prerequisites"]],
                         [("MENU", "expected_caller")])
        self.assertEqual(P["LIST"]["classification"], "unclear")
        self.assertEqual(p["unclear"], [{"name": "LIST", "reason": "no first-entry test found"}])

    def test_levels(self):
        _d, _s, _e, p = shop_process()
        P = p["programs"]
        self.assertEqual([P[n]["level"] for n in ("SIGN", "MENU", "CARD", "LIST", "DETAIL")], [0, 1, 2, 0, 1])
        self.assertEqual(P["LIST"]["level_source"], "state")

    def test_navigation_direction(self):
        _d, _s, _e, p = shop_process()
        d = dict(((e["source"], e["target"]), e["direction"]) for e in p["navigation_edges"])
        self.assertEqual(d[("SIGN", "MENU")], "forward")
        self.assertEqual(d[("MENU", "SIGN")], "back")
        self.assertEqual(d[("MENU", "LIST")], "back")
        self.assertEqual(d[("LIST", "DETAIL")], "forward")

    def test_cyclic_prerequisites(self):
        data = {"online": ["X", "Y"], "graph": {"nodes": [], "edges": []}}
        st = {"cells": [{"id": "c1", "names": ["F"]}, {"id": "c2", "names": ["G"]}],
              "programs": {
                  "X": {"requires": ["c1"], "provides": ["c2"],
                        "requirements": [{"cell": "c1", "kind": "local", "producers": ["Y"], "status": "produced"}]},
                  "Y": {"requires": ["c2"], "provides": ["c1"],
                        "requirements": [{"cell": "c2", "kind": "local", "producers": ["X"], "status": "produced"}]}}}
        p = process.build_process(data, st, {"X": entry_stub(), "Y": entry_stub()})
        X, Y = p["programs"]["X"], p["programs"]["Y"]
        self.assertTrue(X["cyclic_prerequisites"] and Y["cyclic_prerequisites"])
        self.assertEqual(X["level"], Y["level"])

    def test_no_root(self):
        data = shop_data(transactions={})
        d, st, entries, p = shop_process(data)
        self.assertEqual(p["roots"], [])
        self.assertIsNone(p["programs"]["SIGN"]["certainty"])
        main = process.build_main_entry_points(d, st, p, {"jobs": []})
        self.assertEqual(main["online"]["roots"], [])

    def test_main_entry_points_evidence(self):
        d, st, entries, p = shop_process()
        main = process.build_main_entry_points(d, st, p, {"jobs": []})
        r = main["online"]["roots"][0]
        self.assertEqual(r["name"], "SIGN")
        self.assertEqual(r["transactions"], ["T-SIGN"])
        self.assertTrue(len(r["evidence"]) >= 3)
        self.assertIn("only program that sets USER-ID", r["evidence"])


if __name__ == "__main__":
    unittest.main()
