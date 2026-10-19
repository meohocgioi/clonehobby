"""Second source: https://www.hpoi.net/ "最新情报" (Latest Info) -> English Telegram posts.

One news card = one post. The homepage lists the newest ~20 cards; each links to a product page (/hobby/<id>) that
holds the details (photos, maker, characters, series, release). Titles and hashtags are translated to English.

Politeness: robots.txt allows these pages (it disallows /api/ and others, which are never touched); requests are
spaced >= 5 s apart and the homepage is read only once per poll interval (10 min by default).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
import zlib
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import site
from .config import Settings
from .db import DB
from .engine import Deferred, Engine
from .fetch import FetchError, Fetcher
from .telegram import Telegram
from .translate import TranslateError, Translator

log = logging.getLogger("tpclone.hpoi")

BASE = "https://www.hpoi.net/"
KEY_SPAN = 100000          # post key = hobby_id * KEY_SPAN + crc32(headline) % KEY_SPAN  (one product can have several news items)


def post_key(hobby_id: int, headline: str) -> int:
    return hobby_id * KEY_SPAN + zlib.crc32(headline.strip().encode("utf8")) % KEY_SPAN


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("　", " ")).strip()


# ----------------------------------------------------------------------------- parsing
def parse_listing(html: str) -> list[dict]:
    """The cards of the 'Latest Info' block, newest first:
    {id (hobby id), key, headline, name, category, kind, age, cover}"""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict] = []
    for card in soup.select("div.hpoi-conter-left"):
        left, right = card.select_one(".left-leioan"), card.select_one(".right-leioan")
        if not left or not right:
            continue                                   # other blocks of the homepage (plain cover lists)
        a = left.find("a", href=re.compile(r"hobby/(\d+)"))
        if not a:
            continue
        hid = int(re.search(r"hobby/(\d+)", a["href"]).group(1))
        divs = right.find_all("div", recursive=False)
        spans = [_clean(x.get_text()) for x in divs[0].find_all("span")] if divs else []
        bar = right.select_one(".hpoi-hr-small")
        after = [d for d in (bar.find_next_siblings("div") if bar else divs[2:]) if "hpoi-hr-small" not in (d.get("class") or [])]
        headline = _clean(after[0].get_text()) if after else ""
        name = _clean(after[1].get_text()) if len(after) > 1 else ""
        img = left.find("img")
        cover = site_url(img.get("src") or img.get("data-src") or "") if img else None
        cat = left.find("span")
        if not headline:
            continue
        out.append({"id": hid, "key": post_key(hid, headline), "headline": headline, "name": name,
                    "category": _clean(cat.get_text()) if cat else "", "kind": spans[0] if spans else "",
                    "age": spans[1] if len(spans) > 1 else "", "cover": cover})
    return out


def site_url(u: str) -> str:
    return urljoin(BASE, u.strip()) if u else ""


def _img(u: str, folder: str | None = None) -> str:
    u = site_url(u).split("?")[0]
    if folder:
        u = re.sub(r"/gk/(pic|cover)/[a-z]/", rf"/gk/\1/{folder}/", u)
    return u


def _links_or_text(p) -> list[str]:
    if p is None:
        return []
    links = [_clean(a.get_text()) for a in p.find_all("a")]
    if links:
        return [x for x in links if x]
    return [x for x in re.split(r"[、,，/]", _clean(p.get_text())) if x.strip()]


def parse_item(html: str) -> dict:
    """Product page -> {fields: {label: [values]}, release: [row...], cover, images}"""
    soup = BeautifulSoup(html, "lxml")
    fields: dict[str, list[str]] = {}
    release: list[str] = []
    label = ""
    for it in soup.select(".hpoi-infoList-item"):
        sp, p = it.find("span", recursive=False), it.find("p", recursive=False)
        if sp is None and p is None:
            continue
        lab = _clean(sp.get_text()) if sp else ""
        if lab:
            label = lab
        if label in ("发售", "發售", "发售日") or (not lab and label in ("发售", "發售", "发售日")):
            release.append(_clean(p.get_text()) if p else "")
            continue
        vals = _links_or_text(p)
        if label and vals:
            fields.setdefault(label, []).extend(vals)
    cover = None
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if "/gk/cover/" in src:
            cover = _img(src, "n")
            break
    if not cover:
        og = soup.find("meta", {"property": "og:image"})
        if og and og.get("content"):
            cover = _img(og["content"], "n")
    images: list[str] = []
    for img in soup.find_all("img"):
        for src in (img.get("data-src"), img.get("src")):
            if src and "/gk/pic/" in src:
                u = _img(src, "n")
                if u not in images and u != cover:
                    images.append(u)
    return {"fields": fields, "release": release, "cover": cover, "images": images}


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def scheduled_line(release: list[str]) -> str | None:
    """'2027/4 , 1,430日元（税） , 伊地知星歌' -> 'Scheduled Release: Apr 2027' (earliest date of the product)."""
    dates = []
    for row in release:
        m = re.match(r"\s*(\d{4})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{1,2}))?", row)
        if m and 1 <= int(m.group(2)) <= 12:
            dates.append((int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)))
    if not dates:
        return None
    y, mo, d = min(dates)
    text = f"{_MONTHS[mo - 1]} {d}, {y}" if d else f"{_MONTHS[mo - 1]} {y}"
    return f"Scheduled Release: {text}"


# ----------------------------------------------------------------------------- settings
def derive_settings(main: Settings) -> Settings:
    """The HPOI engine's own view of the settings (shares the bot token, may use another channel)."""
    return dataclasses.replace(
        main,
        site_base=BASE, listing_url=BASE, sitemap_url="", site_tz="Asia/Shanghai",
        site_delay_seconds=max(5.0, main.site_delay_seconds),
        poll_interval_seconds=max(60, main.hpoi_poll_interval_seconds),
        post_delay_seconds=main.hpoi_post_delay_seconds,
        initial_post_latest=main.hpoi_initial_post_latest,
        hashtag_style="hashtag",                       # clickable # tags, as requested for this source
        telegram_chat_id=main.hpoi_chat_id.strip() or main.telegram_chat_id,
        db_path=str(Path(main.db_path).with_name("hpoi.db")),
    )


# ----------------------------------------------------------------------------- engine
class HpoiEngine(Engine):
    BACKUP_PREFIX = "hpoi"
    source = "hpoi"

    def __init__(self, main: Settings, db: DB, fetcher: Fetcher, tg: Telegram | None):
        self.main = main
        s = derive_settings(main)
        super().__init__(s, db, fetcher or Fetcher(s), tg)
        db._x("CREATE TABLE IF NOT EXISTS hpoi_items (key INTEGER PRIMARY KEY, hobby_id INTEGER NOT NULL, headline TEXT, "
              "name TEXT, category TEXT, kind TEXT, cover TEXT, seen_at REAL)")
        self.translator = Translator(db, main.translator, main.translate_api_key,
                                     glossary_file=main.data_dir / "hpoi_glossary.json")

    # ---- settings ---------------------------------------------------------
    def apply_settings(self) -> None:
        new = derive_settings(self.main)
        for f in dataclasses.fields(new):
            setattr(self.s, f.name, getattr(new, f.name))
        self.translator.provider, self.translator.api_key = self.main.translator, self.main.translate_api_key
        super().apply_settings()

    def maybe_check_update(self, every: float = 43200.0) -> None:
        return None                                       # the toy-people engine handles app updates

    # ---- site access --------------------------------------------------------
    def _item(self, key: int) -> dict | None:
        r = self.db._q("SELECT * FROM hpoi_items WHERE key=?", (key,))
        return dict(r[0]) if r else None

    def post_url(self, key: int) -> str:
        it = self._item(key)
        return f"{BASE}hobby/{it['hobby_id'] if it else key // KEY_SPAN}"

    def load_sitemap(self, force: bool = False):
        return None

    def resolve_key(self, number: int) -> int:
        """Preview/post box: a full item number, or the product number from the link (…/hobby/137248)."""
        if number >= KEY_SPAN and self._item(number):
            return number
        r = self.db._q("SELECT key FROM hpoi_items WHERE hobby_id=? ORDER BY seen_at DESC LIMIT 1", (number,))
        if r:
            return r[0]["key"]
        raise FetchError(f"{number} is not on the current HPOI 'Latest Info' list (only those items can be previewed)")

    def post_now(self, post_id: int, force: bool = False) -> dict:
        return super().post_now(self.resolve_key(post_id), force)

    @classmethod
    def create(cls, main: Settings) -> "HpoiEngine":
        s = derive_settings(main)
        tg = Telegram(s.telegram_bot_token, s.telegram_chat_id, base=s.telegram_api_base) \
            if (s.telegram_bot_token and s.telegram_chat_id and not s.dry_run) else None
        eng = cls(main, DB(s.db_path), None, tg)
        return eng

    def fetch_listing(self) -> list[dict]:
        return parse_listing(self.fetcher.get_text(BASE).text)

    def _remember(self, cards: list[dict]) -> None:
        for c in cards:
            self.db._x("INSERT OR IGNORE INTO hpoi_items(key,hobby_id,headline,name,category,kind,cover,seen_at) "
                       "VALUES(?,?,?,?,?,?,?,?)",
                       (c["key"], c["id"], c["headline"], c["name"], c["category"], c["kind"], c["cover"], time.time()))

    # ---- discovery ------------------------------------------------------------
    def _discover(self, manual: bool = False) -> tuple[int, int]:
        t0 = time.time()
        cards = self.fetch_listing()
        self.db.kv_set("listing_info", json.dumps({"count": len(cards), "error": None, "ts": time.time()}))
        if not cards:
            raise FetchError("the HPOI homepage showed no 'Latest Info' cards (page layout changed?)")
        self._remember(cards)
        self.db.kv_set("listing_max_id", max(c["id"] for c in cards))
        for c in cards:
            self.db.upsert_seen(c["key"], f"{BASE}hobby/{c['id']}", None, "known", "hpoi")
            self.db.set_meta(c["key"], c["headline"], None)
        first_run = self.db.kv_get("baseline_done") is None
        ordered = sorted(cards, key=lambda c: c["id"])                         # oldest first
        if first_run:
            for c in cards:
                self.db._x("UPDATE posts SET status='skipped', source='baseline' WHERE post_id=? AND status='known'", (c["key"],))
            latest = ordered[-self.s.initial_post_latest:] if self.s.initial_post_latest > 0 else []
            for c in latest:
                self.db.enqueue(c["key"], 0, "new")
            self.db.kv_set("baseline_done", int(time.time()))
            self.db.log("info", f"HPOI watcher started: {len(cards)} existing cards marked as seen (not posted); "
                                f"queued {len(latest)} newest")
            self.db.kv_set("last_discover_ts", t0)
            return len(latest), len(cards)
        new = [c for c in ordered if (self.db.get(c["key"]) or {}).get("status") == "known"]
        if len(new) > self.s.max_auto_queue:
            for c in new:
                self.db._x("UPDATE posts SET status='skipped', source='flood-guard' WHERE post_id=?", (c["key"],))
            self.db.log("warn", f"{len(new)} new HPOI cards at once (more than {self.s.max_auto_queue}); NOT auto-posted")
            n = 0
        else:
            n = sum(1 for c in new if self.db.enqueue(c["key"], 0, "new"))
            if n:
                self.db.log("info", f"HPOI: {n} new item(s): " + "; ".join(c["headline"][:60] for c in new[:5]))
        self.db.kv_set("last_discover_ts", t0)
        return n, len(cards)

    # ---- article ------------------------------------------------------------------
    def _tr(self, text: str) -> str:
        try:
            return self.translator.translate(text)
        except TranslateError as e:
            raise Deferred(f"translation not available yet ({e})", 600) from e

    def fetch_article(self, key: int) -> site.Article:
        it = self._item(key)
        if it is None:
            raise FetchError("this HPOI item is unknown (it is no longer on the homepage list)")
        url = f"{BASE}hobby/{it['hobby_id']}"
        info = parse_item(self.fetcher.get_text(url).text)
        f = info["fields"]
        tags: list[str] = []
        for label in (("制作", "製作"), ("角色",), ("作品",)):
            for lab in label:
                for v in f.get(lab, []):
                    t = self._tr(v)
                    if t and t.lower() not in {x.lower() for x in tags}:
                        tags.append(t)
        title = self._tr(it["headline"])
        art = site.Article(
            post_id=key, url=url, title=title, cover=info["cover"] or it.get("cover"),
            scheduled=scheduled_line(info["release"]), tags=tags,
            images=info["images"][: self.s.max_media], credit_label="via", credits=[("Hpoi", url)], lang="en")
        self.db.set_meta(key, title, None)
        return art
