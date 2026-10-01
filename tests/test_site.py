from conftest import FIX
from tpclone.config import Settings
from tpclone.site import parse_article, parse_date, parse_sitemap

S = Settings()


def test_sitemap_parse_and_sort():
    xml = """<urlset xmlns:xhtml="x"><url><loc>https://www.toy-people.com/en/?p=20</loc>
    <xhtml:link rel="alternate" hreflang="ja" href="https://www.toy-people.com/jp/?p=20"/><lastmod>2026-09-01</lastmod></url>
    <url><loc>https://www.toy-people.com/en/?p=3&amp;x=1</loc></url>
    <url><loc>https://www.toy-people.com/en/about</loc></url></urlset>"""
    r = parse_sitemap(xml)
    assert [x[0] for x in r] == [3, 20]
    assert r[1][2] == "2026-09-01" and r[0][2] is None


def test_parse_date_formats():
    assert parse_date("2026-09-24T18:30:00+00:00", "Asia/Taipei") == "2026-09-25"   # converted to site tz
    assert parse_date("2026/09/25") == "2026-09-25"
    assert parse_date("Sep 25, 2026") == "2026-09-25"
    assert parse_date("25 September 2026") == "2026-09-25"
    assert parse_date("2026年9月25日") == "2026-09-25"
    assert parse_date("nonsense") is None and parse_date(None) is None


def test_parse_article_fixture():
    html = (FIX / "article.html").read_text(encoding="utf8")
    a = parse_article(html, "https://www.toy-people.com/en/?p=114949", 114949, S)
    assert a.title.startswith("Kotobukiya’s Megalo Maria Airly Model Kit Packs")
    assert a.post_date == "2026-09-25"
    assert a.tags == ["Japanese Series", "Kotobukiya", "Plastic Models", "Action Figure", "Megalo Maria"]
    assert a.cover == "https://cdn.toy-people.com/img/114949/cover.jpg"
    assert a.scheduled and a.scheduled.lower().startswith("scheduled release") and "December 2026" in a.scheduled
    assert a.credit_label == "via"
    assert a.credits == [("bandaispirits", "https://www.bandaispirits.com/news/1")]
    # full-size link target wins over thumbnail, lazy-src used, dedupe, junk icon dropped
    assert a.images == ["https://cdn.toy-people.com/img/114949/full1.jpg", "https://cdn.toy-people.com/img/114949/2.jpg",
                        "https://www.toy-people.com/img/114949/3.jpg"]
    joined = " ".join(a.paragraphs)
    assert "Megalo Maria</b> Airly model kit &amp; its articulation" in joined
    assert '<a href="https://www.toy-people.com/en/?p=1">more</a>' in joined
    assert "Pre-orders open <i>soon</i>.<br>Stay tuned." in joined
    # structured bits must not be duplicated in the body
    assert "Scheduled Release" not in joined and "bandaispirits" not in joined
    assert "Share this" not in joined and "Japanese Series" not in joined
