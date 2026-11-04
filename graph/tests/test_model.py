import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from graph_lib.model import Graph  # noqa: E402


class ModelTest(unittest.TestCase):

    def test_edge_merge(self):
        g = Graph()
        g.add_node("program", "A", True)
        g.add_node("dataset", "D", None)
        g.add_edge("PROGRAM_DATASET", "program:A", "dataset:D", "read", {"n": 1})
        e = g.add_edge("PROGRAM_DATASET", "program:A", "dataset:D", "write", {"n": 2})
        self.assertEqual(e["count"], 2)
        self.assertEqual(e["access"], "read_write")
        self.assertEqual(len(e["details"]), 2)
        self.assertEqual(e["strength"], "data")

    def test_to_dict_sorted_ids(self):
        g = Graph()
        for n in ("B", "A"):
            g.add_node("program", n, True)
        g.add_edge("XCTL", "program:B", "program:A")
        g.add_edge("CALL", "program:B", "program:A")
        d = g.to_dict()
        self.assertEqual([e["type"] for e in d["edges"]], ["CALL", "XCTL"])
        self.assertEqual([e["id"] for e in d["edges"]], ["E1", "E2"])
        self.assertEqual([n["id"] for n in d["nodes"]], ["program:A", "program:B"])

    def test_node_merge(self):
        g = Graph()
        g.add_node("program", "A", None, tags=["x"])
        n = g.add_node("program", "A", True, tags=["x", "y"])
        self.assertIs(n["in_codebase"], True)
        self.assertEqual(n["attrs"]["tags"], ["x", "y"])
        g.add_node("program", "A", False)
        self.assertIs(g.get("program:A")["in_codebase"], True)

    def test_unknown_node(self):
        g = Graph()
        g.add_node("program", "A", True)
        with self.assertRaises(KeyError):
            g.add_edge("CALL", "program:A", "program:B")


if __name__ == "__main__":
    unittest.main()
