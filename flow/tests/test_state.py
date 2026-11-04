import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from flow_lib import state  # noqa: E402
from tests.helpers import (assemble, final, item, rawf, shop_data, shop_items, shop_programs, stmt,  # noqa: E402
                           xfer, SHOP_EDGES)


def cells_of(st):
    return dict((c["id"], c) for c in st["cells"])


class StateTest(unittest.TestCase):

    def test_cells(self):
        st = state.build_state(shop_data())
        c = cells_of(st)
        self.assertTrue(c["COMM@0+8"]["shared"])
        self.assertTrue(c["COMM@8+1"]["shared"])
        self.assertEqual(c["COMM@40+8"]["names"], ["DET-SEL", "LIST-SEL"])
        self.assertFalse(c["COMM@40+8"]["shared"])

    def test_producers_and_reset(self):
        c = cells_of(state.build_state(shop_data()))
        self.assertEqual(c["COMM@0+8"]["origin_producers"], ["SIGN"])
        self.assertEqual(c["COMM@8+1"]["origin_producers"], ["SIGN"])
        self.assertIn("CARD", c["COMM@8+1"]["reset_by"])
        self.assertNotIn("CARD", c["COMM@8+1"]["origin_producers"])

    def test_condition_name_read_recovered(self):
        st = state.build_state(shop_data())
        menu = st["programs"]["MENU"]
        self.assertIn("COMM@8+1", menu["requires"])
        rq = [r for r in menu["requirements"] if r["cell"] == "COMM@8+1"][0]
        self.assertEqual((rq["kind"], rq["producers"], rq["status"]), ("shared", ["SIGN"], "produced"))
        self.assertIn("MENU", cells_of(st)["COMM@8+1"]["consumers"])

    def test_local_requirement_needs_direct_sender(self):
        st = state.build_state(shop_data())
        rq = [r for r in st["programs"]["DETAIL"]["requirements"] if r["cell"] == "COMM@40+8"][0]
        self.assertEqual((rq["kind"], rq["producers"], rq["status"]), ("local", ["LIST"], "produced"))
        edges = [e for e in SHOP_EDGES if e != ("XCTL", "LIST", "DETAIL")]
        finals, raws = shop_programs()
        st2 = state.build_state(assemble(finals, raws, edges=edges))
        rq2 = [r for r in st2["programs"]["DETAIL"]["requirements"] if r["cell"] == "COMM@40+8"][0]
        self.assertEqual((rq2["producers"], rq2["status"]), ([], "unproduced"))

    def test_group_move_is_a_copy(self):
        finals, raws = shop_programs()
        raws["DETAIL"]["statements"].append(stmt(3, "move", "MAIN", from_var="COMM", to=["DFHCOMMAREA"],
                                                 reads=["COMM"], writes=["DFHCOMMAREA"]))
        st = state.build_state(assemble(finals, raws))
        d = st["programs"]["DETAIL"]
        self.assertEqual(d["copies"], [3])
        self.assertEqual(d["requires"], ["COMM@40+8"])

    def test_alias_mismatch_and_partial_overlap(self):
        finals, raws = shop_programs()
        finals["DETAIL"]["data_items"] = shop_items("LIST-SEL")
        finals["DETAIL"]["data_items"][4]["offset"] = 41
        st = state.build_state(assemble(finals, raws))
        self.assertIn("alias_mismatch LIST-SEL", st["warnings"])
        finals, raws = shop_programs()
        extra = shop_items()
        extra.append(item(5, "EXTRA-SEL", 5, 40, 4, 1, parent=1))
        extra[0]["children"].append(5)
        finals["EXTRA"] = final("EXTRA", extra, [xfer(1, "XCTL", ["MENU"])])
        raws["EXTRA"] = rawf("EXTRA", ["MAIN"], [stmt(1, "execCics", "MAIN", exec_text="XCTL")])
        st = state.build_state(assemble(finals, raws))
        c = cells_of(st)
        self.assertIn("COMM@40+4", c)
        self.assertTrue(any(w.startswith("partial_overlap") for w in st["warnings"]))


if __name__ == "__main__":
    unittest.main()
