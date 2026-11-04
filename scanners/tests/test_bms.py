import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scan_lib import bms  # noqa: E402


def asm(text, cont=False):
    return text.ljust(71) + ("-" if cont else "")


LINES = [
    asm("COMEN01 DFHMSD CTRL=(ALARM,FREEKB),", True),
    asm("               EXTATT=YES,", True),
    asm("               TYPE=&&SYSPARM"),
    asm("COMEN1A DFHMDI COLUMN=1,", True),
    asm("               LINE=1,", True),
    asm("               SIZE=(24,80)"),
    asm("        DFHMDF ATTRB=(ASKIP,NORM),", True),
    asm("               LENGTH=5,", True),
    asm("               POS=(1,1),", True),
    asm("               INITIAL='Tran:'"),
    asm("TRNNAME DFHMDF ATTRB=(ASKIP,FSET,NORM),", True),
    asm("               LENGTH=4,", True),
    asm("               POS=(1,7)"),
    asm("CUSTID  DFHMDF ATTRB=(UNPROT,FSET),LENGTH=9,POS=(5,20)"),
    asm("        DFHMSD TYPE=FINAL"),
]


class BmsTest(unittest.TestCase):

    def test_parse(self):
        r = bms.parse_lines(LINES)
        self.assertEqual(len(r["mapsets"]), 1)
        ms = r["mapsets"][0]
        self.assertEqual(ms["name"], "COMEN01")
        self.assertEqual(ms["attrs"]["EXTATT"], "YES")
        self.assertEqual(len(ms["maps"]), 1)
        mp = ms["maps"][0]
        self.assertEqual(mp["name"], "COMEN1A")
        self.assertEqual(mp["size"], [24, 80])
        f = mp["fields"]
        self.assertEqual(len(f), 3)
        self.assertIsNone(f[0]["name"])
        self.assertEqual((f[0]["pos"], f[0]["length"], f[0]["initial"], f[0]["role"]), ([1, 1], 5, "Tran:", "label"))
        self.assertEqual(f[1]["name"], "TRNNAME")
        self.assertEqual(f[1]["attrb"], ["ASKIP", "FSET", "NORM"])
        self.assertEqual(f[1]["role"], "output")
        self.assertEqual((f[2]["name"], f[2]["role"], f[2]["pos"], f[2]["length"]), ("CUSTID", "input", [5, 20], 9))
        self.assertEqual(mp["field_count"], 3)
        self.assertEqual(mp["named_fields"], 2)

    def test_scan_file_symbolic(self):
        import tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, "COMEN01.bms")
        with open(p, "w", newline="\n") as fh:
            fh.write("\n".join(LINES) + "\n")
        rec = {"name": "COMEN01", "path": "bms/COMEN01.bms"}
        f = bms.scan_file(p, rec, d, {"COMEN01": "cpy/COMEN01.CPY"})
        self.assertEqual(f["mapsets"][0]["symbolic_copybook"], "cpy/COMEN01.CPY")
        self.assertEqual(f["summary"], {"mapsets": 1, "maps": 1, "fields": 3})
        f2 = bms.scan_file(p, rec, d, {})
        self.assertIsNone(f2["mapsets"][0]["symbolic_copybook"])


if __name__ == "__main__":
    unittest.main()
