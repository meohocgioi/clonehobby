"""Article -> Telegram Rich Message (HTML style).

Preview post (what the channel shows):
    <h6>Title</h6>
    cover photo
    [Show More]   <- a collapsed <details>; tapping it expands the full post in place

Full post (inside the <details>):
    1. Scheduled Release   (italic; omitted if the post has none)
    2. Hashtags            (italic, exactly as on the web)
    3. Text body
    4. All photos in a <tg-collage>  (<= MAX_MEDIA photos in the whole message; overflow becomes ONE collage image)
    5. Credit ("via: source", italic + hyperlink)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import escape
from typing import Callable

from .config import Settings
from .site import Article

MAX_CHARS = 30000      # Telegram: 32768 incl. text; keep head-room
MAX_PARAGRAPHS = 380   # Telegram: 500 blocks incl. nested ones

OVERFLOW_KEY = "__overflow__"


@dataclass
class MediaPlan:
    cover: str | None
    originals: list[str]           # shown as individual photos in the collage
    overflow: list[str] = field(default_factory=list)   # merged into ONE extra collage image (last slot)

    @property
    def slots_used(self) -> int:
        return (1 if self.cover else 0) + len(self.originals) + (1 if self.overflow else 0)


def plan_media(art: Article, max_media: int = 50) -> MediaPlan:
    """Never more than `max_media` images in a message.

    The cover takes one slot (the same image is not repeated in the gallery). If the gallery does not fit,
    the first (slots-1) photos stay original and the last slot is a single collage of everything after.
    """
    cover = art.cover
    gallery = [u for u in art.images if u != cover]
    slots = max_media - (1 if cover else 0)
    if len(gallery) <= slots:
        return MediaPlan(cover, gallery)
    keep = max(slots - 1, 0)
    return MediaPlan(cover, gallery[:keep], gallery[keep:])


SHOW_MORE_STYLES = {
    "classic": "Bold CAPITALS with emoji on both sides (recommended)",
    "highlight": "Same, with a highlighted background",
    "pill": "Blue pill button (Telegram shows its text faded)",
    "plain": "Plain toggle text",
    "telegram": "No toggle (not recommended: the post is shown fully open; Telegram only sometimes folds it)",
}


def effective_style(style: str, art: Article | None = None, plan: MediaPlan | None = None) -> str:
    """'auto' was an experiment (guessing when Telegram folds a post behind its own button) that proved unreliable:
    it left real posts completely open. Anything saved as 'auto' now simply means 'classic' (our toggle)."""
    return "classic" if style == "auto" else style


def summary_html(label: str, style: str, emoji: str = "👇") -> str:
    """The clickable toggle of the collapsed post. Telegram rich text has no font sizes, so 'bigger / more eye-catching'
    is done with bold CAPITALS, emoji on both sides (they render large) and optionally a highlighted background."""
    t = escape(label, quote=False)
    e = escape(emoji.strip(), quote=False)
    loud = f"{e} {escape(label.upper(), quote=False)} {e}".strip() if e else escape(label.upper(), quote=False)
    if style == "highlight":
        return f"<summary><b><mark>{loud}</mark></b></summary>"
    if style == "pill":
        return f'<summary><tg-button type="disabled" style="primary">{t}</tg-button></summary>'
    if style == "plain":
        return f"<summary>{t}</summary>"
    return f"<summary><b>{loud}</b></summary>"      # "classic" and any retired style name


PARAGRAPH_SPACING = {
    "blank": "Blank line between paragraphs (recommended)",
    "spacer": "Blank line using an empty paragraph (alternative)",
    "tight": "No extra space (Telegram's default)",
}


def body_blocks(paragraphs: list[str], mode: str) -> list[str]:
    """HTML blocks for the body text. Telegram puts almost no gap between separate <p> blocks, so paragraphs would
    touch. 'blank' puts them in ONE block separated by <br><br> (one block, however many paragraphs: no block-limit
    cost); 'spacer' inserts an empty paragraph between them; 'tight' is the plain one-block-per-paragraph layout."""
    if not paragraphs:
        return []
    if mode == "tight":
        return [f"<p>{p}</p>" for p in paragraphs]
    if mode == "spacer":
        out: list[str] = []
        for i, p in enumerate(paragraphs):
            if i:
                out.append("<p>&nbsp;</p>")
            out.append(f"<p>{p}</p>")
        return out
    return ["<p>" + "<br><br>".join(paragraphs) + "</p>"]


def tags_line(tags: list[str], hashtag_style: str) -> str:
    if hashtag_style in ("hashtag", "true", "1"):
        return "  ".join("#" + re.sub(r"\W+", "_", t, flags=re.U).strip("_") for t in tags)
    return "  ·  ".join(escape(t, quote=False) for t in tags)


def build_html(art: Article, settings: Settings, plan: MediaPlan, src: Callable[[str], str]) -> str:
    """`src` maps a source image URL (or OVERFLOW_KEY) to the src to embed (http URL or tg://photo?id=...)."""
    title = escape(art.title or f"Post {art.post_id}", quote=False)
    head = [f"<h6>{title}</h6>"]
    if plan.cover:
        head.append(f'<img src="{escape(src(plan.cover), quote=True)}"/>')

    inner: list[str] = []
    if art.scheduled:
        inner.append(f"<p><i>{escape(art.scheduled, quote=False)}</i></p>")
    if art.tags:
        inner.append(f"<p><i>{tags_line(art.tags, settings.hashtag_style)}</i></p>")

    paras = list(art.paragraphs)
    truncated = False
    budget = MAX_CHARS - 4000 - 120 * (len(plan.originals) + 2)   # reserve for urls/markup around the body
    used = 0
    kept: list[str] = []
    for p in paras:
        cap = MAX_PARAGRAPHS // 2 if settings.paragraph_spacing == "spacer" else MAX_PARAGRAPHS   # spacer doubles the blocks
        if used + len(p) > budget or len(kept) >= cap:
            truncated = True
            break
        kept.append(p)
        used += len(p)
    inner.extend(body_blocks(kept, settings.paragraph_spacing))
    if truncated:
        inner.append(f'<p><a href="{escape(art.url, quote=True)}">…</a></p>')
    for v in art.videos[:5]:
        inner.append(f'<p><a href="{escape(v, quote=True)}">▶ {escape(v, quote=False)}</a></p>')

    imgs = [f'<img src="{escape(src(u), quote=True)}"/>' for u in plan.originals]
    if plan.overflow:
        imgs.append(f'<img src="{escape(src(OVERFLOW_KEY), quote=True)}"/>')
    if len(imgs) == 1:
        inner.append(imgs[0])
    elif imgs:
        inner.append("<tg-collage>" + "".join(imgs) + "</tg-collage>")

    if art.credits:
        parts = []
        for text, url in art.credits:
            t = escape(text, quote=False)
            parts.append(f'<a href="{escape(url, quote=True)}">{t}</a>' if url else t)
        label = escape(art.credit_label, quote=False)
        inner.append(f"<p><i>{label}: {', '.join(parts)}</i></p>")

    if not inner:   # nothing to expand
        return "".join(head)
    style = effective_style(settings.show_more_style, art, plan)
    if style == "telegram":    # full content inline; Telegram itself folds the post behind its own green button
        return "".join(head) + "".join(inner)
    summary = summary_html(settings.show_more_label, style, settings.show_more_emoji)
    return "".join(head) + f"<details>{summary}{''.join(inner)}</details>"


def count_media(html: str) -> int:
    return len(re.findall(r"<img\b", html))
