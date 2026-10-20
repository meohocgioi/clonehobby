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


# whole lines of product descriptions the machine translates badly ("本体" -> "Ontology")
LINE_TERMS = {
    "本体": "Main body", "商品内容": "Set contents", "商品构成": "Set contents", "套装内容": "Set contents",
    "附属品": "Accessories", "配件": "Accessories", "附件": "Accessories",
}
BULLET = re.compile(r"^([・•·●○◆◇■□★☆※\-–—*]+\s*)")


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

    def translate_lines(self, lines: list[str], sl: str = "zh-CN") -> list[str]:
        """Translate a text line by line, keeping its layout: one English line per line, list bullets ("・") kept.
        Lines are sent together (few requests); if Google merges or splits lines, they are translated one by one."""
        gloss = self.glossary()
        out: list[str | None] = [None] * len(lines)
        marks: list[str] = [""] * len(lines)
        todo: list[int] = []
        for i, raw in enumerate(lines):
            line = re.sub(r"[ \t]+", " ", (raw or "").replace("\u3000", " ")).strip()
            m = BULLET.match(line)
            if m:
                marks[i], line = m.group(1), line[m.end():].strip()
            if not line or not has_cjk(line):
                out[i] = line
            elif line in LINE_TERMS or line in gloss:
                out[i] = LINE_TERMS.get(line) or gloss[line]
            else:
                row = self.db._q("SELECT out FROM translations WHERE src=? AND lang=?", (line, sl))
                if row:
                    out[i] = row[0]["out"]
                else:
                    out[i] = line                       # translated below
                    todo.append(i)

        def prepare(s: str) -> str:
            for k in sorted(gloss, key=len, reverse=True):
                if k in s:
                    s = s.replace(k, f" {gloss[k]} ")
            return re.sub(r"\s+", " ", s).strip()

        # the lines still to translate, in requests of at most ~1200 characters
        chunks: list[list[int]] = []
        cur: list[int] = []
        size = 0
        for i in todo:
            if cur and size + len(out[i]) + 1 > 1200:
                chunks.append(cur)
                cur, size = [], 0
            cur.append(i)
            size += len(out[i]) + 1
        if cur:
            chunks.append(cur)
        for chunk in chunks:
            src = [out[j] for j in chunk]
            prep = [prepare(x) for x in src]
            joined = "\n".join(prep)
            got = (self._remote(joined, sl) if has_cjk(joined) else joined).split("\n")
            if len(got) != len(chunk):                  # Google merged / split lines: one line at a time
                got = [self._remote(x, sl) if has_cjk(x) else x for x in prep]
            for j, x, g in zip(chunk, src, got):
                g = self._tidy(g)
                if not g:
                    raise TranslateError(f"empty translation for {x!r}")
                self.db._x("INSERT OR REPLACE INTO translations(src, lang, out) VALUES(?,?,?)", (x, sl, g))
                out[j] = g
        return [marks[i] + (out[i] or "") for i in range(len(lines))]

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

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0.0.0 Safari/537.36")

    @staticmethod
    def _parse_clients5(j) -> str:
        # ["text"]  or  [["text", "zh-CN"]]
        first = j[0]
        out = first[0] if isinstance(first, list) else first
        if not isinstance(out, str):
            raise TypeError("unexpected answer")
        return out

    @staticmethod
    def _parse_gtx(j) -> str:
        return "".join(seg[0] for seg in j[0] if seg and seg[0])

    def _google_free(self, text: str, sl: str) -> str:
        """Free endpoints, tried in turn (each one rate-limits on its own): the Chrome-dictionary one, the classic
        'gtx' one, and MyMemory as the last resort."""
        gtx = {"client": "gtx", "sl": sl, "tl": "en", "dt": "t", "q": text}
        tries = [(self.endpoint, gtx, self._parse_gtx)] if self.endpoint else [
            ("https://clients5.google.com/translate_a/t",
             {"client": "dict-chrome-ex", "sl": sl, "tl": "en", "q": text}, self._parse_clients5),
            ("https://translate.googleapis.com/translate_a/single", gtx, self._parse_gtx),
            ("https://translate.google.com/translate_a/single", gtx, self._parse_gtx)]
        errors = []
        for url, params, parse in tries:
            try:
                r = self.client.get(url, params=params, headers={"User-Agent": self.UA})
                if r.status_code != 200:
                    errors.append(f"HTTP {r.status_code}")
                    continue
                out = parse(r.json())
                if out:
                    return out
                errors.append("empty answer")
            except (httpx.HTTPError, ValueError, IndexError, TypeError, KeyError) as e:
                errors.append(f"{type(e).__name__}")
        if not self.endpoint and len(text) <= 450:
            try:
                r = self.client.get("https://api.mymemory.translated.net/get",
                                    params={"q": text, "langpair": f"{sl}|en"}, headers={"User-Agent": self.UA})
                if r.status_code == 200:
                    out = (r.json().get("responseData") or {}).get("translatedText") or ""
                    if out and "MYMEMORY WARNING" not in out.upper():
                        return out
                errors.append(f"MyMemory HTTP {r.status_code}")
            except (httpx.HTTPError, ValueError) as e:
                errors.append(f"MyMemory {type(e).__name__}")
        self.blocked_until = time.time() + 120      # every service said no: stop hammering for a couple of minutes
        raise TranslateError("Google Translate: " + ", ".join(errors))

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
