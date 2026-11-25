"""Conversation history in SQLite. Conversations belong to an anonymous browser id."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, owner TEXT NOT NULL, title TEXT NOT NULL, mode TEXT NOT NULL, book TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL, content TEXT NOT NULL, sources TEXT, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_conv_owner ON conversations(owner, updated_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class History:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    def create(self, owner: str, title: str, mode: str, book: str | None) -> str:
        cid = uuid.uuid4().hex[:12]
        with self.lock:
            self.db.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?,?)", (cid, owner, title[:80], mode, book, _now(), _now()))
            self.db.commit()
        return cid

    def get(self, owner: str, cid: str):
        return self.db.execute("SELECT * FROM conversations WHERE id=? AND owner=?", (cid, owner)).fetchone()

    def add(self, cid: str, role: str, content: str, sources: list | None = None):
        with self.lock:
            self.db.execute("INSERT INTO messages (conversation_id, role, content, sources, created_at) VALUES (?,?,?,?,?)",
                            (cid, role, content, json.dumps(sources) if sources is not None else None, _now()))
            self.db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (_now(), cid))
            self.db.commit()

    def messages(self, cid: str) -> list[dict]:
        rows = self.db.execute("SELECT role, content, sources, created_at FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
        return [{"role": r["role"], "content": r["content"], "sources": json.loads(r["sources"]) if r["sources"] else None,
                 "created_at": r["created_at"]} for r in rows]

    def list(self, owner: str, q: str | None = None) -> list[dict]:
        sql = "SELECT c.* FROM conversations c WHERE owner=?"
        args: list = [owner]
        if q:  # search titles and message text
            sql += " AND (c.title LIKE ? OR EXISTS (SELECT 1 FROM messages m WHERE m.conversation_id=c.id AND m.content LIKE ?))"
            args += [f"%{q}%", f"%{q}%"]
        rows = self.db.execute(sql + " ORDER BY updated_at DESC LIMIT 100", args)
        return [dict(r) for r in rows]

    def rename(self, owner: str, cid: str, title: str) -> bool:
        with self.lock:
            cur = self.db.execute("UPDATE conversations SET title=? WHERE id=? AND owner=?", (title[:80], cid, owner))
            self.db.commit()
        return cur.rowcount > 0

    def delete(self, owner: str, cid: str) -> bool:
        with self.lock:
            cur = self.db.execute("DELETE FROM conversations WHERE id=? AND owner=?", (cid, owner))
            self.db.commit()
        return cur.rowcount > 0
