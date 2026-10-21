"""Facebook / Instagram / X: the same post after Telegram (mock networks: no real accounts are used)."""
import io
import json
import threading
import time
from urllib.parse import parse_qs

import httpx
import pytest
from PIL import Image

from conftest import make_article, png
from tpclone import media
from tpclone import outlets as O
from tpclone.config import Settings
from tpclone.db import DB
from tpclone.engine import Engine, Worker
from tpclone.fetch import Fetcher
from tpclone.hpoi import derive_settings
from tpclone.web import make_server


class Nets:
    """Mock Graph API (Facebook Page 111, Instagram 1784) and X API. Records every request."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict, dict, dict]] = []     # method, path, query, body, headers
        self.fail: dict[tuple[str, str], tuple] = {}                # (method, path end) -> (status, json, headers)
        self.timeout: set[tuple[str, str]] = set()                  # (method, path end) -> no answer
        self.ig_status = ["IN_PROGRESS", "FINISHED"]
        self.quota = 0
        self.n = 0
        self.scopes = ["pages_show_list", "pages_manage_posts", "pages_read_engagement", "instagram_basic",
                       "instagram_content_publish"]
        self.pages = [{"id": "111", "name": "Neko Hobby", "access_token": "PAGETOKEN",
                       "instagram_business_account": {"id": "1784", "username": "nekohobby"}}]

    @staticmethod
    def body(req: httpx.Request) -> dict:
        req.read()
        ct = req.headers.get("content-type", "")
        if ct.startswith("application/x-www-form-urlencoded"):
            return {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        if ct.startswith("application/json"):
            return json.loads(req.content)
        if ct.startswith("multipart/form-data"):
            return {"_multipart": req.content}
        return {}

    def find(self, method, end):
        return [c for c in self.calls if c[0] == method and c[1].endswith(end)]

    def handler(self, req: httpx.Request) -> httpx.Response:
        method, path = req.method, req.url.path
        q, body = dict(req.url.params), self.body(req)
        self.calls.append((method, path, q, body, dict(req.headers)))
        for (m, end), resp in self.fail.items():
            if m == method and path.endswith(end):
                status, j, headers = (resp + ({},))[:3]
                return httpx.Response(status, json=j, headers=headers)
        for (m, end) in self.timeout:
            if m == method and path.endswith(end):
                raise httpx.ReadTimeout("no answer", request=req)
        self.n += 1
        n = self.n
        if req.url.host == "api.x.com":
            if path == "/2/users/me":
                return httpx.Response(200, json={"data": {"id": "1", "username": "neko_x", "name": "Neko"}})
            if path == "/2/media/upload":
                return httpx.Response(200, json={"data": {"id": f"x{n}", "media_key": f"3_x{n}", "expires_after_secs": 86400}})
            if path == "/2/tweets":
                return httpx.Response(201, json={"data": {"id": "1880", "text": body.get("text")}})
            return httpx.Response(404, json={"title": "Not Found"})
        p = path.split("/v25.0/", 1)[1]
        if p == "oauth/access_token":
            return httpx.Response(200, json={"access_token": "LONGLIVED", "token_type": "bearer"})
        if p == "me/accounts":
            return httpx.Response(200, json={"data": self.pages})
        if p == "debug_token":
            return httpx.Response(200, json={"data": {"is_valid": True, "scopes": self.scopes}})
        if p == "111" and method == "GET":
            return httpx.Response(200, json={"id": "111", "name": "Neko Hobby", "link": "https://www.facebook.com/neko"})
        if p == "111/photos":
            return httpx.Response(200, json={"id": f"ph{n}"})
        if p.startswith("ph") and method == "GET":
            return httpx.Response(200, json={"images": [{"source": f"https://scontent.example/{p}_s.jpg", "width": 320},
                                                        {"source": f"https://scontent.example/{p}.jpg", "width": 1080}]})
        if p.startswith("ph") and method == "DELETE":
            return httpx.Response(200, json={"success": True})
        if p == "111/feed":
            return httpx.Response(200, json={"id": "111_999"})
        if p == "1784" and method == "GET":
            return httpx.Response(200, json={"id": "1784", "username": "nekohobby"})
        if p == "1784/content_publishing_limit":
            return httpx.Response(200, json={"data": [{"quota_usage": self.quota, "config": {"quota_total": 100}}]})
        if p == "1784/media":
            return httpx.Response(200, json={"id": f"c{n}"})
        if p.startswith("c") and method == "GET":
            st = self.ig_status.pop(0) if len(self.ig_status) > 1 else self.ig_status[0]
            return httpx.Response(200, json={"status_code": st, "id": p})
        if p == "1784/media_publish":
            return httpx.Response(200, json={"id": "m777"})
        if p == "m777":
            return httpx.Response(200, json={"permalink": "https://www.instagram.com/p/ABC/"})
        return httpx.Response(400, json={"error": {"message": f"unknown {method} {p}", "code": 100}})


def connect_all(s):
    s.fb_page_id, s.fb_page_name, s.fb_page_token = "111", "Neko Hobby", "PAGETOKEN"
    s.ig_user_id, s.ig_username = "1784", "nekohobby"
    s.x_api_key, s.x_api_secret, s.x_access_token, s.x_access_secret = "ck", "cs", "at", "as"
    s.x_username = "neko_x"


@pytest.fixture
def nets(env):
    e, f, tg, db = env
    connect_all(e.s)
    n = Nets()
    sleeps = []
    runner = O.OutletRunner(e.s, {"toypeople": (e, None)}, db, client=httpx.Client(transport=httpx.MockTransport(n.handler)),
                            sleep=sleeps.append, is_active=lambda *a: True)
    f.posts[7] = ("2026-10-20", "Nendoroid Neko")
    return e, f, tg, db, n, runner, sleeps


def publish(e, db, pid=7):
    db.upsert_seen(pid, e.post_url(pid), None, "pending", "new")
    return e.process(db.get(pid))


# ----------------------------------------------------------------------------- pieces
def test_oauth1_signature_matches_the_x_documentation():
    h = O.oauth1_header("POST", "https://api.twitter.com/1.1/statuses/update.json?include_entities=true",
                        "xvz1evFS4wEEPTGEFPHBog", "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
                        "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb", "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
                        params={"status": "Hello Ladies + Gentlemen, a signed OAuth request!"},
                        nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", timestamp=1318622958)
    assert 'oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"' in h and h.startswith("OAuth ")


def test_texts_follow_each_network_s_rules():
    art = make_article(7, title="Nendoroid Neko Arc")
    art.paragraphs = ["Hello <b>world</b>\n &amp; friends", "Line one<br>Line two", ""]
    fb = O.facebook_text(art)
    assert fb == ("Nendoroid Neko Arc\n\nScheduled Release: Dec 2026\n\nHello world & friends\n\nLine one\nLine two\n\n"
                  "via: bandaispirits\n\n#Japanese_Series #Kotobukiya")
    # Instagram: at most 2,200 characters and 30 hashtags; a long text is cut, the hashtags stay at the end
    art.paragraphs = ["word " * 2000]
    art.tags = [f"Tag {i}" for i in range(40)]
    cap = O.instagram_caption(art)
    assert len(cap) <= 2200 and cap.count("#") == 30 and cap.endswith("#Tag_29") and "…" in cap
    assert cap.startswith("Nendoroid Neko Arc\n\nScheduled Release: Dec 2026\n\nword word")
    # X: 280 characters as X counts them, no body text, no link, as many hashtags as fit
    t = O.x_text(art)
    assert O.x_weight(t) <= 280 and "word" not in t and "http" not in t
    assert t.startswith("Nendoroid Neko Arc\n\nScheduled Release: Dec 2026\n\n#Tag_0 #Tag_1")
    art.title = "超" * 200                                   # CJK counts double
    assert O.x_weight("超") == 2 and O.x_weight(O.x_text(art)) <= 280 and O.x_text(art).endswith("…")


def test_pictures_are_prepared_for_each_network():
    sq = Image.open(io.BytesIO(media.square_photo(png(300, 120))))
    assert sq.size == (1080, 1080) and sq.format == "JPEG"
    assert sq.getpixel((540, 10)) == (255, 255, 255)        # white edges, nothing of the picture cut off
    big = Image.new("RGB", (3000, 3000))
    big.putdata([((i * 7) % 256, (i * 13) % 256, (i * 3) % 256) for i in range(3000 * 3000)])
    b = io.BytesIO(); big.save(b, "PNG")
    assert len(media.prepare_photo(b.getvalue(), 2048, 300_000)) <= 300_000


def test_only_connected_and_switched_on_networks_get_the_post(env):
    e, f, tg, db = env
    f.posts[7] = ("2026-10-20", "T7")
    e.s.to_facebook = e.s.to_x = True                 # switched on, but nothing connected yet
    assert publish(e, db) == "posted" and db.outlet_get(7, "facebook") is None
    connect_all(e.s)
    e.s.to_x = False
    f.posts[8] = ("2026-10-20", "T8")
    assert publish(e, db, 8) == "posted"
    assert db.outlet_get(8, "facebook")["status"] == "pending" and db.outlet_get(8, "x") is None
    payload = json.loads(db.outlet_get(8, "facebook")["payload"])
    assert payload["title"] == "T8" and payload["images"]      # the post as it was sent: not fetched again
    assert "next: Facebook" in db.recent_events(1)[0]["message"]
    m = Settings(hpoi_to_x=True, to_x=False, x_api_key="a", x_api_secret="b", x_access_token="c", x_access_secret="d",
                 db_path="data/tpclone.db")
    assert derive_settings(m).to_x is True and O.targets(derive_settings(m)) == ["x"] and O.targets(m) == []


# ----------------------------------------------------------------------------- the three networks
def test_facebook_one_post_with_all_photos(nets):
    e, f, tg, db, n, runner, _ = nets
    e.s.to_facebook = True
    publish(e, db)
    asked = len(f.article_requests)
    assert runner.step("facebook") is True
    assert len(f.article_requests) == asked                      # the website was not asked again
    ups = n.find("POST", "/111/photos")
    assert len(ups) == 2 and all(b"published" in c[3]["_multipart"] and b"false" in c[3]["_multipart"] for c in ups)
    feed = n.find("POST", "/111/feed")[0][3]
    assert feed["message"].startswith("Nendoroid Neko\n\n") and "#" not in feed["message"].split("\n")[0]
    assert [json.loads(feed[f"attached_media[{i}]"])["media_fbid"] for i in range(2)] == ["ph1", "ph2"]
    assert feed["access_token"] == "PAGETOKEN"
    row = db.outlet_get(7, "facebook")
    assert row["status"] == "posted" and row["link"] == "https://www.facebook.com/111_999"
    assert runner.step("facebook") is False                     # nothing else waiting (and the pace holds)


def test_instagram_slideshow_hosted_on_the_page(nets):
    e, f, tg, db, n, runner, sleeps = nets
    e.s.to_instagram = True
    publish(e, db)
    assert runner.step("instagram") is True
    assert n.find("GET", "/1784/content_publishing_limit")
    hosted = n.find("POST", "/111/photos")
    assert len(hosted) == 2
    kids = [c[3] for c in n.find("POST", "/1784/media") if c[3].get("is_carousel_item") == "true"]
    assert [k["image_url"] for k in kids] == ["https://scontent.example/ph2.jpg", "https://scontent.example/ph3.jpg"]
    car = [c[3] for c in n.find("POST", "/1784/media") if c[3].get("media_type") == "CAROUSEL"][0]
    assert len(car["children"].split(",")) == 2 and car["caption"].startswith("Nendoroid Neko")
    cid = n.find("POST", "/1784/media_publish")[0][3]["creation_id"]
    assert n.find("GET", "/" + cid)                               # the carousel's status was asked before publishing
    assert sleeps                                                 # waited for Instagram to fetch the pictures
    assert len(n.find("DELETE", "")) == 2                         # the hidden helper photos are removed again
    row = db.outlet_get(7, "instagram")
    assert row["status"] == "posted" and row["link"] == "https://www.instagram.com/p/ABC/" and row["remote_id"] == "m777"


def test_instagram_single_picture_and_daily_limit(nets):
    e, f, tg, db, n, runner, _ = nets
    e.s.to_instagram = True
    publish(e, db)
    n.quota = 100
    assert runner.step("instagram") is True
    assert db.outlet_get(7, "instagram")["status"] == "pending" and not n.find("POST", "/111/photos")
    assert runner.state("instagram")["hold_until"] > time.time() + 3000      # waits an hour
    assert runner.step("instagram") is False
    runner.set_state("instagram", hold_until=0)
    n.quota = 3
    art = O.article_from(db.outlet_get(7, "instagram")["payload"])
    art.images = []
    db._x("UPDATE outlet_posts SET payload=? WHERE post_id=7", (json.dumps(art.to_dict()),))
    assert runner.step("instagram") is True
    media_posts = [c[3] for c in n.find("POST", "/1784/media")]
    assert len(media_posts) == 1 and "is_carousel_item" not in media_posts[0] and media_posts[0]["caption"]
    assert db.outlet_get(7, "instagram")["status"] == "posted"


def test_x_post_with_up_to_four_photos(nets):
    e, f, tg, db, n, runner, _ = nets
    e.s.to_x = True
    f.posts[7] = ("2026-10-20", "Nendoroid Neko")
    publish(e, db)
    art = O.article_from(db.outlet_get(7, "x")["payload"])
    art.images = [f"https://x/{i}.jpg" for i in range(6)]
    db._x("UPDATE outlet_posts SET payload=? WHERE post_id=7", (json.dumps(art.to_dict()),))
    assert runner.step("x") is True
    ups = n.find("POST", "/2/media/upload")
    assert len(ups) == 4 and all(c[4]["authorization"].startswith("OAuth ") and "oauth_signature=" in c[4]["authorization"]
                                 for c in ups)
    assert b'name="media_category"' in ups[0][3]["_multipart"] and b"tweet_image" in ups[0][3]["_multipart"]
    tw = n.find("POST", "/2/tweets")[0][3]
    assert tw["text"] == O.x_text(art) and len(tw["media"]["media_ids"]) == 4
    assert db.outlet_get(7, "x")["link"] == "https://x.com/neko_x/status/1880"


# ----------------------------------------------------------------------------- trouble
def test_broken_connection_pauses_that_network_only(nets):
    e, f, tg, db, n, runner, _ = nets
    e.s.to_facebook = e.s.to_x = True
    publish(e, db)
    n.fail[("POST", "/111/feed")] = (400, {"error": {"message": "Error validating access token", "type": "OAuthException",
                                                     "code": 190, "error_subcode": 463}})
    assert runner.step("facebook") is True
    st = runner.state("facebook")
    assert "does not work" in st["paused"] and "code 190" in st["paused"]
    row = db.outlet_get(7, "facebook")
    assert row["status"] == "pending" and row["attempts"] == 0            # not the post's fault: it waits
    assert runner.step("facebook") is False                                # paused
    assert runner.step("x") is True and db.outlet_get(7, "x")["status"] == "posted"     # X carries on
    assert len(n.find("DELETE", "")) == 2                                 # its hidden photos were removed again
    del n.fail[("POST", "/111/feed")]
    assert runner.check("facebook")["ok"] and not runner.state("facebook").get("paused")
    runner.set_state("facebook", last_ts=0)
    assert runner.step("facebook") is True and db.outlet_get(7, "facebook")["status"] == "posted"


def test_x_slow_down_duplicate_and_no_answer(nets):
    e, f, tg, db, n, runner, _ = nets
    e.s.to_x = True
    publish(e, db)
    n.fail[("POST", "/2/tweets")] = (429, {"title": "Too Many Requests", "detail": "Too Many Requests"},
                                     {"x-rate-limit-reset": str(int(time.time()) + 600)})
    assert runner.step("x") is True
    assert db.outlet_get(7, "x")["status"] == "pending" and db.outlet_get(7, "x")["attempts"] == 0
    assert 500 < runner.state("x")["hold_until"] - time.time() <= 601
    runner.set_state("x", hold_until=0)
    n.fail[("POST", "/2/tweets")] = (403, {"detail": "You are not allowed to create a Tweet with duplicate content.",
                                           "title": "Forbidden", "status": 403})
    assert runner.step("x") is True
    row = db.outlet_get(7, "x")
    assert row["status"] == "failed" and "duplicate" in row["last_error"] and row["flagged_at"]
    db.outlet_set(7, "x", "pending", None)
    del n.fail[("POST", "/2/tweets")]
    n.timeout.add(("POST", "/2/tweets"))
    runner.set_state("x", last_ts=0)
    assert runner.step("x") is True
    row = db.outlet_get(7, "x")
    assert row["status"] == "uncertain" and "may or may not" in row["last_error"]
    assert db.outlet_attention()[0]["outlet"] == "x"


def test_server_errors_are_retried_then_need_attention(nets):
    e, f, tg, db, n, runner, _ = nets
    e.s.to_x = True
    publish(e, db)
    n.fail[("POST", "/2/media/upload")] = (503, {"title": "Service Unavailable"})
    for i in range(O.GIVE_UP):
        runner.set_state("x", last_ts=0)
        db._x("UPDATE outlet_posts SET not_before=0")
        assert runner.step("x") is True
        row = db.outlet_get(7, "x")
        assert row["attempts"] == i + 1
    assert row["status"] == "failed" and "503" in row["last_error"]


def test_payment_required_pauses_x_with_a_clear_reason(nets):
    e, f, tg, db, n, runner, _ = nets
    e.s.to_x = True
    publish(e, db)
    n.fail[("POST", "/2/media/upload")] = (402, {"title": "Payment Required", "detail": "CreditsDepleted"})
    runner.step("x")
    assert "credits" in runner.state("x")["paused"]


def test_nothing_is_sent_while_the_website_is_stopped_and_old_posts_expire(nets):
    e, f, tg, db, n, runner, _ = nets
    e.s.to_facebook = True
    publish(e, db)
    w = Worker(e)
    stopped = O.OutletRunner(e.s, {"toypeople": (e, w)}, db, client=runner.client)
    assert stopped.step("facebook") is False and not n.calls
    db._x("UPDATE outlet_posts SET created_at=?", (time.time() - 3 * 86400,))
    assert runner.step("facebook") is False
    row = db.outlet_get(7, "facebook")
    assert row["status"] == "skipped" and "2 days" in row["last_error"] and not n.calls


def test_a_send_cut_short_by_a_restart_is_uncertain(nets):
    e, f, tg, db, n, runner, _ = nets
    e.s.to_facebook = True
    publish(e, db)
    db.outlet_set(7, "facebook", "sending")
    runner.start()
    try:
        assert db.outlet_get(7, "facebook")["status"] == "uncertain"
    finally:
        runner.stop(wait=5)


# ----------------------------------------------------------------------------- dashboard API
@pytest.fixture
def api(tmp_path):
    s = Settings(telegram_bot_token="", telegram_chat_id="", db_path=str(tmp_path / "t.db"), web_port=0)
    e = Engine(s, DB(s.db_path), Fetcher(s), None)
    n = Nets()
    runner = O.OutletRunner(s, {"toypeople": (e, Worker(e))}, e.db, client=httpx.Client(transport=httpx.MockTransport(n.handler)))
    srv = make_server(e, Worker(e), outlets=runner)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield e, n, runner, f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def post(base, path, body=None):
    return httpx.post(base + path, json=body or {}, headers={"X-Requested-With": "tpclone"}).json()


def test_connect_facebook_from_settings(api):
    e, n, runner, base = api
    n.pages.append({"id": "222", "name": "Second Page", "access_token": "P2"})
    r = post(base, "/api/outlets/facebook/connect", {"app_id": "123", "app_secret": "sec", "user_token": "SHORT"})
    assert [p["name"] for p in r["pages"]] == ["Neko Hobby", "Second Page"] and "PAGETOKEN" not in json.dumps(r)
    ex = n.find("GET", "/oauth/access_token")[0][2]
    assert ex["grant_type"] == "fb_exchange_token" and ex["fb_exchange_token"] == "SHORT" and "access_token" not in ex
    assert n.find("GET", "/me/accounts")[0][2]["access_token"] == "LONGLIVED"
    r = post(base, "/api/outlets/facebook/connect", {"app_id": "123", "app_secret": "sec", "user_token": "SHORT",
                                                     "page_id": "111"})
    assert r["ok"] and r["page"] == "Neko Hobby" and r["instagram"] == "nekohobby" and r["missing"] == []
    r = post(base, "/api/outlets/facebook/connect", {"app_id": "", "app_secret": "••••••sec", "user_token": "NEW",
                                                     "page_id": "111"})          # later: the saved app id / secret are used
    assert r["ok"] and n.find("GET", "/oauth/access_token")[-1][2]["client_secret"] == "sec"
    s = e.s
    assert (s.fb_page_id, s.fb_page_token, s.ig_user_id, s.fb_app_secret) == ("111", "PAGETOKEN", "1784", "sec")
    saved = json.loads((s.data_dir / "settings.json").read_text())
    assert saved["fb_page_token"] == "PAGETOKEN" and saved["ig_username"] == "nekohobby"
    v = httpx.get(base + "/api/settings").json()
    assert v["fb_page_token"] == "••••••OKEN" and v["fb_app_secret"] == "••••••sec" and v["fb_page_name"] == "Neko Hobby"
    assert v["networks"]["facebook"]["ready"] and v["networks"]["instagram"]["account"] == "@nekohobby"
    assert post(base, "/api/outlets/check", {"outlet": "instagram"})["ok"]
    n.scopes.remove("instagram_content_publish")
    r = post(base, "/api/outlets/check", {"outlet": "instagram"})
    assert not r["ok"] and "instagram_content_publish" in r["error"]
    assert post(base, "/api/outlets/disconnect", {"outlet": "facebook"})["ok"]
    assert not s.fb_page_token and not s.ig_user_id and not httpx.get(base + "/api/settings").json()["networks"]["facebook"]["ready"]


def test_x_keys_saved_masked_and_checked(api):
    e, n, runner, base = api
    r = post(base, "/api/settings", {"x_api_key": "key1", "x_api_secret": "sec1", "x_access_token": "tok1",
                                     "x_access_secret": "tsec1", "to_x": True})
    assert r["saved"]
    v = httpx.get(base + "/api/settings").json()
    assert v["x_api_key"] == "••••••key1" and v["to_x"] is True
    runner.set_state("x", paused="X refused the keys")
    post(base, "/api/settings", {"x_api_key": "••••••key1", "x_access_token": "tok2"})   # masked = unchanged
    assert e.s.x_api_key == "key1" and e.s.x_access_token == "tok2" and not runner.state("x").get("paused")
    r = post(base, "/api/outlets/check", {"outlet": "x"})
    assert r["ok"] and r["username"] == "neko_x" and e.s.x_username == "neko_x"


def test_failed_copies_are_listed_and_resolved(api):
    e, n, runner, base = api
    db = e.db
    db.upsert_seen(5, e.post_url(5), None, "posted", "new")
    db.set_meta(5, "Figure Five", "2026-10-20")
    db.outlet_queue(5, ["facebook", "x"], None)
    db.outlet_set(5, "facebook", "failed", "Facebook refused it")
    db.outlet_set(5, "x", "uncertain", "no answer")
    st = httpx.get(base + "/api/status").json()
    att = {r["outlet"]: r for r in st["outlet_attention"]}
    assert att["facebook"]["title"] == "Figure Five" and att["x"]["status"] == "uncertain"
    assert st["outlets"]["facebook"]["failed"] == 1 and "networks" in st
    db._x("UPDATE outlet_posts SET created_at=0")
    assert post(base, "/api/outlet/resolve", {"id": 5, "outlet": "facebook", "action": "retry"})["ok"]
    row = db.outlet_get(5, "facebook")
    assert row["status"] == "pending" and row["attempts"] == 0 and row["created_at"] > time.time() - 60   # not 'old news'
    assert post(base, "/api/outlet/resolve", {"id": 5, "outlet": "x", "action": "posted"})["ok"]
    assert db.outlet_get(5, "x")["status"] == "posted"
    assert post(base, "/api/outlet/resolve", {"id": 5, "outlet": "facebook", "action": "skip"})["ok"]
    assert db.outlet_get(5, "facebook")["status"] == "skipped"
    assert httpx.get(base + "/api/status").json()["outlet_attention"] == []


def test_background_thread_posts_after_telegram(nets):
    e, f, tg, db, n, runner, _ = nets
    e.s.to_facebook = e.s.to_x = True
    runner.POLL = 0.05
    runner.start()
    try:
        publish(e, db)                                   # Telegram first ...
        for _ in range(200):
            if all((db.outlet_get(7, o) or {}).get("status") == "posted" for o in ("facebook", "x")):
                break
            time.sleep(0.05)
        assert db.outlet_get(7, "facebook")["status"] == "posted" and db.outlet_get(7, "x")["status"] == "posted"
        assert len(tg.sent) == 1                         # ... then each network once
        assert len(n.find("POST", "/111/feed")) == 1 and len(n.find("POST", "/2/tweets")) == 1
    finally:
        runner.stop(wait=5)
    assert not any(t.is_alive() for t in runner._threads.values())


def test_stopping_the_app_ends_the_instagram_wait(nets):
    e, f, tg, db, n, _, _ = nets
    e.s.to_instagram = True
    publish(e, db)
    n.ig_status = ["IN_PROGRESS"]                        # Instagram never finishes
    runner = O.OutletRunner(e.s, {"toypeople": (e, None)}, db, client=httpx.Client(transport=httpx.MockTransport(n.handler)),
                            is_active=lambda *a: True)
    threading.Timer(0.3, runner._stop.set).start()
    t0 = time.time()
    assert runner.step("instagram") is True and time.time() - t0 < 5
    row = db.outlet_get(7, "instagram")
    assert row["status"] == "pending" and row["attempts"] == 0 and "stopping" in row["last_error"]
