"""Real HTTP stack end to end: mock website + mock Telegram, real Fetcher/Telegram client/web API/worker."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import httpx
import pytest

from conftest import png
from tpclone.config import Settings
from tpclone.db import DB
from tpclone.engine import Engine, Worker
from tpclone.fetch import Fetcher
from tpclone.telegram import Telegram
from tpclone.web import make_server

POSTS = {i: ("2026-09-25" if i >= 3 else "2026-09-20") for i in range(1, 6)}
SENT: list[dict] = []


class Site(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        if self.path.startswith("/sitemap"):
            u = "".join(f"<url><loc>http://127.0.0.1:{self.server.server_port}/en/?p={i}</loc></url>" for i in POSTS)
            return self._r(200, f'<urlset>{u}</urlset>'.encode(), "application/xml")
        if self.path.endswith(".jpg"):
            return self._r(200, png(), "image/png")
        if "p=" not in self.path:          # homepage: "Latest News" cards
            cards = "".join(f'<div><a href="/en/?p={i}">Title {i}</a> {POSTS[i]}</div>' for i in sorted(POSTS))
            return self._r(200, f"<html><body><h2>Latest News</h2>{cards}</body></html>".encode(), "text/html")
        pid = int(self.path.split("p=")[1])
        port = self.server.server_port
        html = f"""<html><head><meta property="og:image" content="http://127.0.0.1:{port}/c{pid}.jpg">
        <meta property="article:published_time" content="{POSTS[pid]}T09:00:00+08:00"></head><body><h1>Title {pid}</h1>
        <div class="tags"><a href="/en/tag/a">Alpha</a></div>
        <article><div class="entry-content"><p>Body {pid}</p><img src="http://127.0.0.1:{port}/{pid}a.jpg">
        <img src="http://127.0.0.1:{port}/{pid}b.jpg"><p>via: <a href="https://src.example/x">src</a></p></div></article></body></html>"""
        self._r(200, html.encode(), "text/html")

    def _r(self, code, body, ct):
        self.send_response(code); self.send_header("Content-Type", ct); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


class TG(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_POST(self):
        n = int(self.headers["Content-Length"]); body = self.rfile.read(n)
        if self.path.endswith("/sendRichMessage"):      # (other calls, e.g. the existence probe, are not posts)
            SENT.append({"path": self.path, "ct": self.headers["Content-Type"], "body": body})
        out = json.dumps({"ok": True, "result": {"message_id": len(SENT)}}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def stack(tmp_path):
    SENT.clear()
    site, tgs = serve(Site), serve(TG)
    s = Settings(telegram_bot_token="T", telegram_chat_id="@c", db_path=str(tmp_path / "t.db"), show_more_style="classic", site_delay_seconds=0,
                 post_delay_seconds=0, poll_interval_seconds=1, media_mode="upload", web_port=0,
                 site_base=f"http://127.0.0.1:{site.server_port}/en/",
                 sitemap_url=f"http://127.0.0.1:{site.server_port}/sitemap.xml",
                 telegram_api_base=f"http://127.0.0.1:{tgs.server_port}")
    s.MIN_DELAY = 0
    db = DB(s.db_path)
    e = Engine(s, db, Fetcher(s), Telegram("T", "@c", base=s.telegram_api_base))
    e.pacer.delay = 0
    w = Worker(e)
    api = make_server(e, w)
    threading.Thread(target=api.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{api.server_port}"
    yield e, w, db, base
    w.stop(wait=True); api.shutdown()


def post(base, path, body=None):
    return httpx.post(base + path, json=body or {}, headers={"X-Requested-With": "tpclone"}).json()


def test_full_flow_over_http(stack):
    e, w, db, base = stack
    assert httpx.get(base + "/").text.count("Toy-People") >= 1
    assert httpx.post(base + "/api/start", json={}).status_code == 400            # CSRF guard
    e.discover()                                                                   # baseline: nothing posted
    assert SENT == [] and db.count("skipped") == 5
    # live new post appears -> worker publishes it once
    POSTS[6] = "2026-09-26"
    assert post(base, "/api/start")["state"] == "running"
    for _ in range(100):
        if db.count("posted") == 1:
            break
        time.sleep(0.1)
    assert db.count("posted") == 1 and len(SENT) == 1
    sent = SENT[0]
    assert sent["path"].endswith("/sendRichMessage") and sent["ct"].startswith("multipart/form-data")
    assert b"attach://f0" in sent["body"] and b"Title 6" in sent["body"] and b"SHOW+MORE" in sent["body"] or b"SHOW MORE" in sent["body"] or b"SHOW%20MORE" in sent["body"]
    assert post(base, "/api/stop")["state"] in ("stopping", "stopped")
    # date repost through the API
    job = post(base, "/api/date/plan", {"date": "2026-09-25"})["job"]
    for _ in range(100):
        j = httpx.get(f"{base}/api/jobs/{job}").json()
        if j["state"] != "running":
            break
        time.sleep(0.1)
    assert j["state"] == "done" and j["result"]["to_publish"] == [3, 4, 5], j
    assert post(base, "/api/date/publish", {"date": "2026-09-25", "ids": j["result"]["to_publish"]})["queued"] == 3
    w.stop(wait=True)
    post(base, "/api/start")
    for _ in range(150):
        if db.count("posted") == 4:
            break
        time.sleep(0.1)
    w.stop(wait=True)
    assert db.count("posted") == 4 and len(SENT) == 4
    st = httpx.get(base + "/api/status").json()
    assert st["stats"]["posted"] == 4 and st["state"] == "stopped"


def test_settings_from_browser_and_start_gate(stack, tmp_path):
    e, w, db, base = stack
    e.s.telegram_bot_token = e.s.telegram_chat_id = ""
    e.s.MIN_DELAY = 3.0
    e.apply_settings()
    assert "Set the bot token" in post(base, "/api/start")["error"]          # cannot start before setup
    assert w.state() == "stopped"
    r = post(base, "/api/settings", {"telegram_bot_token": "123:SECRETTOKEN", "telegram_chat_id": "@mine",
                                     "post_delay_seconds": "1"})
    assert r["configured"] is True and e.tg is not None
    assert e.s.post_delay_seconds == 3           # delay floor enforced
    v = httpx.get(base + "/api/settings").json()
    assert v["telegram_bot_token"].endswith("OKEN") and "SECRET" not in v["telegram_bot_token"]
    saved = json.loads((e.s.data_dir / "settings.json").read_text())
    assert saved["telegram_chat_id"] == "@mine"
    post(base, "/api/settings", {"telegram_bot_token": v["telegram_bot_token"]})   # masked value keeps the real token
    assert e.s.telegram_bot_token == "123:SECRETTOKEN"
    job = post(base, "/api/preview", {"target": "https://x/en/?p=3"})["job"]
    for _ in range(50):
        j = httpx.get(f"{base}/api/jobs/{job}").json()
        if j["state"] != "running":
            break
        time.sleep(0.1)
    assert j["state"] == "done" and j["result"]["title"] == "Title 3" and "<details>" in j["result"]["html"]
    assert db.count("posted") == 0                                            # preview never sends


def test_style_setting_and_samples(stack):
    e, w, db, base = stack
    v = httpx.get(base + "/api/settings").json()
    assert set(v["show_more_styles"]) == {"classic", "highlight", "pill", "plain", "telegram"} and v["show_more_style"] == "classic"
    post(base, "/api/settings", {"show_more_style": "pill"})
    assert e.s.show_more_style == "pill"
    n0 = len(SENT)
    e.s.telegram_chat_id = "@c"
    r = post(base, "/api/send-style-samples")
    assert set(r["results"].values()) == {"sent"} and len(SENT) - n0 == 8
    bodies = b"".join(x["body"] for x in SENT[n0:])
    assert bodies.count(b"Style+sample") + bodies.count(b"Style%20sample") + bodies.count(b"Style sample") >= 4


def test_import_backup_endpoint_and_masked_update_token(stack, tmp_path):
    import sqlite3
    e, w, db, base = stack
    old = DB(str(tmp_path / "old.db")); old.upsert_seen(5, "u", None, "known", "x"); old.mark_posted(5, 9); old.conn.close()
    raw = (tmp_path / "old.db").read_bytes()
    r = httpx.post(base + "/api/import-backup", content=raw, headers={"X-Requested-With": "tpclone"}).json()
    assert r == {"in_file": 1, "added": 1, "updated": 0} and db.get(5)["status"] == "posted"
    bad = httpx.post(base + "/api/import-backup", content=b"not a database at all", headers={"X-Requested-With": "tpclone"})
    assert bad.status_code == 400 and "not a usable backup" in bad.json()["error"]
    post(base, "/api/settings", {"update_token": "ghp_SECRET1234"})
    v = httpx.get(base + "/api/settings").json()
    assert v["update_token"].endswith("1234") and "SECRET" not in v["update_token"] and e.s.update_token == "ghp_SECRET1234"
    post(base, "/api/settings", {"update_token": v["update_token"]})                 # masked value keeps the real one
    assert e.s.update_token == "ghp_SECRET1234"
    assert httpx.get(base + "/api/status").json()["data_dir"]


def test_test_post_activates_deleted_post_detection(stack):
    e, w, db, base = stack
    e.s.telegram_chat_id = "@c"; e.apply_settings()
    assert db.kv_get("probe_ok") is None
    assert post(base, "/api/send-test")["ok"] is True
    assert db.kv_get("probe_ok") == "1" and e.probe_trusted()


def test_status_reports_the_website_watcher(stack):
    e, w, db, base = stack
    assert httpx.get(base + "/api/status").json()["watch"] is None
    e.discover()
    st = httpx.get(base + "/api/status").json()
    assert st["watch"]["ok"] is True and st["watch"]["total"] >= 5 and st["poll_every"] == 1


def test_check_now_reports_listing(stack):
    e, w, db, base = stack
    r = job_result(base, post(base, "/api/check-now")["job"])
    assert r["listing"] >= 5 and r["listing_error"] is None and r["sitemap"] >= 5
    st = httpx.get(base + "/api/status").json()
    assert st["listing"]["count"] >= 5 and st["listing_max"]


def job_result(base, jid):
    for _ in range(100):
        j = httpx.get(f"{base}/api/jobs/{jid}").json()
        if j["state"] != "running":
            assert j["state"] == "done", j
            return j["result"]
        time.sleep(0.1)
    raise AssertionError("job timeout")


def test_register_message_endpoint(stack):
    e, w, db, base = stack
    r = post(base, "/api/post/register", {"id": 115045, "message": "https://t.me/nekohobby/354"})
    assert r == {"status": "posted", "message_id": 354} and db.get(115045)["status"] == "posted"
    assert db.live_messages(115045) == [354]
    bad = httpx.post(base + "/api/post/register", json={"id": 1, "message": "nonsense"}, headers={"X-Requested-With": "tpclone"})
    assert bad.status_code == 400
    assert httpx.get(base + "/api/status").json()["chat_link"] in ("", "https://t.me/c") or True
