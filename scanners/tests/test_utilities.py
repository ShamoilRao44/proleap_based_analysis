import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scan_lib import utilities as u  # noqa: E402


class UtilitiesTest(unittest.TestCase):

    def test_idcams(self):
        lines = ["   DELETE AWS.X.ACCT.KSDS -", "          CLUSTER", "   IF MAXCC LE 08 THEN SET MAXCC = 0",
                 "   DEFINE CLUSTER (NAME(AWS.X.ACCT.KSDS) -", "          CYLINDERS(1 5) -",
                 "          KEYS(11 0) -", "          RECORDSIZE(300 300) -", "          INDEXED -",
                 "          ) -", "          DATA (NAME(AWS.X.ACCT.KSDS.DATA) -", "          )",
                 "   REPRO INFILE(ACCTDATA) OUTFILE(ACCTVSAM)", "   DEFINE GENERATIONDATAGROUP -",
                 "   (NAME(AWS.X.TRAN.BKUP) -", "    LIMIT(5) -", "    SCRATCH -", "   )"]
        c = u.idcams_parse(lines)
        self.assertEqual([x["verb"] for x in c], ["DELETE", "DEFINE", "REPRO", "DEFINE"])
        self.assertEqual((c[0]["name"], c[0]["object_type"]), ("AWS.X.ACCT.KSDS", "CLUSTER"))
        self.assertEqual((c[1]["subtype"], c[1]["name"]), ("CLUSTER", "AWS.X.ACCT.KSDS"))
        self.assertEqual(len(c[1]["names"]), 2)
        self.assertEqual(c[1]["attrs"]["KEYS"], [11, 0])
        self.assertEqual(c[1]["attrs"]["RECORDSIZE"], [300, 300])
        self.assertEqual(c[1]["attrs"]["ORGANIZATION"], "INDEXED")
        self.assertEqual((c[2]["infile"], c[2]["outfile"]), ("ACCTDATA", "ACCTVSAM"))
        self.assertEqual((c[3]["subtype"], c[3]["name"], c[3]["attrs"]["LIMIT"]), ("GDG", "AWS.X.TRAN.BKUP", 5))

    def test_idcams_delete_aix(self):
        c = u.idcams_parse(["   DELETE AWS.X.AIX -", "          ALTERNATEINDEX"])
        self.assertEqual(c[0]["object_type"], "AIX")

    def test_sort(self):
        s = u.sort_parse(["TRAN-CARD-NUM,263,16,ZD", "PARM-START-DATE,C'2022-01-01'",
                          " SORT FIELDS=(TRAN-CARD-NUM,A)",
                          " INCLUDE COND=(TRAN-PROC-DT,GE,PARM-START-DATE,AND,",
                          "         TRAN-PROC-DT,LE,PARM-END-DATE)"])
        self.assertEqual([x["verb"] for x in s], ["SORT", "INCLUDE"])
        self.assertEqual(s[0]["fields"], "TRAN-CARD-NUM,A")
        self.assertIn("PARM-END-DATE", s[1]["text"])

    def test_sdsf(self):
        r = u.sdsf_parse([" /F CICSAWSA,'CEMT SET FIL(TRANSACT ) CLO'", " /F CICSAWSA,'CEMT SET FIL(CCXREF ) OPE'"])
        self.assertEqual(len(r), 2)
        self.assertEqual((r[0]["region"], r[0]["verb"], r[0]["resource_type"], r[0]["resource"], r[0]["action"]),
                         ("CICSAWSA", "SET", "FILE", "TRANSACT", "CLOSE"))
        self.assertEqual((r[1]["resource"], r[1]["action"]), ("CCXREF", "OPEN"))

    def test_tso(self):
        r = u.tso_parse(["  DSN SYSTEM(DBCG)", "  RUN PROGRAM(DSNTEP2)  PLAN(DSNTEP12) -",
                         "       LIB('DSNC10.DBCG.RUNLIB.LOAD') PARMS('/ALIGN(MID)')", "  END"])
        self.assertEqual(len(r), 1)
        self.assertEqual((r[0]["program"], r[0]["plan"], r[0]["subsystem"]), ("DSNTEP2", "DSNTEP12", "DBCG"))

    def test_parm_invokes(self):
        self.assertEqual(u.parm_invokes("DFSRRC00", "DLI,PAUTB01,PSBPAUTB"),
                         [{"program": "PAUTB01", "psb": "PSBPAUTB", "via": "DFSRRC00 PARM"}])
        self.assertEqual(u.parm_invokes("IDCAMS", "X"), [])


if __name__ == "__main__":
    unittest.main()
