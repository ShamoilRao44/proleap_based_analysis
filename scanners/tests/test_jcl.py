import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scan_lib import jcl  # noqa: E402

EMPTY = {"procs": {}, "members": {}}


def facts(lines, ctx=None, name="T"):
    ctx = ctx or {"procs": {}, "members": {}}
    raw = jcl.parse_member(lines, name, ctx)
    return jcl.build_facts(raw, {"name": name, "path": name + ".jcl"}, ctx)


def dd_of(step, name):
    return [d for d in step["dds"] if d["name"] == name][0]


class JclTest(unittest.TestCase):

    def test_cards(self):
        cards = jcl.read_cards(["//POSTTRAN JOB 'POSTTRAN',CLASS=A,MSGCLASS=0,", "// NOTIFY=&SYSUID",
                                "//STEP15 EXEC PGM=CBTRN02C", "//STEPLIB  DD DISP=SHR,",
                                "//            DSN=AWS.M2.CARDDEMO.LOADLIB", "//SYSIN DD *", "  DELETE X -",
                                "    CLUSTER", "/*", "//DD2 DD DUMMY", "//*comment", "//"])
        self.assertEqual([c["op"] for c in cards], ["JOB", "EXEC", "DD", "DD", "DD", ""])
        self.assertIn("NOTIFY=&SYSUID", cards[0]["operands"])
        self.assertEqual(cards[2]["name"], "STEPLIB")
        self.assertEqual(cards[2]["operands"], "DISP=SHR,DSN=AWS.M2.CARDDEMO.LOADLIB")
        self.assertEqual(len(cards[3]["inline"]["lines"]), 2)
        self.assertEqual(cards[4]["name"], "DD2")

    def test_dd_parsing(self):
        f = facts(["//J JOB", "//S EXEC PGM=X",
                   "//TRANREPT DD DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,",
                   "//   DCB=(LRECL=133,RECFM=FB,BLKSIZE=0),SPACE=(CYL,(1,1),RLSE),",
                   "//   DSN=AWS.M2.CARDDEMO.TRANREPT(+1)",
                   "//OUT DD DSN=&&TEMP,DISP=(,PASS)", "//IN DD DSN=AWS.X.LIB(MEMB),DISP=SHR",
                   "//Z DD DUMMY"])
        s = f["steps"][0]
        t = dd_of(s, "TRANREPT")
        self.assertEqual(t["dsn"], "AWS.M2.CARDDEMO.TRANREPT")
        self.assertEqual(t["generation"], "+1")
        self.assertEqual(t["disp"], {"raw": "(NEW,CATLG,DELETE)", "status": "NEW", "normal": "CATLG",
                                     "abnormal": "DELETE"})
        self.assertEqual(t["mode_hint"], "create")
        self.assertEqual(t["dcb"], {"lrecl": 133, "recfm": "FB", "blksize": 0, "dsorg": None, "ref": None})
        o = dd_of(s, "OUT")
        self.assertTrue(o["temp"])
        self.assertIsNone(o["disp"]["status"])
        self.assertEqual(o["disp"]["normal"], "PASS")
        self.assertEqual(dd_of(s, "IN")["member"], "MEMB")
        z = dd_of(s, "Z")
        self.assertTrue(z["dummy"])
        self.assertEqual(z["mode_hint"], "dummy")

    def test_symbols(self):
        f = facts(["// SET HLQ=AWS.M2.CARDDEMO", "//STEP1 EXEC PGM=DFHCSDUP,PARM='CSD(READWRITE)'",
                   "//STEPLIB DD DSN=&HLQ..LOADLIB,DISP=SHR", "//X DD DSN=&MISSING..DATA,DISP=SHR",
                   "//Y DD DSN=&SYSUID..DATA,DISP=SHR"])
        s = f["steps"][0]
        self.assertEqual(dd_of(s, "STEPLIB")["dsn"], "AWS.M2.CARDDEMO.LOADLIB")
        self.assertEqual(dd_of(s, "STEPLIB")["mode_hint"], "library")
        self.assertEqual(dd_of(s, "X")["unresolved_symbols"], ["MISSING"])
        self.assertEqual(dd_of(s, "Y")["unresolved_symbols"], [])
        self.assertEqual(s["parm"], "CSD(READWRITE)")

    def test_include(self):
        ctx = {"procs": {}, "members": {"DEFAULT": ["// SET CICSHLQ=DFH560.CICS"]}}
        f = facts(["// INCLUDE MEMBER=DEFAULT", "//S1 EXEC PGM=X", "//L DD DSN=&CICSHLQ..SDFHLOAD,DISP=SHR"], ctx)
        self.assertEqual(f["includes"], [{"member": "DEFAULT", "found": True}])
        self.assertEqual(dd_of(f["steps"][0], "L")["dsn"], "DFH560.CICS.SDFHLOAD")

    def _reproc_ctx(self):
        ctx = {"procs": {}, "members": {}}
        raw = jcl.parse_member(["//REPROC PROC", "//PRC001 EXEC PGM=IDCAMS", "//FILEIN DD DISP=SHR,DSN=NULLFILE",
                                "//FILEOUT DD DISP=SHR,DSN=NULLFILE", "//SYSIN DD DISP=SHR,DSN=&CNTLLIB(REPROCT)",
                                "// PEND"], "REPROC", ctx)
        ctx["procs"]["REPROC"] = raw
        return ctx

    JOB = ["//J JOB", "//S1 EXEC PROC=REPROC,", "// CNTLLIB=AWS.CNTL", "//PRC001.FILEIN DD DISP=SHR,DSN=AWS.IN",
           "//PRC001.FILEOUT DD DISP=(NEW,CATLG),DSN=AWS.OUT(+1)", "//S2 EXEC PGM=MYPROG"]

    def test_proc_expansion(self):
        f = facts(self.JOB, self._reproc_ctx())
        self.assertEqual([s["name"] for s in f["flat_steps"]], ["S1.PRC001", "S2"])
        s = f["flat_steps"][0]
        self.assertEqual(dd_of(s, "FILEIN")["dsn"], "AWS.IN")
        self.assertEqual((dd_of(s, "FILEOUT")["dsn"], dd_of(s, "FILEOUT")["generation"]), ("AWS.OUT", "+1"))
        self.assertEqual((dd_of(s, "SYSIN")["dsn"], dd_of(s, "SYSIN")["member"]), ("AWS.CNTL", "REPROCT"))
        self.assertEqual(f["programs_run"], ["MYPROG"])
        self.assertEqual(f["procs_used"], [{"name": "REPROC", "found": True}])

    def test_proc_missing(self):
        f = facts(self.JOB, EMPTY)
        self.assertEqual(f["procs_used"], [{"name": "REPROC", "found": False}])
        self.assertEqual(len(f["flat_steps"]), 2)
        self.assertEqual([s["name"] for s in f["flat_steps"]], ["S1", "S2"])

    def test_inline_csd_symbols(self):
        f = facts(["// SET HLQ=AWS.X", "//S1 EXEC PGM=DFHCSDUP", "//SYSIN DD *,SYMBOLS=JCLONLY",
                   "  DEFINE LIBRARY(COM2DOLL) GROUP(G)", "        DSNAME01(&HLQ..LOADLIB)",
                   "  DEFINE TRANSACTION(CCDM) GROUP(G)", "        PROGRAM(COADM00C)", "/*"])
        d = f["steps"][0]["utility_data"]["inline_csd"]["definitions"]
        self.assertEqual(len(d), 2)
        self.assertEqual(d[0]["dsnames"], ["AWS.X.LOADLIB"])
        self.assertEqual(d[1]["program"], "COADM00C")

    def test_inline_sql_and_tso(self):
        f = facts(["//GRANT EXEC PGM=IKJEFT01,DYNAMNBR=20", "//SYSTSIN DD *", "  DSN SYSTEM(DBCG)",
                   "  RUN PROGRAM(DSNTEP2) PLAN(DSNTEP12) -", "       LIB('DSNC10.DBCG.RUNLIB.LOAD')", "  END",
                   "//SYSIN DD *", "SET CURRENT SQLID = 'IBMUSER';", "CREATE DATABASE CBSA",
                   "       BUFFERPOOL BP1;", "/*"])
        s = f["steps"][0]
        self.assertEqual(len(s["utility_data"]["tso_runs"]), 1)
        self.assertEqual(s["utility_data"]["tso_runs"][0]["program"], "DSNTEP2")
        self.assertIn({"program": "DSNTEP2", "plan": "DSNTEP12", "via": "SYSTSIN RUN PROGRAM"}, s["invokes"])
        o = s["utility_data"]["inline_sql"]["other"]
        self.assertEqual((len(o), o[0]["kind"], o[0]["name"]), (1, "DATABASE", "CBSA"))

    def test_if_context(self):
        f = facts(["//S1 EXEC PGM=A", "// IF (S1.RC = 0) THEN", "//S2 EXEC PGM=B", "// ELSE", "//S3 EXEC PGM=C",
                   "// ENDIF", "//S4 EXEC PGM=D"])
        s = {x["name"]: x for x in f["steps"]}
        self.assertEqual(s["S2"]["if_context"], ["(S1.RC = 0)"])
        self.assertEqual(s["S3"]["if_context"], ["NOT ((S1.RC = 0))"])
        self.assertEqual(s["S4"]["if_context"], [])

    def test_duplicate_step_and_kinds(self):
        f = facts(["//J JOB", "//S1 EXEC PGM=A", "//S1 EXEC PGM=B"])
        self.assertEqual(f["steps"][1]["warnings"], ["duplicate step name S1"])
        self.assertEqual(facts(["//P PROC", "//S1 EXEC PGM=A", "// PEND"])["kind"], "proc")
        self.assertEqual(facts(["// SET A=B"])["kind"], "fragment")
        self.assertEqual(facts(["//J JOB", "//S1 EXEC PGM=A"])["kind"], "job")

    def test_referback_and_datasets(self):
        f = facts(["//J JOB", "//SORT EXEC PGM=SORT", "//SORTIN DD DISP=SHR,DSN=AWS.IN",
                   "//SORTOUT DD DISP=(NEW,CATLG),DSN=*.SORTIN"])
        dd = dd_of(f["flat_steps"][0], "SORTOUT")
        self.assertTrue(dd["referback_resolved"])
        self.assertEqual(dd["dsn"], "AWS.IN")
        self.assertEqual([d["dsn"] for d in f["datasets"]], ["AWS.IN"])


if __name__ == "__main__":
    unittest.main()
