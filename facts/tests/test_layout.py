import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from facts_lib import layout  # noqa: E402


def raw(id_, level, name, pic=None, usage=None, values=None, occurs=None, redefines=None):
    return {"id": id_, "level": level, "name": name, "section": "WORKING-STORAGE", "fd": None, "pic": pic,
            "usage": usage, "values": values, "occurs": occurs, "redefines": redefines, "sign": None,
            "sync": False, "justified": False, "blank_when_zero": False, "renames": None,
            "pline": id_, "pline_end": id_}


def v(text):
    return [{"from": text, "thru": None}]


def occ(n):
    return {"min": n, "max": n, "depending": None, "indexed_by": []}


class LayoutTest(unittest.TestCase):

    def test_sizes_offsets(self):
        items = layout.build_items([
            raw(1, 1, "R"),
            raw(2, 5, "A", "X(10)"),
            raw(3, 5, "B", "S9(7)V99", "COMP-3"),
            raw(4, 5, "C", "9(4)", "COMP"),
            raw(5, 5, "D", "XX", redefines="C"),
            raw(6, 5, "E", occurs=occ(3)),
            raw(7, 10, "E1", "X(2)"),
            raw(8, 10, "E2", "9(3)"),
        ])
        by = {i["name"]: i for i in items}
        self.assertEqual([by[n]["size"] for n in ("A", "B", "C", "D")], [10, 5, 2, 2])
        self.assertEqual(by["E"]["size"], 5)
        self.assertEqual(by["E"]["total_size"], 15)
        self.assertEqual(by["R"]["size"], 32)
        self.assertEqual([by[n]["offset"] for n in ("A", "B", "C", "D", "E", "E1", "E2")],
                         [0, 10, 15, 15, 17, 17, 19])
        self.assertEqual(by["D"]["redefines_id"], by["C"]["id"])

    def test_pic_size_separate_sign(self):
        self.assertEqual(layout.pic_size("S9(5)V99", "DISPLAY", "SIGN LEADING SEPARATE"), 8)

    def test_value_table(self):
        items = layout.build_items([
            raw(1, 1, "T"),
            raw(2, 5, "T-DATA"),
            raw(3, 10, "FILLER", "9(02)", values=v("1")),
            raw(4, 10, "FILLER", "X(08)", values=v("'PGMA'")),
            raw(5, 10, "FILLER", "9(02)", values=v("2")),
            raw(6, 10, "FILLER", "X(08)", values=v("'PGMB'")),
            raw(7, 5, "T-TAB", redefines="T-DATA"),
            raw(8, 10, "T-ENT", occurs=occ(2)),
            raw(9, 15, "T-NUM", "9(02)"),
            raw(10, 15, "T-PGM", "X(08)"),
        ])
        by = {i["name"]: i for i in items}
        self.assertEqual(layout.occurrence_values(items, by["T-PGM"]["id"]), ["PGMA", "PGMB"])
        self.assertEqual(layout.occurrence_values(items, by["T-NUM"]["id"]), ["01", "02"])

    def test_literal_value(self):
        self.assertEqual(layout.literal_value("'AB''C'"), {"kind": "string", "value": "AB'C"})
        self.assertEqual(layout.literal_value("-12.5")["kind"], "number")
        self.assertEqual(layout.literal_value("SPACES"), {"kind": "figurative", "value": "SPACE"})
        self.assertEqual(layout.literal_value("X'F0F1'"), {"kind": "hex", "value": "F0F1"})
        self.assertEqual(layout.literal_value("ALL '*'"), {"kind": "all", "value": "*"})


if __name__ == "__main__":
    unittest.main()
