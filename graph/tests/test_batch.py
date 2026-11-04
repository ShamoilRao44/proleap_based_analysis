import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tests.helpers import build, cobol, data, dd, edge, has, jcl_file, step  # noqa: E402


class BatchTest(unittest.TestCase):

    def test_main_scenario(self):
        cb = cobol("CBTRN02C", kind="batch_main", files_io=[
            {"select": "A", "dd": "TRANFILE", "access_summary": "write"},
            {"select": "B", "dd": "DALYREJS", "access_summary": "write"},
            {"select": "C", "dd": "XREFFILE", "access_summary": "read"}])
        s = step(1, "S1", "CBTRN02C", dds=[dd("TRANFILE", "AWS.TRAN"), dd("DALYREJS", "AWS.REJ", "create", generation="+1")])
        g, r = build(data(cobol=[cb], jcl=[jcl_file("J", [s])]))
        self.assertTrue(has(g, "JOB_STEP", "job:J", "step:J#1"))
        self.assertTrue(has(g, "STEP_RUNS", "step:J#1", "program:CBTRN02C"))
        self.assertEqual(edge(g, "STEP_DATASET", "step:J#1", "dataset:AWS.TRAN")["access"], "write")
        self.assertEqual(edge(g, "PROGRAM_DATASET", "program:CBTRN02C", "dataset:AWS.TRAN")["access"], "write")
        self.assertIs(g.get("dataset:AWS.REJ")["attrs"]["gdg"], True)
        miss = [u for u in r.unresolved if u["kind"] == "dd_missing"]
        self.assertEqual(len(miss), 1)
        self.assertEqual(miss[0]["dd"], "XREFFILE")

    def test_idcams(self):
        cmds = [{"verb": "DEFINE", "subtype": "CLUSTER", "name": "AWS.K", "names": ["AWS.K"], "attrs": {},
                 "text": "", "line": 5},
                {"verb": "DELETE", "subtype": "CLUSTER", "object_type": "CLUSTER", "name": "AWS.K",
                 "names": ["AWS.K"], "attrs": {}, "text": "", "line": 3},
                {"verb": "DEFINE", "subtype": "AIX", "name": "AWS.K.AIX", "names": ["AWS.K.AIX"],
                 "attrs": {"RELATE": "AWS.K"}, "text": "", "line": 7}]
        s = step(1, "S1", "IDCAMS", utility_data={"idcams_commands": cmds})
        g, _ = build(data(jcl=[jcl_file("J", [s])]))
        self.assertEqual(edge(g, "IDCAMS_DEFINE", "step:J#1", "dataset:AWS.K")["access"], "write")
        self.assertEqual(edge(g, "IDCAMS_DELETE", "step:J#1", "dataset:AWS.K")["access"], "delete")
        self.assertTrue(has(g, "DATASET_RELATE", "dataset:AWS.K.AIX", "dataset:AWS.K"))

    def test_temp_dataset(self):
        s = step(1, "S1", "SORT", dds=[dd("SORTOUT", "&&TEMP", "create", temp=True)])
        g, _ = build(data(jcl=[jcl_file("J", [s])]))
        self.assertIsNotNone(g.get("dataset:&&TEMP@J"))
        self.assertTrue(has(g, "STEP_DATASET", "step:J#1", "dataset:&&TEMP@J"))

    def test_control_card(self):
        s = step(1, "S1", "IDCAMS", dds=[dd("SYSIN", "AWS.CNTL", member="REPROCT")])
        k = {"name": "REPROCT", "path": "ctl/REPROCT.ctl", "kind": "idcams"}
        g, _ = build(data(jcl=[jcl_file("J", [s])], control=[k]))
        self.assertTrue(has(g, "STEP_CONTROL_CARD", "step:J#1", "control_card:REPROCT"))

    def test_sdsf(self):
        s = step(1, "S1", "SDSF", utility_data={"sdsf_commands": [
            {"resource_type": "FILE", "resource": "ACCTDAT", "action": "CLOSE", "region": "R"}]})
        g, _ = build(data(jcl=[jcl_file("J", [s])]))
        e = edge(g, "JOB_CICS_COMMAND", "job:J", "cics_file:ACCTDAT")
        self.assertEqual(e["details"][0]["action"], "CLOSE")

    def test_psb(self):
        s = step(1, "S1", "DFSRRC00",
                 invokes=[{"program": "PAUTB01", "psb": "PSBX", "via": "DFSRRC00 PARM"}])
        g, _ = build(data(jcl=[jcl_file("J", [s])]))
        self.assertTrue(has(g, "STEP_RUNS", "step:J#1", "program:PAUTB01"))
        self.assertTrue(has(g, "STEP_PSB", "step:J#1", "psb:PSBX"))
        self.assertTrue(has(g, "PROGRAM_PSB", "program:PAUTB01", "psb:PSBX"))

    def test_proc_edges_and_not_found(self):
        s1 = step(1, "S1.PRC001", "IDCAMS")
        s2 = step(2, "S2", None, kind="proc")
        s2["proc"] = "MISSING"
        s2["proc_found"] = False
        proc = {"name": "REPROC", "path": "p.prc", "declared_name": "REPROC", "kind": "proc"}
        j = jcl_file("J", [s1, s2], procs_used=[{"name": "REPROC", "found": True}])
        g, r = build(data(jcl=[j], proc=[proc]))
        self.assertTrue(has(g, "JOB_USES_PROC", "job:J", "proc:REPROC"))
        self.assertEqual([u["kind"] for u in r.unresolved], ["proc_not_found"])


if __name__ == "__main__":
    unittest.main()
