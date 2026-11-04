import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from graph_lib import access  # noqa: E402
from tests.helpers import cobol, dd, step  # noqa: E402


class AccessTest(unittest.TestCase):

    def test_combine(self):
        self.assertEqual(access.combine(None, "read"), "read")
        self.assertEqual(access.combine("read", "write"), "read_write")
        self.assertEqual(access.combine("delete", "read"), "read_write")
        self.assertEqual(access.combine("delete", "write"), "write")
        self.assertEqual(access.combine("unknown", "read"), "read")
        self.assertEqual(access.combine("read", "read"), "read")

    def test_ops(self):
        self.assertEqual(access.from_cics_op("browse"), "read")
        self.assertEqual(access.from_cics_op("read_update"), "read_write")
        self.assertEqual(access.from_sql_op("insert"), "write")
        self.assertIsNone(access.from_sql_op("declare"))
        self.assertEqual(access.from_queue_op("delete"), "delete")

    def test_dd_access_cobol(self):
        cf = cobol("P", kind="batch_main", files_io=[{"select": "F", "dd": "TRANFILE", "access_summary": "write"}])
        s = step(1, "S", "P")
        self.assertEqual(access.dd_access(s, dd("TRANFILE", "X", "read"), {"P": cf}), "write")

    def test_dd_access_idcams(self):
        s = step(1, "S", "IDCAMS", utility_data={"idcams_commands": [{"verb": "REPRO", "infile": "IN",
                                                                      "outfile": "OUT"}]})
        self.assertEqual(access.dd_access(s, dd("IN", "X", "old"), {}), "read")
        self.assertEqual(access.dd_access(s, dd("OUT", "X", "old"), {}), "write")
        self.assertEqual(access.dd_access(s, dd("OTHER", "X", "old"), {}), "read_write")

    def test_dd_access_sort_iebgener(self):
        s = step(1, "S", "SORT")
        self.assertEqual(access.dd_access(s, dd("SORTIN", "X", "old"), {}), "read")
        self.assertEqual(access.dd_access(s, dd("SORTOUT", "X", "read"), {}), "write")
        s = step(1, "S", "IEBGENER")
        self.assertEqual(access.dd_access(s, dd("SYSUT1", "X", "old"), {}), "read")
        self.assertEqual(access.dd_access(s, dd("SYSUT2", "X", "read"), {}), "write")

    def test_dd_access_mode_hint(self):
        self.assertEqual(access.dd_access(step(1, "S", "IEFBR14"), dd("DD01", "X", "delete"), {}), "delete")
        self.assertEqual(access.dd_access(step(1, "S", "UNKNOWNPGM"), dd("DD01", "X", "create"), {}), "write")


if __name__ == "__main__":
    unittest.main()
