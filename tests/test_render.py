import re

from conftest import make_article
from tpclone import render
from tpclone.config import Settings

S = Settings(show_more_style="classic")
ident = lambda k: k


def test_structure_and_order():
    a = make_article(n_images=3)
    plan = render.plan_media(a, 50)
    h = render.build_html(a, S, plan, ident)
    # preview part: heading 6 (plain, no link), cover, then the Show More toggle
    assert h.startswith('<h6>A Title</h6><img src="https://x/cover.jpg"/>'
                        '<details><summary><b>👇 SHOW MORE 👇</b></summary>')
    # full post order: scheduled, hashtags, body, collage, credit
    order = [h.index(x) for x in ("<p><i>Scheduled Release", "<p><i>Japanese Series", "<p>Hello", "<tg-collage>", "<p><i>via:")]
    assert order == sorted(order)
    assert '<i>via: <a href="https://b.example/">bandaispirits</a></i>' in h
    assert "Japanese Series  ·  Kotobukiya" in h
    assert h.endswith("</details>")


def test_no_scheduled_line_when_absent():
    a = make_article()
    a.scheduled = None
    assert "Scheduled" not in render.build_html(a, S, render.plan_media(a), ident)


def test_hashtag_style():
    a = make_article()
    h = render.build_html(a, Settings(hashtag_style="hashtag"), render.plan_media(a), ident)
    assert "#Japanese_Series  #Kotobukiya" in h


def test_html_escaping():
    a = make_article(title="A <b> & \"q\"")
    h = render.build_html(a, S, render.plan_media(a), ident)
    assert "A &lt;b&gt; &amp; \"q\"" in h


def test_media_never_exceeds_50():
    for n in (0, 1, 48, 49, 50, 51, 120, 500):
        for cover in (True, False):
            a = make_article(n_images=n, cover=cover)
            plan = render.plan_media(a, 50)
            h = render.build_html(a, S, plan, ident)
            assert render.count_media(h) <= 50, (n, cover)
            assert plan.slots_used <= 50


def test_overflow_rule():
    # no cover: photos 1-49 original, slot 50 = one collage of photo 50 and everything after
    a = make_article(n_images=60, cover=False)
    plan = render.plan_media(a, 50)
    assert plan.originals == a.images[:49] and plan.overflow == a.images[49:]
    h = render.build_html(a, S, plan, ident)
    assert render.count_media(h) == 50 and "__overflow__" in h
    # exactly 50 photos: nothing merged
    plan = render.plan_media(make_article(n_images=50, cover=False), 50)
    assert plan.overflow == [] and len(plan.originals) == 50
    # with a cover the cover takes one slot, so the cap still holds
    plan = render.plan_media(make_article(n_images=60, cover=True), 50)
    assert plan.slots_used == 50 and len(plan.originals) == 48


def test_cover_not_repeated_in_gallery():
    a = make_article(n_images=2)
    a.images.insert(0, a.cover)
    plan = render.plan_media(a)
    assert a.cover not in plan.originals


def test_long_body_truncated_within_limits():
    a = make_article()
    a.paragraphs = ["x" * 900] * 200
    h = render.build_html(a, S, render.plan_media(a), ident)
    assert len(re.sub(r"<[^>]+>", "", h)) < 32768
    assert "…" in h


def test_empty_details_omitted():
    a = make_article(n_images=0)
    a.scheduled, a.tags, a.paragraphs, a.credits = None, [], [], []
    assert "<details>" not in render.build_html(a, S, render.plan_media(a), ident)


def test_show_more_styles():
    a = make_article()

    def html(**kw):
        kw.setdefault("show_more_style", "classic")
        return render.build_html(a, Settings(**kw), render.plan_media(a), ident)

    assert set(render.SHOW_MORE_STYLES) == {"classic", "highlight", "pill", "plain", "telegram"}
    for style in set(render.SHOW_MORE_STYLES) - {"telegram"}:
        h = html(show_more_style=style)
        assert "<details><summary>" in h and h.count("<summary>") == 1 and "</summary>" in h
    t = html(show_more_style="telegram")          # no toggle of ours: content sits inline after the cover
    assert "<details" not in t and "<summary" not in t and "Scheduled Release" in t and "<tg-collage>" in t and "via:" in t
    assert t.startswith("<h6>A Title</h6><img src=\"https://x/cover.jpg\"/>")
    # default: bold CAPITALS with the emoji on both sides
    assert "<summary><b>👇 SHOW MORE 👇</b></summary>" in html()
    assert "<summary><b><mark>👇 SHOW MORE 👇</mark></b></summary>" in html(show_more_style="highlight")
    assert "<summary><b>🔥 SHOW MORE 🔥</b></summary>" in html(show_more_emoji="🔥")
    assert "<summary><b>SHOW MORE</b></summary>" in html(show_more_emoji="")
    assert '<summary><tg-button type="disabled" style="primary">Show More</tg-button></summary>' in html(show_more_style="pill")
    assert "<summary>Show More</summary>" in html(show_more_style="plain")
    assert "<summary><b>👇 SHOW MORE 👇</b></summary>" in html(show_more_style="pill_centered")      # retired name -> default
    assert "<summary><b>👇 A &amp; B 👇</b></summary>" in html(show_more_label="a & b")


def test_legacy_auto_style_now_means_our_toggle():
    """'Automatic' guessed wrongly (post 368 was left fully open). A saved 'auto' must behave like 'classic'."""
    big = make_article(n_images=3)                      # has a cover photo: the case that used to drop the toggle
    h = render.build_html(big, Settings(show_more_style="auto"), render.plan_media(big), ident)
    assert "<details><summary><b>👇 SHOW MORE 👇</b></summary>" in h
    assert render.effective_style("auto") == "classic" and render.effective_style("pill") == "pill"
    assert Settings().show_more_style == "classic" and "auto" not in render.SHOW_MORE_STYLES


def test_paragraph_spacing_modes():
    a = make_article()
    a.paragraphs = ["First paragraph.", "Second <b>paragraph</b>.", "Third."]

    def body(mode):
        h = render.build_html(a, Settings(show_more_style="classic", paragraph_spacing=mode), render.plan_media(a), ident)
        return h

    blank = body("blank")      # default: one block, blank line (two line breaks) between paragraphs
    assert "<p>First paragraph.<br><br>Second <b>paragraph</b>.<br><br>Third.</p>" in blank
    assert Settings().paragraph_spacing == "blank"
    spacer = body("spacer")
    assert "<p>First paragraph.</p><p>&nbsp;</p><p>Second <b>paragraph</b>.</p><p>&nbsp;</p><p>Third.</p>" in spacer
    tight = body("tight")
    assert "<p>First paragraph.</p><p>Second <b>paragraph</b>.</p><p>Third.</p>" in tight
    assert render.body_blocks([], "blank") == [] and render.body_blocks(["only"], "blank") == ["<p>only</p>"]


def test_block_limit_respected_in_every_spacing_mode():
    import re
    a = make_article(n_images=0, cover=False)
    a.paragraphs = [f"Paragraph number {i}." for i in range(900)]
    for mode in ("blank", "spacer", "tight"):
        h = render.build_html(a, Settings(show_more_style="classic", paragraph_spacing=mode), render.plan_media(a), ident)
        blocks = len(re.findall(r"<p>|<h6>|<details>|<summary>|<tg-collage>|<img", h))
        assert blocks <= 500, (mode, blocks)
        assert len(re.sub(r"<[^>]+>", "", h)) < 32768
