"""Orquestación: tendencias -> investigación -> guion -> voz -> imágenes -> vídeo -> miniatura -> subida."""

import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from . import cards, media, script, thumbnail, trends, tts, uploader, video
from .config import env

log = logging.getLogger(__name__)


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:50]


def _save(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def create_video(cfg: dict, llm, db, topic_override: str | None = None) -> Path:
    # 1. Tema
    if topic_override:
        topic = {"topic": topic_override, "angle": "explicación clara, rigurosa y entretenida",
                 "working_title": topic_override, "why": "elegido manualmente",
                 "research_questions": [f"¿Qué es lo más interesante y verificado sobre {topic_override}?"]}
    else:
        log.info("Analizando tendencias…")
        topic = trends.pick_topic(cfg, llm, db)
    log.info("Tema: %s", topic["topic"])

    workdir = Path(cfg["paths"]["output"]) / f"{datetime.now():%Y%m%d-%H%M}-{slugify(topic['topic'])}"
    workdir.mkdir(parents=True, exist_ok=True)
    _save(workdir / "topic.json", topic)
    vid = db.add_video(topic["topic"], str(workdir))

    try:
        # 2. Investigación
        log.info("Investigando…")
        dossier = script.research_topic(cfg, llm, topic)
        (workdir / "research.md").write_text(dossier, encoding="utf-8")

        # 3. Guion
        log.info("Escribiendo guion…")
        sc = script.write_script(cfg, llm, topic, dossier)
        _save(workdir / "script.json", sc)
        db.update_video(vid, title=sc["title"], status="scripted")

        return render_from_script(cfg, db, workdir, sc, dossier, vid)
    except Exception as e:
        db.update_video(vid, status="failed")
        db.log("create_failed", workdir=str(workdir), error=str(e)[:500])
        raise


def _cached_tts(cfg: dict, text: str, audio: Path):
    """Reutiliza el audio si la narración y la voz no han cambiado (re-render rápido)."""
    key = json.dumps([text, tts.spoken(cfg, text), cfg["tts"]], ensure_ascii=False, sort_keys=True)
    meta = audio.with_suffix(".json")
    if audio.exists() and meta.exists():
        cached = json.loads(meta.read_text(encoding="utf-8"))
        if cached.get("key") == key:
            return cached["duration"], cached["words"]
    dur, words = tts.synthesize(cfg, text, audio)
    _save(meta, {"key": key, "duration": dur, "words": words})
    return dur, words


def _use_cards(cfg: dict) -> bool:
    mode = cfg["video"].get("visuals", "auto")
    return mode == "cards" or (mode == "auto" and not env("PEXELS_API_KEY"))


def render_from_script(cfg: dict, db, workdir: Path, sc: dict, dossier: str = "", vid: int | None = None) -> Path:
    """Pasos 4-8: voz, visuales, montaje, miniatura y metadatos a partir de un guion."""
    if vid is None:
        row = db.conn.execute("SELECT id FROM videos WHERE workdir=?", (str(workdir),)).fetchone()
        vid = row["id"] if row else db.add_video(sc.get("topic", sc["title"]), str(workdir))
        db.update_video(vid, title=sc["title"], status="scripted")
    use_cards = _use_cards(cfg)
    size = video.dims(cfg)
    accent = cfg["video"].get("theme_color", "#22D3EE")
    try:
        segments, sub_scenes, starts, media_files, used = [], [], [], [], set()
        offset = 0.0
        for i, scene in enumerate(sc["scenes"]):
            log.info("Escena %d/%d", i + 1, len(sc["scenes"]))
            audio = workdir / f"scene_{i:03d}.mp3"
            dur, words = _cached_tts(cfg, scene["narration"], audio)
            if use_cards and scene.get("card"):
                m = cards.card_frames(scene["card"], size, accent, workdir / f"card_{i:03d}", seed=i)
                is_card = True
            else:
                m = media.fetch_scene_media(cfg, scene["visual_query"], scene["section"],
                                            workdir / f"media_{i:03d}", dur, used)
                is_card = False
            media_files.append(m[-1] if isinstance(m, list) else m)
            seg = workdir / f"seg_{i:03d}.mp4"
            total = video.render_scene(cfg, m, audio, dur, seg, card=is_card)
            segments.append(seg)
            sub_scenes.append({"offset": offset, "words": words})
            starts.append((offset, scene["section"]))
            offset += total

        subs = None
        if cfg["video"]["subtitles"]:
            subs = workdir / "subs.ass"
            video.build_ass(cfg, sub_scenes, subs)
        final = workdir / "video.mp4"
        log.info("Montando vídeo final (%.0f s)…", offset)
        video.assemble(cfg, workdir, segments, subs, final)

        thumb = thumbnail.make_thumbnail(cfg, sc["thumbnail_text"], sc["thumbnail_query"], workdir,
                                         [] if use_cards else media_files, icon=sc.get("thumbnail_icon", ""))

        chap = video.chapters(starts, offset) if cfg["video"]["format"] == "long" else ""
        desc = sc["description"].strip()
        if chap:
            desc += "\n\nCapítulos:\n" + chap
        sources = sc.get("sources") or re.findall(r"^- (https?://\S+)", dossier, flags=re.M)
        if sources:
            desc += "\n\nFuentes:\n" + "\n".join(sources[:10])
        desc += "\n\n" + " ".join(sc["hashtags"][:3])
        meta = {**sc, "full_description": desc, "duration_s": offset}
        _save(workdir / "metadata.json", meta)
        db.update_video(vid, status="rendered", duration_s=offset)

        for p in [*workdir.glob("seg_*.mp4"), *workdir.glob("seg_*.txt"), workdir / "joined.mp4"]:
            p.unlink(missing_ok=True)
        log.info("Vídeo listo en %s (miniatura: %s)", workdir, thumb.name)
        return workdir
    except Exception as e:
        db.update_video(vid, status="failed")
        db.log("render_failed", workdir=str(workdir), error=str(e)[:500])
        raise


def upload_dir(cfg: dict, db, workdir: Path) -> dict:
    meta = json.loads((workdir / "metadata.json").read_text(encoding="utf-8"))
    res = uploader.upload(cfg, workdir / "video.mp4", workdir / "thumbnail.jpg", meta)
    row = db.conn.execute("SELECT id FROM videos WHERE workdir=?", (str(workdir),)).fetchone()
    fields = dict(youtube_id=res["youtube_id"], publish_at=res["publish_at"], status="uploaded", title=meta["title"])
    if row:
        db.update_video(row["id"], **fields)
    else:
        db.update_video(db.add_video(meta["title"], str(workdir)), **fields)
    db.log("uploaded", **res)
    return res
