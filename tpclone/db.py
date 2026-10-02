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
CREATE TABLE IF NOT EXISTS sent_messages (      -- every channel message ever sent for a post (a post can have several)
    post_id INTEGER NOT NULL, message_id INTEGER NOT NULL, sent_at REAL, deleted_at REAL, verified_at REAL,
    PRIMARY KEY (post_id, message_id)
);
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
            try:   # ledgers created before 'verified_at' existed
                self.conn.execute("ALTER TABLE sent_messages ADD COLUMN verified_at REAL")
            except sqlite3.OperationalError:
                pass
            # ledgers from before this table existed: carry over the one message they knew about
            self.conn.execute("INSERT OR IGNORE INTO sent_messages(post_id,message_id,sent_at) "
                              "SELECT post_id, tg_message_id, COALESCE(posted_at, 0) FROM posts "
                              "WHERE tg_message_id IS NOT NULL AND status='posted'")
            self.conn.commit()

    def backup_to(self, dest: str) -> None:
        """Consistent copy of the whole ledger (safe while the app is running)."""
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        tmp = str(dest) + ".part"
        with self.lock:
            out = sqlite3.connect(tmp)
            try:
                self.conn.backup(out)
            finally:
                out.close()
        Path(tmp).replace(dest)

    def merge_posted_from(self, path: str) -> dict:
        """Import the 'already posted' knowledge from another ledger file (old backup / old folder).
        Only ever ADDS: nothing already known here is deleted or downgraded."""
        src = sqlite3.connect(path)
        src.row_factory = sqlite3.Row
        try:
            if not src.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='posts'").fetchone():
                raise ValueError("this file is not a tpclone backup (no posts table)")
            rows = src.execute("SELECT * FROM posts WHERE status='posted'").fetchall()
        finally:
            pass
        added = updated = 0
        with self.lock:
            for r in rows:
                cur = self.conn.execute("SELECT status FROM posts WHERE post_id=?", (r["post_id"],)).fetchone()
                if cur is None:
                    self.conn.execute(
                        "INSERT INTO posts(post_id,url,title,post_date,lastmod,status,priority,source,tg_message_id,"
                        "attempts,discovered_at,posted_at) VALUES(?,?,?,?,?,'posted',?,?,?,0,?,?)",
                        (r["post_id"], r["url"], r["title"], r["post_date"], r["lastmod"], r["priority"], "restored",
                         r["tg_message_id"], r["discovered_at"], r["posted_at"]))
                    added += 1
                    if r["tg_message_id"]:
                        self.conn.execute("INSERT OR IGNORE INTO sent_messages(post_id,message_id,sent_at) VALUES(?,?,?)",
                                          (r["post_id"], r["tg_message_id"], r["posted_at"] or 0))
                elif cur["status"] != "posted":
                    self.conn.execute("UPDATE posts SET status='posted', tg_message_id=?, posted_at=?, "
                                      "title=COALESCE(title,?), post_date=COALESCE(post_date,?), last_error=NULL "
                                      "WHERE post_id=?", (r["tg_message_id"], r["posted_at"], r["title"],
                                                          r["post_date"], r["post_id"]))
                    updated += 1
                    if r["tg_message_id"]:
                        self.conn.execute("INSERT OR IGNORE INTO sent_messages(post_id,message_id,sent_at) VALUES(?,?,?)",
                                          (r["post_id"], r["tg_message_id"], r["posted_at"] or 0))
            self.conn.commit()
        src.close()
        return {"in_file": len(rows), "added": added, "updated": updated}

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
        if message_id:
            self.add_message(post_id, message_id)

    # ---- every message ever sent for a post ----------------------------
    def add_message(self, post_id: int, message_id: int) -> None:
        now = time.time()      # a message we have just sent certainly exists: count that as a verification
        self._x("INSERT INTO sent_messages(post_id,message_id,sent_at,verified_at) VALUES(?,?,?,?) "
                "ON CONFLICT(post_id,message_id) DO UPDATE SET deleted_at=NULL, verified_at=excluded.verified_at",
                (post_id, message_id, now, now))

    def touch_verified(self, post_id: int, message_id: int) -> None:
        self._x("UPDATE sent_messages SET verified_at=? WHERE post_id=? AND message_id=?", (time.time(), post_id, message_id))

    def verified_age(self, post_id: int, message_id: int) -> float | None:
        r = self._q("SELECT verified_at FROM sent_messages WHERE post_id=? AND message_id=?", (post_id, message_id))
        return (time.time() - r[0]["verified_at"]) if r and r[0]["verified_at"] else None

    def stalest_message(self, older_than: float, newer_than_days: float = 7) -> tuple[int, int] | None:
        """The live message of a posted post that was verified longest ago (or never), if older than `older_than` s."""
        now = time.time()
        r = self._q(
            "SELECT m.post_id, m.message_id FROM sent_messages m JOIN posts p ON p.post_id=m.post_id "
            "WHERE m.deleted_at IS NULL AND p.status='posted' AND COALESCE(p.posted_at, 0) > ? "
            "AND COALESCE(m.verified_at, 0) < ? ORDER BY COALESCE(m.verified_at, 0) LIMIT 1",
            (now - newer_than_days * 86400, now - older_than))
        return (r[0]["post_id"], r[0]["message_id"]) if r else None

    def live_messages(self, post_id: int) -> list[int]:
        """Messages we believe are still in the channel (not yet proven deleted)."""
        return [r["message_id"] for r in self._q(
            "SELECT message_id FROM sent_messages WHERE post_id=? AND deleted_at IS NULL ORDER BY message_id", (post_id,))]

    def all_messages(self, post_id: int) -> list[dict]:
        return [dict(r) for r in self._q(
            "SELECT message_id, sent_at, deleted_at FROM sent_messages WHERE post_id=? ORDER BY message_id", (post_id,))]

    def mark_message_deleted(self, post_id: int, message_id: int) -> None:
        self._x("UPDATE sent_messages SET deleted_at=? WHERE post_id=? AND message_id=?",
                (time.time(), post_id, message_id))

    def messages_by_post(self, ids: Iterable[int]) -> dict[int, list[dict]]:
        ids = list(ids)
        out: dict[int, list[dict]] = {i: [] for i in ids}
        if ids:
            q = ",".join("?" * len(ids))
            for r in self._q(f"SELECT post_id, message_id, deleted_at FROM sent_messages WHERE post_id IN ({q}) "
                             f"ORDER BY message_id", ids):
                out[r["post_id"]].append({"message_id": r["message_id"], "deleted": r["deleted_at"] is not None})
        return out

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

    def mark_deleted(self, post_id: int) -> None:
        """The channel message is gone: make the post publishable again (it is no longer 'posted')."""
        self._x("UPDATE posts SET status='known', tg_message_id=NULL, posted_at=NULL, attempts=0, not_before=0, "
                "last_error='deleted from the channel' WHERE post_id=?", (post_id,))

    def posted_with_message(self, ids: Iterable[int] | None = None, limit: int = 300) -> list[dict]:
        if ids is not None:
            ids = list(ids)
            if not ids:
                return []
            q = ",".join("?" * len(ids))
            return [dict(r) for r in self._q(
                f"SELECT * FROM posts WHERE status='posted' AND tg_message_id IS NOT NULL AND post_id IN ({q})", ids)]
        return [dict(r) for r in self._q(
            "SELECT * FROM posts WHERE status='posted' AND tg_message_id IS NOT NULL "
            "ORDER BY posted_at DESC LIMIT ?", (limit,))]

    def unqueued_scanned_since(self, since_ts: float, cutoff_date: str | None) -> list[int]:
        """Posts that a manual date check found AFTER the watcher's previous poll, which nobody has queued or posted yet.
        The watcher treats every row it already holds as 'seen', so without this they would be skipped forever."""
        q = ("SELECT post_id FROM posts p WHERE status='known' AND source='date-scan' AND posted_at IS NULL "
             "AND COALESCE(discovered_at, 0) >= ? "
             "AND NOT EXISTS (SELECT 1 FROM sent_messages m WHERE m.post_id=p.post_id)")
        args: list = [since_ts]
        if cutoff_date:
            q += " AND (post_date IS NULL OR post_date >= ?)"
            args.append(cutoff_date)
        return [r["post_id"] for r in self._q(q + " ORDER BY post_id", args)]

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
