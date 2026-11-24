"""PostgreSQL pgvector hybrid retrieval. Fail visibly on configured backend failure."""
from __future__ import annotations
import asyncio
import hashlib
import json
from .core import PolicyDoc, PolicyKB

DDL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS agent_policy_doc (
 id TEXT PRIMARY KEY, city TEXT NOT NULL, version TEXT NOT NULL,
 title TEXT NOT NULL, body TEXT NOT NULL, keywords JSONB NOT NULL,
 embedding vector(256) NOT NULL
);
"""
def vector(text):
    return "[" + ",".join(str(x) for x in PolicyKB._embed_dense(text)) + "]"

class PgPolicyIndex:
    def __init__(self, dsn):
        self.dsn = dsn
    def run(self, fn):
        async def work():
            import asyncpg
            conn = await asyncpg.connect(self.dsn, timeout=5, command_timeout=10)
            try:
                return await fn(conn)
            finally:
                await conn.close()
        return asyncio.run(work())
    def setup(self, docs):
        async def work(conn):
            async with conn.transaction():
                await conn.execute(DDL)
                for d in docs:
                    await conn.execute(
                        """INSERT INTO agent_policy_doc VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::vector)
                        ON CONFLICT(id) DO UPDATE SET city=excluded.city,version=excluded.version,
                        title=excluded.title,body=excluded.body,keywords=excluded.keywords,embedding=excluded.embedding""",
                        d.id,d.city,d.version,d.title,d.text,json.dumps(d.keywords),vector(d.text+" "+" ".join(d.keywords)))
        self.run(work)
    def search(self, query, city):
        async def work(conn):
            rows = await conn.fetch(
                """SELECT id,city,version,title,body,keywords,1-(embedding <=> $1::vector) AS similarity
                   FROM agent_policy_doc WHERE ($2::text IS NULL OR city=$2 OR city='ALL')""",
                vector(query),city)
            return [(PolicyDoc(r["id"],r["city"],r["version"],r["title"],r["body"],json.loads(r["keywords"])),r["similarity"]) for r in rows]
        return self.run(work)
    def ping(self):
        async def work(conn):
            return await conn.fetchval("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')")
        return self.run(work)

class HybridPolicyKB(PolicyKB):
    def __init__(self, docs, index, cache):
        super().__init__(docs)
        self.index, self.cache = index, cache
        self.cache_namespace = hashlib.sha256(json.dumps([d.__dict__ for d in docs],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.index.setup(docs)
    def search(self, query, city=None, top_k=3):
        key = "agent:policy:v1:"+self.cache_namespace+":"+hashlib.sha256(json.dumps([query,city,top_k],ensure_ascii=False).encode()).hexdigest()
        cached = self.cache.get(key) if self.cache is not None else None
        if cached is not None:
            return [(PolicyDoc(**doc),score) for doc,score in json.loads(cached)]
        scored=[]
        for doc,similarity in self.index.search(query,city):
            # Unknown policy requests must not pass on hash collisions alone.
            kw=self._keyword_score(query,doc)
            if kw <= 0:
                continue
            score=round(0.65*kw+0.35*max(0.0,similarity or 0.0),4)
            scored.append((doc,score))
        scored.sort(key=lambda x:(-x[1],x[0].id))
        out=scored[:top_k]
        if self.cache is not None:
            self.cache.setex(key,60,json.dumps([(d.__dict__,s) for d,s in out],ensure_ascii=False))
        return out
