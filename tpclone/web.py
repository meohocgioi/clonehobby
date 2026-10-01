"""Tiny dashboard + JSON API (stdlib only). Binds to localhost unless WEB_HOST/WEB_TOKEN are set."""
from __future__ import annotations

import hmac
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import parse_qs, urlparse

from .engine import Engine, Worker

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


def make_server(engine: Engine, worker: Worker) -> ThreadingHTTPServer:
    s = engine.s
    jobs = Jobs()
    page = resources.files("tpclone").joinpath("dashboard.html").read_text(encoding="utf8")

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
            "chat": s.telegram_chat_id,
        }

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

        def do_GET(self):
            if not self._auth():
                return self._json({"error": "unauthorized"}, 401)
            u = urlparse(self.path)
            if u.path == "/":
                extra = {"Set-Cookie": f"tpt={s.web_token}; HttpOnly; SameSite=Strict; Path=/"} if s.web_token else {}
                return self._send(200, page.encode(), "text/html; charset=utf-8", extra)
            if u.path == "/api/status":
                return self._json(status())
            if u.path.startswith("/api/jobs/"):
                j = jobs.jobs.get(u.path.rsplit("/", 1)[1])
                return self._json(j or {"error": "no such job"}, 200 if j else 404)
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            if not self._auth():
                return self._json({"error": "unauthorized"}, 401)
            if self.headers.get("X-Requested-With") != "tpclone":   # CSRF guard for the cookie-auth case
                return self._json({"error": "missing X-Requested-With"}, 400)
            path, body = urlparse(self.path).path, self._body()
            try:
                if path == "/api/start":
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
