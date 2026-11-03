"""PostgreSQL 16 + pgvector 的政策向量索引（**可选路径**，有则用、无则回退）。

许可：驱动用 **asyncpg（Apache-2.0）**；不引入 GPL/LGPL 依赖（契约硬要求）。
回退策略：任何异常 ⇒ 退回进程内向量索引，**服务不中断**。
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

DDL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS policy_doc (
    id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    version TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    keywords TEXT NOT NULL DEFAULT '',
    embedding vector(256) NOT NULL
);
CREATE INDEX IF NOT EXISTS policy_doc_embedding_idx
    ON policy_doc USING hnsw (embedding vector_cosine_ops);
"""


class PgPolicyIndex:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self._conn = None
        self.enabled = False
        self.error: Optional[str] = None

    def setup(self, docs) -> bool:
        """建表 + 写入文档；成功则 enabled=True。"""
        try:
            async def _run():
                import asyncpg
                conn = await asyncpg.connect(self.dsn)
                await conn.execute(DDL)
                for d in docs:
                    vec = "[" + ",".join(str(x) for x in self._dense(d)) + "]"
                    await conn.execute(
                        "INSERT INTO policy_doc (id, city, version, title, body, keywords, embedding) "
                        "VALUES ($1,$2,$3,$4,$5,$6,$7::vector) "
                        "ON CONFLICT (id) DO UPDATE SET embedding = EXCLUDED.embedding",
                        d.id, d.city, d.version, d.title, d.text, " ".join(d.keywords), vec)
                return conn
            self._conn = asyncio.run(_run())
            self.enabled = True
            return True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return False

    def search(self, query: str, city: Optional[str], top_k: int = 3):
        """pgvector 余弦检索（关键词侧由调用方合并）。失败则抛异常，由上层回退。"""
        import asyncpg
        vec = "[" + ",".join(str(x) for x in self._dense(query)) + "]"

        async def _run():
            rows = await self._conn.fetch(
                "SELECT id, city, version, title, body, keywords, "
                "1 - (embedding <=> $1::vector) AS score "
                "FROM policy_doc WHERE ($2::text IS NULL OR city = $2 OR city = 'ALL') "
                "ORDER BY embedding <=> $1::vector LIMIT $3",
                vec, city, top_k)
            return [dict(r) for r in rows]

        return asyncio.run(_run())

    def close(self):
        if self._conn is not None:
            try:
                asyncio.run(self._conn.close())
            except Exception:
                pass
