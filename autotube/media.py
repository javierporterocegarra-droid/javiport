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


# ---------------------------------------------------------------- Wikimedia Commons
import re
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "AutoTubeBot/0.2 (educational video generator)"}


def set_contact(url: str) -> None:
    """Wikimedia exige un contacto en el User-Agent de los bots (https://w.wiki/4wJS)."""
    if url:
        UA["User-Agent"] = f"AutoTubeBot/0.2 (+{url}; educational video generator)"
_last_call = [0.0]


_wm_fails = [0]  # fallos seguidos: si Wikimedia nos limita, se deja de usar en este render
WM_MAX_FAILS = 4


class WikimediaUnavailable(requests.HTTPError):
    pass


def _wm_get(url: str, retries: int = 3, **kw) -> requests.Response:
    """GET educado a Wikimedia: espaciado entre peticiones y reintentos ante 429/5xx."""
    import time
    if _wm_fails[0] >= WM_MAX_FAILS:
        raise WikimediaUnavailable("Wikimedia limita las peticiones: se sigue sin fotos")
    for attempt in range(retries):
        wait = 4.0 - (time.time() - _last_call[0])
        if wait > 0:
            time.sleep(wait)
        _last_call[0] = time.time()
        r = requests.get(url, headers=UA, timeout=kw.pop("timeout", 60), **kw)
        if r.status_code in (429, 500, 502, 503, 504):
            try:
                wait = float(r.headers.get("Retry-After") or 0)
            except ValueError:
                wait = 0
            if attempt < retries - 1:
                time.sleep(min(35, max(wait + 1, 5 * 2 ** attempt)))
            continue
        r.raise_for_status()
        if "upload.wikimedia.org" in url:
            _wm_fails[0] = 0
        return r
    _wm_fails[0] += 1
    if _wm_fails[0] >= WM_MAX_FAILS:
        log.warning("Wikimedia sigue limitando (%s): el resto de escenas irán sin foto", r.status_code)
    r.raise_for_status()
    return r
FREE_LICENSES = ("public domain", "pd", "cc0", "cc by", "cc-by", "no restrictions")


def _strip_html(s: str) -> str:
    import html
    import re
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _commons_info(params: dict) -> list[dict]:
    base = {"action": "query", "format": "json", "prop": "imageinfo",
            "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1280}
    r = _wm_get(COMMONS_API, params={**base, **params})
    pages = (r.json().get("query") or {}).get("pages") or {}
    return sorted(pages.values(), key=lambda p: p.get("index", 0))


def wikimedia_photo(query: str, out: Path, used: set) -> tuple[Path, dict] | None:
    """Busca una imagen con licencia libre. `query` puede ser texto o 'File:Nombre_exacto.jpg'.
    Devuelve (ruta, crédito) o None."""
    if query.startswith("File:"):
        pages = _commons_info({"titles": query})
        words = []
    else:
        pages = _commons_info({"generator": "search", "gsrsearch": f"{query} filetype:bitmap",
                               "gsrnamespace": 6, "gsrlimit": 15})
        words = [w for w in query.lower().replace(",", " ").split() if len(w) > 3]
    candidates = []
    for p in pages:
        ii = (p.get("imageinfo") or [None])[0]
        if not ii or p["title"] in used or ii.get("mime") not in ("image/jpeg", "image/png"):
            continue
        meta = ii.get("extmetadata", {})
        lic = _strip_html(meta.get("LicenseShortName", {}).get("value", "")).lower()
        if not any(lic.startswith(f) or f in lic for f in FREE_LICENSES) or "nc" in lic.split() or "-nc" in lic:
            continue
        if ii.get("width", 0) < 960:
            continue
        title = p["title"].lower()
        hits = sum(w in title for w in words)
        if words and hits == 0:
            continue  # el título no tiene nada que ver con la búsqueda
        score = hits + (1 if ii.get("width", 0) >= 1600 else 0) - p.get("index", 0) * 0.01
        candidates.append((score, p, ii, meta))
    candidates.sort(key=lambda c: -c[0])
    for _, p, ii, meta in candidates[:3]:
        thumb = (ii.get("thumburl") or "").replace("://thumb.wikimedia.org/", "://upload.wikimedia.org/").split("?")[0]
        if "/thumb/" not in thumb:
            continue  # sin miniatura: los originales están muy limitados por Wikimedia
        r = None
        for size in ([1280, 960] if ii.get("width", 0) > 1280 else [960]):
            try:
                r = _wm_get(re.sub(r"/\d+px-", f"/{size}px-", thumb), timeout=120, retries=2)
                break
            except WikimediaUnavailable:
                raise
            except requests.HTTPError:
                r = None
        if r is None:
            continue
        dest = out.with_suffix(".png" if ii["mime"] == "image/png" else ".jpg")
        dest.write_bytes(r.content)
        used.add(p["title"])
        credit = {
            "title": p["title"].removeprefix("File:"),
            "author": _strip_html(meta.get("Artist", {}).get("value", "")) or "Autor desconocido",
            "license": _strip_html(meta.get("LicenseShortName", {}).get("value", "")),
            "url": ii.get("descriptionurl", ""),
        }
        return dest, credit
    return None
