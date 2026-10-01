"""Image preparation for Telegram uploads + the overflow collage."""
from __future__ import annotations

import io
import math

from PIL import Image, ImageOps

MAX_UPLOAD_BYTES = 9 * 1024 * 1024        # Telegram: 10 MB per photo
MAX_SIDE_SUM = 9500                       # Telegram: width + height <= 10000
MAX_RATIO = 19.0                          # Telegram: ratio <= 20


def prepare_photo(data: bytes, max_side: int = 2560) -> bytes:
    """Normalise to a Telegram-acceptable JPEG (flatten alpha, cap size, fix extreme ratios)."""
    im = Image.open(io.BytesIO(data))
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > max_side:
        k = max_side / max(w, h)
        im = im.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
        w, h = im.size
    if w / h > MAX_RATIO or h / w > MAX_RATIO:  # pad extreme panoramas / strips
        side = int(max(w, h) / MAX_RATIO) + 1
        canvas = Image.new("RGB", (max(w, side), max(h, side)), (255, 255, 255))
        canvas.paste(im, ((canvas.width - w) // 2, (canvas.height - h) // 2))
        im, (w, h) = canvas, canvas.size
    if w + h > MAX_SIDE_SUM:
        k = MAX_SIDE_SUM / (w + h)
        im = im.resize((int(w * k), int(h * k)), Image.LANCZOS)
    for q in (90, 82, 74, 66, 55):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= MAX_UPLOAD_BYTES:
            return buf.getvalue()
    k = 0.7  # still too big: shrink
    im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70, optimize=True)
    return buf.getvalue()


def make_collage(images: list[bytes], canvas_w: int = 2400, gap: int = 6, row_h: int | None = None) -> bytes:
    """Justified-rows collage of *all* given images in one JPEG (used for photo slot 50 and beyond).

    Rows are filled left to right keeping each image's aspect ratio; the row height is chosen so the tile
    count stays readable, and the canvas never exceeds Telegram's size limits.
    """
    ims: list[Image.Image] = []
    for raw in images:
        try:
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
            ims.append(im)
        except Exception:
            continue
    if not ims:
        raise ValueError("no decodable images for collage")
    n = len(ims)
    if row_h is None:  # roughly: bigger tiles for few images, small for many
        row_h = 700 if n <= 4 else 480 if n <= 12 else 340 if n <= 40 else 240
    ratios = [im.width / im.height for im in ims]

    rows: list[list[int]] = []
    cur: list[int] = []
    cur_w = 0.0
    for i, r in enumerate(ratios):
        cur.append(i)
        cur_w += r * row_h
        if cur_w + gap * (len(cur) - 1) >= canvas_w:
            rows.append(cur)
            cur, cur_w = [], 0.0
    if cur:
        rows.append(cur)

    # lay out: scale every full row to exactly canvas_w, keep the last row at natural height
    layout: list[tuple[list[int], float]] = []
    for idx, row in enumerate(rows):
        total_ratio = sum(ratios[i] for i in row)
        avail = canvas_w - gap * (len(row) - 1)
        h = avail / total_ratio
        if idx == len(rows) - 1 and h > row_h * 1.25:
            h = row_h
        layout.append((row, h))
    total_h = int(sum(h for _, h in layout) + gap * (len(layout) - 1))
    # keep the whole canvas within Telegram limits
    scale = 1.0
    if canvas_w + total_h > MAX_SIDE_SUM:
        scale = MAX_SIDE_SUM / (canvas_w + total_h)
    W, H = int(canvas_w * scale), max(1, int(total_h * scale))
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    y = 0.0
    for row, h in layout:
        x = 0.0
        for i in row:
            w = ratios[i] * h
            tile = ims[i].resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
            canvas.paste(tile, (int(x * scale), int(y * scale)))
            x += w + gap
        y += h + gap
    return prepare_photo_from_image(canvas)


def prepare_photo_from_image(im: Image.Image) -> bytes:
    for q in (88, 78, 68, 58):
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=q, optimize=True)
        if buf.tell() <= MAX_UPLOAD_BYTES:
            return buf.getvalue()
    k = math.sqrt(MAX_UPLOAD_BYTES / buf.tell()) * 0.9
    im = im.resize((int(im.width * k), int(im.height * k)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70, optimize=True)
    return buf.getvalue()
