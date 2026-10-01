import json

import httpx
import pytest

from tpclone.db import DB
from tpclone.telegram import MediaRejected, Pacer, Telegram, TelegramError, UncertainDelivery


def tg_with(handler):
    return Telegram("TOKEN", "@chan", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)


def test_send_rich_json_payload():
    seen = {}

    def h(req):
        seen["url"], seen["body"] = str(req.url), req.content.decode()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    r = tg_with(h).send_rich("<h3>x</h3>", [{"id": "f0"}], None)
    assert r["message_id"] == 7 and seen["url"].endswith("/botTOKEN/sendRichMessage")
    from urllib.parse import parse_qs
    q = parse_qs(seen["body"])
    assert q["chat_id"] == ["@chan"]
    rich = json.loads(q["rich_message"][0])
    assert rich["html"] == "<h3>x</h3>" and rich["skip_entity_detection"] is True and rich["media"] == [{"id": "f0"}]


def test_multipart_when_files():
    seen = {}

    def h(req):
        seen["ct"], seen["body"] = req.headers["content-type"], req.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    tg_with(h).send_rich("<p/>", [{"id": "f0", "media": {"type": "photo", "media": "attach://f0"}}], {"f0": b"JPEG"})
    assert seen["ct"].startswith("multipart/form-data") and b'name="f0"' in seen["body"] and b"attach://f0" in seen["body"]


def test_429_honours_retry_after_then_succeeds():
    calls, slept = [], []

    def h(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"ok": False, "error_code": 429, "description": "Too Many Requests",
                                             "parameters": {"retry_after": 17}})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 2}})

    t = Telegram("T", "@c", client=httpx.Client(transport=httpx.MockTransport(h)), sleep=slept.append)
    assert t.send_rich("<p/>")["message_id"] == 2
    assert len(calls) == 2 and slept and slept[0] >= 17


def test_read_timeout_is_uncertain_not_retried():
    calls = []

    def h(req):
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    with pytest.raises(UncertainDelivery):
        tg_with(h).send_rich("<p/>")
    assert len(calls) == 1          # never blindly re-sent (would risk a duplicate post)


def test_5xx_is_uncertain():
    with pytest.raises(UncertainDelivery):
        tg_with(lambda r: httpx.Response(502, json={"ok": False, "error_code": 502, "description": "Bad Gateway"})).send_rich("x")


def test_connect_error_retried_safely():
    calls = []

    def h(req):
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ConnectError("down")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 3}})

    assert tg_with(h).send_rich("x")["message_id"] == 3 and len(calls) == 3


def test_media_rejection_classified():
    body = {"ok": False, "error_code": 400, "description": "Bad Request: failed to get HTTP URL content"}
    with pytest.raises(MediaRejected):
        tg_with(lambda r: httpx.Response(400, json=body)).send_rich("x")
    body["description"] = "Bad Request: chat not found"
    with pytest.raises(TelegramError) as e:
        tg_with(lambda r: httpx.Response(400, json=body)).send_rich("x")
    assert not isinstance(e.value, MediaRejected)


def test_pacer_enforces_delay_and_persists():
    db, now = DB(":memory:"), [1000.0]
    p = Pacer(45, db, clock=lambda: now[0], jitter=0)
    assert p.wait_time() == 0
    p.mark_sent()
    now[0] += 10
    assert 34 < p.wait_time() <= 35
    assert Pacer(45, db, clock=lambda: now[0]).wait_time() > 30       # a "restart" does not reset the gap
    p.push_back(120)
    assert p.wait_time() > 100
    now[0] += 200
    assert p.wait_time() == 0


def test_message_exists_classification():
    def reply(desc, code=400):
        return tg_with(lambda r: httpx.Response(code, json={"ok": False, "error_code": code, "description": desc}))

    assert reply("Bad Request: message is not modified: specified new message content and reply markup are exactly the same").message_exists(5) is True
    assert reply("Bad Request: message to edit not found").message_exists(5) is False
    assert reply("Bad Request: MESSAGE_ID_INVALID").message_exists(5) is False
    assert reply("Forbidden: bot is not a member of the channel chat", 403).message_exists(5) is None
    assert tg_with(lambda r: httpx.Response(200, json={"ok": True, "result": True})).message_exists(5) is True

    def boom(req):
        raise httpx.ReadTimeout("x")
    assert tg_with(boom).message_exists(5) is None
