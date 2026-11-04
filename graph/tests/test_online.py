import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tests.helpers import build, cobol, csd_file, data, edge, has, resource, transfer  # noqa: E402


class OnlineTest(unittest.TestCase):

    def test_main_scenario(self):
        csd = csd_file("CSD", [
            {"type": "TRANSACTION", "name": "CC00", "program": "COSGN00C"},
            {"type": "FILE", "name": "ACCTDAT", "dsname": "AWS.ACCT"},
            {"type": "TDQUEUE", "name": "JOBS", "queue_type": "EXTRA",
             "attrs": {"DDNAME": "INREADER", "TYPE": "EXTRA"}}])
        a = cobol("COSGN00C", transfers=[transfer("XCTL", ["COMEN01C"]), transfer("RETURN_TRANSID", ["CC00"])],
                  resources=[resource("cics_file", ["ACCTDAT"], "read")])
        b = cobol("COMEN01C", resources=[resource("map", mapset_values=["COMEN01"], op="send"),
                                         resource("td_queue", ["JOBS"], "write")])
        g, r = build(data(cobol=[a, b], csd=[csd]))
        self.assertTrue(has(g, "TRANSACTION_RUNS", "transaction:CC00", "program:COSGN00C"))
        self.assertTrue(has(g, "XCTL", "program:COSGN00C", "program:COMEN01C"))
        self.assertTrue(has(g, "RETURN_TRANSID", "program:COSGN00C", "transaction:CC00"))
        e = edge(g, "PROGRAM_CICS_FILE", "program:COSGN00C", "cics_file:ACCTDAT")
        self.assertEqual(e["access"], "read")
        self.assertTrue(has(g, "CICS_FILE_DATASET", "cics_file:ACCTDAT", "dataset:AWS.ACCT"))
        self.assertTrue(has(g, "USES_MAP", "program:COMEN01C", "mapset:COMEN01"))
        e = edge(g, "PROGRAM_TD_QUEUE", "program:COMEN01C", "td_queue:JOBS")
        self.assertEqual(e["access"], "write")
        self.assertIs(g.get("td_queue:JOBS")["attrs"]["internal_reader"], True)
        self.assertIs(g.get("mapset:COMEN01")["in_codebase"], False)
        self.assertIs(g.get("transaction:CC00")["in_codebase"], True)
        self.assertIs(g.get("cics_file:ACCTDAT")["in_codebase"], True)
        self.assertEqual(r.unresolved, [])

    def test_unresolved_transfer(self):
        a = cobol("A", transfers=[transfer("XCTL", [], unresolved=True, target_text="WS-PGM")])
        g, r = build(data(cobol=[a]))
        self.assertEqual([e for e in g.edges if e[0] == "XCTL"], [])
        self.assertEqual(len(r.unresolved), 1)
        self.assertEqual(r.unresolved[0]["kind"], "dynamic_transfer")
        self.assertEqual(r.unresolved[0]["target_text"], "WS-PGM")

    def test_system_program(self):
        a = cobol("A", kind="batch_main", transfers=[transfer("CALL", ["CEE3ABD"])])
        g, _ = build(data(cobol=[a]))
        n = g.get("program:CEE3ABD")
        self.assertIs(n["in_codebase"], False)
        self.assertIs(n["attrs"]["system"], True)

    def test_copybooks(self):
        a = cobol("X", copybooks=[{"name": "A", "depth": 1, "via": None, "loc": [0, 5]},
                                  {"name": "B", "depth": 2, "via": "A", "loc": [0, 5]}],
                  sql_includes=[{"name": "SQLCA", "loc": [0, 9]}])
        g, _ = build(data(cobol=[a]))
        self.assertTrue(has(g, "COPY", "program:X", "copybook:A"))
        self.assertTrue(has(g, "COPY", "copybook:A", "copybook:B"))
        self.assertTrue(has(g, "SQL_INCLUDE", "program:X", "copybook:SQLCA"))

    def test_db2_and_declare(self):
        a = cobol("X", resources=[resource("db2_table", ["T1"], "insert"), resource("db2_table", ["T2"], "declare")])
        g, _ = build(data(cobol=[a]))
        self.assertEqual(edge(g, "PROGRAM_DB2_TABLE", "program:X", "db2_table:T1")["access"], "write")
        self.assertFalse(has(g, "PROGRAM_DB2_TABLE", "program:X", "db2_table:T2"))


if __name__ == "__main__":
    unittest.main()
