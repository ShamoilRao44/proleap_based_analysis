import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from facts_lib import linemap  # noqa: E402


def mk(text):
    return text.split("\n")


class LineMapTest(unittest.TestCase):

    def test_copybook(self):
        prog = ["       IDENTIFICATION DIVISION.",
                "       PROGRAM-ID. T1.",
                "      * comment",
                "       DATA DIVISION.",
                "       WORKING-STORAGE SECTION.",
                "       COPY CPY1.",
                "       PROCEDURE DIVISION.",
                "       MAIN-PARA.",
                "           GOBACK."]
        cpy = ["       01 A PIC X."]
        pp = ["       IDENTIFICATION DIVISION.",
              "       PROGRAM-ID. T1.",
              "      *> comment",
              "       DATA DIVISION.",
              "       WORKING-STORAGE SECTION.",
              "       ",
              "*> @@CPYENTER CPY1|/x/CPY1.cpy",
              "       01 A PIC X.",
              "*> @@CPYEXIT CPY1",
              "       PROCEDURE DIVISION.",
              "       MAIN-PARA.",
              "           GOBACK."]
        files = {"/x/T1.cbl": prog, "/x/CPY1.cpy": cpy}
        lm = linemap.build_linemap(pp, "/x/T1.cbl", "FIXED", read_lines=lambda p: files.get(p, []))
        got = [(e[0], e[1], e[2]) for e in lm["map"]]
        expected = [(0, 1, True), (0, 2, True), (0, 3, True), (0, 4, True), (0, 5, True),
                    (0, 5, False), (0, 6, True), (1, 1, True), (0, 6, False),
                    (0, 7, True), (0, 8, True), (0, 9, True)]
        self.assertEqual(got, expected)
        self.assertEqual(len(lm["copies"]), 1)
        ev = lm["copies"][0]
        self.assertEqual(ev["name"], "CPY1")
        self.assertEqual(ev["line"], 6)
        self.assertEqual(ev["depth"], 1)
        self.assertEqual(ev["enter_pline"], 7)
        self.assertEqual(ev["exit_pline"], 9)

    def test_continuation(self):
        prog = ["       MOVE 'ABC",
                "      -    'DEF' TO X.",
                "       DISPLAY X."]
        pp = ["       MOVE 'ABCDEF' TO X.",
              "       DISPLAY X."]
        lm = linemap.build_linemap(pp, "/x/T.cbl", "FIXED", read_lines=lambda p: prog)
        self.assertEqual([e[1] for e in lm["map"]], [1, 3])
        self.assertTrue(all(e[2] for e in lm["map"]))


if __name__ == "__main__":
    unittest.main()
