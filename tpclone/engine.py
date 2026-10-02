"""Discovery, publishing, date repost and the Start/Stop worker."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

from . import media as media_mod
from . import render, site, updater
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
        self.probe_gap = 5.0            # min seconds between two 'does it exist?' questions (Telegram flood-limits edits)
        self.bg_pause_until = 0.0       # set when Telegram says 'slow down'
        self._probe_lock = threading.Lock()
        self._probe_last = 0.0

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
        """Download + parse the sitemap. Returns None when the server says it did not change.

        NOTE: this never saves the ETag / Last-Modified itself. Only discover() does, AFTER it has processed the list
        (see _commit_validators). Otherwise a manual date check would 'use up' the marker and the background watcher
        would be told 'not modified' about posts it has never seen."""
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
        self._validators = {"etag": r.headers.get("etag"), "lm": r.headers.get("last-modified")}
        entries = site.parse_sitemap(r.text)
        if not entries:
            raise FetchError("sitemap parsed to zero posts (format changed?)")
        self._sitemap, self._sitemap_at = entries, time.time()
        return entries

    def _commit_validators(self) -> None:
        v = getattr(self, "_validators", None) or {}
        for key, val in (("sitemap_etag", v.get("etag")), ("sitemap_lm", v.get("lm"))):
            if val:
                self.db.kv_set(key, val)
            else:
                self.db.kv_set(key, "")
        self.db.kv_set("last_full_sitemap", time.time())

    def sitemap_entries(self) -> list[tuple[int, str, str | None]]:
        if not self._sitemap or time.time() - self._sitemap_at > 900:
            self.load_sitemap(force=True)
        return self._sitemap

    def fetch_listing(self) -> list[dict]:
        """The 'Latest News' cards the website shows right now (the sitemap is rebuilt only once a day)."""
        page = self.fetcher.get_text(self.s.listing_url or self.s.site_base)
        return site.parse_listing(page.text, self.s.site_tz)

    def fetch_article(self, post_id: int) -> site.Article:
        url = self.post_url(post_id)
        page = self.fetcher.get_text(url)
        art = site.parse_article(page.text, url, post_id, self.s, self.selectors)
        self.db.set_meta(post_id, art.title or None, art.post_date)
        return art

    # ------------------------------------------------------------------ discovery
    def discover(self, manual: bool = False) -> int:
        """Compare the sitemap with the ledger and queue what is new. Returns the number of newly queued posts."""
        try:
            n, total = self._discover(manual)
        except Exception as e:  # noqa: BLE001
            self.db.kv_set("discover_status", json.dumps({"ts": time.time(), "ok": False, "error": str(e)[:300]}))
            raise
        self.db.kv_set("discover_status", json.dumps({"ts": time.time(), "ok": True, "total": total, "new": n}))
        return n

    def _discover(self, manual: bool = False) -> tuple[int, int]:
        t0 = time.time()
        prev_poll = float(self.db.kv_get("last_discover_ts", "0") or 0)
        first_run = self.db.kv_get("baseline_done") is None
        # a full download is forced on the first run and at least every 30 min (guards against a stale validator)
        stale = time.time() - float(self.db.kv_get("last_full_sitemap", "0") or 0) > 1800
        no_max = not self.db.kv_get("sitemap_max_id")      # e.g. right after an update: probing needs this number
        entries = self.load_sitemap(force=first_run or stale or manual or no_max)
        fresh_sitemap = entries is not None
        if entries is None:        # unchanged since the list we already processed
            entries = []
        total = len(entries) or int(self.db.kv_get("sitemap_total", "0") or 0)
        if fresh_sitemap:
            self.db.kv_set("sitemap_total", total)
            self.db.kv_set("sitemap_max_id", entries[-1][0])
        sitemap_max = int(self.db.kv_get("sitemap_max_id", "0") or 0)

        # second source, always live: the Latest News cards on the website
        listing: list[dict] = []
        listing_error = None
        try:
            listing = self.fetch_listing()
        except Exception as e:  # noqa: BLE001  (the sitemap alone must still work)
            listing_error = f"{type(e).__name__}: {e}"
            log.warning("latest-news listing failed: %s", listing_error)
        self.db.kv_set("listing_info", json.dumps({"count": len(listing), "error": listing_error, "ts": time.time()}))
        if listing:
            self.db.kv_set("listing_max_id", max(i["id"] for i in listing))
        cutoff = self._cutoff_date()
        from_listing = [(i["id"], self.post_url(i["id"]), None) for i in listing
                        if not (i["date"] and cutoff and i["date"] < cutoff)]     # never resurrect old posts
        merged: dict[int, tuple] = {e[0]: e for e in entries}
        for e in from_listing:
            merged.setdefault(e[0], e)
        all_entries = sorted(merged.values())
        if not all_entries:
            if not fresh_sitemap and listing_error:
                raise FetchError(f"latest-news page failed: {listing_error}")
            return 0, total

        if first_run:
            n = self._baseline(all_entries)
            self._apply_listing_meta(listing)
            if fresh_sitemap:
                self._commit_validators()
            self.db.kv_set("last_discover_ts", t0)
            return n, total
        known = self.db.known_ids()
        new = [e for e in all_entries if e[0] not in known]
        # Posts a manual date check filed as 'known' but that nobody queued or posted: the watcher would never post them.
        # (a) anything in the website's Latest News list right now is, by definition, a new post -> deliver it;
        # (b) anything a date check found since the previous poll (it may already have dropped out of that list).
        cutoff = self._cutoff_date()
        listed = {i["id"] for i in listing if not (i["date"] and cutoff and i["date"] < cutoff)}
        revive = sorted(set(self.db.unqueued_scanned_since(0, cutoff)) & listed
                        | (set(self.db.unqueued_scanned_since(prev_poll, cutoff)) if prev_poll else set()))
        queued = 0
        if revive and len(new) + len(revive) <= self.s.max_auto_queue:
            for pid in revive:
                if self.db.enqueue(pid, 0, "new"):
                    queued += 1
            self.db.log("info", f"queued {len(revive)} new post(s) that a date check had found first: "
                                + ", ".join(str(p) for p in revive[:10]))
        elif revive:
            self.db.log("warn", f"{len(revive)} new post(s) found by a date check were not auto-posted (too many at once); "
                                f"use 'Repost older posts by date'.")
        # Posts newer than the daily sitemap that no list on the homepage shows (other sections than toy news): probe the
        # newest post numbers, exactly like the date check does.
        probed: list[tuple] = []
        meta: dict[int, tuple] = {}
        if sitemap_max:
            probed, meta = self._probe_recent(known, {e[0] for e in all_entries}, sitemap_max, 60 if manual else 12)
            new = new + probed
        self.db.kv_set("probe_info", json.dumps({"found": len(probed), "ts": time.time()}))
        if new:
            if len(new) > self.s.max_auto_queue:
                self.db.bulk_seen(new, "skipped", "flood-guard")
                msg = (f"{len(new)} unseen posts appeared at once (more than {self.s.max_auto_queue}); NOT auto-posted. "
                       f"Use 'Repost older posts by date' to publish them.")
                self.db.log("warn", msg)
                log.warning(msg)
            else:
                self.db.bulk_seen(new, "pending", "new", priority=0)
                queued += len(new)
                self.db.log("info", f"discovered {len(new)} new post(s): " + ", ".join(str(e[0]) for e in new[:10]))
        for pid, (title, date) in meta.items():
            self.db.set_meta(pid, title, date)
        self._apply_listing_meta(listing)
        if fresh_sitemap:
            self._commit_validators()
        self.db.kv_set("last_discover_ts", t0)
        return queued, total

    LOOKAHEAD = 20                      # post numbers probed beyond the newest one known
    MISS_BACKOFF = (300, 900, 3600, 7200)   # seconds before a post number that did not exist is asked about again

    def _probe_recent(self, known: set[int], seen_now: set[int], sitemap_max: int, cap: int):
        """-> ([(post_id, url, None)], {post_id: (title, date)}).

        The sitemap is rebuilt once a day and the homepage list shows toy news only, so a post of another section
        (ACG, J-Movies, ...) can be live for hours without being listed anywhere. Post numbers grow with time, so ask
        for the numbers above the sitemap that nobody has accounted for. Numbers that do not exist are remembered and
        asked again after 5 min, 15 min, 1 h, 2 h, then left to the next sitemap rebuild."""
        top = max(seen_now | {sitemap_max, max(known) if known else 0})
        hi = top + self.LOOKAHEAD
        lo = max(sitemap_max + 1, hi - 400)
        misses = self.db.kv_json("probe_misses", {})
        now = time.time()
        cutoff = self._cutoff_date()
        due = []
        # closest to the newest known number first, in both directions: the post just below it (another section,
        # published a bit earlier) and the ones just above it (published since) matter most
        for pid in sorted(range(lo, hi + 1), key=lambda n: (abs(n - top), -n)):
            if pid in known or pid in seen_now:
                continue
            m = misses.get(str(pid))
            if m and (m[0] > len(self.MISS_BACKOFF) or now - m[1] < self.MISS_BACKOFF[m[0] - 1]):
                continue
            due.append(pid)
        found, meta, errors = [], {}, 0
        for pid in due[:cap]:
            try:
                art = self.fetch_article(pid)
            except NotFound:
                art = None
            except FetchError as e:
                errors += 1
                log.info("probing post %s failed: %s", pid, e)
                if errors >= 3:
                    break
                continue
            is_post = bool(art and art.title and (art.paragraphs or art.images or art.cover)
                           and not (art.lang and not art.lang.lower().startswith("en")))
            if not is_post:
                cnt = (misses.get(str(pid)) or [0, 0])[0] + 1
                misses[str(pid)] = [cnt, now]
                continue
            misses.pop(str(pid), None)
            if art.post_date and cutoff and art.post_date < cutoff:
                self.db.bulk_seen([(pid, self.post_url(pid), None)], "skipped", "probe-old")
                continue
            found.append((pid, self.post_url(pid), None))
            meta[pid] = (art.title, art.post_date)
        self.db.kv_set("probe_misses", json.dumps(dict(sorted(misses.items())[-3000:])))
        if found:
            self.db.log("info", f"found {len(found)} post(s) newer than the sitemap by probing: "
                                + ", ".join(str(f[0]) for f in found[:10]))
        return found, meta

    def _cutoff_date(self) -> str | None:
        if self.s.listing_max_age_days <= 0:
            return None
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        today = datetime.now(ZoneInfo(self.s.site_tz)).date()
        return (today - timedelta(days=self.s.listing_max_age_days)).isoformat()

    def _apply_listing_meta(self, listing: list[dict]) -> None:
        for it in listing:
            if self.db.get(it["id"]) and (it["title"] or it["date"]):
                self.db.set_meta(it["id"], it["title"], it["date"])

    def _baseline(self, entries) -> int:
        """First run of the watcher. Everything already on the site is marked 'seen' (not posted) so the channel is
        not flooded - EXCEPT, when the ledger already holds published posts (e.g. you posted by date first), posts newer
        than the newest published one: those are exactly the new posts you expect the watcher to deliver."""
        known = self.db.known_ids()
        ref = self.db._q("SELECT MAX(post_id) m FROM posts WHERE status='posted'")[0]["m"]
        newer = [e for e in entries if ref is not None and e[0] > ref and e[0] not in known]
        if len(newer) > self.s.max_auto_queue:
            self.db.log("warn", f"{len(newer)} posts are newer than your last published one (more than "
                                f"{self.s.max_auto_queue}); NOT auto-posted. Use 'Repost older posts by date' for them.")
            newer = []
        newer_ids = {e[0] for e in newer}
        rest = [e for e in entries if e[0] not in newer_ids]
        n = self.db.bulk_seen(rest, "skipped", "baseline")
        if newer:
            self.db.bulk_seen(newer, "pending", "new", priority=0)
        latest = sorted(entries, key=lambda e: e[0], reverse=True)[: self.s.initial_post_latest]
        for e in sorted(latest):
            self.db.enqueue(e[0], 0, "new")
        self.db.kv_set("baseline_done", int(time.time()))
        self.db.log("info", f"website watcher started: {n} existing posts marked as seen (not posted); "
                            f"queued {len(newer) + len(latest)} newer post(s)")
        return len(newer) + len(latest)

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

    def _already_in_channel(self, pid: int) -> str | None:
        """Last line of defence against duplicates: if the ledger says a message of this post may still be in the
        channel, check it before sending another copy."""
        live = self.db.live_messages(pid)
        if not live or self.tg is None or self.s.dry_run:
            return None
        for mid in live:
            if self._probe(mid) is True:
                self.db.mark_posted(pid, mid)
                self.db.log("warn", f"post {pid}: not sent again - message {mid} is still in the channel")
                return "posted"
        if self.probe_trusted() and all(self._probe(m) is False for m in live):
            for m in live:
                self.db.mark_message_deleted(pid, m)
            return None                                   # every old copy is proven gone: fine to send
        self.db.mark_uncertain(pid, f"an earlier copy (message {live[-1]}) may still be in the channel; check, then "
                                    f"choose 'It is in the channel' or 'Send again'")
        self.db.log("warn", f"post {pid}: held back - cannot confirm that message {live[-1]} was deleted")
        return "uncertain"

    def process(self, row: dict, force: bool = False) -> str:
        """Publish one queued row and record the outcome. Returns the resulting status.
        force=True (the user explicitly chose 'post it AGAIN') skips the already-in-channel guard."""
        pid = row["post_id"]
        if not self.db.mark_sending(pid):
            return "skipped"
        guard = None if force else self._already_in_channel(pid)
        if guard:
            return guard
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
        self._calibrate_probe(mid)
        row = self.db.get(pid) or {}
        self.db.log("info", f"posted {pid}: {row.get('title') or ''}")
        return "posted"

    # ------------------------------------------------------------------ update check
    def maybe_check_update(self, every: float = 43200.0) -> None:
        """Twice a day look for a newer version (only records it: the user presses the button)."""
        if time.time() - float(self.db.kv_get("last_update_check", "0") or 0) < every:
            return
        self.db.kv_set("last_update_check", time.time())
        try:
            self.db.kv_set("update_info", json.dumps(updater.check(self.s)))
        except updater.UpdateError as e:
            log.info("update check: %s", e)

    # ------------------------------------------------------------------ automatic backups
    BACKUP_KEEP = 14
    PLAN_PROBES = 10         # a date check asks Telegram at most this many times; the rest is left to the background checker
    FRESH_SECONDS = 1800     # a message confirmed in the channel within this time is not asked about again
    GAP_LIMIT = 400          # most IDs probed between the daily sitemap and the newest listed post

    def backup_dir(self):
        return self.s.data_dir / "backups"

    def maybe_backup(self, every: float = 86400.0) -> str | None:
        """Once a day: dated copy of the ledger in <data>/backups, keeping the newest BACKUP_KEEP."""
        last = float(self.db.kv_get("last_backup_ts", "0") or 0)
        if time.time() - last < every:
            return None
        d = self.backup_dir()
        dest = d / f"tpclone-{time.strftime('%Y-%m-%d_%H%M')}.db"
        self.db.backup_to(str(dest))
        self.db.kv_set("last_backup_ts", time.time())
        for old in sorted(d.glob("tpclone-*.db"))[:-self.BACKUP_KEEP]:
            old.unlink(missing_ok=True)
        self.db.log("info", f"automatic backup saved: {dest.name}")
        return str(dest)

    # ------------------------------------------------------------------ channel verification / manual post
    def _probe(self, mid) -> bool | None:
        """Ask Telegram whether a channel message exists, at a shared gentle pace (foreground, background and guards all
        go through here). While Telegram has asked us to slow down the answer is simply None ('cannot tell')."""
        with self._probe_lock:
            if time.time() < self.bg_pause_until:
                return None
            wait = self._probe_last + self.probe_gap - time.time()
            if wait > 0:
                time.sleep(wait)
            try:
                return self.tg.message_exists(mid)
            except TelegramError as e:
                if e.code == 429:
                    self.bg_pause_until = time.time() + float(e.retry_after or 60) + 2
                    log.info("Telegram says slow down: no channel checks for %.0fs", float(e.retry_after or 60))
                    return None
                raise
            finally:
                self._probe_last = time.time()

    def _calibrate_probe(self, mid) -> None:
        """Right after a send we KNOW the message exists: use it to prove that the 'was it deleted?' probe is honest.
        If the probe claims a just-posted message is gone, deletion detection is switched off (no silent reposts)."""
        if not mid or self.tg is None:
            return
        try:
            res = self._probe(mid)
        except Exception:   # noqa: BLE001  (never let calibration disturb posting)
            return
        if res is True:
            if self.db.kv_get("probe_ok") != "1":
                self.db.kv_set("probe_ok", "1")
        elif res is False:
            self.db.kv_set("probe_ok", "0")
            self.db.log("warn", "deleted-post detection switched OFF: Telegram answered 'not found' for a message that "
                                "was just posted, so it can't be trusted. Nothing will be re-posted automatically.")

    def probe_trusted(self) -> bool:
        return self.db.kv_get("probe_ok") == "1"

    def verify_posted(self, ids=None, progress: Callable[[str], None] | None = None, limit: int = 300,
                      force: bool = False, max_probes: int | None = None) -> dict:
        """Check that posts we think are published still exist in the channel.

        A post can have SEVERAL messages in the channel (re-posts, duplicates). It only becomes publishable again when
        EVERY message ever sent for it is proven gone; if any is still there it stays 'posted'."""
        say = progress or (lambda m: None)
        rows = self.db.posted_with_message(ids, limit)
        res = {"checked": 0, "deleted": [], "unknown": 0}
        if self.tg is None or not rows:
            return res
        if not self.probe_trusted():       # not proven yet (needs one successful post) -> never mark anything deleted
            res["unknown"] = len(rows)
            res["note"] = "deleted-post detection becomes active after the next successful post"
            return res
        for k, r in enumerate(rows):
            pid = r["post_id"]
            live = self.db.live_messages(pid) or ([r["tg_message_id"]] if r["tg_message_id"] else [])
            alive, unsure = [], False
            for mid in live:
                if max_probes is not None and res["checked"] >= max_probes:
                    alive.append(mid)            # enough questions for now; the background checker finishes the rest
                    res["deferred"] = res.get("deferred", 0) + 1
                    continue
                age = None if force else self.db.verified_age(pid, mid)
                if age is not None and age < self.FRESH_SECONDS:
                    alive.append(mid)            # confirmed a few minutes ago: no need to ask Telegram again
                    res["skipped"] = res.get("skipped", 0) + 1
                    continue
                ok = self._probe(mid)
                res["checked"] += 1
                if ok is False:
                    self.db.mark_message_deleted(pid, mid)
                else:
                    alive.append(mid)
                    if ok is True:
                        self.db.touch_verified(pid, mid)
                    unsure = unsure or ok is None
            if not alive:
                self.db.mark_deleted(pid)
                res["deleted"].append(pid)
            else:
                if r["tg_message_id"] not in alive:
                    self.db._x("UPDATE posts SET tg_message_id=? WHERE post_id=?", (alive[-1], pid))
                if unsure:
                    res["unknown"] += 1
            if k % 5 == 0:
                say(f"checking the channel {k + 1}/{len(rows)}")
        if res["deleted"]:
            self.db.log("info", f"channel check: {len(res['deleted'])} post(s) were deleted from the channel -> "
                                f"publishable again: {res['deleted'][:15]}")
        return res

    def background_verify_step(self) -> bool:
        """Idle-time housekeeping: re-confirm ONE old message per call (the stalest first), so deleted posts are noticed
        within minutes and a date check finds everything already verified. Returns True if Telegram was asked."""
        if self.tg is None or self.s.dry_run or not self.probe_trusted() or time.time() < self.bg_pause_until:
            return False
        item = self.db.stalest_message(self.FRESH_SECONDS)
        if item is None:
            return False
        pid, mid = item
        try:
            ok = self._probe(mid)
        except Exception as e:  # noqa: BLE001   (anything else: back off, never disturb posting)
            self.bg_pause_until = time.time() + 600
            log.info("background channel check paused: %s", e)
            return False
        if ok is None and time.time() < self.bg_pause_until:
            return False                      # Telegram asked us to slow down
        if ok is True:
            self.db.touch_verified(pid, mid)
        elif ok is False:
            self.db.mark_message_deleted(pid, mid)
            if not self.db.live_messages(pid):
                self.db.mark_deleted(pid)
                self.db.log("info", f"post {pid} was deleted from the channel -> publishable again")
        else:
            self.db.touch_verified(pid, mid)     # can't tell: don't retry the same one every few seconds
        return True

    def register_message(self, post_id: int, message_id: int) -> dict:
        """The user tells us 'this post is already in my channel as message N' (e.g. a copy the app lost track of)."""
        if self.db.get(post_id) is None:
            self.db.upsert_seen(post_id, self.post_url(post_id), None, "known", "manual")
        self.db.mark_posted(post_id, message_id)
        self.db.log("info", f"post {post_id} registered as already in the channel (message {message_id})")
        return {"status": "posted", "message_id": message_id}

    def post_now(self, post_id: int, force: bool = False) -> dict:
        """Publish one post immediately (manual button). Refuses to duplicate unless force=True."""
        if self.tg is None:
            return {"status": "error", "error": "Set the bot token and channel first (Settings)."}
        row = self.db.get(post_id)
        if row is None:
            self.db.upsert_seen(post_id, self.post_url(post_id), None, "known", "manual")
            row = self.db.get(post_id)
        if row["status"] == "sending":
            return {"status": "sending", "error": "this post is being sent right now"}
        if row["status"] == "posted" and not force:
            live = self.db.live_messages(post_id) or ([row["tg_message_id"]] if row.get("tg_message_id") else [])
            gone = bool(live) and self.probe_trusted() and all(self._probe(m) is False for m in live)
            if gone:
                for m in live:
                    self.db.mark_message_deleted(post_id, m)
                self.db.mark_deleted(post_id)
            else:
                return {"status": "posted", "already": True, "messages": live}
        self.db.reset_status(post_id, "pending")
        status = self.process(self.db.get(post_id), force=force)
        return {"status": status, "error": (self.db.get(post_id) or {}).get("last_error")}

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
        sitemap_max = ids[-1] if ids else 0
        # The sitemap is rebuilt only once a day, so the newest posts are missing from it. Add what the website shows
        # right now (Latest News) and, below, probe the IDs in between.
        say("reading the Latest News list")
        try:
            listing = self.fetch_listing()
        except Exception as e:  # noqa: BLE001
            listing = []
            say(f"(Latest News list unavailable: {e})")
        ids = sorted(set(ids) | {i["id"] for i in listing})
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
        # IDs between the (stale) sitemap and the newest listed post: posts published since the sitemap was rebuilt
        if listing and max(i["id"] for i in listing) > sitemap_max:
            listed = {i["id"] for i in listing}
            gap = [p for p in range(sitemap_max + 1, max(listed) + 1) if p not in listed][-self.GAP_LIMIT:]
            missing = set(self.db.kv_json("gap_missing", []))
            for k, pid in enumerate(gap):
                if pid in missing:
                    continue
                try:
                    d, t = self._meta_for(pid)
                except FetchError:
                    continue
                if d is None and t is None:
                    missing.add(pid)
                elif d == date:
                    found[pid] = t
                if k % 10 == 0:
                    say(f"checking posts newer than the sitemap {k}/{len(gap)} ({len(found)} posts on {date})")
            self.db.kv_set("gap_missing", json.dumps(sorted(missing)[-5000:]))
        for r in self.db.by_date(date):
            found.setdefault(r["post_id"], r.get("title"))

        # record them (visible on the site, nothing queued yet)
        self.db.bulk_seen([(p, self.post_url(p), lm.get(p)) for p in found], "known", "date-scan", priority=1)
        for p, t in found.items():     # titles/dates fetched before the row existed were not saved yet
            self.db.set_meta(p, t, date)
        gone: list[int] = []
        if self.tg is not None:   # did the user delete some of them from the channel?
            say("checking which posts still exist in the channel")
            gone = self.verify_posted(list(found), say, max_probes=self.PLAN_PROBES)["deleted"]
        rows = {p: self.db.get(p) for p in found}
        posted = sorted(p for p, r in rows.items() if r and r["status"] == "posted")
        unpublished = sorted(p for p in found if p not in posted)
        queued = [p for p in unpublished if rows[p] and rows[p]["status"] in ("pending", "sending")]
        uncertain = [p for p in unpublished if rows[p] and rows[p]["status"] == "uncertain"]
        prev = self.db.kv_json(f"date_batch:{date}", [])
        new_since = [p for p in unpublished if p not in prev]

        msgs = self.db.messages_by_post(found)
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
        if not self.db.count("posted") and state in ("none", "partial"):
            msg += (" ⚠ This app has no record of having posted anything yet. If your channel ALREADY contains posts of "
                    "this date (for example you moved or re-downloaded the app), first import your old posted-list "
                    "(Backup card → Import) to avoid duplicates.")
        if (self.tg is not None and not gone and not self.probe_trusted()
                and any(r and r["status"] == "posted" and r.get("tg_message_id") for r in rows.values())):
            msg += (" (To also detect posts you deleted from the channel, first send one test post: "
                    "Settings → “Send a test post”.)")
        if gone:
            msg += f" ({len(gone)} post(s) of this date were deleted from the channel and can be published again.)"
        if uncertain:
            msg += f" ({len(uncertain)} need manual review - delivery was uncertain; they are not re-sent automatically.)"
        return {
            "date": date, "state": state, "message": msg, "total": total,
            "published": posted, "to_publish": [p for p in unpublished if p not in uncertain],
            "already_queued": queued, "uncertain": uncertain, "deleted_from_channel": gone,
            "posts": [{"id": p, "title": (rows[p] or {}).get("title"), "status": (rows[p] or {}).get("status"),
                       "messages": msgs.get(p, [])} for p in sorted(found)],
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
                        e.maybe_backup()
                    except Exception as ex:   # a failed backup must never stop publishing
                        log.warning("backup failed: %s", ex)
                    try:
                        e.maybe_check_update()
                    except Exception as ex:
                        log.info("update check failed: %s", ex)
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
                    did = False
                    try:
                        did = e.background_verify_step()
                    except Exception as ex:   # noqa: BLE001
                        log.info("background check failed: %s", ex)
                    self._stop.wait(6 if did else 5)      # ~10 questions a minute at most
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
