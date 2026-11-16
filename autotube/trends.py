"""Análisis de tendencias y elección del próximo tema."""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .youtube_api import youtube_public

log = logging.getLogger(__name__)


def _video_stats(yt, ids: list[str]) -> list[dict]:
    out = []
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="snippet,statistics,contentDetails", id=",".join(ids[i:i + 50])).execute()
        for it in resp.get("items", []):
            sn, st = it["snippet"], it.get("statistics", {})
            out.append({
                "title": sn["title"],
                "channel": sn["channelTitle"],
                "published": sn["publishedAt"][:10],
                "views": int(st.get("viewCount", 0)),
                "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)),
                "duration": it["contentDetails"]["duration"],
                "tags": sn.get("tags", [])[:8],
            })
    return out


def youtube_trending(cfg: dict, max_results: int = 30) -> list[dict]:
    """Vídeos en tendencia del país configurado."""
    yt = youtube_public(cfg)
    resp = yt.videos().list(
        part="id", chart="mostPopular", regionCode=cfg["channel"]["region"], maxResults=max_results
    ).execute()
    return _video_stats(yt, [it["id"] for it in resp.get("items", [])])


def niche_hits(cfg: dict, days: int = 14, per_keyword: int = 10) -> list[dict]:
    """Vídeos del nicho más vistos en los últimos `days` días (100 unidades de cuota por palabra clave)."""
    yt = youtube_public(cfg)
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    ids: list[str] = []
    for kw in cfg["channel"]["keywords"][:5]:
        resp = yt.search().list(
            part="id", q=kw, type="video", order="viewCount", publishedAfter=after,
            relevanceLanguage=cfg["channel"]["language"], regionCode=cfg["channel"]["region"],
            maxResults=per_keyword,
        ).execute()
        ids += [it["id"]["videoId"] for it in resp.get("items", []) if it["id"].get("videoId")]
    videos = _video_stats(yt, list(dict.fromkeys(ids)))
    return sorted(videos, key=lambda v: v["views"], reverse=True)


def google_autocomplete(cfg: dict) -> list[str]:
    """Sugerencias de búsqueda de YouTube (lo que la gente está buscando ahora)."""
    out = []
    for kw in cfg["channel"]["keywords"][:5]:
        try:
            r = requests.get(
                "https://suggestqueries.google.com/complete/search",
                params={"client": "firefox", "ds": "yt", "q": kw, "hl": cfg["channel"]["language"]},
                timeout=10,
            )
            out += r.json()[1]
        except Exception as e:  # no es crítico
            log.warning("Autocompletado no disponible para %r: %s", kw, e)
    return list(dict.fromkeys(out))


def collect_signals(cfg: dict) -> dict:
    signals = {"niche_hits": [], "trending": [], "searches": []}
    for name, fn in (("niche_hits", niche_hits), ("trending", youtube_trending), ("searches", google_autocomplete)):
        try:
            signals[name] = fn(cfg)
        except Exception as e:
            log.warning("No se pudo obtener %s: %s", name, e)
    return signals


TOPIC_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {
            "type": "array",
            "description": "5 ideas de vídeo evaluadas",
            "items": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string"},
                    "angle": {"type": "string", "description": "enfoque único y la promesa al espectador"},
                    "evidence": {"type": "string", "description": "qué señal de tendencia lo respalda"},
                    "score": {"type": "integer", "description": "1-10 potencial de vistas y retención"},
                },
                "required": ["topic", "angle", "evidence", "score"],
                "additionalProperties": False,
            },
        },
        "chosen": {
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "angle": {"type": "string"},
                "working_title": {"type": "string"},
                "why": {"type": "string"},
                "research_questions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["topic", "angle", "working_title", "why", "research_questions"],
            "additionalProperties": False,
        },
    },
    "required": ["candidates", "chosen"],
    "additionalProperties": False,
}


def _fmt(videos: list[dict], n: int) -> str:
    return "\n".join(
        f"- {v['title']} | {v['channel']} | {v['views']:,} vistas | {v['published']}" for v in videos[:n]
    ) or "(sin datos)"


def pick_topic(cfg: dict, llm, db) -> dict:
    ch = cfg["channel"]
    signals = collect_signals(cfg)
    feedback_path = Path(cfg["paths"]["feedback"])
    feedback = feedback_path.read_text(encoding="utf-8") if feedback_path.exists() else "(aún no hay datos del canal)"
    past = "\n".join(f"- {t}" for t in db.past_topics()) or "(ninguno)"
    fmt = "Shorts verticales de menos de 60 segundos" if cfg["video"]["format"] == "short" else \
        f"vídeos horizontales de unos {cfg['video']['target_minutes']} minutos"

    prompt = f"""Eres el estratega de contenido del canal de YouTube "{ch['name']}".
Nicho: {ch['niche']}
Audiencia: {ch['audience']}
Formato: {fmt}
Temas prohibidos: {', '.join(ch.get('banned_topics', []))}

## Vídeos del nicho con más vistas en las últimas 2 semanas
{_fmt(signals['niche_hits'], 40)}

## Tendencias generales en YouTube ({ch['region']})
{_fmt(signals['trending'], 25)}

## Lo que la gente está buscando
{chr(10).join('- ' + s for s in signals['searches'][:40]) or '(sin datos)'}

## Aprendizajes del rendimiento de nuestro canal
{feedback}

## Temas ya publicados (NO repetir ni hacer variaciones cercanas)
{past}

Propón 5 ideas de vídeo que encajen en el nicho, aprovechen la demanda detectada y se
puedan contar bien con narración + imágenes de archivo. Puntúalas y elige la mejor.
La idea elegida debe aportar valor real y original (no copiar un vídeo concreto) y
basarse en hechos verificables. Escribe en el idioma '{ch['language']}'."""
    result = llm.json("Eres un estratega experto en crecimiento de canales de YouTube.", prompt, TOPIC_SCHEMA)
    db.log("topic_selected", **result["chosen"])
    return result["chosen"]
