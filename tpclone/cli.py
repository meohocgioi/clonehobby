from __future__ import annotations

import argparse
import json
import logging
import re
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

import httpx

from . import reconcile, render
from .config import Settings, load_settings
from .db import DB
from .engine import Engine, Worker
from .fetch import Fetcher
from .site import parse_article, load_selectors
from .telegram import Telegram, TelegramError
from .web import make_server


def build(s: Settings, need_tg: bool = True):
    s.validate(need_telegram=need_tg)
    logging.getLogger("tpclone").info("data folder: %s", s.data_dir.resolve())
    db = DB(s.db_path)
    fetcher = Fetcher(s)
    tg = Telegram(s.telegram_bot_token, s.telegram_chat_id, base=s.telegram_api_base) if (s.telegram_bot_token and not s.dry_run) else None
    return Engine(s, db, fetcher, tg), db


def _post_id(arg: str) -> int:
    m = re.search(r"(?:p=|^)(\d+)$", arg.strip())
    if not m:
        raise SystemExit(f"cannot read a post id from {arg!r}")
    return int(m.group(1))


def cmd_run(s: Settings, a) -> None:
    engine, db = build(s, need_tg=False)      # starts even before Telegram is configured (Settings page)
    if engine.tg:
        try:
            info = engine.tg.check()
            logging.info("Telegram OK: bot @%s -> %s", info["bot"], info["chat"])
        except (TelegramError, httpx.HTTPError) as e:
            raise SystemExit(f"Telegram check failed: {e}")
    worker = Worker(engine)
    server = make_server(engine, worker)
    stopping = threading.Event()

    def shutdown(*_):
        if stopping.is_set():
            return
        stopping.set()
        logging.info("shutting down: letting the in-flight post finish; progress is already saved")
        worker.halt()
        threading.Thread(target=server.shutdown, daemon=True).start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, shutdown)
    if worker.resume_if_desired():
        logging.info("resumed (it was running when the app last stopped)")
    elif a.start:
        worker.start()
    url = f"http://{'127.0.0.1' if s.web_host in ('0.0.0.0', '') else s.web_host}:{server.server_port}/"
    logging.info("dashboard: %s   state=%s", url, worker.state())
    if s.web_token and s.web_host not in ("127.0.0.1", "localhost", "::1"):
        logging.info("dashboard password: %s   (open  http://<this-server-ip>:%s/?token=%s )",
                     s.web_token, s.web_port, s.web_token)
    if a.open:
        threading.Timer(1.0, lambda: webbrowser.open(url + (f"?token={s.web_token}" if s.web_token else ""))).start()
    server.serve_forever()
    server.server_close()


def cmd_ctl(s: Settings, a) -> None:
    base = f"http://{s.web_host if s.web_host != '0.0.0.0' else '127.0.0.1'}:{s.web_port}"
    h = {"X-Requested-With": "tpclone", "X-Token": s.web_token}
    if a.action == "status":
        r = httpx.get(base + "/api/status", headers=h, timeout=10)
    else:
        r = httpx.post(base + f"/api/{a.action}", headers=h, json={}, timeout=10)
    j = r.json()
    print(json.dumps({k: j.get(k) for k in ("state", "error", "pending", "stats", "next_post_in")}, indent=2))


def cmd_check(s: Settings, a) -> None:
    engine, db = build(s)
    if engine.tg:
        print("Telegram:", engine.tg.check())
    entries = engine.load_sitemap(force=True)
    print(f"Sitemap: {len(entries)} posts, newest id {entries[-1][0]}")
    art = engine.fetch_article(entries[-1][0])
    print("Newest article parsed:", json.dumps({"title": art.title, "date": art.post_date, "tags": art.tags,
                                                "images": len(art.images), "paragraphs": len(art.paragraphs),
                                                "scheduled": art.scheduled, "credits": art.credits}, ensure_ascii=False))


def cmd_inspect(s: Settings, a) -> None:
    """Show exactly what the parser extracts - the tool for tuning selectors."""
    sel = load_selectors(s.selectors_file)
    if a.html:
        pid = int(a.target) if a.target.isdigit() else 0
        url = a.target if a.target.startswith("http") else f"{s.site_base.rstrip('/')}/?p={pid}"
        html = Path(a.html).read_text(encoding="utf8")
    else:
        engine, _ = build(s, need_tg=False)
        pid = _post_id(a.target)
        url = engine.post_url(pid)
        html = engine.fetcher.get_text(url).text
        if a.save:
            Path(a.save).write_text(html, encoding="utf8")
    art = parse_article(html, url, pid, s, sel)
    print(json.dumps(art.to_dict(), indent=2, ensure_ascii=False))
    plan = render.plan_media(art, s.max_media)
    print("\n--- rich HTML (image URLs inline) ---")
    print(render.build_html(art, s, plan, lambda k: k))


def cmd_preview(s: Settings, a) -> None:
    s.dry_run = True
    engine, _ = build(s, need_tg=False)
    art = engine.fetch_article(_post_id(a.target))
    plan = render.plan_media(art, s.max_media)
    print(render.build_html(art, s, plan, lambda k: k))
    print(f"\nmedia slots used: {plan.slots_used}/{s.max_media}  (overflow collage: {len(plan.overflow)} photos)")


def cmd_repost_date(s: Settings, a) -> None:
    engine, db = build(s)
    plan = engine.plan_date(a.date, progress=lambda m: print("  ", m, file=sys.stderr))
    print(plan["message"])
    for p in plan["posts"]:
        print(f"  {p['id']:>7}  {p['status']:<9} {p['title'] or ''}")
    if not plan["to_publish"]:
        return
    if not a.yes and input(f"Queue {len(plan['to_publish'])} post(s)? [y/N] ").strip().lower() != "y":
        return
    print("queued:", engine.enqueue_date(a.date, plan["to_publish"]))
    if a.run:   # publish in the foreground (no dashboard needed)
        while True:
            row = db.next_pending()
            if row is None:
                break
            w = engine.pacer.wait_time()
            if w > 0:
                time.sleep(w)
                continue
            print("  ->", row["post_id"], engine.process(row))
        print("done")
    else:
        print("The running app will publish them (or run with --run to publish now).")


def cmd_import(s: Settings, a) -> None:
    db = DB(s.db_path)
    print(reconcile.import_export(db, a.file, s.site_base))


def cmd_scan(s: Settings, a) -> None:
    db = DB(s.db_path)
    print(reconcile.scan_channel(db, s, a.limit))


def cmd_send_test(s: Settings, a) -> None:
    engine, _ = build(s)
    html = ("<h3>tpclone test</h3><details><summary>Show More</summary><p><i>If you can expand this, "
            "rich messages work in this channel.</i></p></details>")
    print(engine.tg.send_rich(html))


def main() -> None:
    p = argparse.ArgumentParser(prog="tpclone", description="toy-people.com -> Telegram rich-message cloner")
    p.add_argument("--env", default=".env")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the app (worker + dashboard)")
    r.add_argument("--start", action="store_true", help="begin publishing immediately")
    r.add_argument("--open", action="store_true", help="open the dashboard in the browser")
    c = sub.add_parser("ctl", help="start/stop/status a running instance")
    c.add_argument("action", choices=["start", "stop", "status"])
    sub.add_parser("check", help="verify Telegram token/channel, sitemap and article parsing")
    i = sub.add_parser("inspect", help="show what the parser extracts from a post (id/url) or saved --html")
    i.add_argument("target"); i.add_argument("--html"); i.add_argument("--save", help="also save the fetched page here")
    pv = sub.add_parser("preview", help="render the rich HTML of a post without sending")
    pv.add_argument("target")
    d = sub.add_parser("repost-date", help="publish all posts of a date (YYYY-MM-DD)")
    d.add_argument("date"); d.add_argument("--yes", action="store_true"); d.add_argument("--run", action="store_true")
    im = sub.add_parser("import-history", help="mark posts found in a Telegram Desktop export (result.json) as posted")
    im.add_argument("file")
    sc = sub.add_parser("scan-channel", help="(optional, Telethon) scan the channel with your account")
    sc.add_argument("--limit", type=int, default=5000)
    sub.add_parser("send-test", help="post a tiny rich message to verify the channel accepts them")
    a = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    s = load_settings(a.env)
    {"run": cmd_run, "ctl": cmd_ctl, "check": cmd_check, "inspect": cmd_inspect, "preview": cmd_preview,
     "repost-date": cmd_repost_date, "import-history": cmd_import, "scan-channel": cmd_scan,
     "send-test": cmd_send_test}[a.cmd](s, a)
