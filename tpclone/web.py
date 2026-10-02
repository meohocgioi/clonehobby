"""Tiny dashboard + JSON API (stdlib only). Binds to localhost unless WEB_HOST/WEB_TOKEN are set."""
from __future__ import annotations

import hmac
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import tpclone
from . import render, updater
from .config import UI_FIELDS, _coerce, save_ui_settings
from .engine import Engine, Worker
from .telegram import TelegramError

DATE_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Jobs:
    """Background jobs (a date scan can take minutes) polled by the UI."""

    def __init__(self):
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def run(self, fn) -> str:
        jid = uuid.uuid4().hex[:10]
        self.jobs[jid] = {"state": "running", "progress": "starting", "result": None, "error": None}

        def target():
            try:
                res = fn(lambda m: self.jobs[jid].__setitem__("progress", m))
                self.jobs[jid].update(state="done", result=res)
            except Exception as e:
                self.jobs[jid].update(state="error", error=f"{type(e).__name__}: {e}")

        threading.Thread(target=target, daemon=True).start()
        return jid


def make_server(engine: Engine, worker: Worker, restart=None) -> ThreadingHTTPServer:
    s = engine.s
    jobs = Jobs()
    update_lock = threading.Lock()
    page = Path(__file__).with_name("dashboard.html").read_text(encoding="utf8")

    def status() -> dict:
        db = engine.db
        nxt = engine.pacer.next_allowed_at()
        return {
            "state": worker.state(), "error": worker.error, "stats": db.stats(),
            "pending": db.pending_count(), "delay": s.effective_delay,
            "next_post_in": max(0, int(nxt - time.time())) if db.pending_count() else None,
            "last_posted": db.last_posted(), "dry_run": s.dry_run,
            "events": db.recent_events(40),
            "uncertain": db.by_status("uncertain", 50), "failed": db.by_status("failed", 50),
            "chat": s.telegram_chat_id, "configured": s.telegram_ready,
            "last_backup": float(db.kv_get("last_backup_ts", "0") or 0) or None,
            "watch": db.kv_json("discover_status"), "listing": db.kv_json("listing_info"), "listing_max": db.kv_get("listing_max_id"), "poll_every": s.poll_interval_seconds, "data_dir": str(s.data_dir.resolve()), "probe": db.kv_get("probe_ok"), "version": tpclone.code_version(), "code_dir": tpclone.__path__[0], "update": db.kv_json("update_info"),
        }

    def settings_view() -> dict:
        out = {k: getattr(s, k) for k in UI_FIELDS}
        t = s.telegram_bot_token
        out["telegram_bot_token"] = ("••••••" + t[-4:]) if t else ""
        u = s.update_token
        out["update_token"] = ("••••••" + u[-4:]) if u else ""
        out["configured"] = s.telegram_ready
        out["show_more_styles"] = render.SHOW_MORE_STYLES
        return out

    def save_settings(body: dict) -> dict:
        changes = {}
        for k in UI_FIELDS:
            if k not in body:
                continue
            v = body[k]
            if k in ("telegram_bot_token", "update_token") and str(v).startswith("•"):
                continue                                   # unchanged (masked) token
            if k == "telegram_bot_token" and not str(v).strip():
                continue
            changes[k] = _coerce(getattr(s, k), v)
        if "post_delay_seconds" in changes and changes["post_delay_seconds"] < s.MIN_DELAY:
            changes["post_delay_seconds"] = s.MIN_DELAY
        for k, v in changes.items():
            setattr(s, k, v)
        save_ui_settings(s, changes)
        engine.apply_settings()
        res = {"saved": True, "configured": s.telegram_ready}
        if engine.tg:
            try:
                res["telegram"] = engine.tg.check()
            except Exception as e:  # noqa: BLE001
                res["telegram_error"] = str(e)
        return res

    def preview(target: str, prog) -> dict:
        m = re.search(r"(\d+)\s*$", target.strip())
        if not m:
            raise ValueError("enter a post number or a link like https://www.toy-people.com/en/?p=114949")
        prog("downloading the article")
        art = engine.fetch_article(int(m.group(1)))
        plan = render.plan_media(art, s.max_media)
        html = render.build_html(art, s, plan, lambda k: k)
        d = art.to_dict()
        d.update(tags_line=render.tags_line(art.tags, s.hashtag_style), hashtag=s.hashtag_style in ('hashtag', 'true', '1'), show_more_style=s.show_more_style, show_more_effective=render.effective_style(s.show_more_style, art, plan),
                 show_more_emoji=s.show_more_emoji, show_more_label=s.show_more_label,
                 slots_used=plan.slots_used, overflow=len(plan.overflow), html=html, max_media=s.max_media)
        return d

    class H(BaseHTTPRequestHandler):
        server_version = "tpclone"

        def log_message(self, *a):  # quiet
            pass

        def _auth(self) -> bool:
            if not s.web_token:
                return True
            tok = self.headers.get("X-Token") or parse_qs(urlparse(self.path).query).get("token", [""])[0]
            ck = self.headers.get("Cookie", "")
            m = re.search(r"tpt=([^;]+)", ck)
            tok = tok or (m.group(1) if m else "")
            return hmac.compare_digest(tok, s.web_token)

        def _send(self, code: int, body: bytes, ctype="application/json", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode())

        def _body(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n) or b"{}") if n else {}

        def _import_backup(self):
            import sqlite3
            import tempfile
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= 300 * 1024 * 1024:
                return self._json({"error": "file is empty or too large"}, 400)
            with tempfile.TemporaryDirectory() as td:
                f = Path(td) / "upload.db"
                f.write_bytes(self.rfile.read(n))
                try:
                    res = engine.db.merge_posted_from(str(f))
                except (sqlite3.DatabaseError, ValueError) as e:
                    return self._json({"error": f"that is not a usable backup file: {e}"}, 400)
            engine.db.log("info", f"imported posted-list from a backup file: {res['added']} added, {res['updated']} corrected")
            self._json(res)

        def do_GET(self):
            if not self._auth():
                return self._json({"error": "unauthorized"}, 401)
            u = urlparse(self.path)
            if u.path == "/":
                extra = {"Set-Cookie": f"tpt={s.web_token}; HttpOnly; SameSite=Strict; Path=/"} if s.web_token else {}
                return self._send(200, page.encode(), "text/html; charset=utf-8", extra)
            if u.path == "/api/status":
                return self._json(status())
            if u.path == "/api/settings":
                return self._json(settings_view())
            if u.path == "/api/backup":      # fresh consistent copy for the user to keep somewhere safe
                import tempfile
                from pathlib import Path
                with tempfile.TemporaryDirectory() as td:
                    dest = Path(td) / "backup.db"
                    engine.db.backup_to(str(dest))
                    data = dest.read_bytes()
                name = time.strftime("tpclone-backup-%Y-%m-%d.db")
                return self._send(200, data, "application/octet-stream",
                                  {"Content-Disposition": f'attachment; filename="{name}"'})
            if u.path.startswith("/api/jobs/"):
                j = jobs.jobs.get(u.path.rsplit("/", 1)[1])
                return self._json(j or {"error": "no such job"}, 200 if j else 404)
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            if not self._auth():
                return self._json({"error": "unauthorized"}, 401)
            if self.headers.get("X-Requested-With") != "tpclone":   # CSRF guard for the cookie-auth case
                return self._json({"error": "missing X-Requested-With"}, 400)
            path = urlparse(self.path).path
            if path == "/api/import-backup":          # raw file upload (an old tpclone .db backup)
                return self._import_backup()
            body = self._body()
            try:
                if path == "/api/settings":
                    return self._json(save_settings(body))
                if path == "/api/preview":
                    jid = jobs.run(lambda prog: preview(str(body.get("target", "")), prog))
                    return self._json({"job": jid})
                if path == "/api/send-style-samples":
                    if not engine.tg:
                        return self._json({"error": "Set the bot token and channel first (Settings)."}, 400)
                    results = {}
                    for key, desc in render.SHOW_MORE_STYLES.items():
                        if key == "auto":       # picks one of the others per post; no sample of its own
                            continue
                        if key == "telegram":      # no toggle of ours: needs a LONG post to see Telegram's own button
                            body = "".join(f"<p>Sample paragraph {i}: this is filler text to make the post long, so you can "
                                           f"see whether Telegram folds it behind its own green “Show more” button.</p>"
                                           for i in range(1, 31))
                            html = f"<h6>Style sample: {key} (long post)</h6>{body}"
                        else:
                            html = (f"<h6>Style sample: {key}</h6>"
                                    f"<details>{render.summary_html(s.show_more_label, key, s.show_more_emoji)}"
                                    f"<p><i>This is the expanded text. If you read this, the style “{key}” works.</i></p></details>")
                        try:
                            res = engine.tg.send_rich(html)
                            engine._calibrate_probe(res.get("message_id"))
                            results[key] = "sent"
                        except Exception as e:  # noqa: BLE001
                            results[key] = f"Telegram refused it: {e}"
                        time.sleep(min(3, s.effective_delay))
                    return self._json({"results": results})
                if path == "/api/send-test":
                    if not engine.tg:
                        return self._json({"error": "Set the bot token and channel first (Settings)."}, 400)
                    try:
                        res = engine.tg.send_rich("<h6>Test post</h6><details><summary>Show More</summary>"
                                                  "<p><i>If you can open this, rich messages work in your channel.</i></p></details>")
                        engine._calibrate_probe(res.get("message_id"))   # also switches on deleted-post detection
                    except TelegramError as e:
                        return self._json({"error": str(e)}, 400)
                    return self._json({"ok": True})
                if path == "/api/update/check":
                    def do_check(prog):
                        prog("looking for a newer version")
                        info = updater.check(s)
                        engine.db.kv_set("update_info", json.dumps(info))
                        engine.db.kv_set("last_update_check", time.time())
                        return info
                    return self._json({"job": jobs.run(do_check)})
                if path == "/api/update/apply":
                    if restart is None:
                        return self._json({"error": "this app cannot restart itself"}, 400)
                    if not update_lock.acquire(blocking=False):
                        return self._json({"error": "an update is already running"}, 409)

                    def do_apply(prog):
                        try:
                            res = updater.apply(s, prog)
                            engine.db.kv_set("update_info", json.dumps({"available": False, "remote": res["version"],
                                                                         "local": res["version"], "changed": []}))
                            engine.db.log("info", f"updated to version {res['version']} - restarting")
                            threading.Timer(1.5, restart).start()     # let this answer reach the browser first
                            return {**res, "restarting": True}
                        finally:
                            update_lock.release()
                    return self._json({"job": jobs.run(do_apply)})
                if path == "/api/check-now":
                    def do_check_now(prog):
                        prog("checking the website")
                        n = engine.discover()
                        info = engine.db.kv_json("listing_info") or {}
                        st = engine.db.kv_json("discover_status") or {}
                        return {"new": n, "listing": info.get("count", 0), "listing_error": info.get("error"),
                                "sitemap": st.get("total", 0), "newest": engine.db.kv_get("listing_max_id")}
                    return self._json({"job": jobs.run(do_check_now)})
                if path == "/api/post-now":
                    pid, force = int(body["id"]), bool(body.get("force"))
                    jid = jobs.run(lambda prog: engine.post_now(pid, force))
                    return self._json({"job": jid})
                if path == "/api/verify":
                    jid = jobs.run(lambda prog: engine.verify_posted(progress=prog))
                    return self._json({"job": jid})
                if path == "/api/start":
                    if not s.telegram_ready and not s.dry_run:
                        return self._json({"error": "Set the bot token and channel first (Settings)."}, 400)
                    worker.start()
                    return self._json(status())
                if path == "/api/stop":
                    worker.stop()
                    return self._json(status())
                if path == "/api/date/plan":
                    d = body.get("date", "")
                    if not DATE_RX.match(d):
                        return self._json({"error": "date must be YYYY-MM-DD"}, 400)
                    jid = jobs.run(lambda prog: engine.plan_date(d, progress=prog))
                    return self._json({"job": jid})
                if path == "/api/date/publish":
                    d = body.get("date", "")
                    if not DATE_RX.match(d):
                        return self._json({"error": "date must be YYYY-MM-DD"}, 400)
                    ids = [int(x) for x in body.get("ids", [])]
                    n = engine.enqueue_date(d, ids)
                    return self._json({"queued": n, "worker": worker.state()})
                if path == "/api/post/resolve":   # uncertain / failed rows
                    pid, action = int(body["id"]), body["action"]
                    if action == "posted":
                        engine.db.mark_posted_import(pid)
                    elif action == "retry":
                        engine.db.reset_status(pid, "pending")
                    elif action == "skip":
                        engine.db.reset_status(pid, "skipped")
                    else:
                        return self._json({"error": "bad action"}, 400)
                    return self._json({"ok": True})
            except Exception as e:
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            self._json({"error": "not found"}, 404)

    return ThreadingHTTPServer((s.web_host, s.web_port), H)
