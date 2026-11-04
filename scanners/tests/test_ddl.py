import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from scan_lib import ddl  # noqa: E402


def cob(text, ind=" "):
    return "      " + ind + text


DDL = """CREATE TABLE CARDDEMO.AUTHFRDS
(CARD_NUM              CHAR(16)    NOT NULL,
    AUTH_TS                TIMESTAMP   NOT NULL,
    MERCHANT_NAME          VARCHAR(22)         ,
    TRANSACTION_AMT        DECIMAL(12,2)       ,
    ACCT_ID                DECIMAL(11)         ,
    PRIMARY KEY(CARD_NUM,AUTH_TS )             );
CREATE UNIQUE INDEX CARDDEMO.XAUTHFRD
    ON CARDDEMO.AUTHFRDS
    (CARD_NUM ASC, AUTH_TS DESC)
    COPY YES;
"""

SQL = """SET CURRENT SQLID = 'IBMUSER';
CREATE TABLE IBMUSER.ACCOUNT (
   ACCOUNT_SORTCODE CHAR(6) NOT NULL,
   ACCOUNT_NUMBER CHAR(8) NOT NULL,
   ACCOUNT_AVAILABLE_BALANCE DECIMAL(12, 2)
)
IN CBSA.ACCOUNT NOT VOLATILE
CARDINALITY AUDIT NONE DATA CAPTURE NONE;
CREATE UNIQUE INDEX IBMUSER.ACCTINDX
  ON IBMUSER.ACCOUNT(ACCOUNT_SORTCODE,ACCOUNT_NUMBER)
  USING STOGROUP ACCOUNT;
"""

DCL = [
    cob("******************************************************************", "*"),
    cob("* DCLGEN TABLE(AWSTSSC.AUTHFRDS)                                 *", "*"),
    cob("   EXEC SQL DECLARE CARDDEMO.AUTHFRDS TABLE"),
    cob("   ( CARD_NUM                       CHAR(16) NOT NULL,"),
    cob("     AUTH_TS                        TIMESTAMP NOT NULL,"),
    cob("     MERCHANT_NAME                  VARCHAR(22),"),
    cob("     ACCT_ID                        DECIMAL(11, 0)"),
    cob("   ) END-EXEC."),
    cob("******************************************************************", "*"),
    cob("01  DCLAUTHFRDS."),
    cob("    10 CARD-NUM             PIC X(16)."),
    cob("    10 AUTH-TS              PIC X(26)."),
    cob("    10 MERCHANT-NAME."),
    cob("       49 MERCHANT-NAME-LEN  PIC S9(4) USAGE COMP."),
    cob("       49 MERCHANT-NAME-TEXT PIC X(22)."),
    cob("    10 ACCT-ID              PIC S9(11)V USAGE COMP-3."),
]


class DdlTest(unittest.TestCase):

    def test_ddl(self):
        b = ddl.parse_sql(ddl.strip_comments(DDL))
        self.assertEqual(len(b["tables"]), 1)
        t = b["tables"][0]
        self.assertEqual((t["qualified"], t["schema"], t["name"]), ("CARDDEMO.AUTHFRDS", "CARDDEMO", "AUTHFRDS"))
        self.assertEqual(len(t["columns"]), 5)
        c = {x["name"]: x for x in t["columns"]}
        self.assertEqual((c["CARD_NUM"]["type"], c["CARD_NUM"]["length"], c["CARD_NUM"]["nullable"]),
                         ("CHAR", 16, False))
        self.assertEqual((c["AUTH_TS"]["type"], c["AUTH_TS"]["length"]), ("TIMESTAMP", None))
        self.assertEqual((c["MERCHANT_NAME"]["type"], c["MERCHANT_NAME"]["length"],
                          c["MERCHANT_NAME"]["nullable"]), ("VARCHAR", 22, True))
        self.assertEqual((c["TRANSACTION_AMT"]["type"], c["TRANSACTION_AMT"]["length"],
                          c["TRANSACTION_AMT"]["scale"]), ("DECIMAL", 12, 2))
        self.assertEqual((c["ACCT_ID"]["length"], c["ACCT_ID"]["scale"]), (11, None))
        self.assertEqual(t["primary_key"], ["CARD_NUM", "AUTH_TS"])
        self.assertEqual(len(b["indexes"]), 1)
        i = b["indexes"][0]
        self.assertEqual((i["name"], i["unique"], i["table"]), ("CARDDEMO.XAUTHFRD", True, "CARDDEMO.AUTHFRDS"))
        self.assertEqual(i["columns"], [{"name": "CARD_NUM", "order": "ASC"}, {"name": "AUTH_TS", "order": "DESC"}])

    def test_inline_sql(self):
        b = ddl.parse_sql(ddl.strip_comments(SQL))
        self.assertEqual(len(b["tables"]), 1)
        t = b["tables"][0]
        self.assertEqual(t["qualified"], "IBMUSER.ACCOUNT")
        self.assertEqual(t["tablespace"], "CBSA.ACCOUNT")
        self.assertEqual(len(t["columns"]), 3)
        self.assertEqual(t["columns"][2]["scale"], 2)
        self.assertEqual(len(b["indexes"]), 1)
        self.assertEqual(b["indexes"][0]["name"], "IBMUSER.ACCTINDX")
        self.assertEqual(len(b["indexes"][0]["columns"]), 2)

    def test_other_and_dml(self):
        b = ddl.parse_sql("CREATE DATABASE CBSA BUFFERPOOL BP1;\nINSERT INTO T1 VALUES (1);\n"
                          "DELETE FROM T3 WHERE K IN (SELECT K FROM T4);\nDROP TABLE T9;\n"
                          "ALTER TABLE T1 ADD COLUMN X INT;")
        self.assertEqual(b["other"][0]["kind"], "DATABASE")
        self.assertEqual(b["other"][0]["name"], "CBSA")
        self.assertEqual(b["dml"][0]["tables"], [{"name": "T1", "op": "insert"}])
        self.assertEqual(b["dml"][1]["tables"], [{"name": "T3", "op": "delete"}, {"name": "T4", "op": "read"}])
        self.assertEqual(b["drops"][0]["name"], "T9")
        self.assertEqual(b["alters"][0]["table"], "T1")

    def test_comments_and_lines(self):
        t = "-- comment\n/* block\n comment */\nCREATE TABLE A (X INT);\n"
        s = ddl.split_statements(ddl.strip_comments(t))
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0][1], 4)

    def test_dclgen(self):
        b = ddl.parse_dclgen(DCL)
        self.assertEqual(len(b["tables"]), 1)
        t = b["tables"][0]
        self.assertEqual(t["qualified"], "CARDDEMO.AUTHFRDS")
        self.assertEqual(len(t["columns"]), 4)
        hs = t["host_structure"]
        self.assertEqual(hs["name"], "DCLAUTHFRDS")
        f = {x["name"]: x for x in hs["fields"]}
        self.assertEqual(f["CARD-NUM"]["pic"], "X(16)")
        self.assertEqual((f["ACCT-ID"]["pic"], f["ACCT-ID"]["usage"]), ("S9(11)V", "COMP-3"))
        hv = {c["name"]: c["host_var"] for c in t["columns"]}
        self.assertEqual(hv, {"CARD_NUM": "CARD-NUM", "AUTH_TS": "AUTH-TS", "MERCHANT_NAME": "MERCHANT-NAME",
                              "ACCT_ID": "ACCT-ID"})


if __name__ == "__main__":
    unittest.main()
