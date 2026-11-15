"""Búsqueda y descarga de material visual libre de derechos (Pexels) con respaldo generado."""

import logging
import random
import textwrap
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from .config import env

log = logging.getLogger(__name__)
PEXELS = "https://api.pexels.com"


def _headers():
    key = env("PEXELS_API_KEY")
    return {"Authorization": key} if key else None


def _download(url: str, out: Path) -> Path:
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(out, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return out


def pexels_video(query: str, out: Path, orientation: str, min_seconds: float, used: set) -> Path | None:
    h = _headers()
    if not h:
        return None
    r = requests.get(f"{PEXELS}/videos/search", headers=h, timeout=30,
                     params={"query": query, "orientation": orientation, "per_page": 15, "size": "medium"})
    r.raise_for_status()
    target_w = 1920 if orientation == "landscape" else 1080
    for vid in r.json().get("videos", []):
        if vid["id"] in used or vid.get("duration", 0) < min(min_seconds, 6):
            continue
        files = [f for f in vid["video_files"] if f.get("width") and f.get("file_type") == "video/mp4"]
        if not files:
            continue
        best = min(files, key=lambda f: abs(f["width"] - target_w))
        used.add(vid["id"])
        return _download(best["link"], out.with_suffix(".mp4"))
    return None


def pexels_photo(query: str, out: Path, orientation: str = "landscape") -> Path | None:
    h = _headers()
    if not h:
        return None
    r = requests.get(f"{PEXELS}/v1/search", headers=h, timeout=30,
                     params={"query": query, "orientation": orientation, "per_page": 10})
    r.raise_for_status()
    photos = r.json().get("photos", [])
    if not photos:
        return None
    return _download(random.choice(photos[:5])["src"]["large2x"], out.with_suffix(".jpg"))


def placeholder(text: str, out: Path, size: tuple[int, int], font_path: str) -> Path:
    """Fondo degradado con texto, por si no hay material de stock."""
    w, h = size
    c1 = tuple(random.randint(10, 60) for _ in range(3))
    c2 = tuple(random.randint(60, 140) for _ in range(3))
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        draw.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    font = ImageFont.truetype(font_path, int(h * 0.06))
    lines = textwrap.wrap(text, width=28)[:4]
    y = h / 2 - len(lines) * h * 0.04
    for line in lines:
        draw.text((w / 2, y), line, font=font, fill="white", anchor="mm", stroke_width=3, stroke_fill="black")
        y += h * 0.08
    img.save(out.with_suffix(".png"))
    return out.with_suffix(".png")


def fetch_scene_media(cfg: dict, query: str, fallback_text: str, out: Path,
                      min_seconds: float, used: set) -> Path:
    vertical = cfg["video"]["format"] == "short"
    orientation = "portrait" if vertical else "landscape"
    size = (1080, 1920) if vertical else (1920, 1080)
    simple = " ".join(query.split()[:2])
    for q in dict.fromkeys([query, simple]):
        try:
            p = pexels_video(q, out, orientation, min_seconds, used)
            if p:
                return p
        except Exception as e:
            log.warning("Pexels vídeo falló (%s): %s", q, e)
    try:
        p = pexels_photo(query, out, orientation)
        if p:
            return p
    except Exception as e:
        log.warning("Pexels foto falló (%s): %s", query, e)
    return placeholder(fallback_text, out, size, cfg["thumbnail"]["font"])
