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
CREATE TABLE IF NOT EXISTS outlet_posts (       -- the same post on Facebook / Instagram / X (after Telegram)
    post_id    INTEGER NOT NULL,
    outlet     TEXT NOT NULL,                   -- facebook | instagram | x
    status     TEXT NOT NULL DEFAULT 'pending', -- pending | sending | posted | failed | uncertain | skipped
    attempts   INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    not_before REAL NOT NULL DEFAULT 0,
    remote_id  TEXT,                            -- id of the post on that network
    link       TEXT,                            -- address of the post on that network
    payload    TEXT,                            -- the post as sent to Telegram (JSON), so it is not fetched again
    created_at REAL, posted_at REAL, flagged_at REAL,
    PRIMARY KEY (post_id, outlet)
);
CREATE INDEX IF NOT EXISTS idx_outlet_status ON outlet_posts(outlet, status, not_before, created_at);
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
            for col in ("uncertain_anchor INTEGER", "uncertain_at REAL", "uncertain_tried REAL", "flagged_at REAL",
                        "uncertain_from REAL"):
                try:   # ledgers created before the automatic resolution of uncertain deliveries
                    self.conn.execute(f"ALTER TABLE posts ADD COLUMN {col}")
                except sqlite3.OperationalError:
                    pass
            # 'today' counts on the dashboard
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts(posted_at)")
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

    def pending_breakdown(self) -> tuple[int, int, float | None]:
        """(ready to post now, waiting for a retry time, earliest retry time) of the queued posts."""
        now = time.time()
        r = self._q("SELECT SUM(not_before<=?) ready, SUM(not_before>?) waiting, MIN(CASE WHEN not_before>? "
                    "THEN not_before END) nxt FROM posts WHERE status='pending'", (now, now, now))[0]
        return int(r["ready"] or 0), int(r["waiting"] or 0), r["nxt"]

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
            self.conn.execute("UPDATE posts SET status=?, attempts=?, last_error=?, not_before=?, "
                              "flagged_at=CASE WHEN ?='failed' THEN ? ELSE flagged_at END WHERE post_id=?",
                              (status, attempts, error[:500], time.time() + delay, status, time.time(), post_id))
            self.conn.commit()
            return status

    def mark_uncertain(self, post_id: int, error: str, anchor: int | None = None, started: float | None = None,
                       ended: float | None = None) -> None:
        """anchor = highest channel message number known when the send began. Only set for 'did it arrive?' cases; the
        app then settles them by itself (see Engine.resolve_uncertain_step). started / ended = when that send began and
        when it broke off (uncertain_from / uncertain_at)."""
        now = time.time()
        has = anchor is not None
        self._x("UPDATE posts SET status='uncertain', last_error=?, uncertain_anchor=?, uncertain_at=?, uncertain_from=?, "
                "uncertain_tried=NULL, flagged_at=? WHERE post_id=?",
                (error[:500], anchor, (ended or now) if has else None, started if has else None, now, post_id))

    def max_message_id(self) -> int:
        r = self._q("SELECT MAX(message_id) m FROM sent_messages")
        return int(r[0]["m"] or 0)

    def known_message_ids(self, above: int = 0) -> set[int]:
        return {r["message_id"] for r in self._q("SELECT message_id FROM sent_messages WHERE message_id>?", (above,))}

    def last_message_before(self, ts: float) -> int:
        """Highest message number written down at or before `ts` (0 = none)."""
        r = self._q("SELECT MAX(message_id) m FROM sent_messages WHERE COALESCE(sent_at, 0) <= ?", (ts,))
        return int(r[0]["m"] or 0)

    def first_message_after(self, ts: float, above: int) -> int | None:
        """Lowest message number above `above` written down after `ts` (None = none yet)."""
        r = self._q("SELECT MIN(message_id) m FROM sent_messages WHERE sent_at > ? AND message_id > ?", (ts, above))
        return r[0]["m"]

    def delivery_uncertain(self) -> list[dict]:
        """Posts whose send may or may not have arrived (oldest first)."""
        return [dict(r) for r in self._q("SELECT * FROM posts WHERE status='uncertain' AND uncertain_anchor IS NOT NULL "
                                         "ORDER BY uncertain_at, post_id")]

    def touch_uncertain_tried(self, post_id: int) -> None:
        self._x("UPDATE posts SET uncertain_tried=? WHERE post_id=?", (time.time(), post_id))

    def resolve_uncertain_stale(self) -> int:
        """Called at startup: a 'sending' row means the process died mid-request."""
        cur = self._x("UPDATE posts SET status='uncertain', last_error='process stopped while sending', flagged_at=? "
                      "WHERE status='sending'", (time.time(),))
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

    def unqueued_scanned_since(self, since_ts: float, cutoff_date: str | None, require_date: bool = False) -> list[int]:
        """Posts that a manual date check found AFTER the watcher's previous poll, which nobody has queued or posted yet.
        The watcher treats every row it already holds as 'seen', so without this they would be skipped forever."""
        q = ("SELECT post_id FROM posts p WHERE status='known' AND source='date-scan' AND posted_at IS NULL "
             "AND COALESCE(discovered_at, 0) >= ? "
             "AND NOT EXISTS (SELECT 1 FROM sent_messages m WHERE m.post_id=p.post_id)")
        args: list = [since_ts]
        if cutoff_date:
            q += " AND post_date >= ?" if require_date else " AND (post_date IS NULL OR post_date >= ?)"
            args.append(cutoff_date)
        elif require_date:
            q += " AND post_date IS NOT NULL"
        return [r["post_id"] for r in self._q(q + " ORDER BY post_id", args)]

    def by_date(self, date: str) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM posts WHERE post_date=? ORDER BY post_id", (date,))]

    def by_status(self, status: str, limit: int = 100) -> list[dict]:
        return [dict(r) for r in self._q("SELECT * FROM posts WHERE status=? ORDER BY post_id DESC LIMIT ?",
                                         (status, limit))]

    def recent_posts(self, n: int = 30) -> list[dict]:
        return [dict(r) for r in self._q(
            "SELECT post_id, url, title, status, source, tg_message_id, last_error, discovered_at, posted_at FROM posts "
            "ORDER BY discovered_at DESC, post_id DESC LIMIT ?", (n,))]

    def title_index(self) -> dict[int, str]:
        return {r["post_id"]: r["title"] for r in self._q("SELECT post_id,title FROM posts WHERE title IS NOT NULL")}

    def stats(self) -> dict[str, int]:
        out = {r["status"]: r["c"] for r in self._q("SELECT status, COUNT(*) c FROM posts GROUP BY status")}
        out["total"] = sum(out.values())
        return out

    def last_posted(self) -> dict | None:
        r = self._q("SELECT * FROM posts WHERE status='posted' ORDER BY posted_at DESC LIMIT 1")
        return dict(r[0]) if r else None

    def today_counts(self, since: float) -> dict[str, int]:
        """The dashboard's 'Today' chart: posts the app published since `since` (the viewer's midnight) and posts that
        ran into trouble since then and still need a decision. Posts only marked as posted by hand are not counted."""
        posted = self._q("SELECT COUNT(*) c FROM posts WHERE status='posted' AND posted_at>=? "
                         "AND COALESCE(source,'') NOT IN ('import','registered')", (since,))[0]["c"]
        bad = {r["status"]: r["c"] for r in self._q(
            "SELECT status, COUNT(*) c FROM posts WHERE status IN ('failed','uncertain') AND flagged_at>=? "
            "GROUP BY status", (since,))}
        return {"posted": posted, "failed": bad.get("failed", 0), "uncertain": bad.get("uncertain", 0)}

    def posts_in_last_hour(self) -> int:
        return self._q("SELECT COUNT(*) c FROM posts WHERE status='posted' AND source!='import' AND posted_at>?",
                       (time.time() - 3600,))[0]["c"]

    # ---- Facebook / Instagram / X copies ------------------------------
    def outlet_queue(self, post_id: int, outlets: Iterable[str], payload: str | None) -> list[str]:
        """Queue a just-published post for the other networks. A post is never queued twice for the same network."""
        now, added = time.time(), []
        with self.lock:
            for o in outlets:
                cur = self.conn.execute("INSERT OR IGNORE INTO outlet_posts(post_id,outlet,payload,created_at) "
                                        "VALUES(?,?,?,?)", (post_id, o, payload, now))
                if cur.rowcount:
                    added.append(o)
            self.conn.commit()
        return added

    def outlet_get(self, post_id: int, outlet: str) -> dict | None:
        r = self._q("SELECT * FROM outlet_posts WHERE post_id=? AND outlet=?", (post_id, outlet))
        return dict(r[0]) if r else None

    def outlet_next(self, outlet: str) -> dict | None:
        r = self._q("SELECT * FROM outlet_posts WHERE outlet=? AND status='pending' AND not_before<=? "
                    "ORDER BY created_at, post_id LIMIT 1", (outlet, time.time()))
        return dict(r[0]) if r else None

    def outlet_set(self, post_id: int, outlet: str, status: str, error: str | None = None, **cols) -> None:
        """Change the state of one copy. failed / uncertain get a time stamp for 'Needs your attention'."""
        sets, args = ["status=?", "last_error=?"], [status, (error or "")[:500] or None]
        if status in ("failed", "uncertain"):
            sets.append("flagged_at=?"); args.append(time.time())
        if status == "posted":
            sets.append("posted_at=?"); args.append(time.time())
        for k, v in cols.items():
            if k not in ("attempts", "not_before", "remote_id", "link", "created_at"):
                raise ValueError(k)
            sets.append(f"{k}=?"); args.append(v)
        self._x(f"UPDATE outlet_posts SET {', '.join(sets)} WHERE post_id=? AND outlet=?", args + [post_id, outlet])

    def outlet_stale_sending(self) -> int:
        """At startup: a copy left 'sending' means the app stopped while the last request was on its way."""
        cur = self._x("UPDATE outlet_posts SET status='uncertain', flagged_at=?, last_error=? WHERE status='sending'",
                      (time.time(), "the app stopped while this was being posted - it may or may not be there"))
        return cur.rowcount

    def outlet_expire(self, outlet: str, older_than: float, note: str) -> int:
        cur = self._x("UPDATE outlet_posts SET status='skipped', last_error=? WHERE outlet=? AND status='pending' "
                      "AND created_at<?", (note, outlet, older_than))
        return cur.rowcount

    def outlet_summary(self, since: float) -> dict[str, dict]:
        """Per network: how many copies are waiting / need a decision / were posted today, and the newest one posted."""
        out: dict[str, dict] = {}
        now = time.time()
        for r in self._q("SELECT outlet, status, COUNT(*) c, SUM(not_before>?) later FROM outlet_posts "
                         "GROUP BY outlet, status", (now,)):
            d = out.setdefault(r["outlet"], {"pending": 0, "waiting": 0, "posted": 0, "failed": 0, "uncertain": 0,
                                             "skipped": 0, "sending": 0, "today": 0, "last": None})
            d[r["status"]] = d.get(r["status"], 0) + r["c"]
            if r["status"] == "pending":
                d["waiting"] = int(r["later"] or 0)
        for r in self._q("SELECT outlet, COUNT(*) c FROM outlet_posts WHERE status='posted' AND posted_at>=? "
                         "GROUP BY outlet", (since,)):
            out[r["outlet"]]["today"] = r["c"]
        for o, d in out.items():
            r = self._q("SELECT o.post_id, o.link, o.posted_at, p.title FROM outlet_posts o LEFT JOIN posts p "
                        "ON p.post_id=o.post_id WHERE o.outlet=? AND o.status='posted' ORDER BY o.posted_at DESC LIMIT 1", (o,))
            d["last"] = dict(r[0]) if r else None
        return out

    def outlet_attention(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self._q(
            "SELECT o.post_id, o.outlet, o.status, o.last_error, o.flagged_at, o.attempts, p.title, p.url "
            "FROM outlet_posts o LEFT JOIN posts p ON p.post_id=o.post_id WHERE o.status IN ('failed','uncertain') "
            "ORDER BY o.flagged_at DESC LIMIT ?", (limit,))]

    # ---- json kv convenience -------------------------------------------
    def kv_json(self, key: str, default: Any = None) -> Any:
        v = self.kv_get(key)
        return json.loads(v) if v else default
