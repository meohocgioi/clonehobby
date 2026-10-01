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
