import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from test_all import build
from app.api import Api
from app.store import Store
from app.pgindex import HybridPolicyKB
from app.core import PolicyDoc

class StorageTests(unittest.TestCase):
    def test_restart_restore_and_token_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/"state.db")
            engine,_=build()
            api=Api(engine,store)
            code,body=api.dispatch("POST","/api/v1/agent/sessions",{}, {}, {})
            sid,token=body["session_id"],body["session_token"]
            path=f"/api/v1/agent/sessions/{sid}/messages"
            headers={"x-session-token":token}
            api.dispatch("POST",path,{},{"text":"我叫小王"},headers)
            api.dispatch("POST",path,{},{"text":"1995年3月"},headers)
            with sqlite3.connect(store.path) as conn:
                payload=conn.execute("SELECT payload FROM sessions").fetchone()[0]
            self.assertNotIn(token,payload)
            self.assertNotIn("我叫小王",payload)
            self.assertNotIn("turns",json.loads(payload))
            engine2,_=build()
            api2=Api(engine2,Store(store.path))
            self.assertEqual(api2.dispatch("POST",path,{},{"text":"住在望京小区"},{})[0],401)
            code,body=api2.dispatch("POST",path,{},{"text":"住在望京小区"},headers)
            self.assertEqual(code,200)
            self.assertEqual(body["progress"]["done"],3)
            self.assertEqual(body["candidate"]["birth_ym"],"1995-03")
    def test_pg_hybrid_cache_and_unknown(self):
        doc=PolicyDoc("d1","BJ","1","测试政策","测试保障说明",["保障"])
        class Index:
            calls=0
            def setup(self,docs): self.docs=docs
            def search(self,q,city):
                self.calls+=1
                return [(doc,.9)] if city=="BJ" else []
        class Cache:
            data={}
            def get(self,k): return self.data.get(k)
            def setex(self,k,ttl,v):
                assert ttl==60
                self.data[k]=v
        index,cache=Index(),Cache()
        kb=HybridPolicyKB([doc],index,cache)
        self.assertEqual(kb.search("保障","BJ")[0][0].id,"d1")
        self.assertEqual(kb.search("保障","BJ")[0][0].id,"d1")
        self.assertEqual(index.calls,1)
        self.assertEqual(kb.search("未知问题","BJ"),[])
        self.assertEqual(kb.search("保障","SH"),[])
        self.assertTrue(all("保障" not in k for k in cache.data))
if __name__=="__main__": unittest.main()
