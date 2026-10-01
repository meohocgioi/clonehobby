"""Minimal Telegram Bot API client built for sendRichMessage + the pacing rules around it."""
from __future__ import annotations

import json
import logging
import random
import threading
import time
from typing import Callable

import httpx

log = logging.getLogger("tpclone.telegram")


class TelegramError(Exception):
    def __init__(self, message: str, code: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after


class UncertainDelivery(Exception):
    """The request was sent but we never saw the answer: the message may or may not exist in the channel."""


class MediaRejected(TelegramError):
    """Telegram could not fetch / accept an image URL (retry with uploaded files)."""


_MEDIA_HINTS = ("wrong file identifier", "failed to get http url content", "wrong type of the web page content",
                "wrong remote file", "photo_invalid_dimensions", "image_process_failed", "wrong http url",
                "media_invalid", "failed to download", "unsupported", "dimensions", "file is too big",
                "too big", "invalid media", "can't fetch", "cannot fetch")


class Telegram:
    def __init__(self, token: str, chat_id: str, *, base: str = "https://api.telegram.org",
                 client: httpx.Client | None = None, sleep: Callable[[float], None] = time.sleep):
        self.token, self.chat_id = token, chat_id
        self.base = base.rstrip("/")
        self.client = client or httpx.Client(timeout=httpx.Timeout(120, connect=20))
        self.sleep = sleep

    def _url(self, method: str) -> str:
        return f"{self.base}/bot{self.token}/{method}"

    def call(self, method: str, data: dict | None = None, files: dict[str, bytes] | None = None,
             *, max_429_retries: int = 5) -> dict:
        """POST a Bot API method. Retries 429 (honouring retry_after) and connect failures only:
        anything that may have reached Telegram raises UncertainDelivery instead of being retried blind."""
        data = data or {}
        for attempt in range(max_429_retries + 1):
            try:
                if files:
                    r = self.client.post(self._url(method), data=data,
                                         files={k: (f"{k}.jpg", v, "image/jpeg") for k, v in files.items()})
                else:
                    r = self.client.post(self._url(method), data=data)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                if attempt >= 3:
                    raise TelegramError(f"cannot connect to Telegram: {e}") from e
                self.sleep(2 ** attempt * 3)
                continue
            except httpx.HTTPError as e:
                raise UncertainDelivery(f"{type(e).__name__}: {e}") from e
            try:
                j = r.json()
            except ValueError:
                if r.status_code >= 500:
                    raise UncertainDelivery(f"HTTP {r.status_code} with non-JSON body")
                raise TelegramError(f"HTTP {r.status_code}: {r.text[:200]}", r.status_code)
            if j.get("ok"):
                return j["result"]
            desc = j.get("description", "unknown error")
            code = j.get("error_code", r.status_code)
            ra = (j.get("parameters") or {}).get("retry_after")
            if code == 429 and ra is not None:
                if attempt >= max_429_retries:
                    raise TelegramError(desc, code, float(ra))
                wait = float(ra) + 1 + random.random()
                log.warning("Telegram flood control: sleeping %.0fs", wait)
                self.sleep(wait)
                continue
            if code >= 500:
                raise UncertainDelivery(f"Telegram {code}: {desc}")
            low = desc.lower()
            if any(h in low for h in _MEDIA_HINTS):
                raise MediaRejected(desc, code)
            raise TelegramError(desc, code, float(ra) if ra else None)
        raise TelegramError("too many retries")

    # ---- high level ----------------------------------------------------
    def send_rich(self, html: str, media: list[dict] | None = None, files: dict[str, bytes] | None = None,
                  *, skip_entity_detection: bool = True, disable_notification: bool = False) -> dict:
        rich: dict = {"html": html, "skip_entity_detection": skip_entity_detection}
        if media:
            rich["media"] = media
        data = {"chat_id": self.chat_id, "rich_message": json.dumps(rich, ensure_ascii=False)}
        if disable_notification:
            data["disable_notification"] = "true"
        return self.call("sendRichMessage", data, files)

    def message_exists(self, message_id: int) -> bool | None:
        """Does this channel message still exist?  True / False / None (could not tell).

        The Bot API cannot list or fetch channel messages, but editing the reply markup of our own message answers
        "message is not modified" when it exists and "message to edit not found" when it was deleted.
        """
        try:
            self.call("editMessageReplyMarkup", {"chat_id": self.chat_id, "message_id": message_id},
                      max_429_retries=3)
            return True
        except UncertainDelivery:
            return None
        except TelegramError as e:
            low = str(e).lower()
            if "message is not modified" in low:
                return True
            if any(h in low for h in ("message to edit not found", "message_id_invalid", "message not found",
                                      "message to be edited not found")):
                return False
            return None

    def check(self) -> dict:
        """Validate token + that the bot may post in the channel. Raises TelegramError with a readable reason."""
        me = self.call("getMe")
        chat = self.call("getChat", {"chat_id": self.chat_id})
        member = self.call("getChatMember", {"chat_id": self.chat_id, "user_id": me["id"]})
        status = member.get("status")
        if status not in ("administrator", "creator"):
            raise TelegramError(f"bot @{me.get('username')} is '{status}' in {self.chat_id}; make it an admin")
        if status == "administrator" and member.get("can_post_messages") is False:
            raise TelegramError("bot is admin but lacks the 'Post messages' right")
        return {"bot": me.get("username"), "chat": chat.get("title") or chat.get("username"), "chat_id": chat["id"]}


class Pacer:
    """Enforces a minimum gap between posts (persisted, so restarts don't burst) + an optional hourly cap."""

    def __init__(self, delay: float, db, max_per_hour: int = 0, jitter: float = 0.1,
                 clock: Callable[[], float] = time.time):
        self.delay, self.db, self.max_per_hour, self.jitter, self.clock = delay, db, max_per_hour, jitter, clock

    def next_allowed_at(self) -> float:
        last = float(self.db.kv_get("last_send_ts", "0") or 0)
        t = last + self.delay
        if self.max_per_hour:
            posted = self.db.posts_in_last_hour()
            if posted >= self.max_per_hour:
                t = max(t, self.clock() + 60)   # re-check every minute until the window frees up
        return t

    def wait_time(self) -> float:
        return max(0.0, self.next_allowed_at() - self.clock())

    def mark_sent(self) -> None:
        self.db.kv_set("last_send_ts", self.clock() + random.uniform(0, self.delay * self.jitter))

    def push_back(self, seconds: float) -> None:
        """Telegram told us to wait (retry_after): hold the whole queue."""
        self.db.kv_set("last_send_ts", self.clock() + seconds - self.delay)
