import io
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tpclone.config import Settings  # noqa: E402
from tpclone.db import DB  # noqa: E402
from tpclone.engine import Engine  # noqa: E402
from tpclone.fetch import NotFound, Page  # noqa: E402
from tpclone.site import Article  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def png(w=300, h=200, color=(200, 30, 30)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def make_article(pid=1, n_images=3, cover=True, title="A Title", **kw) -> Article:
    return Article(
        post_id=pid, url=f"https://www.toy-people.com/en/?p={pid}", title=title,
        cover="https://x/cover.jpg" if cover else None, post_date="2026-09-25", scheduled="Scheduled Release: Dec 2026",
        tags=["Japanese Series", "Kotobukiya"], paragraphs=["Hello <b>world</b>", "Second"],
        images=[f"https://x/{i}.jpg" for i in range(n_images)], credits=[("bandaispirits", "https://b.example/")], **kw)


class FakeTG:
    """A channel with sequential message numbers. Messages can be delivered although the answer is lost."""

    def __init__(self):
        self.sent = []
        self.fail_with = None
        self.deliver_then_fail = False      # the message reaches the channel, but the caller gets an error
        self.deleted: set[int] = set()
        self.unknown: set[int] = set()
        self.probes: list[int] = []        # every existence question asked
        self.next_id = 1001
        self.existing: set[int] = set()    # messages the bot can edit (its own)
        self.human: set[int] = set()       # messages posted by people: exist, but the bot cannot edit them
        self.flood: bool = False

    def human_post(self, n=1):
        for _ in range(n):
            self.human.add(self.next_id); self.next_id += 1

    def send_rich(self, html, media=None, files=None, **kw):
        if self.fail_with and not self.deliver_then_fail:
            e, self.fail_with = self.fail_with, None
            raise e
        mid = self.next_id
        self.next_id += 1
        self.existing.add(mid)
        self.sent.append({"html": html, "media": media, "files": files, "kw": kw})
        if self.fail_with and self.deliver_then_fail:
            e, self.fail_with = self.fail_with, None
            self.deliver_then_fail = False
            raise e
        return {"message_id": mid}

    def message_exists(self, message_id):
        self.probes.append(message_id)
        if message_id in self.unknown:
            return None
        return message_id not in self.deleted

    def message_status(self, message_id):
        from tpclone.telegram import TelegramError
        self.probes.append(message_id)
        if self.flood:
            raise TelegramError("Too Many Requests", 429, 30)
        if message_id in self.unknown:
            return "unknown"
        if message_id in self.deleted:
            return "missing"
        if message_id in self.human:
            return "other"
        return "mine" if message_id in self.existing else "missing"


class FakeClient:
    def __init__(self, fetcher):
        self.f = fetcher

    def get(self, url, headers=None):
        etag = '"%d-%s"' % (len(self.f.posts), max(self.f.posts, default=0))
        self.f.requests.append(dict(headers or {}))
        if (headers or {}).get("If-None-Match") == etag:
            class R304:
                status_code = 304
                headers = {"etag": etag}
                text = ""
            return R304()

        class R:
            status_code = 200
            headers = {"etag": etag}
            text = self.f.sitemap_xml()
        return R()


class FakeFetcher:
    def __init__(self):
        self.posts: dict[int, tuple[str, str]] = {}   # id -> (date, title)
        self.requests: list[dict] = []
        self.listing: list[int] = []      # ids shown in the homepage 'Latest News'
        self.lang: dict[int, str] = {}     # id -> <html lang> of its article page (default: en)
        self.article_requests: list[int] = []
        self.hidden: set[int] = set()     # exist on the site (article page works) but NOT in the sitemap
        self.client = FakeClient(self)

    def sitemap_xml(self):
        u = "".join(f"<url><loc>https://www.toy-people.com/en/?p={i}</loc><lastmod>2026-10-01</lastmod></url>"
                    for i in sorted(self.posts) if i not in self.hidden)
        return f'<?xml version="1.0"?><urlset>{u}</urlset>'

    def get_text(self, url, **kw):
        if "?p=" not in url:        # the homepage: "Latest News" cards for the ids in self.listing
            cards = "".join(
                f'<div class="card"><a href="/en/?p={i}"><img src="/i/{i}.jpg"></a><div><a href="/en/?p={i}">'
                f'{self.posts[i][1]}</a><span>{self.posts[i][0]}</span></div></div>'
                for i in self.listing if i in self.posts)
            return Page(url, 200, f"<html><body><h2>Latest News</h2>{cards}</body></html>", {})
        pid = int(url.rsplit("=", 1)[1])
        self.article_requests.append(pid)
        if pid not in self.posts:
            raise NotFound(url)
        date, title = self.posts[pid]
        return Page(url, 200, f"""<html lang="{self.lang.get(pid, 'en-US')}"><head><meta property="og:image" content="https://x/c{pid}.jpg">
        <meta property="article:published_time" content="{date}T10:00:00+08:00"></head><body><h1>{title}</h1>
        <article><div class="entry-content"><p>Body of {pid}</p><p><img src="https://x/{pid}.jpg"></p>
        <p>via: <a href="https://src.example/">src</a></p></div></article></body></html>""", {})

    def get_bytes(self, url, referer=None):
        return png(), "image/png"


@pytest.fixture
def env(tmp_path):
    s = Settings(telegram_bot_token="t", telegram_chat_id="@c", db_path=str(tmp_path / "data" / "tpclone.db"),
                 post_delay_seconds=5, media_mode="url")
    fetcher, tg = FakeFetcher(), FakeTG()
    db = DB(":memory:")
    e = Engine(s, db, fetcher, tg)
    e.probe_gap = 0
    return e, fetcher, tg, db
