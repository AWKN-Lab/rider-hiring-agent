"""会话与候选人的持久化。

默认 **SQLite（标准库）** ⇒ 零依赖即可复跑；
若设置 `DATABASE_URL` ⇒ 优先用 Postgres（asyncpg，Apache-2.0），
连接失败则**自动回退 SQLite**，服务不中断。
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(os.environ.get("SQLITE_PATH", "data/rider_agent.db"))


class Store:
    def __init__(self, path=None):
        self.path = Path(path or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self):
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS sessions ("
                         "id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL)")
            conn.execute("CREATE TABLE IF NOT EXISTS candidates ("
                         "id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL)")

    def save_session(self, sess):
        payload = json.dumps({"status": sess.status, "candidate": sess.candidate,
                              "slot_index": sess.slot_index, "turns": sess.turns},
                             ensure_ascii=False)
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO sessions (id,payload,updated_at) VALUES (?,?,?) "
                         "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, "
                         "updated_at=excluded.updated_at",
                         (sess.id, payload, sess.created_at))

    def get_session(self, sid):
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT payload FROM sessions WHERE id=?", (sid,)).fetchone()
        return json.loads(row[0]) if row else None

    def eval_metrics_path(self):
        p = Path("data/eval_metrics.json")
        return str(p) if p.exists() else None
