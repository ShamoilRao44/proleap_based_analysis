import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scan_lib import csd  # noqa: E402


class CsdTest(unittest.TestCase):

    def test_aws_style(self):
        r = csd.parse_lines([" DEFINE FILE(ACCTDAT) GROUP(CARDDEMO)", " DESCRIPTION(TEST FILE)",
                             "        DSNAME(AWS.X.ACCT) RLSACCESS(NO)",
                             "        BROWSE(YES) DELETE(YES) READ(YES)"])
        self.assertEqual(len(r["definitions"]), 1)
        d = r["definitions"][0]
        self.assertEqual((d["type"], d["name"], d["group"]), ("FILE", "ACCTDAT", "CARDDEMO"))
        self.assertEqual(d["description"], "TEST FILE")
        self.assertEqual(d["dsname"], "AWS.X.ACCT")
        self.assertEqual(d["attrs"]["DELETE"], "YES")
        self.assertEqual(r["commands"], [])

    def test_cbsa_style(self):
        r = csd.parse_lines(["* comment", "", " DELETE GROUP(BANK)", "", "DEFINE TRANSACTION(BKB2) GROUP(BANK)",
                             " DESCRIPTION('BANK Online Bank to Bank Transfer Receive')",
                             "        PROGRAM(XFRB2BR) TWASIZE(0) PROFILE(DFHCICST) STATUS(ENABLED)"])
        self.assertEqual(len(r["commands"]), 1)
        self.assertEqual(r["commands"][0]["verb"], "DELETE")
        self.assertEqual(r["commands"][0]["text"], "DELETE GROUP(BANK)")
        self.assertEqual(len(r["definitions"]), 1)
        d = r["definitions"][0]
        self.assertEqual((d["type"], d["name"], d["program"]), ("TRANSACTION", "BKB2", "XFRB2BR"))
        self.assertEqual(d["description"], "BANK Online Bank to Bank Transfer Receive")

    def test_program_transid(self):
        r = csd.parse_lines(["  DEFINE PROGRAM(COSGN00C) GROUP(CARDDEMO) DA(ANY) TRANSID(CC00)"])
        d = r["definitions"][0]
        self.assertEqual((d["type"], d["transid"]), ("PROGRAM", "CC00"))

    def test_first_line(self):
        r = csd.parse_lines(["", " DEFINE FILE(A) GROUP(G)"], first_line=10)
        self.assertEqual(r["definitions"][0]["line"], 11)
        r = csd.parse_lines([" DEFINE FILE(A) GROUP(G)"], first_line=10)
        self.assertEqual(r["definitions"][0]["line"], 10)

    def test_summary(self):
        r = csd.parse_lines([" DEFINE FILE(A) GROUP(G)", " DEFINE FILE(B) GROUP(G)", " DEFINE MAPSET(M) GROUP(G)"])
        s = csd.summarize(r["definitions"])
        self.assertEqual(s["by_type"], {"FILE": 2, "MAPSET": 1})
        self.assertEqual(s["groups"], ["G"])


if __name__ == "__main__":
    unittest.main()
