import json
from pathlib import Path

import httpx
import pytest

from conftest import FIX, FakeTG, png
from tpclone import hpoi
from tpclone.config import Settings
from tpclone.db import DB
from tpclone.fetch import Page
from tpclone.translate import TranslateError, Translator

HOME = (Path(__file__).parent / "fixtures" / "hpoi_home.html").read_text(encoding="utf8")
ITEM = (Path(__file__).parent / "fixtures" / "hpoi_item.html").read_text(encoding="utf8")
HEAD = "Bushiroad Creative 孤独摇滚！ 毛绒玩偶挂件 vol.3 开订 每款1430日元含税 2027年4月出货"


def mock_google(calls=None, status=200):
    def handler(req: httpx.Request):
        q = req.url.params["q"]
        if calls is not None:
            calls.append(q)
        if status != 200:
            return httpx.Response(status, text="Sorry")
        return httpx.Response(200, json=[[[f"EN({q})", q, None, None, 1]], None, "zh-CN"])
    return httpx.Client(transport=httpx.MockTransport(handler))


def translator(tmp_path, **kw):
    t = Translator(DB(":memory:"), glossary_file=tmp_path / "g.json", client=mock_google(kw.pop("calls", None), kw.pop("status", 200)), endpoint="https://mock.test/t",
                   sleep=lambda s: None, **kw)
    return t


class HFetcher:
    def __init__(self):
        self.home = HOME
        self.item = ITEM
        self.urls = []

    def get_text(self, url, **kw):
        self.urls.append(url)
        return Page(url, 200, self.home if url == hpoi.BASE else self.item, {})

    def get_bytes(self, url, referer=None):
        return png(), "image/png"


def make(tmp_path):
    main = Settings(telegram_bot_token="t", telegram_chat_id="@main", db_path=str(tmp_path / "tpclone.db"),
                    post_delay_seconds=5, media_mode="url", hpoi_chat_id="")
    tg = FakeTG()
    e = hpoi.HpoiEngine(main, DB(":memory:"), HFetcher(), tg)
    e.probe_gap = 0
    e.translator = translator(tmp_path)
    return e, tg, main


def test_parse_listing_only_news_cards():
    cards = hpoi.parse_listing(HOME)
    assert len(cards) == 5                      # the decoy cover-list block is ignored
    c = cards[0]
    assert c["id"] == 137248 and c["headline"] == HEAD
    assert c["kind"] == "预定时间" and c["category"] == "毛绒布偶"
    assert c["cover"].endswith("9425255719d146419f33e9e5e530d226.jpg")
    assert c["key"] == hpoi.post_key(137248, HEAD)


def test_parse_item_fields_and_images():
    i = hpoi.parse_item(ITEM)
    assert i["fields"]["制作"] == ["Bushiroad Creative"]
    assert i["fields"]["角色"] == ["伊地知星歌", "音戏ALTO", "广井菊理", "后藤偶"]
    assert i["fields"]["作品"] == ["孤独摇滚！"]
    assert hpoi.scheduled_line(i["release"]) == "Scheduled Release: Apr 2027"
    assert len(i["images"]) == 5 and all("/gk/pic/n/" in u and "?" not in u for u in i["images"])
    assert "/gk/cover/n/" in i["cover"] and i["cover"] not in i["images"]


def test_scheduled_line_variants():
    assert hpoi.scheduled_line(["2026/12/25 , 9,000日元"]) == "Scheduled Release: Dec 25, 2026"
    assert hpoi.scheduled_line(["未定"]) is None
    assert hpoi.scheduled_line(["2027/4 , a", "2027/2 , b"]) == "Scheduled Release: Feb 2027"


def test_translator_cache_glossary_and_passthrough(tmp_path):
    calls = []
    t = translator(tmp_path, calls=calls)
    assert t.translate("Bushiroad Creative") == "Bushiroad Creative" and not calls      # no CJK: untouched
    assert t.translate("伊地知星歌") == "Ijichi Seika" and not calls                    # glossary
    out = t.translate("毛绒布偶")
    assert out == "EN(毛绒布偶)"
    t.translate("毛绒布偶")
    assert calls == ["毛绒布偶"]                                                          # cached
    t.translate("Bushiroad 孤独摇滚！ 毛绒")                                              # glossary applied inside text
    assert "Lonely Rock!" in calls[-1] and "孤独摇滚" not in calls[-1]


def test_translator_rate_limit_cools_down(tmp_path):
    t = translator(tmp_path, status=429)
    with pytest.raises(TranslateError):
        t.translate("毛绒布偶")
    with pytest.raises(TranslateError, match="cooling"):
        t.translate("手办")


def test_first_run_baselines_then_posts_new(tmp_path):
    e, tg, _ = make(tmp_path)
    assert e.discover() == 0
    assert e.db.count("skipped") == 5 and e.db.pending_count() == 0
    # a new card appears on the homepage
    e.fetcher.home = HOME.replace('hobby/137244', 'hobby/137300')
    assert e.discover() == 1
    row = e.db.next_pending()
    assert row["post_id"] // hpoi.KEY_SPAN == 137300
    assert e.discover() == 0                                  # not queued twice


def test_publish_translated_post(tmp_path):
    e, tg, _ = make(tmp_path)
    e.fetcher.home = HOME
    e.discover()
    key = hpoi.post_key(137248, HEAD)
    e.db.enqueue(key, 0, "new")
    assert e.process(e.db.get(key)) == "posted"
    html = tg.sent[0]["html"]
    assert "<h6>EN(" in html and "Lonely Rock!" in html.split("</h6>")[0]
    assert "Scheduled Release: Apr 2027" in html
    assert "#Bushiroad_Creative" in html and "#Ijichi_Seika" in html and "#Onkyo_ALTO" in html
    assert "#Hiroi_Kikuri" in html and "#Goto_Doll" in html and "#Lonely_Rock" in html
    assert "<tg-collage>" in html and html.count("<img") == 6               # cover + 5 photos
    assert '<a href="https://www.hpoi.net/hobby/137248">Hpoi</a>' in html
    assert "via" in html
    assert tg.sent[0]["kw"]["skip_entity_detection"] is False                # clickable hashtags


def test_translation_failure_defers_without_posting(tmp_path):
    e, tg, _ = make(tmp_path)
    e.translator = translator(tmp_path, status=429)
    e.discover()
    key = hpoi.post_key(137248, HEAD)
    e.db.enqueue(key, 0, "new")
    assert e.process(e.db.get(key)) == "pending"
    assert not tg.sent
    row = e.db.get(key)
    assert row["attempts"] == 0 and row["not_before"] > 0 and "translation" in row["last_error"]


def test_hpoi_settings_use_own_channel_and_db(tmp_path):
    main = Settings(telegram_bot_token="t", telegram_chat_id="@main", db_path=str(tmp_path / "tpclone.db"),
                    hpoi_chat_id="@other", hpoi_poll_interval_seconds=900, hashtag_style="plain")
    d = hpoi.derive_settings(main)
    assert d.telegram_chat_id == "@other" and d.poll_interval_seconds == 900 and d.hashtag_style == "hashtag"
    assert Path(d.db_path).name == "hpoi.db" and d.site_delay_seconds >= 5
    main.hpoi_chat_id = ""
    assert hpoi.derive_settings(main).telegram_chat_id == "@main"


def test_unknown_preview_target(tmp_path):
    e, _, _ = make(tmp_path)
    e.discover()
    assert e.resolve_key(137248) == hpoi.post_key(137248, HEAD)
    e.fetcher.item = "<html></html>"
    with pytest.raises(Exception):
        e.resolve_key(5)


def _wait(base, job):
    import time
    for _ in range(100):
        j = httpx.get(f"{base}/api/jobs/{job}").json()
        if j["state"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_dashboard_routes_by_source(tmp_path):
    import threading
    from conftest import FakeFetcher
    from tpclone.db import DB
    from tpclone.engine import Engine, Worker
    from tpclone.web import make_server
    e, tg, main = make(tmp_path)
    main_tg = FakeTG()
    toy = Engine(main, DB(":memory:"), FakeFetcher(), main_tg)
    srv = make_server(toy, Worker(toy), sources={"hpoi": (e, Worker(e))})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    h = {"X-Requested-With": "tpclone"}
    try:
        e.discover()
        st = httpx.get(base + "/api/status?source=hpoi").json()
        assert st["stats"]["skipped"] == 5 and len(st["recent"]) == 5 and st["sources"] == ["toypeople", "hpoi"]
        assert httpx.get(base + "/api/status").json()["stats"]["total"] == 0 and httpx.get(base + "/api/status").json()["recent"] == []
        # preview by the product number from the link
        job = httpx.post(base + "/api/preview?source=hpoi", json={"target": "https://www.hpoi.net/hobby/137248"}, headers=h).json()["job"]
        j = _wait(base, job)
        assert j["state"] == "done" and "Scheduled Release: Apr 2027" in j["result"]["html"] and j["result"]["title"].startswith("EN(")
        # post one item by hand: goes to the HPOI engine's Telegram, not the toy-people one
        job = httpx.post(base + "/api/post-now?source=hpoi", json={"id": 137248}, headers=h).json()["job"]
        assert _wait(base, job)["result"]["status"] == "posted"
        assert len(tg.sent) == 1 and not main_tg.sent
        # saving settings re-derives the HPOI settings, and masks the key
        r = httpx.post(base + "/api/settings", json={"hpoi_chat_id": "@hp", "translate_api_key": "K12345678"}, headers=h).json()
        assert r["saved"] and e.s.telegram_chat_id == "@hp"
        assert httpx.get(base + "/api/settings").json()["translate_api_key"].endswith("5678")
    finally:
        srv.shutdown()


def test_old_product_can_be_previewed_and_posted(tmp_path):
    e, tg, _ = make(tmp_path)
    e.fetcher.item = ITEM.replace("<title>x</title>", "<title>孤独摇滚！ 毛绒玩偶挂件 vol.3 | Hpoi动漫模玩百科资料库</title>")
    key = e.resolve_key(137248)                      # never listed: read from its own page
    assert key == hpoi.post_key(137248, "孤独摇滚！ 毛绒玩偶挂件 vol.3") and e.resolve_key(137248) == key
    art = e.fetch_article(key)
    assert art.title.startswith("EN(") and art.scheduled == "Scheduled Release: Apr 2027"
    assert e.post_now(137248)["status"] == "posted" and len(tg.sent) == 1


def test_translator_falls_back_to_next_service(tmp_path):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req.url.host)
        if req.url.host == "clients5.google.com":
            return httpx.Response(429, text="no")
        if req.url.host == "translate.googleapis.com":
            return httpx.Response(200, json=[[["plush doll", "x", None, None, 1]]])
        return httpx.Response(500)
    t = Translator(DB(":memory:"), glossary_file=tmp_path / "g.json", client=httpx.Client(transport=httpx.MockTransport(handler)),
                   sleep=lambda s: None)
    assert t.translate("毛绒布偶") == "plush doll" and seen[:2] == ["clients5.google.com", "translate.googleapis.com"]
    assert t.blocked_until == 0
    # the Chrome-dictionary answer format
    t2 = Translator(DB(":memory:"), glossary_file=tmp_path / "g2.json", sleep=lambda s: None,
                    client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=["plush doll"]))))
    assert t2.translate("毛绒布偶") == "plush doll"
