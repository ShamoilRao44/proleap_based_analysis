import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from facts_lib import cics  # noqa: E402


class CicsTest(unittest.TestCase):

    def test_xctl_literal(self):
        p = cics.parse("EXEC CICS XCTL PROGRAM('COSGN00C') COMMAREA(CARDDEMO-COMMAREA) END-EXEC")
        self.assertEqual(p["command"], "XCTL")
        self.assertEqual(p["options"]["PROGRAM"], {"literal": "COSGN00C"})
        self.assertEqual(p["options"]["COMMAREA"]["var"], "CARDDEMO-COMMAREA")

    def test_return_transid_space(self):
        p = cics.parse("EXEC CICS RETURN TRANSID (WS-TRANID) COMMAREA (CARDDEMO-COMMAREA) END-EXEC")
        self.assertEqual(p["command"], "RETURN")
        self.assertEqual(p["options"]["TRANSID"]["var"], "WS-TRANID")
        r = cics.interpret(p)
        self.assertEqual(r["transfers"][0]["kind"], "RETURN_TRANSID")
        self.assertEqual(r["transfers"][0]["commarea"], "CARDDEMO-COMMAREA")

    def test_send_map(self):
        p = cics.parse("EXEC CICS SEND MAP('COMEN1A') MAPSET('COMEN01') FROM(COMEN1AO) ERASE END-EXEC")
        self.assertEqual(p["command"], "SEND MAP")
        self.assertEqual(p["options"]["MAP"], {"literal": "COMEN1A"})
        self.assertEqual(p["options"]["ERASE"], {"flag": True})
        self.assertEqual(p["options"]["FROM"]["var"], "COMEN1AO")
        r = cics.interpret(p)
        self.assertEqual(r["resources"][0]["kind"], "map")
        self.assertEqual(r["resources"][0]["op"], "send")
        self.assertEqual(r["resources"][0]["mapset"], {"literal": "COMEN01"})

    def test_read(self):
        p = cics.parse("EXEC CICS READ DATASET (WS-USRSEC-FILE) INTO (SEC-USER-DATA) "
                       "RIDFLD (WS-USER-ID) RESP (WS-RESP-CD) END-EXEC")
        r = cics.interpret(p)
        self.assertEqual(r["resources"][0]["kind"], "cics_file")
        self.assertEqual(r["resources"][0]["op"], "read")
        self.assertIn("SEC-USER-DATA", r["writes"])
        self.assertIn("WS-RESP-CD", r["writes"])
        self.assertIn("WS-USER-ID", r["reads"])
        self.assertNotIn("WS-USRSEC-FILE", r["reads"])
        self.assertEqual([e["kind"] for e in r["error_handling"]], ["RESP_CHECK"])

    def test_nested_parens(self):
        p = cics.parse("EXEC CICS XCTL PROGRAM(CDEMO-MENU-OPT-PGMNAME(WS-OPTION)) END-EXEC")
        o = p["options"]["PROGRAM"]
        self.assertEqual(o["var"], "CDEMO-MENU-OPT-PGMNAME")
        self.assertEqual(o["text"], "CDEMO-MENU-OPT-PGMNAME(WS-OPTION)")

    def test_split_merged_blocks(self):
        # ProLeap merges consecutive EXEC blocks into one statement
        cmds = cics.split_commands("EXEC CICS SYNCPOINT END-EXEC EXEC CICS XCTL PROGRAM (CDEMO-TO-PROGRAM) "
                                   "COMMAREA(CARDDEMO-COMMAREA) END-EXEC")
        self.assertEqual(len(cmds), 2)
        self.assertEqual(cics.parse(cmds[0])["command"], "SYNCPOINT")
        self.assertEqual(cics.parse(cmds[1])["command"], "XCTL")
        self.assertEqual(cics.parse(cmds[1])["options"]["PROGRAM"]["var"], "CDEMO-TO-PROGRAM")

    def test_handle_condition(self):
        p = cics.parse("EXEC CICS HANDLE CONDITION NOTFND(9000-NOTFND) ERROR(9999-ERR) END-EXEC")
        self.assertEqual(p["command"], "HANDLE CONDITION")
        r = cics.interpret(p)
        self.assertEqual(r["labels"], ["9000-NOTFND", "9999-ERR"])


if __name__ == "__main__":
    unittest.main()
