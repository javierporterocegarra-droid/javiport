"""Generación de miniaturas 1280x720 llamativas."""

import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from . import cards, media

W, H = 1280, 720


def _cover(img: Image.Image, size=(W, H)) -> Image.Image:
    img = img.convert("RGB")
    scale = max(size[0] / img.width, size[1] / img.height)
    img = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.LANCZOS)
    left, top = (img.width - size[0]) // 2, (img.height - size[1]) // 2
    return img.crop((left, top, left + size[0], top + size[1]))


def _frame_from_video(video: Path, out: Path, at: float = 3.0) -> Path | None:
    proc = subprocess.run(["ffmpeg", "-y", "-ss", str(at), "-i", str(video), "-frames:v", "1", str(out)],
                          capture_output=True)
    return out if proc.returncode == 0 and out.exists() else None


def _fit_font(draw, lines, font_path, max_w, max_h):
    size = 170
    while size > 40:
        font = ImageFont.truetype(font_path, size)
        widths = [draw.textbbox((0, 0), l, font=font, stroke_width=size // 12)[2] for l in lines]
        if max(widths) <= max_w and len(lines) * size * 1.08 <= max_h:
            return font
        size -= 6
    return ImageFont.truetype(font_path, size)


def make_thumbnail(cfg: dict, text: str, query: str, workdir: Path, fallback_media: list[Path],
                   icon: str = "") -> Path:
    out = workdir / "thumbnail.jpg"
    bg_path = None
    try:
        bg_path = media.pexels_photo(query, workdir / "thumb_bg", "landscape")
    except Exception:
        pass
    if not bg_path:
        for m in fallback_media:
            bg_path = _frame_from_video(m, workdir / "thumb_bg.png") if m.suffix == ".mp4" else m
            if bg_path:
                break
    accent = cfg["thumbnail"].get("accent_color", "#FFD400")
    if bg_path:
        bg = _cover(Image.open(bg_path))
        bg = ImageEnhance.Contrast(ImageEnhance.Color(bg).enhance(1.35)).enhance(1.15)
    else:  # estilo gráfico: fondo tecnológico + emoji gigante
        theme = cards.hex_rgb(cfg["video"].get("theme_color", "#22D3EE"))
        bg = cards.background((W, H), theme, seed=7).copy()
        glow = Image.new("RGB", (W, H))
        ImageDraw.Draw(glow).ellipse([W - 560, 80, W - 20, 620], fill=theme)
        glow = glow.filter(ImageFilter.GaussianBlur(90))
        bg = Image.composite(glow, bg, glow.convert("L").point(lambda v: int(v * 0.55)))
    e = cards.emoji(icon, 430) if icon else None
    if e:
        bg.paste(e, (W - e.width - 50, (H - e.height) // 2), e)

    # degradado oscuro a la izquierda para que el texto se lea
    shade = Image.new("L", (W, H))
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        sd.line([(x, 0), (x, H)], fill=int(215 * max(0.0, 1 - x / (W * 0.75))))
    bg = Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), bg, shade.filter(ImageFilter.GaussianBlur(20)))

    draw = ImageDraw.Draw(bg)
    words = text.upper().split()
    lines = textwrap.wrap(" ".join(words), width=max(8, len(" ".join(words)) // 2 + 1))[:3]
    font_path = cfg["thumbnail"]["font"]
    font = _fit_font(draw, lines, font_path, int(W * 0.62), int(H * 0.78))
    y = (H - len(lines) * font.size * 1.08) / 2
    for i, line in enumerate(lines):
        draw.text((50, y), line, font=font, fill=accent if i % 2 else "white",
                  stroke_width=max(4, font.size // 12), stroke_fill="black")
        y += font.size * 1.08
    draw.rectangle([0, H - 14, W, H], fill=accent)
    bg.save(out, "JPEG", quality=90, optimize=True)
    q = 85
    while out.stat().st_size > 2_000_000 and q > 40:  # límite de YouTube: 2 MB
        bg.save(out, "JPEG", quality=q, optimize=True)
        q -= 10
    return out
