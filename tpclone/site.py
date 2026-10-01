"""Parsing of toy-people.com: sitemap, dates and article pages.

The article parser is heuristic (meta tags / JSON-LD / common class names / text patterns) and every part can be
overridden with a JSON file (SELECTORS_FILE) of CSS selectors - see README "Tuning the parser" and `tpclone inspect`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, NavigableString, Tag

from .config import Settings

# ----------------------------------------------------------------------------- sitemap
_URL_BLOCK = re.compile(r"<url>(.*?)</url>", re.S)
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_LASTMOD = re.compile(r"<lastmod>\s*([^<\s]+)\s*</lastmod>")
_PID = re.compile(r"[?&]p=(\d+)")


def parse_sitemap(xml: str) -> list[tuple[int, str, str | None]]:
    """-> [(post_id, url, lastmod)] for every ?p=ID entry, sorted by post_id ascending."""
    out: dict[int, tuple[int, str, str | None]] = {}
    for m in _URL_BLOCK.finditer(xml):
        block = m.group(1)
        loc = _LOC.search(block)
        if not loc:
            continue
        pid = _PID.search(loc.group(1))
        if not pid:
            continue
        lm = _LASTMOD.search(block)
        i = int(pid.group(1))
        out[i] = (i, loc.group(1).replace("&amp;", "&"), lm.group(1) if lm else None)
    return [out[k] for k in sorted(out)]


# ----------------------------------------------------------------------------- dates
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_PATTERNS = [
    (re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"), "ymd"),
    (re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"), "ymd"),
    (re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"), "mdy"),
    (re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})"), "dmy"),
]


def parse_date(raw: str | None, tz: str = "Asia/Taipei") -> str | None:
    """Return YYYY-MM-DD in the site's timezone, or None."""
    if not raw:
        return None
    raw = raw.strip()
    # full ISO timestamp with offset -> convert to site tz
    if re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo:
                dt = dt.astimezone(ZoneInfo(tz))
            return dt.date().isoformat()
        except ValueError:
            pass
    for rx, kind in _DATE_PATTERNS:
        m = rx.search(raw)
        if not m:
            continue
        try:
            if kind == "ymd":
                y, mo, d = int(m[1]), int(m[2]), int(m[3])
            elif kind == "mdy":
                mo = _MONTHS.get(m[1][:3].lower())
                y, d = int(m[3]), int(m[2])
            else:
                mo = _MONTHS.get(m[2][:3].lower())
                y, d = int(m[3]), int(m[1])
            if mo:
                return datetime(y, mo, d).date().isoformat()
        except ValueError:
            continue
    return None


# ----------------------------------------------------------------------------- article model
@dataclass
class Article:
    post_id: int
    url: str
    title: str = ""
    cover: str | None = None
    post_date: str | None = None
    scheduled: str | None = None            # full line as shown on the web, e.g. "Scheduled Release: 2026/12"
    tags: list[str] = field(default_factory=list)
    paragraphs: list[str] = field(default_factory=list)   # sanitised inline HTML, one per paragraph
    images: list[str] = field(default_factory=list)
    credit_label: str = "via"
    credits: list[tuple[str, str | None]] = field(default_factory=list)  # [(text, url)]
    videos: list[str] = field(default_factory=list)       # embedded video page URLs (kept as links)

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------- helpers
DEFAULT_BODY_SELECTORS = [
    "[itemprop=articleBody]", ".entry-content", ".post-content", ".article-content", ".article_content",
    ".post-body", ".news-content", ".content-body", "#article-content", "#content article", "article", "main",
]
_CREDIT_RX = re.compile(r"^\s*(via|cre|credit|credits|source|photo)\s*[:：]\s*", re.I)
_SCHED_RX = re.compile(r"scheduled\s*release|release\s*schedule|release\s*date|expected\s*release", re.I)
_JUNK_IMG = re.compile(r"(icon|logo|emoji|avatar|sprite|spacer|pixel|loading|blank|/ads?/|ad_code|banner|"
                       r"facebook|twitter|line_|share)", re.I)
_BAD_BODY_CLASS = re.compile(r"(share|related|comment|sidebar|breadcrumb|pagination|social|advert|\bads?\b|"
                             r"newsletter|recommend|navigation|navbar)", re.I)
_TITLE_SUFFIX = re.compile(r"\s*[|\-–—_]\s*(toy[\s-]*people).*$", re.I)


def load_selectors(path: str) -> dict:
    if path and Path(path).is_file():
        return json.loads(Path(path).read_text(encoding="utf8"))
    return {}


def _gone(el: Tag) -> bool:
    return bool(getattr(el, "decomposed", False))


def _txt(node: Tag | None) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _abs(url: str | None, base: str) -> str | None:
    if not url:
        return None
    url = url.strip()
    if url.startswith(("data:", "javascript:", "#")):
        return None
    return urljoin(base, url)


def _img_url(img: Tag, base: str) -> str | None:
    for attr in ("data-original", "data-src", "data-lazy-src", "data-full", "data-large"):
        if img.get(attr):
            return _abs(img[attr], base)
    ss = img.get("srcset") or img.get("data-srcset")
    if ss:
        best, bw = None, -1
        for part in ss.split(","):
            bits = part.strip().split()
            if not bits:
                continue
            w = int(re.sub(r"\D", "", bits[1]) or 0) if len(bits) > 1 else 0
            if w >= bw:
                best, bw = bits[0], w
        if best:
            return _abs(best, base)
    return _abs(img.get("src"), base)


def _inline(node, base: str) -> str:
    """Sanitised inline HTML (only b/i/u/s/a/br)."""
    out: list[str] = []
    for ch in node.children:
        if isinstance(ch, NavigableString):
            if ch.__class__.__name__ in ("Comment", "Doctype", "CData"):
                continue
            out.append(escape(str(ch).replace("\xa0", " "), quote=False))
        elif isinstance(ch, Tag):
            n = ch.name
            if n in ("script", "style", "noscript", "img", "iframe", "svg", "video", "audio", "button", "form"):
                continue
            inner = _inline(ch, base)
            if n in ("b", "strong"):
                out.append(f"<b>{inner}</b>" if inner.strip() else inner)
            elif n in ("i", "em"):
                out.append(f"<i>{inner}</i>" if inner.strip() else inner)
            elif n in ("u", "ins"):
                out.append(f"<u>{inner}</u>" if inner.strip() else inner)
            elif n in ("s", "del", "strike"):
                out.append(f"<s>{inner}</s>" if inner.strip() else inner)
            elif n == "br":
                out.append("<br>")
            elif n == "a":
                href = _abs(ch.get("href"), base)
                if href and href.startswith(("http://", "https://", "mailto:")) and inner.strip():
                    out.append(f'<a href="{escape(href, quote=True)}">{inner}</a>')
                else:
                    out.append(inner)
            else:
                out.append(inner)
    return "".join(out)


_BLOCK_PARA = {"p", "li", "blockquote", "figcaption", "dd", "dt"}
_BLOCK_HEAD = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_RECURSE = {"div", "section", "article", "ul", "ol", "figure", "table", "tbody", "tr", "td", "th", "dl",
                  "main", "span", "center", "font", "details", "summary"}


def _paragraphs(container: Tag, base: str) -> list[str]:
    paras: list[str] = []
    buf: list[str] = []

    def flush():
        s = "".join(buf).strip()
        s = re.sub(r"(\s*<br>\s*)+$", "", s)
        s = re.sub(r"^(\s*<br>\s*)+", "", s)
        if re.sub(r"<[^>]+>|&\w+;|\s", "", s):
            paras.append(re.sub(r"[ \t\r\n]+", " ", s).strip())
        buf.clear()

    def walk(node: Tag):
        for ch in node.children:
            if isinstance(ch, NavigableString):
                if ch.__class__.__name__ not in ("Comment", "Doctype", "CData"):
                    buf.append(escape(str(ch).replace("\xa0", " "), quote=False))
                continue
            if not isinstance(ch, Tag):
                continue
            n = ch.name
            if n in ("script", "style", "noscript", "iframe", "svg", "img", "video", "audio", "button", "form"):
                continue
            if n in _BLOCK_PARA:
                flush()
                buf.append(_inline(ch, base))
                flush()
            elif n in _BLOCK_HEAD:
                flush()
                t = _inline(ch, base).strip()
                if t:
                    buf.append(f"<b>{t}</b>")
                flush()
            elif n in _BLOCK_RECURSE:
                flush()
                walk(ch)
                flush()
            elif n == "br":
                buf.append("<br>")
            else:
                buf.append(_inline(ch, base))

    walk(container)
    flush()
    return paras


def _find_body(soup: BeautifulSoup, selectors: dict) -> Tag | None:
    cands = ([selectors["body"]] if selectors.get("body") else []) + DEFAULT_BODY_SELECTORS
    for sel in cands:
        try:
            found = soup.select(sel)
        except Exception:
            continue
        for el in found:
            if el.find("p") or el.find("img"):
                return el
    # fallback: the element whose direct <p> children hold the most text
    best, score = None, 0
    for el in soup.find_all(["div", "section"]):
        s = sum(len(_txt(p)) for p in el.find_all("p", recursive=False))
        if s > score:
            best, score = el, s
    return best


def _extract_credits(root: Tag, base: str, selectors: dict) -> tuple[Tag | None, str, list[tuple[str, str | None]]]:
    """Locate the 'via: xxx' element. Returns (element, label, [(text,url)])."""
    el: Tag | None = None
    if selectors.get("credit"):
        el = root.select_one(selectors["credit"])
    if el is None:
        best = None
        for cand in root.find_all(["p", "div", "span", "li", "small", "em", "i", "h5", "h6"]):
            t = _txt(cand)
            if len(t) <= 220 and _CREDIT_RX.match(t):
                # innermost match wins (smallest text), later in document wins ties
                if best is None or len(t) <= len(_txt(best)):
                    best = cand
        el = best
    if el is None:
        return None, "via", []
    t = _txt(el)
    m = _CREDIT_RX.match(t)
    label = m.group(1) if m else "via"
    creds: list[tuple[str, str | None]] = []
    for a in el.find_all("a"):
        href = _abs(a.get("href"), base)
        text = _txt(a)
        if text:
            creds.append((text, href if href and href.startswith("http") else None))
    if not creds:
        rest = _CREDIT_RX.sub("", t).strip()
        if rest:
            creds.append((rest, None))
    return el, label, creds


def _find_tags(soup: BeautifulSoup, h1: Tag | None, selectors: dict) -> tuple[list[str], list[Tag]]:
    els: list[Tag] = []
    if selectors.get("tags"):
        els = soup.select(selectors["tags"])
    else:
        rx = re.compile(r"(/tags?/|[?&]tags?=|[?&]tag_id=|/tag-)", re.I)
        scope: Tag | None = h1
        for _ in range(5):  # climb from the title until an ancestor contains tag links
            if scope is None or scope.parent is None:
                break
            scope = scope.parent
            els = [a for a in scope.find_all("a", href=rx)]
            if els:
                break
        if not els:
            els = [a for a in soup.select(".tags a, .tag a, [class*=tag] a") if a.get("href")][:15]
    tags: list[str] = []
    for a in els:
        t = _txt(a).lstrip("#").strip()
        if t and t.lower() not in (x.lower() for x in tags):
            tags.append(t)
    if not tags:
        for m in soup.find_all("meta", attrs={"property": "article:tag"}):
            t = (m.get("content") or "").strip()
            if t and t not in tags:
                tags.append(t)
    return tags, els


def _find_scheduled(root: Tag, selectors: dict) -> tuple[str | None, Tag | None]:
    if selectors.get("scheduled"):
        el = root.select_one(selectors["scheduled"])
        return (_txt(el) or None), el
    for cand in root.find_all(["p", "div", "span", "li", "h4", "h5", "h6", "strong", "b", "dt", "td", "em", "i"]):
        t = _txt(cand)
        if len(t) <= 160 and _SCHED_RX.search(t):
            if len(_txt(cand)) <= len(_SCHED_RX.search(t).group(0)) + 2:
                # label only -> value is in the next sibling element
                sib = cand.find_next_sibling()
                if sib is not None:
                    return f"{t.rstrip(':：')}: {_txt(sib)}", cand
            return t, cand
    return None, None


def _find_date(soup: BeautifulSoup, selectors: dict, tz: str) -> str | None:
    if selectors.get("date"):
        el = soup.select_one(selectors["date"])
        if el is not None:
            return parse_date(el.get("datetime") or el.get("content") or _txt(el), tz)
    for attrs in ({"property": "article:published_time"}, {"itemprop": "datePublished"},
                  {"name": "pubdate"}, {"property": "og:article:published_time"}):
        m = soup.find("meta", attrs=attrs)
        if m and m.get("content"):
            d = parse_date(m["content"], tz)
            if d:
                return d
    for sc in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(sc.string or "")
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                if o.get("datePublished"):
                    d = parse_date(str(o["datePublished"]), tz)
                    if d:
                        return d
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    t = soup.find("time")
    if t:
        d = parse_date(t.get("datetime") or _txt(t), tz)
        if d:
            return d
    for el in soup.select("[class*=date], [class*=time], [class*=publish], [class*=posted]"):
        d = parse_date(_txt(el), tz)
        if d:
            return d
    return None


# ----------------------------------------------------------------------------- main entry
def parse_article(html: str, url: str, post_id: int, settings: Settings, selectors: dict | None = None) -> Article:
    selectors = selectors or {}
    soup = BeautifulSoup(html, "lxml")
    art = Article(post_id=post_id, url=url)

    # title
    h1 = soup.select_one(selectors["title"]) if selectors.get("title") else soup.find("h1")
    title = _txt(h1)
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        title = (og.get("content") if og else "") or _txt(soup.find("title"))
    art.title = _TITLE_SUFFIX.sub("", title).strip()

    art.post_date = _find_date(soup, selectors, settings.site_tz)
    tags, tag_els = _find_tags(soup, h1, selectors)
    art.tags = tags

    # cover
    cover = None
    if selectors.get("cover"):
        el = soup.select_one(selectors["cover"])
        if el is not None:
            cover = el.get("content") or el.get("src") or el.get("data-src")
    if not cover:
        og = soup.find("meta", attrs={"property": "og:image"}) or soup.find("meta", attrs={"name": "twitter:image"})
        cover = og.get("content") if og else None
    art.cover = _abs(cover, url)

    body = _find_body(soup, selectors)
    if body is None:
        return art

    for sel in selectors.get("remove", []):
        for el in body.select(sel):
            el.decompose()
    for el in body.find_all(["script", "style", "noscript", "nav", "aside", "footer", "form", "button"]):
        el.decompose()
    for el in list(body.find_all(True)):
        if _gone(el):
            continue
        cls = " ".join(el.get("class", [])) + " " + (el.get("id") or "")
        if cls.strip() and _BAD_BODY_CLASS.search(cls) and el is not body:
            el.decompose()

    # videos kept as links (embeds can't be shown inside the message)
    for fr in body.find_all("iframe"):
        src = _abs(fr.get("src") or fr.get("data-src"), url)
        if src and re.search(r"(youtube|youtu\.be|vimeo|bilibili|nicovideo|facebook\.com/plugins/video)", src):
            art.videos.append(src)

    # images (full-size link target wins over the thumbnail)
    seen: set[str] = set()
    for img in body.find_all("img"):
        w = img.get("width", "")
        if w.isdigit() and int(w) < 100:
            continue
        src = _img_url(img, url)
        a = img.find_parent("a")
        if a is not None and a.get("href") and re.search(r"\.(jpe?g|png|webp|gif)(\?|$)", a["href"], re.I):
            src = _abs(a["href"], url) or src
        if not src or _JUNK_IMG.search(urlparse(src).path) or src in seen:
            continue
        seen.add(src)
        art.images.append(src)

    # pull out the structured bits so they are not duplicated in the body text
    ced, label, creds = _extract_credits(body, url, selectors)
    art.credit_label, art.credits = label, creds
    if ced is not None:
        ced.decompose()
    sched, sel_el = _find_scheduled(body, selectors)
    if sched is None:  # often sits in the header next to the title
        sched, sel_el = _find_scheduled(soup, selectors)
    art.scheduled = sched
    if sel_el is not None and not _gone(sel_el):
        sel_el.decompose()
    for el in tag_els:
        if body in el.parents:
            el.decompose()

    art.paragraphs = _paragraphs(body, url)
    return art
