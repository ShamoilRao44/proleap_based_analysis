import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scan_lib import ims  # noqa: E402


def asm(text, cont=False):
    return text.ljust(71) + ("-" if cont else "")


DBD = [
    "***********************************************************************",
    "         TITLE   'ASSEMBLE OF DBDNAME=DBPAUTP0 '",
    asm("       DBD     NAME=DBPAUTP0,ACCESS=(HIDAM,VSAM),PASSWD=NO,", True),
    asm("               EXIT=(*,KEY,DATA,NOPATH,(NOCASCADE),LOG),", True),
    asm("               VERSION="),
    "DSG001 DATASET DD1=DDPAUTP0,SIZE=(4096),SCAN=3",
    asm("       SEGM    NAME=PAUTSUM0,PARENT=0,BYTES=100,RULES=(,HERE),", True),
    asm("               POINTER=(TWINBWD)"),
    "       FIELD   NAME=(ACCNTID,SEQ,U),START=1,BYTES=6,TYPE=P",
    asm("       LCHILD  NAME=(PAUTINDX,DBPAUTX0),", True),
    asm("               POINTER=INDX"),
    "       SEGM    NAME=PAUTDTL1,PARENT=((PAUTSUM0,)),BYTES=200",
    "       FIELD   NAME=(PAUT9CTS,SEQ,U),START=1,BYTES=8,TYPE=C",
    "       DBDGEN",
    "       FINISH",
    "       END",
]

PSB = [
    "PAUTBPCB PCB   TYPE=DB,DBDNAME=DBPAUTP0,PROCOPT=AP,KEYLEN=14",
    "         SENSEG  NAME=PAUTSUM0,PARENT=0",
    "         SENSEG  NAME=PAUTDTL1,PARENT=PAUTSUM0",
    "         PSBGEN  LANG=COBOL,PSBNAME=PSBPAUTB,CMPAT=YES",
    "         END",
]


class ImsTest(unittest.TestCase):

    def test_dbd(self):
        r = ims.parse_lines(DBD)
        d = r["dbd"]
        self.assertEqual(d["name"], "DBPAUTP0")
        self.assertEqual(d["access"], ["HIDAM", "VSAM"])
        self.assertEqual(len(d["datasets"]), 1)
        self.assertEqual((d["datasets"][0]["label"], d["datasets"][0]["dd1"]), ("DSG001", "DDPAUTP0"))
        s = d["segments"]
        self.assertEqual(len(s), 2)
        self.assertEqual((s[0]["name"], s[0]["parent"], s[0]["bytes"]), ("PAUTSUM0", None, 100))
        self.assertEqual(len(s[0]["fields"]), 1)
        f = s[0]["fields"][0]
        self.assertEqual((f["name"], f["seq"], f["unique"], f["start"], f["bytes"]), ("ACCNTID", True, True, 1, 6))
        self.assertEqual(len(s[0]["lchild"]), 1)
        self.assertEqual((s[0]["lchild"][0]["segment"], s[0]["lchild"][0]["dbd"]), ("PAUTINDX", "DBPAUTX0"))
        self.assertEqual((s[1]["name"], s[1]["parent"], s[1]["bytes"]), ("PAUTDTL1", "PAUTSUM0", 200))
        self.assertIsNone(r["psb"])

    def test_psb(self):
        r = ims.parse_lines(PSB)
        p = r["psb"]
        self.assertEqual((p["name"], p["lang"]), ("PSBPAUTB", "COBOL"))
        self.assertEqual(len(p["pcbs"]), 1)
        c = p["pcbs"][0]
        self.assertEqual((c["index"], c["label"], c["type"], c["dbdname"], c["procopt"], c["keylen"],
                          c["access_hint"]), (1, "PAUTBPCB", "DB", "DBPAUTP0", "AP", 14, "update"))
        self.assertEqual([(s["name"], s["parent"]) for s in c["segments"]],
                         [("PAUTSUM0", None), ("PAUTDTL1", "PAUTSUM0")])

    def test_read_hint(self):
        r = ims.parse_lines(["         PCB   TYPE=DB,DBDNAME=X,PROCOPT=GOTP"])
        self.assertEqual(r["psb"]["pcbs"][0]["access_hint"], "read")

    def test_scan_file_kind(self):
        import tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, "PSBPAUTB.psb")
        with open(p, "w", newline="\n") as fh:
            fh.write("\n".join(PSB) + "\n")
        f = ims.scan_file(p, {"name": "PSBPAUTB", "path": "ims/PSBPAUTB.psb"}, d)
        self.assertEqual((f["kind"], f["declared_name"]), ("psb", "PSBPAUTB"))
        p2 = os.path.join(d, "DBPAUTP0.dbd")
        with open(p2, "w", newline="\n") as fh:
            fh.write("\n".join(DBD) + "\n")
        f2 = ims.scan_file(p2, {"name": "DBPAUTP0", "path": "ims/DBPAUTP0.dbd"}, d)
        self.assertEqual((f2["kind"], f2["declared_name"]), ("dbd", "DBPAUTP0"))


if __name__ == "__main__":
    unittest.main()
