"""HTTP access to the website, with Cloudflare fallbacks.

Order in FETCH_BACKEND=auto:  plain httpx  ->  FlareSolverr (if FLARESOLVERR_URL)  ->  Playwright Chromium.
Once a browser/FlareSolverr solved a challenge, its cookies + UA are copied into the httpx client so most
following requests stay cheap.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

from .config import Settings

log = logging.getLogger("tpclone.fetch")


class FetchError(Exception):
    pass


class ChallengeError(FetchError):
    pass


class NotFound(FetchError):
    pass


@dataclass
class Page:
    url: str
    status: int
    text: str
    headers: dict


def is_challenge(status: int, headers: dict, text: str) -> bool:
    if headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    if status in (403, 429, 503):
        head = text[:4000].lower()
        return "just a moment" in head or "cf-chl" in head or "challenge-platform" in head or "attention required" in head
    return False


class BrowserBackend:
    """Playwright Chromium, driven from ONE dedicated thread (the sync API is thread-bound)."""

    def __init__(self, settings: Settings):
        self.s = settings
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")
        self._pw = self._browser = self._ctx = None

    def _ensure(self):
        if self._ctx:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as e:  # pragma: no cover
            raise ChallengeError("Cloudflare challenge hit and Playwright is not installed "
                                 "(pip install playwright && playwright install chromium)") from e
        self._pw = sync_playwright().start()
        kw = {"headless": True, "args": ["--disable-blink-features=AutomationControlled"]}
        if self.s.proxy_url:
            kw["proxy"] = {"server": self.s.proxy_url}
        self._browser = self._pw.chromium.launch(**kw)
        self._ctx = self._browser.new_context(user_agent=self.s.user_agent, locale="en-US")

    def _get(self, url: str, timeout: float) -> tuple[int, str, list[dict]]:
        self._ensure()
        page = self._ctx.new_page()
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=int(timeout * 1000))
            deadline = time.time() + timeout
            while time.time() < deadline:
                title = (page.title() or "").lower()
                if "just a moment" not in title and "attention required" not in title:
                    break
                page.wait_for_timeout(2000)
            else:
                raise ChallengeError("browser could not pass the Cloudflare challenge in time")
            return (resp.status if resp else 0), page.content(), self._ctx.cookies()
        finally:
            page.close()

    def get(self, url: str, timeout: float = 60) -> tuple[int, str, list[dict]]:
        return self.pool.submit(self._get, url, timeout).result(timeout + 30)


class Fetcher:
    def __init__(self, settings: Settings):
        self.s = settings
        self.client = httpx.Client(
            headers={"User-Agent": settings.user_agent, "Accept-Language": "en-US,en;q=0.9",
                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"},
            follow_redirects=True, timeout=httpx.Timeout(30, connect=15),
            proxy=settings.proxy_url or None,
        )
        self._browser: BrowserBackend | None = None
        self._last = 0.0
        self._lock = threading.Lock()

    # politeness: never hammer the site, whichever thread asks
    def _pace(self) -> None:
        with self._lock:
            wait = self._last + self.s.site_delay_seconds - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()

    def _adopt_cookies(self, cookies: list[dict]) -> None:
        for c in cookies:
            self.client.cookies.set(c["name"], c["value"], domain=c.get("domain", "").lstrip(".") or None,
                                    path=c.get("path", "/"))

    def _via_flaresolverr(self, url: str) -> Page:
        r = httpx.post(self.s.flaresolverr_url, json={"cmd": "request.get", "url": url, "maxTimeout": 60000},
                       timeout=90)
        r.raise_for_status()
        j = r.json()
        if j.get("status") != "ok":
            raise ChallengeError(f"FlareSolverr failed: {j.get('message')}")
        sol = j["solution"]
        self._adopt_cookies([{"name": c["name"], "value": c["value"], "domain": c.get("domain"),
                              "path": c.get("path", "/")} for c in sol.get("cookies", [])])
        if sol.get("userAgent"):
            self.client.headers["User-Agent"] = sol["userAgent"]
        return Page(url, int(sol.get("status", 200)), sol.get("response", ""), {})

    def _via_browser(self, url: str) -> Page:
        if not self._browser:
            self._browser = BrowserBackend(self.s)
        status, html, cookies = self._browser.get(url)
        self._adopt_cookies(cookies)
        return Page(url, status, html, {})

    def get_text(self, url: str, *, retries: int = 3, headers: dict | None = None) -> Page:
        backend = self.s.fetch_backend
        last_exc: Exception | None = None
        for attempt in range(retries):
            self._pace()
            try:
                if backend in ("auto", "http"):
                    r = self.client.get(url, headers=headers)
                    h = {k.lower(): v for k, v in r.headers.items()}
                    if is_challenge(r.status_code, h, r.text):
                        if backend == "http":
                            raise ChallengeError(f"Cloudflare challenge on {url}")
                        log.warning("Cloudflare challenge on %s - using fallback", url)
                        page = self._fallback(url)
                    else:
                        page = Page(url, r.status_code, r.text, h)
                else:
                    page = self._fallback(url, force=backend)
                if page.status == 404:
                    raise NotFound(url)
                if page.status >= 500 or page.status == 429:
                    raise FetchError(f"HTTP {page.status} for {url}")
                if page.status >= 400:
                    raise FetchError(f"HTTP {page.status} for {url}")
                return page
            except (NotFound, ChallengeError):
                raise
            except (httpx.HTTPError, FetchError) as e:
                last_exc = e
                time.sleep(2 ** attempt * 2)
        raise FetchError(f"{url}: {last_exc}")

    def _fallback(self, url: str, force: str = "") -> Page:
        if (force == "flaresolverr") or (not force and self.s.flaresolverr_url):
            return self._via_flaresolverr(url)
        return self._via_browser(url)

    def get_bytes(self, url: str, referer: str | None = None) -> tuple[bytes, str]:
        self._pace()
        h = {"Referer": referer or self.s.site_base, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
        r = self.client.get(url, headers=h)
        if r.status_code == 404:
            raise NotFound(url)
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "")

    def close(self) -> None:
        self.client.close()
