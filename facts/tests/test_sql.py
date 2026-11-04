import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from facts_lib import sql  # noqa: E402


class SqlTest(unittest.TestCase):

    def test_select(self):
        r = sql.parse("EXEC SQL SELECT A, B INTO :WS-A, :WS-B FROM CARDDEMO.ACCT_TBL WHERE ID = :WS-ID END-EXEC")
        self.assertEqual(r["kind"], "select")
        self.assertEqual(r["tables"], [{"name": "CARDDEMO.ACCT_TBL", "op": "read"}])
        self.assertEqual(r["host_writes"], ["WS-A", "WS-B"])
        self.assertEqual(r["host_reads"], ["WS-ID"])

    def test_insert(self):
        r = sql.parse("EXEC SQL INSERT INTO TRAN_TYPE (C1, C2) VALUES (:H1, :H2) END-EXEC")
        self.assertEqual(r["kind"], "insert")
        self.assertEqual(r["tables"], [{"name": "TRAN_TYPE", "op": "insert"}])

    def test_cursor_join(self):
        r = sql.parse("EXEC SQL DECLARE C1 CURSOR FOR SELECT X FROM T1 A JOIN T2 B ON A.K = B.K END-EXEC")
        self.assertEqual(r["kind"], "declare_cursor")
        self.assertEqual(r["cursor"], "C1")
        self.assertEqual(sorted(t["name"] for t in r["tables"]), ["T1", "T2"])
        self.assertTrue(all(t["op"] == "read" for t in r["tables"]))

    def test_include(self):
        r = sql.parse("EXEC SQL INCLUDE SQLCA END-EXEC")
        self.assertEqual(r["kind"], "include")
        self.assertEqual(r["include"], "SQLCA")

    def test_delete_subselect(self):
        r = sql.parse("EXEC SQL DELETE FROM T3 WHERE K IN (SELECT K FROM T4) END-EXEC")
        self.assertEqual(r["tables"], [{"name": "T3", "op": "delete"}, {"name": "T4", "op": "read"}])


if __name__ == "__main__":
    unittest.main()
