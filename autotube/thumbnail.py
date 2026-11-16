"""Miniaturas 1280x720 pensadas para el CTR.

Diseño: foto histórica nítida a la derecha (o emoji gigante sobre fondo tecnológico), panel oscuro en
diagonal a la izquierda, 2-4 palabras en tipografía muy gruesa con la última línea resaltada como con
rotulador, una etiqueta con el año y la marca del canal.
"""

import itertools
import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from . import cards, media

W, H = 1280, 720
HEAVY_FONTS = [
    "/usr/share/fonts/opentype/montserrat/Montserrat-Black.otf",
    "/usr/share/fonts/truetype/montserrat/Montserrat-Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _heavy_font(cfg: dict) -> str:
    for p in [cfg["thumbnail"].get("font_heavy", ""), *HEAVY_FONTS]:
        if p and os.path.exists(p):
            return p
    return cfg["thumbnail"]["font"]


def _cover(img: Image.Image, size=(W, H), top_bias: float = 0.18) -> Image.Image:
    img = img.convert("RGB")
    scale = max(size[0] / img.width, size[1] / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left = (img.width - size[0]) // 2
    top = int((img.height - size[1]) * top_bias)  # en retratos, priorizar la cara
    return img.crop((left, top, left + size[0], top + size[1]))


def _frame_from_video(video: Path, out: Path, at: float = 3.0) -> Path | None:
    proc = subprocess.run(["ffmpeg", "-y", "-ss", str(at), "-i", str(video), "-frames:v", "1", str(out)],
                          capture_output=True)
    return out if proc.returncode == 0 and out.exists() else None


def _layout_text(draw, text: str, font_path: str, max_w: int, max_h: int):
    """Reparte el texto en 1-3 líneas equilibradas con la letra más grande posible."""
    words = text.upper().split()
    n = len(words)
    result = None
    for lines_n in (1, 2, 3):
        if lines_n > n:
            break
        best = None
        for cuts in itertools.combinations(range(1, n), lines_n - 1):
            parts = [" ".join(words[a:b]) for a, b in zip((0, *cuts), (*cuts, n))]
            score = max(len(p) for p in parts)
            if best is None or score < best[0]:
                best = (score, parts)
        lines = best[1]
        size = 190
        while size > 40:
            f = ImageFont.truetype(font_path, size)
            if max(draw.textlength(l, font=f) for l in lines) <= max_w and len(lines) * size * 1.05 <= max_h:
                break
            size -= 4
        if result is None or size > result[0].size * 1.08:
            result = (ImageFont.truetype(font_path, size), lines)
    return result


def make_thumbnail(cfg: dict, text: str, query: str, workdir: Path, fallback_media: list[Path],
                   icon: str = "", photo: Path | None = None, badge: str = "") -> Path:
    out = workdir / "thumbnail.jpg"
    accent_rgb = cards.hex_rgb(cfg["thumbnail"].get("accent_color", "#FFD400"))
    theme = cards.hex_rgb(cfg["video"].get("theme_color", "#F5B942"))
    bg_path = photo
    if not bg_path and query:
        try:
            bg_path = media.pexels_photo(query, workdir / "thumb_bg", "landscape")
        except Exception:
            bg_path = None
    if not bg_path:
        for m in fallback_media:
            bg_path = _frame_from_video(m, workdir / "thumb_bg.png") if m.suffix == ".mp4" else m
            if bg_path:
                break

    split = int(W * 0.56)  # dónde empieza la imagen
    canvas = cards.background((W, H), theme, seed=7).copy()
    if bg_path:
        src = Image.open(bg_path).convert("RGB")
        portrait = src.height > src.width * 0.9
        pic = _cover(src, (W - split + 120, H), top_bias=0.12 if portrait else 0.5)
        pic = ImageEnhance.Contrast(ImageEnhance.Color(pic).enhance(1.25)).enhance(1.12)
        pic = ImageEnhance.Sharpness(pic).enhance(1.4)
        canvas.paste(pic, (split - 120, 0))
    else:
        glow = Image.new("RGB", (W, H))
        ImageDraw.Draw(glow).ellipse([W - 600, 60, W - 20, 640], fill=theme)
        glow = glow.filter(ImageFilter.GaussianBlur(90))
        canvas = Image.composite(glow, canvas, glow.convert("L").point(lambda v: int(v * 0.6)))
        e = cards.emoji(icon, 440) if icon else None
        if e:
            canvas.paste(e, (W - e.width - 60, (H - e.height) // 2), e)

    # panel oscuro en diagonal + filo de color
    panel = Image.new("L", (W, H), 0)
    ImageDraw.Draw(panel).polygon([(0, 0), (split + 70, 0), (split - 70, H), (0, H)], fill=235)
    panel = panel.filter(ImageFilter.GaussianBlur(6))
    canvas = Image.composite(Image.new("RGB", (W, H), (10, 12, 22)), canvas, panel)
    d = ImageDraw.Draw(canvas)
    d.line([(split + 70, 0), (split - 70, H)], fill=accent_rgb, width=10)

    # texto: líneas blancas y la última resaltada con «rotulador»
    font_path = _heavy_font(cfg)
    f, lines = _layout_text(d, text, font_path, max_w=split - 70, max_h=int(H * 0.66))
    line_h = f.size * 1.05
    y = (H - len(lines) * line_h) / 2 + 10
    for i, line in enumerate(lines):
        tw = d.textlength(line, font=f)
        if i == len(lines) - 1 and len(lines) > 1:
            pad = f.size * 0.12
            d.rectangle([40 - pad, y + f.size * 0.08, 40 + tw + pad, y + f.size * 1.02], fill=accent_rgb)
            d.text((40, y), line, font=f, fill=(15, 15, 20))
        else:
            d.text((40, y), line, font=f, fill="white", stroke_width=max(3, f.size // 22), stroke_fill=(0, 0, 0))
        y += line_h

    if badge:  # etiqueta con el año o un dato
        bf = ImageFont.truetype(font_path, 54)
        bw = d.textlength(badge, font=bf) + 44
        bx, by = W - bw - 34, 30
        d.rounded_rectangle([bx, by, bx + bw, by + 78], radius=16, fill=(220, 30, 40))
        d.text((bx + 22, by + 8), badge, font=bf, fill="white")

    brand = cfg["channel"].get("name", "").upper()
    if brand:
        d.text((40, H - 58), brand, font=ImageFont.truetype(font_path, 26), fill=accent_rgb)

    canvas.save(out, "JPEG", quality=92, optimize=True)
    q = 85
    while out.stat().st_size > 2_000_000 and q > 40:  # límite de YouTube: 2 MB
        canvas.save(out, "JPEG", quality=q, optimize=True)
        q -= 10
    return out
