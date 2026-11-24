"""Animaciones de las tarjetas: cada tarjeta se convierte en una secuencia de fotogramas con su duración.

- number: el número cuenta desde 0 (o aparece con un «pop» si es un año o no es numérico).
- title / quote: las palabras aparecen una a una (tipografía cinética).
- bullets / steps: cada elemento entra deslizándose desde la izquierda.
- chart: barras horizontales que crecen. items = ["Etiqueta: valor", ...]

Devuelve [(ruta_png, segundos), ...] para el demuxer concat de ffmpeg.
"""

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw

from . import cards

FPS = 15  # fotogramas por segundo de la animación (luego el vídeo va a 30)


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3  # ease-out cúbico


def _save(img: Image.Image, prefix: Path, n: int) -> Path:
    p = prefix.with_name(f"{prefix.name}_a{n:03d}.png")
    img.save(p, optimize=False, compress_level=1)
    return p


def _blank_like(img: Image.Image) -> Image.Image:
    return Image.new("RGBA", img.size, (0, 0, 0, 0))


def _fade(img: Image.Image, a: float) -> Image.Image:
    if a >= 1:
        return img
    out = img.copy()
    alpha = out.getchannel("A").point(lambda v: int(v * a))
    out.putalpha(alpha)
    return out


_NUM = re.compile(r"^([^\d\-+]*)([\-+]?)(\d{1,3}(?:[.\s]\d{3})+|\d+)(?:,(\d+))?(.*)$")


def _parse_number(text: str):
    """'5 billones $' -> (prefix, sign, value, decimals, suffix, sep). None si no es un número contable."""
    m = _NUM.match(text.strip())
    if not m:
        return None
    pre, sign, intpart, dec, suf = m.groups()
    sep = "." if "." in intpart else (" " if " " in intpart else "")
    val = int(re.sub(r"[.\s]", "", intpart))
    if not sep and not dec and 1000 <= val <= 2100 and not pre and not suf.strip():
        return None  # parece un año: no se cuenta
    return pre, sign, val, dec, suf, sep


def _fmt(val: float, dec: str | None, sep: str) -> str:
    if dec:
        s = f"{val:.{len(dec)}f}".replace(".", ",")
        ip, dp = s.split(",")
    else:
        ip, dp = str(int(round(val))), None
    if sep or len(ip) > 4:
        ip = f"{int(ip):,}".replace(",", sep or ".")
    return ip + ("," + dp if dp else "")


def _number_frames(card, size, accent, prefix, seed, transparent):
    items = [i for i in card.get("items", []) if i.strip()]
    big, _cap = cards.number_parts(card.get("heading", ""), items)
    big_in_items = bool(items) and big == items[0]
    parsed = _parse_number(big)
    final = cards.render_card(card, size, accent, seed=seed, transparent=transparent)
    frames = []
    if parsed:
        pre, sign, val, dec, suf, sep = parsed
        n = int(1.1 * FPS)
        for k in range(n):
            v = val * _ease((k + 1) / n)
            txt = f"{pre}{sign}{_fmt(v, dec, sep)}{suf}"
            c = dict(card)
            if big_in_items:
                c["items"] = [txt] + items[1:]
            else:
                c["heading"] = txt
            frames.append(cards.render_card(c, size, accent, seed=seed, transparent=transparent))
    else:  # «pop»: aparece creciendo desde el centro
        n = int(0.5 * FPS)
        w, h = size
        for k in range(n):
            t = _ease((k + 1) / n)
            sc = 0.82 + 0.18 * t
            im = final.resize((max(1, int(w * sc)), max(1, int(h * sc))), Image.LANCZOS)
            base = _blank_like(final) if transparent else final.copy()
            if not transparent:
                base = cards.render_card({"layout": "title", "heading": ""}, size, accent, seed=seed)
            base.alpha_composite(_fade(im.convert("RGBA"), t), ((w - im.width) // 2, (h - im.height) // 2))
            frames.append(base)
    return frames, final


def _words_frames(card, size, accent, prefix, seed, transparent):
    """Palabras del titular / cita apareciendo una a una."""
    heading = card.get("heading", "")
    words = heading.split()
    final = cards.render_card(card, size, accent, seed=seed, transparent=transparent)
    if len(words) < 2:
        return [], final
    frames = []
    step = max(1, math.ceil(len(words) / 10))  # como mucho ~10 pasos
    for k in range(step, len(words), step):
        c = dict(card)
        # palabras aún ocultas sustituidas por espacios no separables para no mover la maquetación
        shown = words[:k] + [" " * len(w_) for w_ in words[k:]]
        c["heading"] = " ".join(shown)
        c["items"] = []  # el subtítulo aparece al final
        im = cards.render_card(c, size, accent, seed=seed, transparent=transparent)
        frames += [im, im]  # cada paso dura 2 fotogramas
    return frames, final


def _reveal_frames(card, size, accent, prefix, seed, transparent, total):
    """bullets/steps: cada elemento entra deslizándose desde la izquierda."""
    items = [i for i in card.get("items", []) if i.strip()]
    states = [cards.render_card(card, size, accent, reveal=k, seed=seed, transparent=transparent)
              for k in range(0, len(items) + 1)]
    lead = min(1.2, total * 0.25)
    per = (total - lead) / max(1, len(items))
    tl = []  # [(img, dur)]
    slide = 4  # fotogramas de la entrada
    dx = int(size[0] * 0.04)
    tl.append((states[0], max(0.2, lead - slide / FPS) if items else total))
    for k in range(1, len(items) + 1):
        prev, cur = states[k - 1], states[k]
        diff = Image.eval(Image.composite(cur, prev, _changed(cur, prev)).getchannel("A"), lambda v: v)
        mask = _changed(cur, prev)
        for f in range(slide):
            t = _ease((f + 1) / slide)
            moving = Image.new("RGBA", cur.size, (0, 0, 0, 0))
            piece = Image.composite(cur, moving, mask)
            frame = prev.copy()
            frame.alpha_composite(_fade(piece, t), (int(-dx * (1 - t)), 0))
            tl.append((frame, 1 / FPS))
        hold = per - slide / FPS
        tl.append((cur, max(0.1, hold)))
        del diff
    return tl


def _changed(cur: Image.Image, prev: Image.Image) -> Image.Image:
    """Máscara de los píxeles que cambian entre dos estados."""
    a = cur.convert("RGBA")
    b = prev.convert("RGBA")
    from PIL import ImageChops
    d = ImageChops.difference(a, b).convert("L")
    return d.point(lambda v: 255 if v > 8 else 0)


def _chart_frames(card, size, accent_hex, prefix, seed, transparent):
    """Barras horizontales que crecen. items: ["2018: 1", "2022: 3"] o ["Netflix: 325", ...]."""
    accent = cards.hex_rgb(accent_hex)
    w, h = size
    s = min(w, h) / 1080
    rows = []
    for it in card.get("items", []):
        if ":" not in it:
            continue
        label, val = it.rsplit(":", 1)
        p = _parse_number(val.strip()) or (None,)
        try:
            num = float(re.sub(r"[^\d,]", "", val).replace(",", ".")) if p[0] is None else p[2]
        except ValueError:
            continue
        rows.append((label.strip(), val.strip(), num))
    if not rows:
        return [], cards.render_card({**card, "layout": "bullets"}, size, accent_hex, seed=seed, transparent=transparent)
    vmax = max(r[2] for r in rows) or 1
    margin = int(110 * s)

    def draw(t):
        img = Image.new("RGBA", size, (0, 0, 0, 0)) if transparent else cards.background(size, accent, seed).copy()
        d = ImageDraw.Draw(img)
        fh, hl = cards._fit(d, card.get("heading", ""), cards.BOLD, w - 2 * margin, h * 0.18, int(80 * s))
        y = margin * (1.4 if h > w else 0.9)
        for ln in hl:
            d.text((margin, y), ln, font=fh, fill=cards.TEXT)
            y += fh.size * 1.15
        cards._pill(d, (margin, y + 14 * s), accent)
        top = y + 90 * s
        avail = h - top - (0.30 * h if h > w else 140 * s)
        bh = min(110 * s, avail / len(rows) * 0.62)
        gap = (avail - bh * len(rows)) / max(1, len(rows))
        label_w = max(d.textlength(r[0], font=cards.font(cards.BOLD, int(44 * s))) for r in rows) + 40 * s
        label_w = min(label_w, w * 0.32)
        maxbar = w - 2 * margin - label_w - 200 * s
        for i, (label, vtxt, num) in enumerate(rows):
            cy = top + i * (bh + gap)
            d.text((margin, cy + bh / 2), label, font=cards.font(cards.BOLD, int(44 * s)), fill=cards.TEXT, anchor="lm")
            ti = _ease(t * 1.3 - i * 0.15)
            bw = max(4, maxbar * (num / vmax) * ti)
            x0 = margin + label_w
            d.rounded_rectangle([x0, cy, x0 + bw, cy + bh], radius=int(bh * 0.25), fill=accent)
            if ti > 0.6:
                d.text((x0 + bw + 20 * s, cy + bh / 2), vtxt, font=cards.font(cards.BOLD, int(46 * s)),
                       fill=cards.TEXT, anchor="lm")
        return img

    n = int(1.4 * FPS)
    frames = [draw((k + 1) / n) for k in range(n)]
    return frames, draw(1.0)


def card_timeline(card: dict, size, accent: str, out_prefix: Path, total: float, seed: int = 0,
                  transparent: bool = False) -> list[tuple[Path, float]]:
    """Secuencia [(png, duración)] que suma `total` segundos."""
    layout = card.get("layout", "title")
    items = [i for i in card.get("items", []) if i.strip()]
    if layout in ("bullets", "steps") and len(items) > 1:
        tl = _reveal_frames(card, size, accent, out_prefix, seed, transparent, total)
    else:
        if layout == "number":
            frames, final = _number_frames(card, size, accent, out_prefix, seed, transparent)
        elif layout == "chart":
            frames, final = _chart_frames(card, size, accent, out_prefix, seed, transparent)
        elif layout in ("title", "quote"):
            frames, final = _words_frames(card, size, accent, out_prefix, seed, transparent)
        else:
            frames, final = [], cards.render_card(card, size, accent, seed=seed, transparent=transparent)
        tl = [(f, 1 / FPS) for f in frames]
        used = sum(d for _, d in tl)
        tl.append((final, max(0.2, total - used)))
    out = []
    for n, (img, dur) in enumerate(tl):
        out.append((_save(img, out_prefix, n), dur))
    # ajusta la última duración para que la suma sea exacta
    extra = total - sum(d for _, d in out)
    p, d = out[-1]
    out[-1] = (p, max(0.05, d + extra))
    return out
