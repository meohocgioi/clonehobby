"""Fetcher against a fake 'Cloudflare' (real Chromium): after the first challenge the browser path is used directly."""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tpclone.config import Settings
from tpclone.fetch import Fetcher

CHROMIUM = os.environ.get("PW_TEST_CHROMIUM", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
pytestmark = pytest.mark.skipif(not Path(CHROMIUM).is_file(), reason="no Chromium available for the browser test")

STATS = {"challenged": 0, "served": 0}
CHALLENGE = ("<html><head><title>Just a moment...</title></head><body>checking your browser<script>"
             "setTimeout(function(){document.cookie='cf=1; path=/'; location.reload();}, 600)</script></body></html>")


class FakeCF(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        page = self.path.startswith("/en")          # ignore the browser asking for /favicon.ico
        if "cf=1" in (self.headers.get("Cookie") or ""):
            STATS["served"] += page
            body, code = f"<html><head><title>Real</title></head><body>page {self.path}</body></html>".encode(), 200
        else:
            STATS["challenged"] += page
            body, code = CHALLENGE.encode(), 403
        self.send_response(code); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)


def test_challenge_solved_once_then_browser_is_used_directly():
    STATS.update(challenged=0, served=0)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeCF)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    s = Settings(site_delay_seconds=0, browser_path=CHROMIUM, fetch_backend="auto")
    f = Fetcher(s)
    try:
        pages = [f.get_text(f"{base}/en/?p={i}") for i in range(1, 7)]
        assert all(f"page /en/?p={i}" in p.text for i, p in enumerate(pages, 1))
        # 1st request: plain HTTP challenged (1). The real page load in the browser: challenged once, then the page after reload.
        # Pages 2..6 must NOT be challenged again and must not even try plain HTTP first.
        assert STATS["challenged"] == 2, STATS
        assert STATS["served"] == 6 + 0 or STATS["served"] >= 6, STATS
        assert f._browser._warm is True and f._blocked_until > 0
    finally:
        srv.shutdown()
        if f._browser:
            f._browser.pool.submit(lambda: f._browser._browser and f._browser._browser.close()).result(30)
