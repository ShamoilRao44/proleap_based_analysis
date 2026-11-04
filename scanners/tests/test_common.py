import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scan_lib import common  # noqa: E402


class CommonTest(unittest.TestCase):

    def test_split_top(self):
        self.assertEqual(len(common.split_top("DISP=(NEW,CATLG,DELETE),UNIT=SYSDA,DCB=(RECFM=F,LRECL=430)")), 3)
        self.assertEqual(common.split_top("A,'B,C',D"), ["A", "'B,C'", "D"])
        self.assertEqual(common.split_top("(,CATLG)"), ["(,CATLG)"])
        self.assertEqual(common.split_top(""), [])

    def test_sub_params(self):
        self.assertEqual(common.sub_params("(,CATLG)"), ["", "CATLG"])
        self.assertEqual(common.sub_params("SHR"), ["SHR"])

    def test_take_operand_field(self):
        self.assertEqual(common.take_operand_field("DISP=SHR, comment text"), "DISP=SHR,")
        self.assertEqual(common.take_operand_field("PARM='A B',X=1 rest"), "PARM='A B',X=1")

    def test_parse_params(self):
        self.assertEqual(common.parse_params("PGM=IDCAMS,REGION=0M,'TEXT'"),
                         [("PGM", "IDCAMS"), ("REGION", "0M"), (None, "'TEXT'")])

    def test_paren_args(self):
        self.assertEqual(common.paren_args("DSNAME01(&HLQ..LOADLIB) GROUP(X) ATOMIC"),
                         [("DSNAME01", "&HLQ..LOADLIB"), ("GROUP", "X"), ("ATOMIC", None)])

    def test_unquote(self):
        self.assertEqual(common.unquote("'A''B'"), "A'B")
        self.assertEqual(common.unquote(" X "), "X")


if __name__ == "__main__":
    unittest.main()
