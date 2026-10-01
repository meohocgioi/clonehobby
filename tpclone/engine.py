"""Discovery, publishing, date repost and the Start/Stop worker."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

from . import media as media_mod
from . import render, site
from .config import Settings
from .db import DB
from .fetch import ChallengeError, Fetcher, FetchError, NotFound
from .telegram import MediaRejected, Pacer, Telegram, TelegramError, UncertainDelivery

log = logging.getLogger("tpclone.engine")

FATAL_CODES = (401, 403)   # bad token / kicked from the channel: stop instead of burning every post


class Engine:
    def __init__(self, settings: Settings, db: DB, fetcher: Fetcher, tg: Telegram | None):
        self.s, self.db, self.fetcher, self.tg = settings, db, fetcher, tg
        self.selectors = site.load_selectors(settings.selectors_file)
        self.pacer = Pacer(settings.effective_delay, db, settings.max_posts_per_hour)
        self._sitemap: list[tuple[int, str, str | None]] = []
        self._sitemap_at = 0.0

    def apply_settings(self) -> None:
        """Re-read the (already updated) Settings object: Telegram client, pacing."""
        if self.s.telegram_ready and not self.s.dry_run:
            self.tg = Telegram(self.s.telegram_bot_token, self.s.telegram_chat_id, base=self.s.telegram_api_base)
        else:
            self.tg = None
        self.pacer.delay = self.s.effective_delay
        self.pacer.max_per_hour = self.s.max_posts_per_hour

    # ------------------------------------------------------------------ site access
    def post_url(self, post_id: int) -> str:
        return f"{self.s.site_base.rstrip('/')}/?p={post_id}"

    def load_sitemap(self, force: bool = False) -> list[tuple[int, str, str | None]] | None:
        """Download + parse the sitemap. Returns None when the server says it did not change (ETag/Last-Modified)."""
        headers = {}
        if not force:
            if self.db.kv_get("sitemap_etag"):
                headers["If-None-Match"] = self.db.kv_get("sitemap_etag")
            if self.db.kv_get("sitemap_lm"):
                headers["If-Modified-Since"] = self.db.kv_get("sitemap_lm")
        r = self.fetcher.client.get(self.s.sitemap_url, headers=headers)
        if r.status_code == 304:
            return None
        if r.status_code != 200:
            raise FetchError(f"sitemap HTTP {r.status_code}")
        if "etag" in r.headers:
            self.db.kv_set("sitemap_etag", r.headers["etag"])
        if "last-modified" in r.headers:
            self.db.kv_set("sitemap_lm", r.headers["last-modified"])
        entries = site.parse_sitemap(r.text)
        if not entries:
            raise FetchError("sitemap parsed to zero posts (format changed?)")
        self._sitemap, self._sitemap_at = entries, time.time()
        return entries

    def sitemap_entries(self) -> list[tuple[int, str, str | None]]:
        if not self._sitemap or time.time() - self._sitemap_at > 900:
            self.load_sitemap(force=True)
        return self._sitemap

    def fetch_article(self, post_id: int) -> site.Article:
        url = self.post_url(post_id)
        page = self.fetcher.get_text(url)
        art = site.parse_article(page.text, url, post_id, self.s, self.selectors)
        self.db.set_meta(post_id, art.title or None, art.post_date)
        return art

    # ------------------------------------------------------------------ discovery
    def discover(self) -> int:
        """Compare the sitemap with the ledger. Returns number of newly queued posts."""
        entries = self.load_sitemap()
        if entries is None:
            return 0
        known = self.db.known_ids()
        if self.db.kv_get("baseline_done") is None:
            return self._baseline(entries)
        new = [e for e in entries if e[0] not in known]
        if not new:
            return 0
        if len(new) > self.s.max_auto_queue:
            self.db.bulk_seen(new, "skipped", "flood-guard")
            msg = (f"{len(new)} unseen posts appeared at once (> MAX_AUTO_QUEUE={self.s.max_auto_queue}); "
                   f"NOT auto-queued. Use 'Repost by date' to publish them.")
            self.db.log("warn", msg)
            log.warning(msg)
            return 0
        self.db.bulk_seen(new, "pending", "new", priority=0)
        self.db.log("info", f"discovered {len(new)} new post(s): " + ", ".join(str(e[0]) for e in new[:10]))
        return len(new)

    def _baseline(self, entries) -> int:
        n = self.db.bulk_seen(entries, "skipped", "baseline")
        latest = sorted(entries, key=lambda e: e[0], reverse=True)[: self.s.initial_post_latest]
        for e in sorted(latest):
            self.db.enqueue(e[0], 0, "new")
        self.db.kv_set("baseline_done", int(time.time()))
        self.db.log("info", f"first start: {n} existing site posts marked as seen (not posted); "
                            f"queued latest {len(latest)}")
        return len(latest)

    # ------------------------------------------------------------------ publishing
    def _download(self, url: str) -> bytes | None:
        try:
            data, _ = self.fetcher.get_bytes(url, referer=self.s.site_base)
            return data
        except Exception as e:
            log.warning("image download failed %s: %s", url, e)
            return None

    def _compose(self, art: site.Article, plan: render.MediaPlan, mode: str):
        """-> (html, media entries, files). In 'upload' mode every image is downloaded and attached."""
        refs: dict[str, str] = {}
        files: dict[str, bytes] = {}
        media: list[dict] = []

        def attach(key: str, data: bytes) -> None:
            fid = f"f{len(files)}"
            files[fid] = data
            media.append({"id": fid, "media": {"type": "photo", "media": f"attach://{fid}"}})
            refs[key] = f"tg://photo?id={fid}"

        plan = render.MediaPlan(plan.cover, list(plan.originals), list(plan.overflow))
        if mode == "upload":
            max_side = 2560
            while True:
                files.clear(); media.clear(); refs.clear()
                if plan.cover:
                    d = self._download(plan.cover)
                    if d:
                        attach(plan.cover, media_mod.prepare_photo(d, max_side))
                    else:
                        plan.cover = None
                ok = []
                for u in plan.originals:
                    d = self._download(u)
                    if d:
                        attach(u, media_mod.prepare_photo(d, max_side))
                        ok.append(u)
                plan.originals = ok
                if sum(len(v) for v in files.values()) <= 40 * 1024 * 1024 or max_side <= 1024:
                    break
                max_side = max(1024, max_side // 2)    # keep the request below ~40 MB
        else:
            for u in ([plan.cover] if plan.cover else []) + plan.originals:
                refs[u] = u
        if plan.overflow:
            blobs = [b for b in (self._download(u) for u in plan.overflow) if b]
            if blobs:
                attach(render.OVERFLOW_KEY, media_mod.make_collage(blobs))
            else:
                plan.overflow = []
        html = render.build_html(art, self.s, plan, lambda k: refs[k])
        return html, media, files

    def build_message(self, art: site.Article, mode: str | None = None):
        plan = render.plan_media(art, self.s.max_media)
        mode = mode or ("url" if self.s.media_mode == "auto" else self.s.media_mode)
        return self._compose(art, plan, mode), plan

    def publish(self, post_id: int) -> int | None:
        """Fetch -> render -> send one post. Returns Telegram message_id."""
        art = self.fetch_article(post_id)
        if not art.title or not (art.paragraphs or art.images or art.cover):
            raise FetchError(f"parse produced an empty post (title={art.title!r}, paragraphs={len(art.paragraphs)}, "
                             f"images={len(art.images)}) - check selectors with 'tpclone inspect {post_id}'")
        plan = render.plan_media(art, self.s.max_media)
        mode = self.s.media_mode
        tag_hash = self.s.hashtag_style in ("hashtag", "true", "1")
        html, media, files = self._compose(art, plan, "url" if mode == "auto" else mode)
        assert render.count_media(html) <= self.s.max_media
        if self.s.dry_run or self.tg is None:
            log.info("DRY RUN post %s:\n%s", post_id, html)
            return None
        try:
            res = self.tg.send_rich(html, media, files, skip_entity_detection=not tag_hash)
        except MediaRejected as e:
            if mode != "auto":
                raise
            log.warning("post %s: Telegram rejected image URLs (%s) - retrying with uploads", post_id, e)
            html, media, files = self._compose(art, plan, "upload")
            res = self.tg.send_rich(html, media, files, skip_entity_detection=not tag_hash)
        return res.get("message_id")

    def process(self, row: dict) -> str:
        """Publish one queued row and record the outcome. Returns the resulting status."""
        pid = row["post_id"]
        if not self.db.mark_sending(pid):
            return "skipped"
        try:
            mid = self.publish(pid)
        except ChallengeError as e:
            self.db.defer(pid, f"Cloudflare: {e}", 900)
            self.db.log("warn", f"post {pid}: Cloudflare blocked the fetch; retrying in 15 min")
            return "pending"
        except NotFound:
            st = self.db.mark_retry(pid, "article not found (404)", 900, give_up_after=4)
            self.db.log("warn", f"post {pid}: 404 ({st})")
            return st
        except FetchError as e:
            st = self.db.mark_retry(pid, str(e), 300)
            self.db.log("warn", f"post {pid}: {e} ({st})")
            return st
        except UncertainDelivery as e:
            self.db.mark_uncertain(pid, str(e))
            self.pacer.push_back(300)
            self.db.log("error", f"post {pid}: delivery UNCERTAIN ({e}). Check the channel, then mark it posted/pending "
                                 f"in the dashboard.")
            return "uncertain"
        except TelegramError as e:
            if e.code in FATAL_CODES or (e.code == 400 and "chat not found" in str(e).lower()):
                self.db.defer(pid, str(e), 60)
                raise
            if e.code == 429 and e.retry_after:
                self.pacer.push_back(e.retry_after)
                self.db.defer(pid, str(e), e.retry_after)
                return "pending"
            st = self.db.mark_retry(pid, str(e), 600)
            self.db.log("error", f"post {pid}: Telegram error: {e} ({st})")
            return st
        except Exception as e:  # parser/Pillow bugs etc.: never take the worker down, never repost blindly
            st = self.db.mark_retry(pid, f"{type(e).__name__}: {e}", 600)
            log.exception("post %s failed", pid)
            self.db.log("error", f"post {pid}: {type(e).__name__}: {e} ({st})")
            return st
        if self.s.dry_run or self.tg is None:
            self.db.reset_status(pid, "known")
            return "known"
        self.db.mark_posted(pid, mid)
        self.pacer.mark_sent()
        row = self.db.get(pid) or {}
        self.db.log("info", f"posted {pid}: {row.get('title') or ''}")
        return "posted"

    # ------------------------------------------------------------------ date repost
    def _meta_for(self, post_id: int) -> tuple[str | None, str | None]:
        row = self.db.get(post_id)
        if row and row.get("post_date"):
            return row["post_date"], row.get("title")
        try:
            art = self.fetch_article(post_id)
            return art.post_date, art.title
        except NotFound:
            return None, None

    def plan_date(self, date: str, margin: int = 25, tail: int = 60, progress: Callable[[str], None] | None = None) -> dict:
        """Find every website post of `date` (YYYY-MM-DD, site timezone) and compare with the ledger.

        Post IDs grow with time, so the day is located by binary search over the sitemap's IDs (a few dozen
        page fetches instead of thousands), widened by `margin` IDs each side to absorb out-of-order IDs.
        The newest `tail` IDs are always checked too, so a post added later with a back-dated day is found
        (fetched pages are cached in the ledger, so repeated plans only pay for new posts).
        """
        say = progress or (lambda m: None)
        say("reading the sitemap")
        entries = self.load_sitemap(force=True)   # always the site's current state (new posts since last time)
        ids = [e[0] for e in entries]
        lm = {e[0]: e[2] for e in entries}
        n = len(ids)

        def probe(i: int) -> str | None:
            for j in range(i, min(i + 6, n)):
                d, _ = self._meta_for(ids[j])
                if d:
                    return d
            return None

        def bound(strict: bool) -> int:
            lo, hi = 0, n
            while lo < hi:
                mid = (lo + hi) // 2
                d = probe(mid)
                say(f"locating {date}: id {ids[mid]} -> {d}")
                if d is None or (d > date if strict else d >= date):
                    hi = mid
                else:
                    lo = mid + 1
            return lo

        lower, upper = bound(False), bound(True)
        a, b = max(0, lower - margin), min(n, upper + margin)
        scan = list(range(a, b)) + list(range(max(b, n - tail), n))
        found: dict[int, str | None] = {}
        for k, i in enumerate(scan):
            pid = ids[i]
            d, t = self._meta_for(pid)
            if d == date:
                found[pid] = t
            if k % 10 == 0:
                say(f"scanning {k}/{len(scan)} ({len(found)} posts on {date})")
        for r in self.db.by_date(date):
            found.setdefault(r["post_id"], r.get("title"))

        # record them (visible on the site, nothing queued yet)
        self.db.bulk_seen([(p, self.post_url(p), lm.get(p)) for p in found], "known", "date-scan", priority=1)
        rows = {p: self.db.get(p) for p in found}
        posted = sorted(p for p, r in rows.items() if r and r["status"] == "posted")
        unpublished = sorted(p for p in found if p not in posted)
        queued = [p for p in unpublished if rows[p] and rows[p]["status"] in ("pending", "sending")]
        uncertain = [p for p in unpublished if rows[p] and rows[p]["status"] == "uncertain"]
        prev = self.db.kv_json(f"date_batch:{date}", [])
        new_since = [p for p in unpublished if p not in prev]

        total = len(found)
        if total == 0:
            state, msg = "empty", f"No posts found on the website for {date}."
        elif not unpublished:
            state, msg = "all_published", f"You have already published all {total} post(s) from {date}."
            self.db.kv_set(f"date_batch:{date}", json.dumps(sorted(found)))
        elif prev and set(prev) <= set(posted) and new_since:
            state = "new_since"
            msg = (f"You have already published all posts from {date}. However, the website has added "
                   f"{len(new_since)} new post(s) since then. Would you like to publish only the new posts?")
        elif posted:
            state = "partial"
            msg = (f"{len(posted)} of {total} post(s) from {date} are already published. "
                   f"Publish the remaining {len(unpublished)}?")
        else:
            state, msg = "none", f"Found {total} post(s) from {date}, none published yet. Publish them all?"
        if uncertain:
            msg += f" ({len(uncertain)} need manual review - delivery was uncertain; they are not re-sent automatically.)"
        return {
            "date": date, "state": state, "message": msg, "total": total,
            "published": posted, "to_publish": [p for p in unpublished if p not in uncertain],
            "already_queued": queued, "uncertain": uncertain,
            "posts": [{"id": p, "title": (rows[p] or {}).get("title"), "status": (rows[p] or {}).get("status")}
                      for p in sorted(found)],
        }

    def enqueue_date(self, date: str, post_ids: list[int]) -> int:
        n = 0
        for p in sorted(post_ids):
            if self.db.enqueue(p, 1, "repost"):
                n += 1
        batch = set(self.db.kv_json(f"date_batch:{date}", [])) | set(post_ids)
        self.db.kv_set(f"date_batch:{date}", json.dumps(sorted(batch)))
        self.db.log("info", f"repost {date}: queued {n} post(s)")
        return n


class Worker:
    """Start/Stop controller. State lives in the DB so a restart (or crash) resumes where it left off."""

    def __init__(self, engine: Engine):
        self.e, self.db, self.s = engine, engine.db, engine.s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.error: str | None = None
        self.next_poll = 0.0

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def state(self) -> str:
        if self.running:
            return "stopping" if self._stop.is_set() else "running"
        return "error" if self.error else "stopped"

    def start(self) -> None:
        if not self.s.telegram_ready and not self.s.dry_run:
            self.db.log("warn", "cannot start: Telegram bot token / channel not set (Settings)")
            return
        self.db.kv_set("desired_state", "running")
        if self.running and not self._stop.is_set():
            return
        if self.running:  # stop requested but still finishing the in-flight post: wait for it
            self._thread.join(timeout=120)
        self._stop.clear()
        self.error = None
        n = self.db.resolve_uncertain_stale()
        if n:
            self.db.log("warn", f"{n} post(s) were mid-send when the app stopped -> marked 'uncertain' "
                                f"(not re-sent automatically). Check the channel.")
        self._thread = threading.Thread(target=self._loop, name="worker", daemon=True)
        self._thread.start()
        self.db.log("info", "started")

    def stop(self, wait: bool = False) -> None:
        self.db.kv_set("desired_state", "stopped")
        self._stop.set()
        if wait and self._thread:
            self._thread.join(timeout=180)
        self.db.log("info", "stop requested (in-flight post is allowed to finish)")

    def halt(self) -> None:
        """Process shutdown (SIGTERM/Ctrl-C): finish the in-flight post but KEEP the persisted desired_state,
        so a reboot resumes exactly as the user left it (running stays running, stopped stays stopped)."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=180)

    def resume_if_desired(self) -> bool:
        if self.s.auto_resume and self.db.kv_get("desired_state") == "running":
            self.start()
            return True
        return False

    def _loop(self) -> None:
        e = self.e
        try:
            while not self._stop.is_set():
                if time.time() >= self.next_poll:
                    try:
                        e.discover()
                    except ChallengeError as ex:
                        self.db.log("warn", f"discovery blocked by Cloudflare: {ex}")
                    except Exception as ex:
                        log.exception("discovery failed")
                        self.db.log("error", f"discovery failed: {ex}")
                    self.next_poll = time.time() + self.s.poll_interval_seconds
                row = self.db.next_pending()
                if row is None:
                    self._stop.wait(5)
                    continue
                wait = e.pacer.wait_time()
                if wait > 0:
                    self._stop.wait(min(wait, 5))
                    continue
                e.process(row)
        except TelegramError as ex:
            self.error = f"{ex} (code {ex.code})"
            self.db.log("error", f"worker halted: {self.error}")
            log.error("worker halted: %s", self.error)
        except Exception as ex:   # pragma: no cover
            self.error = f"{type(ex).__name__}: {ex}"
            log.exception("worker crashed")
            self.db.log("error", f"worker crashed: {self.error}")
        finally:
            self.db.log("info", "stopped")
