"""Gráficos animados tipo "motion graphics" para vídeos sin material de stock.

Cada escena puede llevar una tarjeta:
  {"layout": "title|bullets|number|quote|steps", "heading": str, "items": [str], "icon": "emoji"}
Para bullets/steps se genera una imagen por cada elemento revelado (aparecen uno a uno).
"""

import functools
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

EMOJI_FONT = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"
BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
BG_TOP, BG_BOTTOM = (8, 12, 28), (18, 26, 54)
TEXT, MUTED = (240, 244, 255), (150, 165, 200)


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


@functools.lru_cache(maxsize=64)
def font(path: str, size: int):
    return ImageFont.truetype(path, size)


@functools.lru_cache(maxsize=16)
def background(size: tuple[int, int], accent: tuple[int, int, int], seed: int = 0) -> Image.Image:
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)))
    step = max(w, h) // 24
    grid = tuple(min(255, c + 14) for c in BG_TOP)
    for x in range(0, w, step):
        d.line([(x, 0), (x, h)], fill=grid, width=1)
    for y in range(0, h, step):
        d.line([(0, y), (w, y)], fill=grid, width=1)
    rnd = random.Random(seed)
    glow = Image.new("RGB", size, (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(2):
        r = rnd.randint(h // 3, h // 2)
        cx, cy = rnd.randint(0, w), rnd.randint(0, h)
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(int(c * 0.35) for c in accent))
    glow = glow.filter(ImageFilter.GaussianBlur(h // 6))
    return Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.6)


def emoji(char: str, size: int) -> Image.Image | None:
    if not char:
        return None
    try:
        f = font(EMOJI_FONT, 109)  # Noto Color Emoji solo existe a 109 px
        tmp = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        ImageDraw.Draw(tmp).text((80, 80), char, font=f, embedded_color=True, anchor="mm")
        box = tmp.getbbox()
        if not box:
            return None
        tmp = tmp.crop(box)
        scale = size / max(tmp.size)
        return tmp.resize((max(1, int(tmp.width * scale)), max(1, int(tmp.height * scale))), Image.LANCZOS)
    except Exception:
        return None


def _wrap(draw, text, f, max_w):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        test = f"{cur} {wd}".strip()
        if draw.textlength(test, font=f) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    return lines


def _fit(draw, text, path, max_w, max_h, start, min_size=28, line_h=1.18):
    size = start
    while size > min_size:
        f = font(path, size)
        lines = _wrap(draw, text, f, max_w)
        widest = max((draw.textlength(l, font=f) for l in lines), default=0)
        if len(lines) * size * line_h <= max_h and widest <= max_w:
            return f, lines
        size -= 4
    f = font(path, min_size)
    return f, _wrap(draw, text, f, max_w)


def _paste_icon(img, char, size, center):
    e = emoji(char, size)
    if e:
        pos = (int(center[0] - e.width / 2), int(center[1] - e.height / 2))
        if img.mode == "RGBA":
            img.alpha_composite(e, (max(0, pos[0]), max(0, pos[1])))
        else:
            img.paste(e, pos, e)


def _pill(d, xy, accent):
    x, y = xy
    d.rounded_rectangle([x, y, x + 90, y + 10], radius=5, fill=accent)


def render_card(card: dict, size: tuple[int, int], accent_hex: str, reveal: int | None = None,
                seed: int = 0, transparent: bool = False) -> Image.Image:
    """transparent=True: solo el contenido (RGBA), para superponerlo a un fondo animado."""
    accent = hex_rgb(accent_hex)
    w, h = size
    vertical = h > w
    s = min(w, h) / 1080  # escala
    img = Image.new("RGBA", size, (0, 0, 0, 0)) if transparent else background(size, accent, seed).copy()
    d = ImageDraw.Draw(img)
    layout = card.get("layout", "title")
    heading = card.get("heading", "").strip()
    items = [i for i in card.get("items", []) if i.strip()]
    icon = card.get("icon", "")
    margin = int(110 * s)

    if layout == "number":
        big = items[0] if items else heading
        caption = heading if items else ""
        f, lines = None, [big]
        for size in range(int(260 * s), int(120 * s), -6):  # mejor en una sola línea
            if d.textlength(big, font=font(BOLD, size)) <= w - 2 * margin:
                f = font(BOLD, size)
                break
        if f is None:
            f, lines = _fit(d, big, BOLD, w - 2 * margin, h * 0.38, int(200 * s))
        y = h * (0.40 if vertical else 0.42) - len(lines) * f.size * 0.6
        for ln in lines:
            d.text((w / 2, y), ln, font=f, fill=accent, anchor="mt", stroke_width=int(3 * s), stroke_fill=(0, 0, 0))
            y += f.size * 1.1
        if caption:
            fc, cl = _fit(d, caption, BOLD, w - 2 * margin, h * 0.22, int(64 * s))
            y += 30 * s
            for ln in cl:
                d.text((w / 2, y), ln, font=fc, fill=TEXT, anchor="mt")
                y += fc.size * 1.2
        if icon:
            _paste_icon(img, icon, int(130 * s), (w / 2, h * 0.14 if not vertical else h * 0.2))

    elif layout == "quote":
        _paste_icon(img, icon or "💬", int(150 * s), (w / 2, h * (0.2 if not vertical else 0.25)))
        f, lines = _fit(d, f"«{heading}»", BOLD, w - 2.4 * margin, h * 0.45, int(84 * s))
        y = h * 0.55 - len(lines) * f.size * 0.6
        for ln in lines:
            d.text((w / 2, y), ln, font=f, fill=TEXT, anchor="mt")
            y += f.size * 1.2
        if items:
            d.text((w / 2, y + 30 * s), items[0], font=font(REG, int(46 * s)), fill=accent, anchor="mt")

    elif layout in ("bullets", "steps"):
        shown = items[: reveal if reveal is not None else len(items)]
        fh, hl = _fit(d, heading, BOLD, w - 2 * margin - (0 if vertical else 260 * s), h * 0.2, int(80 * s))
        y = margin * (1.4 if vertical else 0.9)
        for ln in hl:
            d.text((margin, y), ln, font=fh, fill=TEXT)
            y += fh.size * 1.15
        _pill(d, (margin, y + 14 * s), accent)
        y += 70 * s
        if icon and not vertical:
            _paste_icon(img, icon, int(200 * s), (w - margin - 100 * s, margin + 110 * s))
        if layout == "steps" and not vertical and len(items) <= 4:
            n = len(items)
            gap = 40 * s
            bw = (w - 2 * margin - gap * (n - 1)) / n
            top, bh = h * 0.42, h * 0.42
            for i, it in enumerate(shown):
                x0 = margin + i * (bw + gap)
                d.rounded_rectangle([x0, top, x0 + bw, top + bh], radius=int(28 * s),
                                    fill=(24, 34, 70), outline=accent, width=int(4 * s))
                d.ellipse([x0 + 30 * s, top + 30 * s, x0 + 110 * s, top + 110 * s], fill=accent)
                d.text((x0 + 70 * s, top + 70 * s), str(i + 1), font=font(BOLD, int(48 * s)),
                       fill=BG_TOP, anchor="mm")
                fi, il = _fit(d, it, BOLD, bw - 60 * s, bh - 170 * s, int(46 * s), min_size=24)
                ty = top + 140 * s
                for ln in il:
                    d.text((x0 + 30 * s, ty), ln, font=fi, fill=TEXT)
                    ty += fi.size * 1.2
                if i < n - 1:
                    ax = x0 + bw + gap / 2
                    d.polygon([(ax - 12 * s, top + bh / 2 - 18 * s), (ax + 12 * s, top + bh / 2),
                               (ax - 12 * s, top + bh / 2 + 18 * s)], fill=accent)
        else:
            avail = h - y - (0.32 * h if vertical else 200 * s)
            per = avail / max(1, len(items))
            fs = int(min(60 * s, per * 0.42))
            for i, it in enumerate(shown):
                cy = y + i * per
                if layout == "steps":
                    d.ellipse([margin, cy, margin + fs * 1.3, cy + fs * 1.3], fill=accent)
                    d.text((margin + fs * 0.65, cy + fs * 0.65), str(i + 1), font=font(BOLD, int(fs * 0.8)),
                           fill=BG_TOP, anchor="mm")
                else:
                    d.rounded_rectangle([margin, cy + fs * 0.35, margin + fs * 0.6, cy + fs * 0.95],
                                        radius=int(fs * 0.15), fill=accent)
                icon_gap = 300 * s if icon and not vertical else 0
                fi, il = _fit(d, it, BOLD if layout == "steps" else REG, w - 2 * margin - fs * 2 - icon_gap,
                              per * 0.9, fs, min_size=24)
                ty = cy
                for ln in il[:3]:
                    d.text((margin + fs * 1.7, ty), ln, font=fi, fill=TEXT)
                    ty += fi.size * 1.2

    else:  # title
        if icon:
            _paste_icon(img, icon, int(220 * s), (w / 2, h * (0.3 if not vertical else 0.3)))
        f, lines = _fit(d, heading, BOLD, w - 2 * margin, h * (0.2 if vertical else 0.32), int(110 * s))
        y = h * ((0.42 if vertical else 0.52) if icon else 0.4)
        for ln in lines:
            d.text((w / 2, y), ln, font=f, fill=TEXT, anchor="mt", stroke_width=int(2 * s), stroke_fill=(0, 0, 0))
            y += f.size * 1.15
        if items:
            fs, sl = _fit(d, items[0], REG, w - 2.5 * margin, h * 0.15, int(48 * s))
            y += 20 * s
            for ln in sl:
                d.text((w / 2, y), ln, font=fs, fill=accent, anchor="mt")
                y += fs.size * 1.2
    return img


def card_frames(card: dict, size, accent: str, out_prefix: Path, seed: int = 0,
                transparent: bool = False) -> list[Path]:
    """Genera las imágenes de la tarjeta (varias si los elementos aparecen uno a uno)."""
    items = [i for i in card.get("items", []) if i.strip()]
    paths = []
    if card.get("layout") in ("bullets", "steps") and len(items) > 1:
        for k in range(1, len(items) + 1):
            p = out_prefix.with_name(f"{out_prefix.name}_{k}.png")
            render_card(card, size, accent, reveal=k, seed=seed, transparent=transparent).save(p)
            paths.append(p)
    else:
        p = out_prefix.with_suffix(".png")
        render_card(card, size, accent, seed=seed, transparent=transparent).save(p)
        paths.append(p)
    return paths


def wide_background(size: tuple[int, int], accent_hex: str, seed: int = 0, factor: float = 1.3) -> Image.Image:
    """Fondo más grande que el vídeo, para desplazarlo suavemente (fondo animado)."""
    w, h = size
    big = (int(w * factor) // 2 * 2, int(h * factor) // 2 * 2)
    accent = hex_rgb(accent_hex)
    img = background(big, accent, seed).copy()
    rnd = random.Random(seed + 99)
    glow = Image.new("RGB", big, (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for _ in range(3):  # más manchas de luz para que el movimiento se note
        r = rnd.randint(big[1] // 5, big[1] // 3)
        cx, cy = rnd.randint(0, big[0]), rnd.randint(0, big[1])
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(int(c * 0.28) for c in accent))
    glow = glow.filter(ImageFilter.GaussianBlur(big[1] // 8))
    return Image.blend(img, Image.composite(glow, img, glow.convert("L")), 0.5)


def photo_frame(photo_path: Path, caption: str, size: tuple[int, int], accent_hex: str) -> Image.Image:
    """Foto histórica enmarcada sobre su propia versión desenfocada, con rótulo arriba a la izquierda."""
    w, h = size
    s = min(w, h) / 1080
    accent = hex_rgb(accent_hex)
    photo = Image.open(photo_path).convert("RGB")
    # fondo: la propia foto, a pantalla completa, desenfocada y oscurecida
    scale = max(w / photo.width, h / photo.height)
    bg = photo.resize((int(photo.width * scale) + 2, int(photo.height * scale) + 2), Image.LANCZOS)
    bg = bg.crop(((bg.width - w) // 2, (bg.height - h) // 2, (bg.width - w) // 2 + w, (bg.height - h) // 2 + h))
    bg = bg.filter(ImageFilter.GaussianBlur(int(40 * s)))
    bg = Image.blend(bg, Image.new("RGB", size, BG_TOP), 0.55)
    # foto nítida, ajustada al área central
    max_w, max_h = w * 0.86, h * 0.68
    k = min(max_w / photo.width, max_h / photo.height)
    pw, ph = int(photo.width * k), int(photo.height * k)
    fg = photo.resize((pw, ph), Image.LANCZOS)
    x, y = (w - pw) // 2, int(h * 0.15)
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle([x + 10 * s, y + 14 * s, x + pw + 10 * s, y + ph + 14 * s], fill=(0, 0, 0, 170))
    bg = Image.alpha_composite(bg.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(int(14 * s)))).convert("RGB")
    d = ImageDraw.Draw(bg)
    border = int(6 * s)
    d.rectangle([x - border, y - border, x + pw + border - 1, y + ph + border - 1], fill=(235, 230, 220))
    bg.paste(fg, (x, y))
    if caption:
        f, lines = _fit(d, caption, BOLD, w * 0.8, 60 * s, int(46 * s), min_size=26)
        text = lines[0] if len(lines) == 1 else caption
        f = f if len(lines) == 1 else _fit(d, caption, BOLD, w * 0.8, 200 * s, int(40 * s), min_size=22)[0]
        tw = d.textlength(text, font=f)
        bx, by = int(60 * s), int(40 * s)
        d.rounded_rectangle([bx, by, bx + tw + 44 * s, by + f.size * 1.5], radius=int(12 * s), fill=accent)
        d.text((bx + 22 * s, by + f.size * 0.25), text, font=f, fill=BG_TOP)
    return bg

