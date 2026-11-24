"""Session persistence. Postgres is mandatory when DATABASE_URL is configured."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from .core import Session

DEFAULT_DB = Path(os.environ.get("SQLITE_PATH", "data/rider_agent.db"))

def snapshot(sess):
    # Never persist original dialogue text or cleartext session credentials.
    return {"created_at": sess.created_at,
            "token_hash": sess.session_token_hash or hashlib.sha256(sess.session_token.encode()).hexdigest(),
            "status": sess.status, "candidate": sess.candidate,
            "slot_index": sess.slot_index, "handoff_reason": sess.handoff_reason,
            "model_calls": sess.model_calls}

def restore(sid, payload):
    return Session(id=sid, created_at=payload["created_at"], session_token="",
                   session_token_hash=payload["token_hash"],
                   candidate=payload["candidate"], status=payload["status"],
                   slot_index=payload["slot_index"],
                   handoff_reason=payload.get("handoff_reason"),
                   model_calls=payload.get("model_calls", []))

class Store:
    backend = "sqlite"
    def __init__(self, path=None):
        self.path = Path(path or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL)")
    def save_session(self, sess):
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO sessions VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at",
                         (sess.id, json.dumps(snapshot(sess), ensure_ascii=False), sess.created_at))
    def get_session(self, sid):
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT payload FROM sessions WHERE id=?", (sid,)).fetchone()
        return restore(sid, json.loads(row[0])) if row else None
    def ping(self):
        with sqlite3.connect(self.path) as conn:
            return conn.execute("SELECT 1").fetchone()[0] == 1
    def eval_metrics_path(self):
        p = Path("data/eval_metrics.json")
        return str(p) if p.exists() else None

class PostgresStore(Store):
    backend = "postgresql"
    def __init__(self, dsn):
        self.dsn = dsn
        self._run("execute", "CREATE TABLE IF NOT EXISTS agent_sessions (id UUID PRIMARY KEY, payload JSONB NOT NULL, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())")
    def _run(self, method, sql, *args):
        async def query():
            import asyncpg
            conn = await asyncpg.connect(self.dsn, timeout=5, command_timeout=10)
            try:
                return await getattr(conn, method)(sql, *args)
            finally:
                await conn.close()
        return asyncio.run(query())
    def save_session(self, sess):
        import uuid
        self._run("execute", "INSERT INTO agent_sessions (id,payload) VALUES ($1,$2::jsonb) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=now()",
                  uuid.UUID(sess.id), json.dumps(snapshot(sess), ensure_ascii=False))
    def get_session(self, sid):
        import uuid
        try:
            ident = uuid.UUID(sid)
        except ValueError:
            return None
        row = self._run("fetchval", "SELECT payload FROM agent_sessions WHERE id=$1", ident)
        return restore(sid, json.loads(row)) if row else None
    def ping(self):
        return self._run("fetchval", "SELECT 1") == 1

def build_store():
    dsn = os.environ.get("DATABASE_URL")
    return PostgresStore(dsn) if dsn else Store()
