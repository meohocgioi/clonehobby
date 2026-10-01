"""SQLite ledger: which posts exist on the site, which were published, and the work queue.

Status values
  known      seen on the site, nothing queued (default for posts discovered while browsing dates)
  skipped    seen at first start / flood-guard; NOT posted, but can be posted via date repost
  pending    queued for publishing
  sending    a send is in flight (left over after a crash => treated as 'uncertain' on restart)
  posted     published to Telegram (never queued again)
  failed     gave up after repeated errors; can be retried manually
  uncertain  the request may or may not have reached Telegram; needs a human decision
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    post_id       INTEGER PRIMARY KEY,
    url           TEXT NOT NULL,
    title         TEXT,
    post_date     TEXT,            -- YYYY-MM-DD in SITE_TZ
    lastmod       TEXT,
    status        TEXT NOT NULL DEFAULT 'known',
    priority      INTEGER NOT NULL DEFAULT 0,   -- lower = sooner (0 = live new post, 1 = date repost)
    source        TEXT,
    tg_message_id INTEGER,
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    not_before    REAL NOT NULL DEFAULT 0,
    discovered_at REAL,
    posted_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status, priority, post_date, post_id);
CREATE INDEX IF NOT EXISTS idx_posts_date ON posts(post_date);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, level TEXT, message TEXT
);
"""


class DB:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            if path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")  # a crash must not forget a published post
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ---- helpers -------------------------------------------------------
    def _x(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.lock:
            cur = self.conn.execute(sql, tuple(args))
            self.conn.commit()
            return cur

    def _q(self, sql: str, args: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(args)).fetchall()

    # ---- kv ------------------------------------------------------------
    def kv_get(self, key: str, default: str | None = None) -> str | None:
        r = self._q("SELECT value FROM kv WHERE key=?", (key,))
        return r[0]["value"] if r else default

    def kv_set(self, key: str, value: Any) -> None:
        self._x("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, str(value)))

    # ---- events --------------------------------------------------------
    def log(self, level: str, message: str) -> None:
        self._x("INSERT INTO events(ts,level,message) VALUES(?,?,?)", (time.time(), level, message))
        self._x("DELETE FROM events WHERE id < (SELECT MAX(id) FROM events) - 500")

    def recent_events(self, n: int = 80) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM events ORDER BY id DESC LIMIT ?", (n,))]

    # ---- posts ---------------------------------------------------------
    def get(self, post_id: int) -> dict | None:
        r = self._q("SELECT * FROM posts WHERE post_id=?", (post_id,))
        return dict(r[0]) if r else None

    def known_ids(self) -> set[int]:
        return {r["post_id"] for r in self._q("SELECT post_id FROM posts")}

    def count(self, status: str | None = None) -> int:
        if status:
            return self._q("SELECT COUNT(*) c FROM posts WHERE status=?", (status,))[0]["c"]
        return self._q("SELECT COUNT(*) c FROM posts")[0]["c"]

    def upsert_seen(self, post_id: int, url: str, lastmod: str | None, status: str,
                    source: str, priority: int = 0) -> bool:
        """Insert a never-seen post. Existing rows are never downgraded. Returns True if inserted."""
        with self.lock:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO posts(post_id,url,lastmod,status,source,priority,discovered_at) "
                "VALUES(?,?,?,?,?,?,?)", (post_id, url, lastmod, status, source, priority, time.time()))
            self.conn.commit()
            return cur.rowcount == 1

    def bulk_seen(self, rows: list[tuple[int, str, str | None]], status: str, source: str, priority: int = 0) -> int:
        """Insert many never-seen posts in one transaction (existing rows untouched). Returns inserted count."""
        now = time.time()
        with self.lock:
            before = self.conn.total_changes
            self.conn.executemany(
                "INSERT OR IGNORE INTO posts(post_id,url,lastmod,status,source,priority,discovered_at) "
                "VALUES(?,?,?,?,?,?,?)", [(i, u, lm, status, source, priority, now) for i, u, lm in rows])
            self.conn.commit()
            return self.conn.total_changes - before

    def defer(self, post_id: int, error: str, seconds: float) -> None:
        """Put a post back in the queue without counting it as a failed attempt (site/Telegram trouble)."""
        self._x("UPDATE posts SET status='pending', last_error=?, not_before=? WHERE post_id=?",
                (error[:500], time.time() + seconds, post_id))

    def set_meta(self, post_id: int, title: str | None, post_date: str | None) -> None:
        self._x("UPDATE posts SET title=COALESCE(?,title), post_date=COALESCE(?,post_date) WHERE post_id=?",
                (title, post_date, post_id))

    def enqueue(self, post_id: int, priority: int, source: str) -> bool:
        """Queue a post unless it is already published / in flight. Returns True if it was (re)queued."""
        with self.lock:
            cur = self.conn.execute(
                "UPDATE posts SET status='pending', priority=?, source=?, attempts=0, last_error=NULL, not_before=0 "
                "WHERE post_id=? AND status IN ('known','skipped','failed','pending')",
                (priority, source, post_id))
            self.conn.commit()
            return cur.rowcount == 1

    def next_pending(self) -> dict | None:
        r = self._q("SELECT * FROM posts WHERE status='pending' AND not_before<=? "
                    "ORDER BY priority, COALESCE(post_date,'9999'), post_id LIMIT 1", (time.time(),))
        return dict(r[0]) if r else None

    def pending_count(self) -> int:
        return self.count("pending")

    def mark_sending(self, post_id: int) -> bool:
        cur = self._x("UPDATE posts SET status='sending' WHERE post_id=? AND status='pending'", (post_id,))
        return cur.rowcount == 1

    def mark_posted(self, post_id: int, message_id: int | None) -> None:
        self._x("UPDATE posts SET status='posted', tg_message_id=?, posted_at=?, last_error=NULL WHERE post_id=?",
                (message_id, time.time(), post_id))

    def mark_posted_import(self, post_id: int) -> None:
        self._x("UPDATE posts SET status='posted', posted_at=COALESCE(posted_at,?), source='import' "
                "WHERE post_id=? AND status!='posted'", (time.time(), post_id))

    def mark_retry(self, post_id: int, error: str, delay: float, give_up_after: int = 6) -> str:
        with self.lock:
            row = self.conn.execute("SELECT attempts FROM posts WHERE post_id=?", (post_id,)).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            status = "failed" if attempts >= give_up_after else "pending"
            self.conn.execute("UPDATE posts SET status=?, attempts=?, last_error=?, not_before=? WHERE post_id=?",
                              (status, attempts, error[:500], time.time() + delay, post_id))
            self.conn.commit()
            return status

    def mark_uncertain(self, post_id: int, error: str) -> None:
        self._x("UPDATE posts SET status='uncertain', last_error=? WHERE post_id=?", (error[:500], post_id))

    def resolve_uncertain_stale(self) -> int:
        """Called at startup: a 'sending' row means the process died mid-request."""
        cur = self._x("UPDATE posts SET status='uncertain', last_error='process stopped while sending' "
                      "WHERE status='sending'")
        return cur.rowcount

    def reset_status(self, post_id: int, status: str) -> None:
        self._x("UPDATE posts SET status=?, last_error=NULL, attempts=0, not_before=0 WHERE post_id=?",
                (status, post_id))

    def by_date(self, date: str) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM posts WHERE post_date=? ORDER BY post_id", (date,))]

    def by_status(self, status: str, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM posts WHERE status=? ORDER BY post_id DESC LIMIT ?",
                                         (status, limit))]

    def title_index(self) -> dict[int, str]:
        return {r["post_id"]: r["title"] for r in self._q("SELECT post_id,title FROM posts WHERE title IS NOT NULL")}

    def stats(self) -> dict[str, int]:
        out = {r["status"]: r["c"] for r in self._q("SELECT status, COUNT(*) c FROM posts GROUP BY status")}
        out["total"] = sum(out.values())
        return out

    def last_posted(self) -> dict | None:
        r = self._q("SELECT * FROM posts WHERE status='posted' ORDER BY posted_at DESC LIMIT 1")
        return dict(r[0]) if r else None

    def posts_in_last_hour(self) -> int:
        return self._q("SELECT COUNT(*) c FROM posts WHERE status='posted' AND source!='import' AND posted_at>?",
                       (time.time() - 3600,))[0]["c"]

    # ---- json kv convenience -------------------------------------------
    def kv_json(self, key: str, default: Any = None) -> Any:
        v = self.kv_get(key)
        return json.loads(v) if v else default
