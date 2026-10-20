import io

from PIL import Image

from conftest import png
from tpclone import media


def test_prepare_photo_flattens_and_limits():
    b = io.BytesIO(); Image.new("RGBA", (6000, 100), (255, 0, 0, 0)).save(b, "PNG")
    out = Image.open(io.BytesIO(media.prepare_photo(b.getvalue())))
    assert out.format == "JPEG" and out.width + out.height <= 10000 and max(out.size) / min(out.size) <= 20


def test_collage_contains_everything_and_is_valid():
    imgs = [png(400 + 37 * i, 300 + 11 * i, (i * 5 % 255, 80, 120)) for i in range(70)]
    out = media.make_collage(imgs)
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG" and len(out) < 10 * 1024 * 1024 and im.width + im.height <= 10000
    # sanity: not blank, and taller than a single row (70 tiles needed multiple rows)
    assert im.height > 400 and im.convert("L").resize((16, 16)).getextrema()[0] != im.convert("L").resize((16, 16)).getextrema()[1]


def test_collage_skips_undecodable():
    out = media.make_collage([png(), b"not an image", png()])
    assert Image.open(io.BytesIO(out)).format == "JPEG"


def _gif(frames=2):
    import io
    from PIL import Image
    ims = [Image.new("RGB", (40, 30), c) for c in [(255, 0, 0), (0, 0, 255), (0, 255, 0)][:frames]]
    b = io.BytesIO()
    ims[0].save(b, "GIF", save_all=frames > 1, append_images=ims[1:], duration=100, loop=0)
    return b.getvalue()


def test_kind_of_media():
    from tpclone.media import kind_from_url, sniff_kind
    assert kind_from_url("https://img.toy-people.com/member/179133504358_1200.gif") == "animation"
    assert kind_from_url("https://x/clip.MP4?x=1") == "video" and kind_from_url("https://x/a.jpg") == "photo"
    assert sniff_kind(_gif(2)) == "animation" and sniff_kind(_gif(1)) == "photo"       # a still GIF is a photo
    assert sniff_kind(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 20) == "video"
    import io
    from PIL import Image
    b = io.BytesIO(); Image.new("RGB", (10, 10)).save(b, "WEBP")
    assert sniff_kind(b.getvalue()) == "photo"                                          # WebP behind a '.jpg' link
    out = media.prepare_photo(b.getvalue())                                                   # ... becomes a real JPEG
    assert out[:2] == b"\xff\xd8"
    assert media.prepare_photo(_gif(2))[:2] == b"\xff\xd8"                                     # first frame as a still
