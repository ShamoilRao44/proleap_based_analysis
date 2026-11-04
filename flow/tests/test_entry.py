import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from flow_lib import entry  # noqa: E402
from tests.helpers import final, item, rawf, shop_programs, stmt, xfer, clone  # noqa: E402

KNOWN = set(["SIGN", "MENU", "LIST", "DETAIL", "CARD"])


def fe(name, finals, raws):
    return entry.first_entry(finals[name], raws[name], KNOWN)


class EntryTest(unittest.TestCase):

    def test_own_screen(self):
        finals, raws = shop_programs()
        r = fe("SIGN", finals, raws)
        self.assertTrue(r["found"])
        self.assertEqual((r["outcome"], r["events"], r["condition"]), ("own_screen", ["send"], "EIBCALEN = 0"))
        self.assertEqual(r["paragraph"], "MAIN")

    def test_handoff_path_resolved(self):
        finals, raws = shop_programs()
        r = fe("MENU", finals, raws)
        self.assertEqual(r["outcome"], "handoff")
        self.assertEqual(r["handoff_targets"], ["SIGN"])
        self.assertTrue(r["path_resolved"])
        self.assertEqual(r["events"], ["assign", "transfer"])

    def test_handoff_without_assignment(self):
        finals, raws = shop_programs()
        raws["MENU"]["statements"] = [s for s in raws["MENU"]["statements"] if s["id"] != 2]
        r = fe("MENU", finals, raws)
        self.assertEqual(r["handoff_targets"], ["LIST", "SIGN"])
        self.assertFalse(r["path_resolved"])

    def test_self_initialising_and_expected_caller(self):
        finals, raws = shop_programs()
        r = fe("CARD", finals, raws)
        self.assertEqual(r["outcome"], "self_initialising")
        self.assertEqual(r["expected_callers"], ["MENU"])

    def test_equal_to_form_and_missing_test(self):
        finals, raws = shop_programs()
        raws["SIGN"]["statements"][0]["condition"] = "EIBCALEN IS EQUAL TO 0"
        self.assertTrue(fe("SIGN", finals, raws)["found"])
        r = fe("DETAIL", finals, raws)
        self.assertFalse(r["found"])
        self.assertEqual(r["outcome"], "none")
        self.assertEqual(entry.first_entry(finals["SIGN"], None, KNOWN)["outcome"], "unknown")

    def test_recursive_perform_terminates(self):
        f = final("REC", [item(1, "COMM", 1, 0, 8, 1)], [])
        r = rawf("REC", ["MAIN", "A", "B"], [
            stmt(1, "if", "MAIN", condition="EIBCALEN = 0"),
            stmt(2, "perform", "MAIN", 1, "then", target="A", thru=None, inline=False),
            stmt(3, "perform", "A", target="B", thru=None, inline=False),
            stmt(4, "perform", "B", target="A", thru=None, inline=False)])
        self.assertEqual(entry.first_entry(f, r, KNOWN)["outcome"], "other")

    def test_depth_limit(self):
        names = ["MAIN"] + ["P%d" % i for i in range(1, 7)]
        sts = [stmt(1, "if", "MAIN", condition="EIBCALEN = 0"),
               stmt(2, "perform", "MAIN", 1, "then", target="P1", thru=None, inline=False)]
        n = 3
        for i in range(1, 6):
            sts.append(stmt(n, "perform", "P%d" % i, target="P%d" % (i + 1), thru=None, inline=False))
            n += 1
        sts.append(stmt(n, "execCics", "P6", exec_text="EXEC CICS XCTL PROGRAM('OTHER') END-EXEC"))
        f = final("DEEP", [item(1, "COMM", 1, 0, 8, 1)], [xfer(n, "XCTL", ["OTHER"])])
        r = rawf("DEEP", names, sts)
        self.assertEqual(entry.first_entry(f, r, KNOWN)["outcome"], "other")


if __name__ == "__main__":
    unittest.main()
