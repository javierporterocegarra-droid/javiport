"""Orquestación: tendencias -> investigación -> guion -> voz -> imágenes -> vídeo -> miniatura -> subida."""

import json
import logging
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from . import media, script, thumbnail, trends, tts, uploader, video

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

        # 4-5. Voz + material visual + render por escena
        segments, sub_scenes, starts, media_files, used = [], [], [], [], set()
        offset = 0.0
        for i, scene in enumerate(sc["scenes"]):
            log.info("Escena %d/%d", i + 1, len(sc["scenes"]))
            audio = workdir / f"scene_{i:03d}.mp3"
            dur, words = tts.synthesize(cfg, scene["narration"], audio)
            m = media.fetch_scene_media(cfg, scene["visual_query"], scene["section"],
                                        workdir / f"media_{i:03d}", dur, used)
            media_files.append(m)
            seg = workdir / f"seg_{i:03d}.mp4"
            total = video.render_scene(cfg, m, audio, dur, seg)
            segments.append(seg)
            sub_scenes.append({"offset": offset, "words": words})
            starts.append((offset, scene["section"]))
            offset += total

        # 6. Montaje final
        subs = None
        if cfg["video"]["subtitles"]:
            subs = workdir / "subs.ass"
            video.build_ass(cfg, sub_scenes, subs)
        final = workdir / "video.mp4"
        log.info("Montando vídeo final (%.0f s)…", offset)
        video.assemble(cfg, workdir, segments, subs, final)

        # 7. Miniatura
        thumb = thumbnail.make_thumbnail(cfg, sc["thumbnail_text"], sc["thumbnail_query"], workdir, media_files)

        # 8. Metadatos finales
        chap = video.chapters(starts, offset) if cfg["video"]["format"] == "long" else ""
        desc = sc["description"].strip()
        if chap:
            desc += "\n\nCapítulos:\n" + chap
        sources = re.findall(r"^- (https?://\S+)", dossier, flags=re.M)
        if sources:
            desc += "\n\nFuentes:\n" + "\n".join(sources[:10])
        desc += "\n\n" + " ".join(sc["hashtags"][:3])
        meta = {**sc, "full_description": desc, "duration_s": offset}
        _save(workdir / "metadata.json", meta)
        db.update_video(vid, status="rendered", duration_s=offset)

        # limpieza de intermedios pesados
        for p in workdir.glob("seg_*.mp4"):
            p.unlink()
        (workdir / "joined.mp4").unlink(missing_ok=True)
        log.info("Vídeo listo en %s", workdir)
        return workdir
    except Exception as e:
        db.update_video(vid, status="failed")
        db.log("create_failed", workdir=str(workdir), error=str(e)[:500])
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
