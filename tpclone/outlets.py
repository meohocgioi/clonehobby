"""Also post every published post to a Facebook Page, Instagram and X - the same English post as in Telegram.

* Facebook  - one Page post with all photos (an album in the feed): every photo is uploaded unpublished, then one post
              is made with all of them attached (POST /{page}/feed with attached_media).
* Instagram - a carousel ("slideshow") of up to 10 photos. Instagram fetches pictures from a public web address and this
              app runs on your own computer, so every slide is first uploaded to your Facebook Page as a hidden
              (unpublished) photo whose address Instagram uses; the hidden photos are deleted afterwards. Slides are made
              square (white edges) because Instagram crops every slide to the shape of the first one.
* X         - one post with up to 4 photos: title, release and as many hashtags as fit in 280 characters. No link
              (X charges more for posts with a link).

Each network has its own queue (table outlet_posts in each website's ledger), its own pace and its own error handling,
so trouble on one never holds up Telegram or the others:
  * the connection does not work (expired token, missing permission, no X credits) -> that network pauses until it is
    fixed in Settings; nothing is lost (a post still waiting after 2 days is skipped as old news)
  * "slow down" / daily limit reached                         -> waits, then tries again
  * a network or server error                                 -> a few more tries, then 'Needs your attention'
  * the request that publishes got no answer                  -> 'uncertain': have a look, then choose
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from html import unescape
from urllib.parse import parse_qsl, quote, urlparse

import httpx

from . import media as media_mod
from .site import Article

log = logging.getLogger("tpclone.outlets")

GRAPH = "https://graph.facebook.com/v25.0"
X_API = "https://api.x.com"

OUTLETS = ("facebook", "instagram", "x")
NAMES = {"facebook": "Facebook", "instagram": "Instagram", "x": "X"}
MAX_PHOTOS = {"facebook": 30, "instagram": 10, "x": 4}
FB_MAX_BYTES = 4 * 1024 * 1024 - 65536         # Facebook: photos up to 4 MB
X_MAX_BYTES = 5 * 1024 * 1024 - 65536          # X: photos up to 5 MB
MAX_AGE = 2 * 86400            # a post still waiting after 2 days (e.g. the connection was broken) is skipped: old news
GIVE_UP = 4                    # tries before a post goes to 'Needs your attention'
RETRY = (300, 900, 1800)       # seconds between those tries


class OutletError(Exception):
    """kind: 'auth'      the connection does not work -> pause this network until Settings are fixed
             'limit'     slow down / daily limit -> wait `retry_after` seconds, then try again
             'temporary' network or server trouble -> try again later
             'rejected'  the network refused this post -> 'Needs your attention'
             'uncertain' the publishing request got no answer -> the post may or may not be there"""

    def __init__(self, message: str, kind: str = "temporary", retry_after: float | None = None):
        super().__init__(message)
        self.kind, self.retry_after = kind, retry_after


_SECRET_RX = re.compile(r"(access_token|client_secret|fb_exchange_token|input_token)=[^&\s'\"]+")


def _scrub(text: str) -> str:
    """Error texts can contain a request address: never show a token."""
    return _SECRET_RX.sub(r"\1=•••", str(text))


# ----------------------------------------------------------------------------- content
_TAG = re.compile(r"<[^>]+>")


def plain(fragment: str) -> str:
    """Paragraph HTML (as in the Telegram post) -> plain text; only <br> becomes a line break (a line break in the
    HTML source is just a space)."""
    t = re.sub(r"\s*<br\s*/?>\s*", "\n", re.sub(r"\s+", " ", fragment or ""), flags=re.I)
    t = unescape(_TAG.sub("", t)).replace("\xa0", " ")
    return "\n".join(re.sub(r"[ \t]+", " ", x).strip() for x in t.split("\n")).strip()


def hashtags(tags: list[str]) -> list[str]:
    """The post's tags as #Hashtags (spelled like the clickable tags in Telegram: words joined by _)."""
    out: list[str] = []
    for t in tags:
        h = re.sub(r"\W+", "_", t or "", flags=re.U).strip("_")
        if h and "#" + h not in out:
            out.append("#" + h)
    return out


def _credit(art: Article) -> str:
    return f"{art.credit_label}: " + ", ".join(t for t, _ in art.credits) if art.credits else ""


def _cut(text: str, room: int) -> str:
    """At most `room` characters, cut at a word and ended with '…'."""
    if len(text) <= room:
        return text
    if room <= 1:
        return ""
    cut = text[:room - 1]
    if " " in cut[room // 2:]:
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,.;:-–—\n") + "…"


def _body(art: Article) -> list[str]:
    return [b for b in (plain(p) for p in art.paragraphs) if b]


FB_MAX = 60000          # Facebook: 63,206 characters per post


def facebook_text(art: Article) -> str:
    parts = [art.title, art.scheduled or ""] + _body(art) + [f"▶ {v}" for v in art.videos[:5]]
    parts += [_credit(art), " ".join(hashtags(art.tags))]
    return _cut("\n\n".join(p for p in parts if p), FB_MAX)


IG_MAX = 2150           # Instagram: 2,200 characters per caption (a little room kept for how it counts emoji)
IG_TAGS = 30            # Instagram: at most 30 hashtags


def instagram_caption(art: Article) -> str:
    head = [p for p in (art.title, art.scheduled) if p]
    tail = [p for p in (_credit(art), " ".join(hashtags(art.tags)[:IG_TAGS])) if p]
    room = IG_MAX - len("\n\n".join(head + tail)) - 4
    body: list[str] = []
    for b in _body(art):
        if room <= 20:
            break
        piece = _cut(b, room)
        body.append(piece)
        room -= len(piece) + 2
        if piece != b:
            break
    return _cut("\n\n".join(head + body + tail), IG_MAX)


X_MAX = 280


def x_weight(text: str) -> int:
    """Length as X counts it: Latin letters, digits and punctuation 1, everything else (CJK, emoji…) 2."""
    n = 0
    for ch in text:
        c = ord(ch)
        n += 1 if (c <= 0x10FF or 0x2000 <= c <= 0x200D or 0x2010 <= c <= 0x201F or 0x2032 <= c <= 0x2037) else 2
    return n


def _cut_x(text: str, room: int) -> str:
    while text and x_weight(text) > room:
        text = _cut(text, len(text) - 1)
    return text


def x_text(art: Article) -> str:
    """Title, release and the hashtags that still fit in 280 characters (no body text, no link)."""
    text = "\n\n".join(p for p in (art.title.strip(), art.scheduled) if p)
    if x_weight(text) > X_MAX:
        return _cut_x(art.title.strip(), X_MAX)
    first = True
    for tag in hashtags(art.tags):
        cand = text + ("\n\n" if first else " ") + tag
        if x_weight(cand) > X_MAX:
            break
        text, first = cand, False
    return text


def pick_images(art: Article) -> list[str]:
    """Cover first, then the gallery; videos are left out (photo posts only; a GIF becomes its first picture)."""
    out: list[str] = []
    for u in ([art.cover] if art.cover else []) + list(art.images):
        if u and u not in out and media_mod.kind_from_url(u) != "video":
            out.append(u)
    return out


def article_from(payload: str) -> Article:
    d = json.loads(payload)
    d["credits"] = [tuple(c) for c in d.get("credits") or []]
    return Article(**{k: v for k, v in d.items() if k in Article.__dataclass_fields__})


# ----------------------------------------------------------------------------- OAuth 1.0a (X)
def _pct(s) -> str:
    return quote(str(s), safe="~-._")          # RFC 3986: everything except unreserved characters


def oauth1_header(method: str, url: str, consumer_key: str, consumer_secret: str, token: str, token_secret: str,
                  params: dict | None = None, nonce: str | None = None, timestamp: int | None = None) -> str:
    """The 'Authorization' header of an OAuth 1.0a request (HMAC-SHA1). `params` = query-string parameters and the
    fields of a urlencoded form; multipart and JSON bodies are not part of the signature."""
    oauth = {"oauth_consumer_key": consumer_key, "oauth_nonce": nonce or secrets.token_hex(16),
             "oauth_signature_method": "HMAC-SHA1", "oauth_timestamp": str(timestamp or int(time.time())),
             "oauth_token": token, "oauth_version": "1.0"}
    u = urlparse(url)
    pairs = parse_qsl(u.query, keep_blank_values=True) + list((params or {}).items()) + list(oauth.items())
    norm = "&".join(f"{k}={v}" for k, v in sorted((_pct(k), _pct(v)) for k, v in pairs))
    base = "&".join((method.upper(), _pct(f"{u.scheme.lower()}://{u.netloc.lower()}{u.path}"), _pct(norm)))
    key = f"{_pct(consumer_secret)}&{_pct(token_secret)}"
    oauth["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth.items()))


# ----------------------------------------------------------------------------- Facebook / Instagram
def graph_error(status: int, j: dict, final: bool = False) -> OutletError:
    e = (j or {}).get("error") or {}
    code, sub = e.get("code"), e.get("error_subcode")
    msg = e.get("error_user_msg") or e.get("message") or f"HTTP {status}"
    text = _scrub(f"{msg} (code {code}{'/' + str(sub) if sub else ''})" if code else msg)
    if code in (4, 17, 32, 613, 80001, 80002, 80005) or (code == 9 and sub == 2207042) or sub == 2207042:
        return OutletError(f"too many posts for now: {text}", "limit", 3600 if (sub == 2207042 or code == 9) else 900)
    if code == 368:                         # "you are going too fast" - a temporary block
        return OutletError(f"Facebook blocked posting for a while: {text}", "limit", 3600)
    if code in (190, 102, 10, 3, 463, 467) or (isinstance(code, int) and 200 <= code <= 299):
        return OutletError(f"the connection does not work: {text}", "auth")
    if sub in (2207001, 2207003, 2207020, 2207027) or code in (1, 2, 9004) or e.get("is_transient") or status >= 500:
        return OutletError(text, "uncertain" if final else "temporary")
    return OutletError(text, "rejected")


class Graph:
    """Facebook Graph API calls (the Facebook Page and the Instagram account linked to it)."""

    def __init__(self, token: str, client: httpx.Client | None = None, base: str = GRAPH):
        self.token = token
        self.client = client or httpx.Client(timeout=httpx.Timeout(90, connect=20))
        self.base = base.rstrip("/")

    def call(self, method: str, path: str, params: dict | None = None, data: dict | None = None,
             files: dict | None = None, final: bool = False, token: str | None = None) -> dict:
        """final=True: the request that publishes (no answer then means 'maybe published')."""
        url = f"{self.base}/{path.lstrip('/')}"
        tok = self.token if token is None else token
        params, data = dict(params or {}), dict(data or {})
        if tok:
            (params if method in ("GET", "DELETE") else data)["access_token"] = tok
        try:
            r = self.client.request(method, url, params=params or None, data=data or None, files=files)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise OutletError(f"cannot connect to Facebook: {_scrub(e)}") from e
        except httpx.HTTPError as e:
            raise OutletError(f"no answer from Facebook ({type(e).__name__})", "uncertain" if final else "temporary") from e
        try:
            j = r.json()
        except ValueError:
            j = {}
        if r.status_code == 200 and isinstance(j, dict) and "error" not in j:
            return j
        raise graph_error(r.status_code, j if isinstance(j, dict) else {}, final)


class FacebookPage:
    def __init__(self, page_id: str, token: str, client: httpx.Client | None = None, base: str = GRAPH):
        self.page_id = page_id
        self.g = Graph(token, client, base)

    def check(self) -> dict:
        j = self.g.call("GET", self.page_id, {"fields": "id,name,link"})
        return {"page": j.get("name") or self.page_id, "link": j.get("link")}

    def upload_photo(self, jpeg: bytes) -> str:
        """An unpublished (hidden) photo of the Page; its id can be attached to a post."""
        j = self.g.call("POST", f"{self.page_id}/photos", data={"published": "false"},
                        files={"source": ("photo.jpg", jpeg, "image/jpeg")})
        return str(j["id"])

    def photo_url(self, photo_id: str) -> str:
        """Public address of an uploaded photo (largest size)."""
        imgs = self.g.call("GET", photo_id, {"fields": "images"}).get("images") or []
        imgs = sorted((i for i in imgs if i.get("source")), key=lambda i: -(i.get("width") or 0))
        if not imgs:
            raise OutletError("Facebook gave no address for an uploaded picture")
        return imgs[0]["source"]

    def delete(self, obj_id: str) -> None:
        try:
            self.g.call("DELETE", obj_id)
        except OutletError as e:          # only housekeeping: a hidden photo left behind does no harm
            log.info("could not delete Facebook object %s: %s", obj_id, e)

    def post(self, message: str, photo_ids: list[str]) -> str:
        data = {"message": message}
        for i, pid in enumerate(photo_ids):
            data[f"attached_media[{i}]"] = json.dumps({"media_fbid": pid})
        return str(self.g.call("POST", f"{self.page_id}/feed", data=data, final=True)["id"])


class Instagram:
    WAITS = (3, 5, 8, 15, 30, 60, 60, 60, 60)      # about 5 minutes in all for Instagram to fetch the pictures

    def __init__(self, ig_user_id: str, page: FacebookPage, sleep=time.sleep):
        self.ig, self.page, self.g, self.sleep = ig_user_id, page, page.g, sleep

    def check(self) -> dict:
        j = self.g.call("GET", self.ig, {"fields": "username"})
        used, total = self.quota()
        return {"username": j.get("username"), "used": used, "total": total}

    def quota(self) -> tuple[int, int]:
        """(posts published through the API in the last 24 h, how many are allowed)."""
        j = self.g.call("GET", f"{self.ig}/content_publishing_limit", {"fields": "quota_usage,config"})
        d = (j.get("data") or [{}])[0]
        return int(d.get("quota_usage") or 0), int((d.get("config") or {}).get("quota_total") or 100)

    def _ready(self, container: str) -> None:
        for wait in self.WAITS:
            j = self.g.call("GET", container, {"fields": "status_code,status"})
            st = j.get("status_code")
            if st in ("FINISHED", "PUBLISHED"):
                return
            if st in ("ERROR", "EXPIRED"):
                raise OutletError(f"Instagram could not use the pictures ({j.get('status') or st})", "rejected")
            self.sleep(wait)
        raise OutletError("Instagram took too long to fetch the pictures")

    def publish(self, caption: str, urls: list[str], before_final=None) -> str:
        if len(urls) == 1:
            c = self.g.call("POST", f"{self.ig}/media", data={"image_url": urls[0], "caption": caption})["id"]
        else:
            kids = [self.g.call("POST", f"{self.ig}/media", data={"image_url": u, "is_carousel_item": "true"})["id"]
                    for u in urls]
            c = self.g.call("POST", f"{self.ig}/media", data={"media_type": "CAROUSEL", "children": ",".join(kids),
                                                               "caption": caption})["id"]
        self._ready(c)
        if before_final:
            before_final()
        return str(self.g.call("POST", f"{self.ig}/media_publish", data={"creation_id": c}, final=True)["id"])

    def permalink(self, media_id: str) -> str | None:
        try:
            return self.g.call("GET", media_id, {"fields": "permalink"}).get("permalink")
        except OutletError:
            return None


def connect_facebook(app_id: str, app_secret: str, user_token: str, client: httpx.Client | None = None,
                     base: str = GRAPH) -> list[dict]:
    """A user token from the Graph API Explorer -> a long-lived one -> the Pages it manages, each with a Page token that
    does not expire and the Instagram account linked to the Page (if any)."""
    if not (app_id.strip() and app_secret.strip() and user_token.strip()):
        raise OutletError("fill in the App ID, the App secret and the access token", "rejected")
    g = Graph("", client, base)
    try:
        lt = g.call("GET", "oauth/access_token", {"grant_type": "fb_exchange_token", "client_id": app_id.strip(),
                                                   "client_secret": app_secret.strip(),
                                                   "fb_exchange_token": user_token.strip()}, token="")["access_token"]
        j = g.call("GET", "me/accounts", {"fields": "id,name,access_token,instagram_business_account{id,username}",
                                          "limit": 100}, token=lt)
    except OutletError as e:
        low = str(e).lower()
        hint = (" - check the App ID" if "client id" in low else " - check the App secret" if "secret" in low
                else " - the access token is wrong or expired: make a new one in the Graph API Explorer"
                if ("code 190" in low or "access token" in low) else "")
        raise OutletError(f"Facebook says: {e}{hint}", e.kind) from e
    pages = []
    for p in j.get("data") or []:
        ig = p.get("instagram_business_account") or {}
        pages.append({"id": str(p["id"]), "name": p.get("name") or str(p["id"]), "token": p.get("access_token") or "",
                      "ig_id": str(ig["id"]) if ig.get("id") else "", "ig_username": ig.get("username") or ""})
    if not pages:
        raise OutletError("this token sees no Facebook Page: when making it, tick pages_show_list (and "
                          "business_management) and choose your Page", "rejected")
    return pages


def token_scopes(app_id: str, app_secret: str, token: str, client: httpx.Client | None = None,
                 base: str = GRAPH) -> set[str] | None:
    """Permissions granted to a token (None = cannot tell)."""
    if not (app_id and app_secret and token):
        return None
    try:
        d = Graph("", client, base).call("GET", "debug_token", {"input_token": token},
                                         token=f"{app_id}|{app_secret}").get("data") or {}
    except OutletError:
        return None
    return set(d.get("scopes") or []) if d.get("is_valid", True) else set()


# ----------------------------------------------------------------------------- X
def x_error(r: httpx.Response, final: bool = False) -> OutletError:
    try:
        j = r.json()
    except ValueError:
        j = {}
    j = j if isinstance(j, dict) else {}
    errs = j.get("errors") or [{}]
    detail = _scrub(j.get("detail") or errs[0].get("message") or errs[0].get("detail") or j.get("title")
                    or r.text[:200] or f"HTTP {r.status_code}")
    low = (detail + " " + str(j.get("title") or "") + " " + str(j.get("type") or "")).lower()
    st = r.status_code
    if st == 402 or "credits" in low:
        return OutletError("X: your API credits are used up - add credits in the X developer console", "auth")
    if st == 429:
        if "usage" in low and "cap" in low:
            return OutletError(f"X: the usage limit of your plan is reached ({detail})", "limit", 6 * 3600)
        reset = r.headers.get("x-rate-limit-reset")
        try:
            wait = max(60.0, float(reset) - time.time()) if reset else 900.0
        except ValueError:
            wait = 900.0
        return OutletError(f"X says slow down ({detail})", "limit", min(wait, 24 * 3600))
    if st == 401:
        return OutletError(f"X refused the keys ({detail}) - check the 4 keys in Settings → X", "auth")
    if st == 403:
        if "duplicate" in low:
            return OutletError("X refused it as a duplicate of an earlier post", "rejected")
        return OutletError(f"X does not allow this app to post ({detail}). In the X developer portal set the app's "
                           f"permissions to 'Read and write', then make new Access Token keys", "auth")
    if st >= 500:
        return OutletError(f"X server error {st}", "uncertain" if final else "temporary")
    return OutletError(f"X refused it: {detail} (HTTP {st})", "rejected")


class XAccount:
    def __init__(self, api_key: str, api_secret: str, access_token: str, access_secret: str,
                 client: httpx.Client | None = None, base: str = X_API):
        self.keys = (api_key, api_secret, access_token, access_secret)
        self.client = client or httpx.Client(timeout=httpx.Timeout(90, connect=20))
        self.base = base.rstrip("/")

    def _call(self, method: str, path: str, json_body: dict | None = None, data: dict | None = None,
              files: dict | None = None, final: bool = False) -> dict:
        url = self.base + path
        k = self.keys
        auth = oauth1_header(method, url, k[0], k[1], k[2], k[3])
        try:
            r = self.client.request(method, url, headers={"Authorization": auth}, json=json_body, data=data, files=files)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise OutletError(f"cannot connect to X: {e}") from e
        except httpx.HTTPError as e:
            raise OutletError(f"no answer from X ({type(e).__name__})", "uncertain" if final else "temporary") from e
        if 200 <= r.status_code < 300:
            try:
                return r.json()
            except ValueError:
                raise OutletError("X sent an unreadable answer", "uncertain" if final else "temporary")
        raise x_error(r, final)

    def check(self) -> dict:
        return {"username": (self._call("GET", "/2/users/me").get("data") or {}).get("username")}

    def upload(self, jpeg: bytes) -> str:
        j = self._call("POST", "/2/media/upload", data={"media_category": "tweet_image"},
                       files={"media": ("photo.jpg", jpeg, "image/jpeg")})
        mid = (j.get("data") or {}).get("id") or j.get("media_id_string")
        if not mid:
            raise OutletError("X did not accept the picture (no media id in its answer)")
        return str(mid)

    def post(self, text: str, media_ids: list[str]) -> str:
        body: dict = {"text": text}
        if media_ids:
            body["media"] = {"media_ids": media_ids}
        return str(self._call("POST", "/2/tweets", json_body=body, final=True)["data"]["id"])


# ----------------------------------------------------------------------------- who is connected
def ready(s, outlet: str) -> bool:
    """Is this network connected (Settings)?"""
    if outlet == "facebook":
        return bool(s.fb_page_id and s.fb_page_token)
    if outlet == "instagram":
        return bool(s.ig_user_id and s.fb_page_id and s.fb_page_token)
    if outlet == "x":
        return bool(s.x_api_key and s.x_api_secret and s.x_access_token and s.x_access_secret)
    return False


def targets(s) -> list[str]:
    """Where this website's posts also go: switched on in Settings AND connected. (`s` is the website's own settings:
    for HPOI its hpoi_to_* switches arrive as to_*.)"""
    return [o for o in OUTLETS if getattr(s, f"to_{o}", False) and ready(s, o)]


# ----------------------------------------------------------------------------- the senders
class OutletRunner:
    """One thread per network. Each sends the oldest waiting post of any website whose Start/Stop is on, keeping its own
    pace. Per-network state (paused because the connection broke / held because of a limit / time of the last post) is
    remembered in the Toy-People ledger, so a restart keeps it."""

    POLL = 10.0

    def __init__(self, settings, sources: dict, state_db, client: httpx.Client | None = None, sleep=None,
                 is_active=None):
        self.s = settings
        self.sources = sources                       # {"toypeople": (engine, worker), "hpoi": (...)}
        self.db = state_db
        self.client = client or httpx.Client(timeout=httpx.Timeout(90, connect=20))
        self.sleep = sleep or self._nap
        self.is_active = is_active or (lambda name, eng, wk: wk.state() == "running")
        self._stop = threading.Event()
        self._threads: dict[str, threading.Thread] = {}
        self.busy: dict[str, str | None] = {o: None for o in OUTLETS}

    # ---- clients (built from the current settings, so a change in Settings counts at once)
    def facebook(self) -> FacebookPage:
        return FacebookPage(self.s.fb_page_id, self.s.fb_page_token, self.client)

    def instagram(self) -> Instagram:
        return Instagram(self.s.ig_user_id, self.facebook(), self.sleep)

    def x(self) -> XAccount:
        s = self.s
        return XAccount(s.x_api_key, s.x_api_secret, s.x_access_token, s.x_access_secret, self.client)

    # ---- state
    def state(self, o: str) -> dict:
        return self.db.kv_json(f"outlet:{o}", {}) or {}

    def set_state(self, o: str, **kw) -> None:
        st = self.state(o)
        st.update(kw)
        self.db.kv_set(f"outlet:{o}", json.dumps(st))

    def resume(self, o: str) -> None:
        """The connection was fixed (new keys saved / check passed): continue."""
        if self.state(o).get("paused"):
            self.set_state(o, paused=None)
            self.db.log("info", f"{NAMES[o]}: connection fixed - posting continues")

    def delay(self, o: str) -> float:
        return max(10.0, float(getattr(self.s, f"{o}_delay_seconds", 60) or 60))

    def public(self) -> dict:
        """For the dashboard: per network whether it is connected, paused, waiting, and the account it posts to."""
        s, now, out = self.s, time.time(), {}
        acct = {"facebook": s.fb_page_name or s.fb_page_id, "instagram": ("@" + s.ig_username) if s.ig_username else "",
                "x": ("@" + s.x_username) if s.x_username else ""}
        for o in OUTLETS:
            st = self.state(o)
            hold = st.get("hold_until") or 0
            out[o] = {"ready": ready(s, o), "account": acct[o], "paused": st.get("paused"),
                      "hold": int(hold - now) if hold > now else 0, "hold_reason": st.get("hold_reason"),
                      "busy": self.busy.get(o), "delay": self.delay(o)}
        return out

    # ---- threads
    def start(self) -> None:
        n = 0
        for eng, _ in self.sources.values():
            k = eng.db.outlet_stale_sending()
            if k:
                n += k
                eng.db.log("warn", f"{k} Facebook/Instagram/X post(s) were being sent when the app stopped -> "
                                   f"'Needs your attention' (they may or may not be there)")
        self._stop.clear()
        for o in OUTLETS:
            if o not in self._threads or not self._threads[o].is_alive():
                t = threading.Thread(target=self._loop, args=(o,), name=f"outlet-{o}", daemon=True)
                self._threads[o] = t
                t.start()

    def stop(self, wait: float = 60) -> None:
        self._stop.set()
        for t in self._threads.values():
            t.join(timeout=wait)

    def _nap(self, seconds: float) -> None:
        """Waiting for Instagram to fetch the pictures; ends at once when the app stops (the post waits for the restart)."""
        if self._stop.wait(seconds):
            raise OutletError("the app is stopping - this post is sent after the restart", "limit", 30)

    def _loop(self, o: str) -> None:
        while not self._stop.is_set():
            try:
                did = self.step(o)
            except Exception:  # noqa: BLE001  (never let one bad post stop the network)
                log.exception("%s: unexpected error", o)
                did = False
            self._stop.wait(1.0 if did else self.POLL)

    def step(self, o: str) -> bool:
        """Send at most one waiting post to network `o`. Returns True when something was tried."""
        if self.s.dry_run or not ready(self.s, o):
            return False
        st, now = self.state(o), time.time()
        if st.get("paused") or now < (st.get("hold_until") or 0) or now < (st.get("last_ts") or 0) + self.delay(o):
            return False
        pick = None
        for name, (eng, wk) in self.sources.items():
            n = eng.db.outlet_expire(o, now - MAX_AGE, f"not posted on {NAMES[o]}: it waited more than 2 days (old news)")
            if n:
                eng.db.log("warn", f"{NAMES[o]}: {n} post(s) waited more than 2 days and were skipped (old news)")
            if not self.is_active(name, eng, wk):
                continue
            row = eng.db.outlet_next(o)
            if row and (pick is None or (row["created_at"] or 0) < (pick[2]["created_at"] or 0)):
                pick = (name, eng, row)
        if pick is None:
            return False
        self.send(o, pick[1], pick[2])
        return True

    def send(self, o: str, eng, row: dict) -> str:
        from .engine import Deferred
        from .fetch import FetchError
        pid = row["post_id"]
        title = (eng.db.get(pid) or {}).get("title") or f"post {pid}"
        self.busy[o] = title
        try:
            art = article_from(row["payload"]) if row.get("payload") else eng.fetch_article(pid)
            remote, link = getattr(self, f"_send_{o}")(eng, pid, art)
        except OutletError as e:
            return self._trouble(o, eng, row, e)
        except Deferred as e:                         # e.g. the translator is busy: later, not a failed try
            eng.db.outlet_set(pid, o, "pending", str(e), not_before=time.time() + e.seconds)
            return "pending"
        except FetchError as e:
            return self._trouble(o, eng, row, OutletError(f"website: {e}"))
        except Exception as e:  # noqa: BLE001
            log.exception("%s: post %s", o, pid)
            return self._trouble(o, eng, row, OutletError(f"{type(e).__name__}: {e}"))
        finally:
            self.busy[o] = None
        eng.db.outlet_set(pid, o, "posted", None, remote_id=remote, link=link)
        self.set_state(o, last_ts=time.time(), hold_until=0, hold_reason=None)
        eng.db.log("info", f"{NAMES[o]}: posted {eng.display_id(pid)}: {title}")
        return "posted"

    def _trouble(self, o: str, eng, row: dict, e: OutletError) -> str:
        pid, name, ref = row["post_id"], NAMES[o], eng.display_id(row["post_id"])
        if e.kind == "auth":                          # not this post's fault: it waits for the fix
            eng.db.outlet_set(pid, o, "pending", str(e))
            self.set_state(o, paused=str(e), paused_at=time.time())
            eng.db.log("error", f"{name} paused: {e}. Fix it in ⚙ Settings; waiting posts are sent afterwards.")
            return "paused"
        if e.kind == "limit":
            wait = e.retry_after or 900
            eng.db.outlet_set(pid, o, "pending", str(e))
            self.set_state(o, hold_until=time.time() + wait, hold_reason=str(e))
            eng.db.log("warn", f"{name}: {e} - trying again in {max(1, int(wait // 60))} min")
            return "pending"
        if e.kind == "uncertain":
            eng.db.outlet_set(pid, o, "uncertain", f"{e} - it may or may not be on {name}: have a look, then choose")
            self.set_state(o, last_ts=time.time())
            eng.db.log("warn", f"{name}: post {ref} - {e}; not sent again by itself (see 'Needs your attention')")
            return "uncertain"
        attempts = (row.get("attempts") or 0) + 1
        if e.kind == "rejected" or attempts >= GIVE_UP:
            eng.db.outlet_set(pid, o, "failed", str(e), attempts=attempts)
            eng.db.log("error", f"{name}: post {ref} not posted - {e}")
            return "failed"
        delay = RETRY[min(attempts, len(RETRY)) - 1]
        eng.db.outlet_set(pid, o, "pending", str(e), attempts=attempts, not_before=time.time() + delay)
        eng.db.log("warn", f"{name}: post {ref}: {e} - trying again in {int(delay // 60)} min")
        return "pending"

    # ---- the three networks
    def _photos(self, eng, art: Article, outlet: str, prep) -> list[bytes]:
        """Up to MAX_PHOTOS pictures of the post, downloaded and prepared; one that fails is left out."""
        out: list[bytes] = []
        urls = pick_images(art)
        for u in urls:
            if len(out) >= MAX_PHOTOS[outlet]:
                break
            try:
                data, _ = eng.fetcher.get_bytes(u, referer=eng.s.site_base)
                out.append(prep(data))
            except Exception as e:  # noqa: BLE001
                log.info("%s: picture %s left out: %s", outlet, u, e)
        if urls and not out:
            raise OutletError("could not download any of the pictures")
        return out

    def _send_facebook(self, eng, pid: int, art: Article) -> tuple[str, str]:
        fb = self.facebook()
        photos = self._photos(eng, art, "facebook", lambda d: media_mod.prepare_photo(d, 2048, FB_MAX_BYTES))
        ids: list[str] = []
        try:
            for p in photos:
                ids.append(fb.upload_photo(p))
            eng.db.outlet_set(pid, "facebook", "sending")
            post_id = fb.post(facebook_text(art), ids)
        except OutletError as e:
            if e.kind != "uncertain":                 # not posted: remove the hidden photos (the next try uploads anew)
                for i in ids:
                    fb.delete(i)
            raise
        return post_id, f"https://www.facebook.com/{post_id}"

    def _send_instagram(self, eng, pid: int, art: Article) -> tuple[str, str]:
        fb, ig = self.facebook(), self.instagram()
        used, total = ig.quota()
        if used >= total:
            raise OutletError(f"Instagram's limit is reached ({used} of {total} posts in 24 hours)", "limit", 3600)
        photos = self._photos(eng, art, "instagram", media_mod.square_photo)
        if not photos:
            raise OutletError("Instagram needs at least one picture and this post has none", "rejected")
        hosted: list[str] = []
        try:
            for p in photos:
                hosted.append(fb.upload_photo(p))
            urls = [fb.photo_url(h) for h in hosted]
            media_id = ig.publish(instagram_caption(art), urls,
                                  before_final=lambda: eng.db.outlet_set(pid, "instagram", "sending"))
        finally:
            for h in hosted:                          # Instagram has its own copy now (or will fetch them again)
                fb.delete(h)
        return media_id, ig.permalink(media_id) or "https://www.instagram.com/" + (self.s.ig_username or "")

    def _send_x(self, eng, pid: int, art: Article) -> tuple[str, str]:
        xa = self.x()
        photos = self._photos(eng, art, "x", lambda d: media_mod.prepare_photo(d, 2048, X_MAX_BYTES))
        ids = [xa.upload(p) for p in photos]
        eng.db.outlet_set(pid, "x", "sending")
        tid = xa.post(x_text(art), ids)
        return tid, f"https://x.com/{self.s.x_username or 'i/web'}/status/{tid}"

    # ---- Settings page
    def check(self, o: str) -> dict:
        """Does the connection work? (Settings → Check connection.) A working check also lifts a pause."""
        s = self.s
        if not ready(s, o):
            return {"ok": False, "error": "not connected yet"}
        try:
            if o == "facebook":
                info = self.facebook().check()
                text = f"can post on the Page “{info['page']}”"
                need = {"pages_manage_posts"}
            elif o == "instagram":
                info = self.instagram().check()
                text = f"can post as @{info['username']} ({info['used']} of {info['total']} posts used in the last 24 h)"
                need = {"instagram_basic", "instagram_content_publish"}
            else:
                info = self.x().check()
                if info.get("username") and info["username"] != s.x_username:
                    from .config import save_ui_settings
                    s.x_username = info["username"]
                    save_ui_settings(s, {"x_username": s.x_username})
                text = f"can post as @{info.get('username')}"
                need = set()
        except OutletError as e:
            return {"ok": False, "error": str(e)}
        if need:
            got = token_scopes(s.fb_app_id, s.fb_app_secret, s.fb_page_token, self.client)
            if got is not None and not need <= got:
                return {"ok": False, "error": "the connection works but this permission is missing: "
                                              + ", ".join(sorted(need - got)) + " - connect again and tick it"}
        self.resume(o)
        return {"ok": True, "text": text, **info}
