"""External contract assertions, independent of app.contract constants."""
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from test_all import build

class BuyerContractTests(unittest.TestCase):
    def setUp(self):
        self.engine,self.api=build()
    def create(self):
        code,body=self.api.dispatch("POST","/api/v1/agent/sessions",{}, {}, {})
        self.assertEqual(code,201)
        self.assertNotEqual(body["session_id"],body["session_token"])
        return body["session_id"],body["session_token"]
    def message(self,sid,token,text):
        headers={"x-session-token":token} if token is not None else {}
        return self.api.dispatch("POST",f"/api/v1/agent/sessions/{sid}/messages",{},{"text":text},headers)
    def test_credentials_and_cross_session(self):
        sid,token=self.create()
        _,other=self.create()
        self.assertEqual(self.message(sid,None,"我叫小王")[0],401)
        self.assertEqual(self.message(sid,sid,"我叫小王")[0],403)
        self.assertEqual(self.message(sid,other,"我叫小王")[0],403)
        self.assertEqual(self.message(sid,token,"我叫小王")[0],200)
    def test_read_requires_credentials(self):
        sid,token=self.create()
        path=f"/api/v1/agent/sessions/{sid}"
        self.assertEqual(self.api.dispatch("GET",path,{}, {}, {})[0],401)
        self.assertEqual(self.api.dispatch("GET",path,{}, {}, {"x-session-token":sid})[0],403)
        self.assertEqual(self.api.dispatch("GET",path,{}, {}, {"x-session-token":token})[0],200)
    def test_progress_response_for_all_branches(self):
        sid,token=self.create()
        for text in ["我叫小王","1995年3月","住在望京小区","我要全职","我有电动车","明天就能到","跑过半年"]:
            code,body=self.message(sid,token,text)
            self.assertEqual(code,200)
            self.assertTrue({"done","total","fields"} <= body["progress"].keys())
            self.assertIsInstance(body["actions"],list)
        self.assertEqual(body["progress"]["done"],7)
        self.assertEqual(body["candidate"]["status"],"complete")
        sid,token=self.create()
        _,body=self.message(sid,token,"转人工")
        self.assertIn("handoff",body["actions"])
        self.assertTrue({"done","total","fields"} <= body["progress"].keys())
    def test_age_month_boundary_and_terminal(self):
        with patch("app.core.time.localtime",return_value=SimpleNamespace(tm_year=2026,tm_mon=11)):
            for month,expected in [(10,"collecting"),(11,"handoff"),(12,"end_minor")]:
                sid,token=self.create()
                _,body=self.message(sid,token,f"2008年{month}月")
                self.assertEqual(body["status"],expected)
                if expected!="collecting":
                    self.assertEqual(body["quick_replies"],[])
                    self.assertIn(expected,body["actions"])
                    _,after=self.message(sid,token,"我要全职")
                    self.assertEqual(after["status"],expected)
    def test_future_birth_rejected(self):
        with patch("app.core.time.localtime",return_value=SimpleNamespace(tm_year=2026,tm_mon=11)):
            sid,token=self.create()
            _,body=self.message(sid,token,"2026年12月")
            self.assertIsNone(body["candidate"]["birth_ym"])
            self.assertNotEqual(body["status"],"complete")
if __name__=="__main__":
    unittest.main()
