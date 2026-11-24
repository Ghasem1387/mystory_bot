"""ساخت عکس کیک تولد با شمع عددی روشن/خاموش — از روی assets.zip"""
import io
import json
import random
import zipfile
import statistics
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter

ZIP_PATH = "assets.zip"
CAKE_SIZE = 1000
BASE = (498, 372)        # مرکز و پایین شمع روی کیک
CANDLE_H = 175           # ارتفاع شمع‌ها
MAX_W = {1: 190, 2: 330, 3: 400}
FLAME_H = 105
SMOKE_H = 125

_Z = None


def _zip():
    global _Z
    if _Z is None:
        _Z = zipfile.ZipFile(ZIP_PATH)
    return _Z


@lru_cache(maxsize=None)
def _img(name):
    with _zip().open(name) as f:
        return Image.open(io.BytesIO(f.read())).convert("RGBA")


@lru_cache(maxsize=None)
def _meta():
    with _zip().open("meta.json") as f:
        return json.load(f)


def _top_at(img, cx, win=10):
    a = img.getchannel("A").crop((max(0, int(cx) - win), 0, min(img.width, int(cx) + win), img.height))
    px = a.load()
    for y in range(a.height):
        for x in range(a.width):
            if px[x, y] > 128:
                return y
    return 0


def _strip(age):
    """شمع عددی (تصویر) و مرکز هر رقم"""
    meta = _meta()
    if str(age) in meta["nums"]:
        im = _img(f"nums/{age}.png")
        return im, list(meta["nums"][str(age)]["cx"])
    rnd = random.Random(age * 7919)
    pool = {}
    for name in meta["digits"]:
        pool.setdefault(name.split("_")[0], []).append(name)
    digits = str(age)
    parts = []
    for i, ch in enumerate(digits):
        names = pool[ch]
        if len(digits) > 1:
            # رقم اول: لبه چپ طبیعی (L)، رقم آخر: لبه راست طبیعی (R)
            tag = "L" if i == 0 else "R"
            pref = [n for n in names if n.endswith(tag)]
            names = pref or names
        parts.append(_img(f"digits/{rnd.choice(names)}.png"))
    ref = statistics.median(p.height for p in parts)
    parts = [p.resize((max(1, round(p.width * ref / p.height)), round(ref)), Image.LANCZOS) for p in parts]
    gap = -4
    W = sum(p.width for p in parts) + gap * (len(parts) - 1)
    canvas = Image.new("RGBA", (W, parts[0].height), (0, 0, 0, 0))
    x, centers = 0, []
    for p in parts:
        canvas.alpha_composite(p, (x, 0))
        centers.append(x + p.width / 2)
        x += p.width + gap
    return canvas, centers


def _glow(size, pts, radius):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for cx, cy in pts:
        d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(255, 165, 50, 120))
    return layer.filter(ImageFilter.GaussianBlur(radius * 0.45))


def render(age, lit):
    age = int(age)
    cake = _img("cake.jpg").copy()
    strip, centers = _strip(age)
    n = len(str(age))
    s = min(CANDLE_H / strip.height, MAX_W.get(n, 400) / strip.width)
    sw, sh = round(strip.width * s), round(strip.height * s)
    strip_s = strip.resize((sw, sh), Image.LANCZOS)
    centers_s = [c * s for c in centers]
    x0 = round(BASE[0] - sw / 2)
    y0 = round(BASE[1] - sh)

    # سایه زیر شمع
    sh_layer = Image.new("RGBA", cake.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh_layer).ellipse((x0 - 6, BASE[1] - 22, x0 + sw + 6, BASE[1] + 14), fill=(20, 8, 0, 150))
    cake.alpha_composite(sh_layer.filter(ImageFilter.GaussianBlur(9)))
    cake.alpha_composite(strip_s, (x0, y0))

    tops = [(x0 + c, y0 + _top_at(strip_s, c)) for c in centers_s]

    if lit:
        cake.alpha_composite(_glow(cake.size, [(cx, ty - FLAME_H * 0.45) for cx, ty in tops], 95))
        flame = _img("flame.png")
        fw = round(flame.width * FLAME_H / flame.height)
        flame = flame.resize((fw, FLAME_H), Image.LANCZOS)
        wick_x = _meta()["flame_wick_x"] * fw
        for cx, ty in tops:
            cake.alpha_composite(flame, (round(cx - wick_x), round(ty - FLAME_H + 3)))
    else:
        smoke = _img("smoke.png")
        sw2 = round(smoke.width * SMOKE_H / smoke.height)
        smoke = smoke.resize((sw2, SMOKE_H), Image.LANCZOS)
        a = smoke.getchannel("A").point(lambda v: int(v * 0.9))
        smoke.putalpha(a)
        d = ImageDraw.Draw(cake)
        for cx, ty in tops:
            d.line([(cx, ty + 2), (cx, ty - 9)], fill=(45, 28, 20, 255), width=3)
            cake.alpha_composite(smoke, (round(cx - sw2 / 2), round(ty - SMOKE_H - 4)))
    return cake.convert("RGB")


@lru_cache(maxsize=48)
def jpeg_bytes(age, lit):
    buf = io.BytesIO()
    render(age, lit).save(buf, "JPEG", quality=88, optimize=True)
    return buf.getvalue()


if __name__ == "__main__":
    import sys
    for a in map(int, sys.argv[1:] or [7]):
        for lit in (True, False):
            open(f"test_{a}_{'lit' if lit else 'out'}.jpg", "wb").write(jpeg_bytes(a, lit))
