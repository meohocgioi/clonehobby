import json

import pytest

from tpclone.telegram import TelegramError, UncertainDelivery
from tpclone.engine import Worker


def add_posts(fetcher, spec):
    for pid, (date, title) in spec.items():
        fetcher.posts[pid] = (date, title)


def test_first_start_baselines_without_posting(env):
    e, f, tg, db = env
    add_posts(f, {i: ("2026-09-20", f"T{i}") for i in range(1, 6)})
    assert e.discover() == 0
    assert db.stats().get("skipped") == 5 and db.pending_count() == 0 and tg.sent == []
    assert e.discover() == 0                      # idempotent


def test_initial_post_latest(env):
    e, f, tg, db = env
    e.s.initial_post_latest = 2
    add_posts(f, {i: ("2026-09-20", f"T{i}") for i in range(1, 6)})
    assert e.discover() == 2
    assert [p["post_id"] for p in (db.next_pending(),)] == [4]    # oldest of the latest two first


def test_new_posts_queued_posted_once(env):
    e, f, tg, db = env
    add_posts(f, {1: ("2026-09-20", "Old")})
    e.discover()
    add_posts(f, {2: ("2026-09-25", "New A"), 3: ("2026-09-25", "New B")})
    assert e.discover() == 2
    while (row := db.next_pending()):
        assert e.process(row) == "posted"
    assert len(tg.sent) == 2 and db.count("posted") == 2
    assert e.discover() == 0 and db.pending_count() == 0           # nothing re-queued
    assert tg.sent[0]["html"].startswith("<h6>")
    # a second engine instance on the same DB ("app restarted after days off") must not repost anything
    from tpclone.engine import Engine
    e2 = Engine(e.s, db, f, tg)
    assert e2.discover() == 0 and len(tg.sent) == 2


def test_flood_guard(env):
    e, f, tg, db = env
    e.s.max_auto_queue = 3
    add_posts(f, {1: ("2026-09-20", "x")})
    e.discover()
    add_posts(f, {i: ("2026-09-25", f"n{i}") for i in range(2, 12)})
    assert e.discover() == 0 and db.pending_count() == 0 and db.count("skipped") == 11


def test_uncertain_never_auto_resent(env):
    e, f, tg, db = env
    add_posts(f, {1: ("2026-09-20", "x")}); e.discover()
    add_posts(f, {2: ("2026-09-25", "y")}); e.discover()
    tg.fail_with = UncertainDelivery("timeout")
    assert e.process(db.next_pending()) == "uncertain"
    assert db.next_pending() is None and db.get(2)["status"] == "uncertain" and tg.sent == []
    assert e.discover() == 0 and db.next_pending() is None


def test_crash_mid_send_becomes_uncertain_on_start(env):
    e, f, tg, db = env
    add_posts(f, {1: ("2026-09-20", "x")}); e.discover()
    add_posts(f, {2: ("2026-09-25", "y")}); e.discover()
    assert db.mark_sending(2)                       # process dies here
    assert db.resolve_uncertain_stale() == 1 and db.get(2)["status"] == "uncertain"


def test_telegram_errors_retry_then_fail(env):
    e, f, tg, db = env
    add_posts(f, {1: ("2026-09-20", "x")}); e.discover()
    add_posts(f, {2: ("2026-09-25", "y")}); e.discover()
    for _ in range(6):
        tg.fail_with = TelegramError("Bad Request: something", 400)
        row = db.get(2)
        db.conn.execute("UPDATE posts SET not_before=0 WHERE post_id=2"); db.conn.commit()
        e.process(db.next_pending() or db.get(2) | {"post_id": 2})
    assert db.get(2)["status"] == "failed"


def test_fatal_telegram_error_halts_worker(env):
    e, f, tg, db = env
    add_posts(f, {1: ("2026-09-20", "x")}); e.discover()
    add_posts(f, {2: ("2026-09-25", "y")}); e.discover()
    tg.fail_with = TelegramError("Forbidden: bot was kicked from the channel chat", 403)
    with pytest.raises(TelegramError):
        e.process(db.next_pending())
    assert db.get(2)["status"] == "pending"          # not lost, not marked failed


def test_dry_run_does_not_touch_ledger(env):
    e, f, tg, db = env
    e.s.dry_run = True
    add_posts(f, {1: ("2026-09-20", "x")}); e.discover()
    add_posts(f, {2: ("2026-09-25", "y")}); e.discover()
    assert e.process(db.next_pending()) == "known" and db.count("posted") == 0 and tg.sent == []


def test_start_stop_resume(env):
    e, f, tg, db = env
    e.s.poll_interval_seconds = 0
    add_posts(f, {1: ("2026-09-20", "x")}); e.discover()
    add_posts(f, {i: ("2026-09-25", f"n{i}") for i in range(2, 6)}); e.discover()
    e.pacer.delay = 0
    w = Worker(e)
    w.start()
    import time
    for _ in range(100):
        if db.count("posted") >= 1:
            break
        time.sleep(0.05)
    w.stop(wait=True)
    assert w.state() == "stopped" and db.kv_get("desired_state") == "stopped"
    done = db.count("posted")
    assert done >= 1 and done + db.pending_count() == 4          # progress saved, nothing lost or duplicated
    time.sleep(0.2)
    assert db.count("posted") == done                             # really stopped
    w.start()                                                     # resume exactly where it left off
    for _ in range(200):
        if db.count("posted") == 4:
            break
        time.sleep(0.05)
    w.stop(wait=True)
    assert db.count("posted") == 4 and len(tg.sent) == 4          # each exactly once


# ------------------------------------------------------------------ date repost
def seed_site(f, ids_dates):
    for pid, d in ids_dates.items():
        f.posts[pid] = (d, f"Post {pid}")


def test_plan_date_binary_search_finds_only_that_day(env):
    e, f, tg, db = env
    spec = {}
    pid = 1000
    for day in range(1, 31):
        for k in range(8):
            spec[pid] = f"2026-09-{day:02d}"; pid += 1
    seed_site(f, spec)
    plan = e.plan_date("2026-09-25", margin=3)
    want = sorted(p for p, d in spec.items() if d == "2026-09-25")
    assert [p["id"] for p in plan["posts"]] == want and plan["state"] == "none"
    # far fewer fetches than a full scan
    assert len(db.known_ids()) < 100


def test_date_flow_messages_and_no_duplicates(env):
    e, f, tg, db = env
    e.pacer.delay = 0
    seed_site(f, {1: "2026-09-24", 2: "2026-09-25", 3: "2026-09-25", 4: "2026-09-26"})
    plan = e.plan_date("2026-09-25", margin=2)
    assert plan["state"] == "none" and plan["to_publish"] == [2, 3]
    assert e.enqueue_date("2026-09-25", plan["to_publish"]) == 2
    while (row := db.next_pending()):
        e.process(row)
    assert len(tg.sent) == 2

    # same date again: must not publish anything
    plan = e.plan_date("2026-09-25", margin=2)
    assert plan["state"] == "all_published" and plan["to_publish"] == []
    assert "already published all 2 post(s) from 2026-09-25" in plan["message"]
    assert e.enqueue_date("2026-09-25", plan["to_publish"]) == 0 and db.pending_count() == 0

    # website adds posts to that date later (back-dated: their ids are higher than the 09-26 post's)
    seed_site(f, {5: "2026-09-25", 6: "2026-09-25"})
    plan = e.plan_date("2026-09-25", margin=2, tail=10)
    assert plan["state"] == "new_since" and plan["to_publish"] == [5, 6]
    assert "added 2 new post(s) since then" in plan["message"] and "publish only the new posts" in plan["message"]
    e.enqueue_date("2026-09-25", plan["to_publish"])
    while (row := db.next_pending()):
        e.process(row)
    assert len(tg.sent) == 4
    assert e.plan_date("2026-09-25", margin=2, tail=10)["state"] == "all_published"


def test_date_repost_does_not_reenqueue_posted_or_inflight(env):
    e, f, tg, db = env
    seed_site(f, {1: "2026-09-25"})
    e.plan_date("2026-09-25", margin=1)
    db.mark_posted(1, 9)
    assert db.enqueue(1, 1, "repost") is False
    db.reset_status(1, "known"); db.enqueue(1, 1, "repost"); db.mark_sending(1)
    assert db.enqueue(1, 1, "repost") is False


def test_empty_date(env):
    e, f, tg, db = env
    seed_site(f, {1: "2026-09-24", 2: "2026-09-26"})
    assert e.plan_date("2026-09-25", margin=1)["state"] == "empty"


def test_import_history_marks_posted(env, tmp_path):
    from tpclone import reconcile
    e, f, tg, db = env
    seed_site(f, {1: "2026-09-25", 2: "2026-09-25"})
    e.plan_date("2026-09-25", margin=1)               # ledger learns titles ("Post 1", "Post 2")
    db.conn.execute("UPDATE posts SET title='Kotobukiya Megalo Maria model kit' WHERE post_id=2"); db.conn.commit()
    export = {"messages": [
        {"id": 5, "text": [{"type": "text_link", "text": "x", "href": "https://www.toy-people.com/en/?p=1"}]},
        {"id": 6, "text": "Kotobukiya Megalo Maria model kit"}, {"id": 7, "text": "unrelated"}]}
    p = tmp_path / "result.json"; p.write_text(json.dumps(export))
    res = reconcile.import_export(db, str(p), "https://www.toy-people.com/en/")
    assert res["recognised"] == 2 and db.get(1)["status"] == "posted" and db.get(2)["status"] == "posted"
    assert e.plan_date("2026-09-25", margin=1)["state"] == "all_published"


def test_deleted_from_channel_is_detected_and_republishable(env):
    e, f, tg, db = env
    e.pacer.delay = 0
    seed_site(f, {1: "2026-09-30", 2: "2026-09-30", 3: "2026-09-30"})
    plan = e.plan_date("2026-09-30", margin=2)
    e.enqueue_date("2026-09-30", plan["to_publish"])
    while (row := db.next_pending()):
        e.process(row)
    assert db.count("posted") == 3
    mids = {p: db.get(p)["tg_message_id"] for p in (1, 2, 3)}
    assert e.plan_date("2026-09-30", margin=2)["state"] == "all_published"      # nothing deleted yet

    tg.deleted |= {mids[1], mids[2], mids[3]}                                    # user wipes the channel
    plan = e.plan_date("2026-09-30", margin=2)
    assert plan["state"] in ("none", "partial", "new_since") and plan["to_publish"] == [1, 2, 3]
    assert plan["deleted_from_channel"] == [1, 2, 3] and "deleted from the channel" in plan["message"]
    assert db.count("posted") == 0 and db.get(1)["tg_message_id"] is None
    e.enqueue_date("2026-09-30", plan["to_publish"])
    while (row := db.next_pending()):
        e.process(row)
    assert db.count("posted") == 3 and len(tg.sent) == 6


def test_partial_delete_and_unknown_kept(env):
    e, f, tg, db = env
    seed_site(f, {1: "2026-09-30", 2: "2026-09-30"})
    e.plan_date("2026-09-30", margin=1)
    for p, m in ((1, 11), (2, 12)):
        db.mark_posted(p, m)
    db.kv_set("probe_ok", "1")
    tg.deleted.add(11); tg.unknown.add(12)
    res = e.verify_posted()
    assert res == {"checked": 2, "deleted": [1], "unknown": 1}
    assert db.get(1)["status"] == "known" and db.get(2)["status"] == "posted"   # undecidable -> never assume deleted


def test_post_now(env):
    e, f, tg, db = env
    seed_site(f, {7: "2026-09-30"})
    r = e.post_now(7)
    assert r["status"] == "posted" and len(tg.sent) == 1
    assert e.post_now(7) == {"status": "posted", "already": True} and len(tg.sent) == 1     # no accidental duplicate
    r = e.post_now(7, force=True)
    assert r["status"] == "posted" and len(tg.sent) == 2                                    # explicit re-post
    tg.deleted.add(db.get(7)["tg_message_id"])
    assert e.post_now(7)["status"] == "posted" and len(tg.sent) == 3                       # deleted -> posts again
    assert e.post_now(999)["status"] in ("known", "pending", "failed")                      # unknown id: handled, no crash


def test_post_now_unconfigured(env):
    e, f, tg, db = env
    e.tg = None
    assert e.post_now(1)["status"] == "error"


def test_plan_date_saves_titles_for_new_rows(env):
    e, f, tg, db = env
    seed_site(f, {1: "2026-09-30"})
    plan = e.plan_date("2026-09-30", margin=1)
    assert plan["posts"][0]["title"] == "Post 1" and db.get(1)["title"] == "Post 1" and db.get(1)["post_date"] == "2026-09-30"


def test_automatic_backup_daily_retention_and_restore(env, tmp_path):
    from tpclone.db import DB
    e, f, tg, db = env
    e.s.db_path = str(tmp_path / "data" / "tpclone.db")
    e.BACKUP_KEEP = 3
    bdir = tmp_path / "data" / "backups"
    bdir.mkdir(parents=True)
    for d in range(1, 6):                                          # five old backups already there
        (bdir / f"tpclone-2020-01-0{d}_0000.db").write_bytes(b"old")
    seed_site(f, {1: "2026-09-30"})
    e.plan_date("2026-09-30", margin=1)
    db.mark_posted(1, 77)
    new = e.maybe_backup()
    assert new and e.maybe_backup() is None                        # only once a day
    names = sorted(p.name for p in bdir.glob("tpclone-*.db"))
    assert len(names) == 3 and names[0] == "tpclone-2020-01-04_0000.db" and new.endswith(names[-1])  # oldest pruned
    restored = DB(new)                                             # a backup is a complete, usable ledger
    assert restored.get(1)["status"] == "posted" and restored.get(1)["tg_message_id"] == 77


def test_untrusted_probe_never_causes_duplicates(env):
    """If the 'deleted?' probe lies (says a message we just posted is gone) nothing may be re-posted silently."""
    e, f, tg, db = env
    seed_site(f, {7: "2026-09-30"})
    tg.deleted_always = True
    orig = tg.message_exists
    tg.message_exists = lambda mid: False                 # a broken probe: claims everything is deleted
    assert e.post_now(7)["status"] == "posted" and len(tg.sent) == 1
    assert db.kv_get("probe_ok") == "0"                   # calibration right after the send caught it
    assert e.post_now(7) == {"status": "posted", "already": True} and len(tg.sent) == 1   # no silent duplicate
    assert e.verify_posted() ["deleted"] == [] and db.get(7)["status"] == "posted"
    seed_site(f, {8: "2026-09-30"})
    assert e.plan_date("2026-09-30", margin=2)["deleted_from_channel"] == []
    tg.message_exists = orig


def test_merge_posted_list_from_old_backup(env, tmp_path):
    from tpclone.db import DB
    e, f, tg, db = env
    seed_site(f, {1: "2026-09-30", 2: "2026-09-30"})
    old = DB(str(tmp_path / "old.db"))
    old.upsert_seen(1, "u1", None, "known", "x"); old.set_meta(1, "T1", "2026-09-30"); old.mark_posted(1, 55)
    old.upsert_seen(99, "u99", None, "known", "x"); old.mark_posted(99, 56)
    old.upsert_seen(2, "u2", None, "pending", "x")                       # not posted there: must NOT be imported
    old.conn.commit()
    e.plan_date("2026-09-30", margin=1)
    assert db.get(1)["status"] == "known"
    res = db.merge_posted_from(str(tmp_path / "old.db"))
    assert res == {"in_file": 2, "added": 1, "updated": 1}
    assert db.get(1)["status"] == "posted" and db.get(1)["tg_message_id"] == 55 and db.get(99)["status"] == "posted"
    assert db.get(2)["status"] == "known"
    assert db.merge_posted_from(str(tmp_path / "old.db")) == {"in_file": 2, "added": 0, "updated": 0}   # idempotent
    plan = e.plan_date("2026-09-30", margin=1)
    assert plan["published"] == [1] and plan["to_publish"] == [2]


def test_plan_warns_when_nothing_ever_posted(env):
    e, f, tg, db = env
    seed_site(f, {1: "2026-09-30"})
    assert "no record of having posted anything" in e.plan_date("2026-09-30", margin=1)["message"]


def test_date_check_must_not_hide_new_posts_from_the_watcher(env):
    """Regression: plan_date used to save the sitemap ETag, so the next discover() got '304 not modified' and the
    new post that appeared before the date check was never queued."""
    e, f, tg, db = env
    add_posts(f, {1: ("2026-09-20", "Old")})
    e.discover()                                              # baseline
    add_posts(f, {2: ("2026-10-02", "Brand new post")})       # appears on the website ...
    seed_site(f, {3: "2026-09-30"})
    e.plan_date("2026-09-30", margin=2)                       # ... then the user checks a date (downloads the sitemap)
    assert e.discover() == 1                                  # watcher still sees the new post 2 ...
    assert db.get(2)["status"] == "pending"
    assert db.get(3)["status"] == "known"                     # ... while post 3 (found by the date check) is not auto-posted


def test_first_discover_after_a_date_check_still_does_the_baseline(env):
    e, f, tg, db = env
    add_posts(f, {i: ("2026-09-20", f"T{i}") for i in range(1, 6)})
    seed_site(f, {})
    e.plan_date("2026-09-20", margin=2)                       # user used 'Repost by date' before ever pressing Start
    e.discover()
    assert db.kv_get("baseline_done") is not None and db.count() == 5


def test_baseline_on_existing_ledger_queues_posts_newer_than_the_last_posted(env):
    e, f, tg, db = env
    add_posts(f, {i: ("2026-09-20", f"T{i}") for i in range(1, 11)})
    db.upsert_seen(7, "u", None, "known", "x"); db.mark_posted(7, 70)      # user already published up to #7 by hand
    e.discover()                                                           # first ever watcher run
    assert [db.get(i)["status"] for i in (8, 9, 10)] == ["pending"] * 3    # newer than the last posted -> queued
    assert [db.get(i)["status"] for i in (1, 6)] == ["skipped", "skipped"] # older history is not posted


def test_baseline_flood_guard_for_big_backlog(env):
    e, f, tg, db = env
    e.s.max_auto_queue = 3
    add_posts(f, {i: ("2026-09-20", f"T{i}") for i in range(1, 21)})
    db.upsert_seen(2, "u", None, "known", "x"); db.mark_posted(2, 70)
    e.discover()
    assert db.pending_count() == 0 and db.count("skipped") == 19


def test_discovery_status_is_recorded(env):
    e, f, tg, db = env
    add_posts(f, {1: ("2026-09-20", "x")})
    e.discover()
    st = db.kv_json("discover_status")
    assert st["ok"] is True and st["total"] == 1 and st["new"] == 0 and st["ts"] > 0


def test_watcher_sees_posts_the_daily_sitemap_does_not_have(env):
    """The sitemap is rebuilt once a day; the homepage 'Latest News' is live. New posts must come from the latter."""
    e, f, tg, db = env
    import datetime
    today = datetime.datetime.now(__import__("zoneinfo").ZoneInfo(e.s.site_tz)).date().isoformat()
    add_posts(f, {1: ("2026-01-01", "Old")})
    e.discover()                                                           # baseline
    add_posts(f, {115078: (today, "Brand new A"), 115080: (today, "Brand new B")})
    f.hidden |= {115078, 115080}                                           # not in the sitemap yet
    f.listing = [115080, 115078]
    assert e.discover() == 2
    assert db.get(115078)["status"] == "pending" and db.get(115078)["title"] == "Brand new A"
    row = db.next_pending()
    assert row["post_id"] == 115078                                        # oldest first
    e.process(row)
    assert db.get(115078)["status"] == "posted"
    assert e.discover() == 0                                               # not queued twice


def test_old_listed_posts_are_never_auto_posted(env):
    e, f, tg, db = env
    add_posts(f, {1: ("2026-01-01", "Old")})
    e.discover()
    add_posts(f, {500: ("2020-01-01", "Ancient trending post")})
    f.hidden.add(500); f.listing = [500]
    assert e.discover() == 0 and db.get(500) is None


def test_listing_failure_does_not_break_the_sitemap_path(env):
    e, f, tg, db = env
    add_posts(f, {1: ("2026-09-20", "Old")})
    e.discover()
    add_posts(f, {2: ("2026-09-25", "New via sitemap")})
    orig = f.get_text
    f.get_text = lambda url, **kw: (_ for _ in ()).throw(RuntimeError("homepage down")) if "?p=" not in url else orig(url, **kw)
    assert e.discover() == 1
    assert db.kv_json("listing_info")["error"] and "homepage down" in db.kv_json("listing_info")["error"]


def test_first_run_queues_listed_posts_newer_than_last_posted(env):
    """Exactly the user's situation: posted up to 115034 by date, sitemap stale, newer posts only on the homepage."""
    e, f, tg, db = env
    import datetime
    today = datetime.datetime.now(__import__("zoneinfo").ZoneInfo(e.s.site_tz)).date().isoformat()
    add_posts(f, {115034: (today, "Last published")})
    db.upsert_seen(115034, "u", None, "known", "x"); db.mark_posted(115034, 9)
    add_posts(f, {115070: (today, "N1"), 115078: (today, "N2"), 115080: (today, "N3")})
    f.hidden |= {115070, 115078, 115080}; f.listing = [115080, 115078, 115070]
    assert e.discover() == 3
    assert [db.get(i)["status"] for i in (115070, 115078, 115080)] == ["pending"] * 3


def test_date_check_finds_posts_missing_from_the_stale_sitemap(env):
    """User's report: date check for today showed 7 posts although many more exist (115070, 115078, 115080...)."""
    e, f, tg, db = env
    seed_site(f, {115018: "2026-10-02", 115027: "2026-10-02", 115034: "2026-10-02"})
    seed_site(f, {i: "2026-10-02" for i in (115040, 115055, 115070, 115078, 115080)})
    f.hidden |= {115040, 115055, 115070, 115078, 115080}                  # newer than the daily sitemap
    f.listing = [115080, 115078, 115070]                                   # homepage shows only the newest few
    plan = e.plan_date("2026-10-02", margin=2)
    assert [p["id"] for p in plan["posts"]] == [115018, 115027, 115034, 115040, 115055, 115070, 115078, 115080]
    assert db.kv_json("gap_missing")                                       # non-existent ids in the gap are remembered
    before = len(f.requests)
    e.plan_date("2026-10-02", margin=2)                                    # second time: gap misses are not re-probed
    assert len(db.kv_json("gap_missing")) > 0
