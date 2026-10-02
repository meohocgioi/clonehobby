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


MENU = ('<div class="topmenu"><a href="/en/trending">Trending This Week</a><a href="/en/schedule">Release Schedule</a>'
        '<a href="/en/unboxing">Unboxing Report</a><a href="/en/column">Column</a><a href="/en/nikkan">Nikkan Denden</a>'
        '<a href="/en/screen">SCREEN FANDOM</a></div>')


def page(body_extra="", menu=MENU):
    return (f'<html><head><meta property="og:image" content="https://c/x.jpg"></head><body>{menu}'
            f'<header><div class="tags"><a href="/en/tag/a">ANIPLEX</a></div><h1>Title</h1></header>'
            f'<article><div class="entry-content"><p>Hello</p>{body_extra}</div></article></body></html>')


def sched(html):
    return parse_article(html, "https://www.toy-people.com/en/?p=1", 1, S).scheduled


def test_site_menu_is_never_taken_as_release_schedule():
    assert sched(page()) is None                                       # the bug: menu tabs were posted as the line
    assert sched(page(menu='<nav><ul><li>Release Schedule</li><li>Column</li></ul></nav>')) is None


def test_release_schedule_needs_a_date_beside_it():
    assert sched(page("<p>Release Schedule: 2026/12/15</p>")) == "Release Schedule: 2026/12/15"
    assert sched(page("<p><b>Scheduled Release</b>: December 2026</p>")) == "Scheduled Release: December 2026"
    assert sched(page("<p><strong>Release Schedule</strong></p><p>2027年3月</p>")) == "Release Schedule: 2027年3月"
    assert sched(page("<p>Release Date: TBA</p>")) == "Release Date: TBA"
    assert sched(page("<p>Release Schedule:</p>")) is None             # label without a date -> skip the line
    assert sched(page("<p>Release Schedule is a section we update weekly.</p>")) is None
    assert sched(page("<p>See our <a href='/s'>Release Schedule</a> page 2026</p>")) is None


def test_release_schedule_in_title_banner_but_not_menu():
    html = ('<html><body>' + MENU + '<header><div class="tags"><a href="/en/tag/a">A</a></div>'
            '<div class="rel">Release Schedule: 2026/11</div><h1>Title</h1></header>'
            '<article><div class="entry-content"><p>Hello</p></div></article></body></html>')
    assert sched(html) == "Release Schedule: 2026/11"


LISTING = """<html><body><header><div class="menu"><a href="/en/schedule">Release Schedule</a></div></header>
<h2>Latest News</h2>
<div class="list">
 <div class="card"><a href="https://www.toy-people.com/en/?p=115078"><img src="/x.jpg"></a>
   <div class="body"><a href="/en/?p=115078"><h3>BANDAI HOBBY MGEX 1/100 Mighty Strike Freedom Gundam Makes Its In-Person Debut</h3></a>
   <span class="date">2026-10-02</span><span class="sched">Scheduled Release : Mar 2027</span><span class="by">BIN 180</span></div></div>
 <div class="card"><a href="/en/?p=115080"><img src="/y.jpg"></a>
   <div class="body"><a href="/en/?p=115080&lang=en">30MP Model Kit Prototypes Debut Rei Ayanami</a><span>2026-10-02</span></div></div>
 <div class="card"><a href="/en/?p=115070"><img src="/z.jpg"></a><a href="/en/?p=115070">SMP COM-BATTLER V6 50th Legacy</a><span>2026-10-01</span></div>
</div>
<div class="trending"><a href="/en/?p=114949">Old trending post</a></div>
<a href="/en/tag/gundam">not a post</a><a href="/en/?page_id=7">not a post either</a>
</body></html>"""


def test_parse_listing_cards():
    from tpclone.site import parse_listing
    items = parse_listing(LISTING)
    assert [i["id"] for i in items] == [115078, 115080, 115070, 114949]      # page order, deduped, non-post links ignored
    assert items[0]["title"].startswith("BANDAI HOBBY MGEX 1/100") and items[0]["date"] == "2026-10-02"
    assert items[1]["title"] == "30MP Model Kit Prototypes Debut Rei Ayanami" and items[1]["date"] == "2026-10-02"
    assert items[2]["date"] == "2026-10-01"
    assert items[3]["date"] is None                                           # no date printed in that card


def test_parse_listing_empty_page():
    from tpclone.site import parse_listing
    assert parse_listing("<html><body>Just a moment...</body></html>") == []
