"""Chinese/Japanese -> English text translation for the HPOI source.

* provider "google_free"  - the public endpoint behind Google Translate's web page (no key; unofficial, so it can
                            rate-limit: the caller then simply retries the post later - nothing is ever posted untranslated)
* provider "google_cloud" - the official Cloud Translation API (needs an API key)

Every translation is cached in the ledger database, so the same name is never asked twice. A small glossary
(<data>/hpoi_glossary.json, editable) forces the English spelling of names the machine gets wrong.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path

import httpx

log = logging.getLogger("tpclone.translate")

CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿ｦ-ﾟ]")

# Spellings the user asked for (machine translation turns names into "Hoshiuta" etc.). Edit the JSON file to add more.
DEFAULT_GLOSSARY = {
    "孤独摇滚！": "Lonely Rock!",
    "孤独摇滚": "Lonely Rock!",
    "伊地知星歌": "Ijichi Seika",
    "音戏ALTO": "Onkyo ALTO",
    "广井菊理": "Hiroi Kikuri",
    "后藤偶": "Goto Doll",
}


class TranslateError(Exception):
    pass


def has_cjk(text: str) -> bool:
    return bool(CJK.search(text or ""))


class Translator:
    GAP = 1.2                       # seconds between two requests (the free endpoint flood-limits)

    def __init__(self, db, provider: str = "google_free", api_key: str = "", glossary_file: Path | None = None,
                 client: httpx.Client | None = None, endpoint: str | None = None, sleep=time.sleep):
        self.db, self.provider, self.api_key = db, provider, api_key
        self.glossary_file = glossary_file
        self.client = client or httpx.Client(timeout=httpx.Timeout(30, connect=15))
        self.endpoint = endpoint
        self.sleep = sleep
        self._lock = threading.Lock()
        self._last = 0.0
        self.blocked_until = 0.0
        db._x("CREATE TABLE IF NOT EXISTS translations (src TEXT NOT NULL, lang TEXT NOT NULL, out TEXT NOT NULL, "
              "PRIMARY KEY (src, lang))")

    # ---- glossary ------------------------------------------------------
    def glossary(self) -> dict[str, str]:
        g = dict(DEFAULT_GLOSSARY)
        f = self.glossary_file
        if f:
            try:
                if f.is_file():
                    g.update({str(k): str(v) for k, v in json.loads(f.read_text(encoding="utf8")).items()})
                else:
                    f.parent.mkdir(parents=True, exist_ok=True)
                    f.write_text(json.dumps(DEFAULT_GLOSSARY, indent=2, ensure_ascii=False), encoding="utf8")
            except (OSError, ValueError) as e:
                log.warning("glossary file unusable: %s", e)
        return g

    # ---- public API ----------------------------------------------------
    def translate(self, text: str, sl: str = "zh-CN") -> str:
        """English text for `text`. Text without any CJK characters is returned unchanged."""
        text = re.sub(r"\s+", " ", (text or "").replace("　", " ")).strip()
        if not text or not has_cjk(text):
            return text
        gloss = self.glossary()
        if text in gloss:
            return gloss[text]
        row = self.db._q("SELECT out FROM translations WHERE src=? AND lang=?", (text, sl))
        if row:
            return row[0]["out"]
        # force the glossary spellings inside longer text (Google leaves Latin words alone)
        prepared = text
        for k in sorted(gloss, key=len, reverse=True):
            if k in prepared:
                prepared = prepared.replace(k, f" {gloss[k]} ")
        prepared = re.sub(r"\s+", " ", prepared).strip()
        out = prepared if not has_cjk(prepared) else self._remote(prepared, sl)
        out = self._tidy(out)
        if not out:
            raise TranslateError(f"empty translation for {text!r}")
        self.db._x("INSERT OR REPLACE INTO translations(src, lang, out) VALUES(?,?,?)", (text, sl, out))
        return out

    @staticmethod
    def _tidy(s: str) -> str:
        s = re.sub(r"\s+", " ", s or "").strip()
        s = re.sub(r"\s+([,.;:!?])", r"\1", s)
        return s

    # ---- providers -----------------------------------------------------
    def _remote(self, text: str, sl: str) -> str:
        with self._lock:
            now = time.time()
            if now < self.blocked_until:
                raise TranslateError(f"translator is cooling down for {int(self.blocked_until - now)}s")
            wait = self._last + self.GAP - now
            if wait > 0:
                self.sleep(wait)
            try:
                return self._google_cloud(text, sl) if self.provider == "google_cloud" else self._google_free(text, sl)
            finally:
                self._last = time.time()

    def _google_free(self, text: str, sl: str) -> str:
        urls = [self.endpoint] if self.endpoint else ["https://translate.googleapis.com/translate_a/single",
                                                      "https://translate.google.com/translate_a/single"]
        last = ""
        for url in urls:
            try:
                r = self.client.get(url, params={"client": "gtx", "sl": sl, "tl": "en", "dt": "t", "q": text})
            except httpx.HTTPError as e:
                last = f"{type(e).__name__}: {e}"
                continue
            if r.status_code == 200:
                try:
                    return "".join(seg[0] for seg in r.json()[0] if seg and seg[0])
                except (ValueError, IndexError, TypeError, KeyError) as e:
                    last = f"unexpected answer: {e}"
                    continue
            last = f"HTTP {r.status_code}"
            if r.status_code == 429:
                self.blocked_until = time.time() + 600
        raise TranslateError(f"Google Translate: {last}")

    def _google_cloud(self, text: str, sl: str) -> str:
        if not self.api_key:
            raise TranslateError("no Google Cloud Translation API key set")
        url = self.endpoint or "https://translation.googleapis.com/language/translate/v2"
        try:
            r = self.client.post(url, params={"key": self.api_key},
                                 json={"q": text, "source": sl.split("-")[0], "target": "en", "format": "text"})
        except httpx.HTTPError as e:
            raise TranslateError(f"{type(e).__name__}: {e}") from e
        if r.status_code != 200:
            raise TranslateError(f"Google Cloud Translation HTTP {r.status_code}: {r.text[:150]}")
        try:
            from html import unescape
            return unescape(r.json()["data"]["translations"][0]["translatedText"])
        except (ValueError, KeyError, IndexError) as e:
            raise TranslateError(f"unexpected answer: {e}") from e
