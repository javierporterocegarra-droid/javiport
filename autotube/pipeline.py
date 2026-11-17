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


def _align_words(words: list[dict], text: str) -> list[dict]:
    """Pone a los tiempos de palabra el texto original (con puntuación y mayúsculas del guion)."""
    import unicodedata as _u

    def norm(w: str) -> str:
        w = _u.normalize("NFKD", w.lower())
        return "".join(c for c in w if c.isalnum())

    tokens = text.split()
    if len(tokens) == len(words):
        return [{**w, "text": t} for w, t in zip(words, tokens)]
    out, j = [], 0
    for w in words:
        nw = norm(w["text"])
        k = j
        while k < len(tokens) and k < j + 4 and norm(tokens[k]) != nw and nw not in norm(tokens[k]):
            k += 1
        if k < len(tokens) and k < j + 4:
            out.append({**w, "text": tokens[k]})
            j = k + 1
        else:
            out.append(w)
    return out


def _cached_tts(cfg: dict, text: str, audio: Path):
    """Reutiliza el audio si la narración y la voz no han cambiado (re-render rápido)."""
    t = cfg["tts"]
    voice = [t.get("engine"), t.get("kokoro_voice"), t.get("kokoro_speed"), t.get("voice"), t.get("rate"),
             t.get("elevenlabs_voice_id")]
    key = json.dumps([text, tts.spoken(cfg, text), voice], ensure_ascii=False)
    meta = audio.with_suffix(".json")
    if audio.exists() and meta.exists():
        cached = json.loads(meta.read_text(encoding="utf-8"))
        if cached.get("key") == key:
            return cached["duration"], cached["words"]
        try:  # formato antiguo: [texto, texto_hablado, config_tts_completa]
            old = json.loads(cached.get("key", "[]"))
            if (isinstance(old, list) and len(old) == 3 and isinstance(old[2], dict) and old[:2] == [text, tts.spoken(cfg, text)]
                    and [old[2].get(k) for k in ("engine", "kokoro_voice", "kokoro_speed", "voice", "rate",
                                                  "elevenlabs_voice_id")] == voice):
                _save(meta, {**cached, "key": key})
                return cached["duration"], cached["words"]
        except (ValueError, TypeError):
            pass
    dur, words = tts.synthesize(cfg, text, audio)
    _save(meta, {"key": key, "duration": dur, "words": words})
    return dur, words


def _scene_photo(cfg: dict, workdir: Path, i: int, scene: dict, used: set, size, accent: str):
    """Foto histórica de Wikimedia para la escena (si tiene 'photo'), compuesta y cacheada."""
    query = (scene.get("photo") or "").strip()
    if not query:
        return None
    caption = scene.get("photo_caption") or (scene.get("card") or {}).get("heading", "")
    meta = workdir / f"photo_{i:03d}.json"
    frame = workdir / f"photo_{i:03d}_frame.png"
    if meta.exists() and frame.exists():
        cached = json.loads(meta.read_text(encoding="utf-8"))
        if cached.get("query") == query and cached.get("caption") == caption:
            if cached.get("credit"):
                used.add("File:" + cached["credit"]["title"])
                return frame, cached["credit"]
            return None
    try:
        found = media.wikimedia_photo(query, workdir / f"photo_{i:03d}", used)
    except Exception as e:
        log.warning("Wikimedia falló para %r: %s", query, e)
        return None  # no se cachea: se reintentará en el próximo render
    if not found:
        _save(meta, {"query": query, "caption": caption, "credit": None})
        return None
    path, credit = found
    cards.photo_frame(path, caption, size, accent).save(frame)
    _save(meta, {"query": query, "caption": caption, "credit": credit})
    return frame, credit


def _use_cards(cfg: dict) -> bool:
    mode = cfg["video"].get("visuals", "auto")
    return mode in ("cards", "footage") or (mode == "auto" and not env("PEXELS_API_KEY"))


def _scene_footage(cfg: dict, workdir: Path, i: int, scene: dict, dur: float, used: set) -> Path | None:
    """Vídeo real de Pexels para el fondo de la escena (se cachea en el directorio de trabajo)."""
    cached = workdir / f"footage_{i:03d}.mp4"
    if cached.exists() and cached.stat().st_size > 0:
        return cached
    miss = workdir / f"footage_{i:03d}.none"
    if miss.exists():
        return None
    vertical = cfg["video"]["format"] == "short"
    query = scene.get("visual_query") or scene["card"].get("heading", "")
    for q in dict.fromkeys([query, " ".join(query.split()[:2])]):
        if not q:
            continue
        try:
            p = media.pexels_video(q, cached, "portrait" if vertical else "landscape", dur, used)
            if p:
                return p
        except Exception as e:
            log.warning("Pexels falló para %r: %s", q, e)
            return None  # no se cachea el fallo de red
    miss.write_text(query, encoding="utf-8")
    return None


def render_from_script(cfg: dict, db, workdir: Path, sc: dict, dossier: str = "", vid: int | None = None) -> Path:
    """Pasos 4-8: voz, visuales, montaje, miniatura y metadatos a partir de un guion."""
    if vid is None:
        row = db.conn.execute("SELECT id FROM videos WHERE workdir=?", (str(workdir),)).fetchone()
        vid = row["id"] if row else db.add_video(sc.get("topic", sc["title"]), str(workdir))
        db.update_video(vid, title=sc["title"], status="scripted")
    use_cards = _use_cards(cfg)
    use_footage = cfg["video"].get("footage", True) and bool(env("PEXELS_API_KEY"))
    size = video.dims(cfg)
    accent = cfg["video"].get("theme_color", "#22D3EE")
    animated = cfg["video"].get("animated", True)
    use_photos = cfg["video"].get("photos", True)
    media.set_contact(cfg["video"].get("contact_url", ""))
    try:
        # Pasada 1: voz y fotos (hace falta la duración total para la barra de progreso)
        plan, used, used_photos, credits = [], set(), set(), []
        for i, scene in enumerate(sc["scenes"]):
            log.info("Voz e imágenes %d/%d", i + 1, len(sc["scenes"]))
            audio = workdir / f"scene_{i:03d}.mp3"
            dur, words = _cached_tts(cfg, scene["narration"], audio)
            photo = _scene_photo(cfg, workdir, i, scene, used_photos, size, accent) if use_photos else None
            if photo:
                kind, assets = "photo", photo[0]
                if photo[1] not in credits:
                    credits.append(photo[1])
            elif use_cards and scene.get("card"):
                kind = "card"
                assets = cards.card_frames(scene["card"], size, accent, workdir / f"card_{i:03d}", seed=i,
                                           transparent=animated)
                clip = _scene_footage(cfg, workdir, i, scene, dur, used) if use_footage else None
                if clip:
                    kind, assets = "footage", (clip, assets)
            else:
                kind = "stock"
                assets = media.fetch_scene_media(cfg, scene["visual_query"], scene["section"],
                                                 workdir / f"media_{i:03d}", dur, used)
            plan.append((scene, audio, dur, _align_words(words, scene["narration"]), kind, assets))
        total_video = sum(p[2] + video.SCENE_GAP for p in plan)

        # Pasada 2: render de cada escena
        bg_wide = workdir / "bg_wide.png"
        cards.wide_background(size, accent, seed=len(sc["title"])).save(bg_wide)
        segments, sub_scenes, starts, media_files = [], [], [], []
        offset = 0.0
        for i, (scene, audio, dur, words, kind, assets) in enumerate(plan):
            log.info("Escena %d/%d (%s)", i + 1, len(plan), kind)
            seg = workdir / f"seg_{i:03d}.mp4"
            if animated and kind != "stock":
                total = video.render_segment(cfg, kind, assets, audio, dur, seg, offset, total_video, bg_wide, accent)
            else:
                total = video.render_scene(cfg, assets, audio, dur, seg, card=(kind == "card"))
            media_files.append(assets[-1] if isinstance(assets, list) else assets)
            segments.append(seg)
            sub_scenes.append({"offset": offset, "words": words})
            starts.append((offset, scene["section"]))
            offset += total

        music_track = None
        if cfg["video"].get("generated_music", True):
            from . import music
            music_track = workdir / "music.wav"
            if not music_track.exists():
                music.generate(offset + 1, music_track, seed=len(sc["title"]) * 7 + len(sc["scenes"]))
        subs = None
        if cfg["video"]["subtitles"]:
            subs = workdir / "subs.ass"
            video.build_ass(cfg, sub_scenes, subs)
        final = workdir / "video.mp4"
        log.info("Montando vídeo final (%.0f s)…", offset)
        video.assemble(cfg, workdir, segments, subs, final, music=music_track)

        thumb_photo = None
        if use_photos and sc.get("thumbnail_photo"):
            for j, scene in enumerate(sc["scenes"]):  # reutilizar si ya se descargó para una escena
                pj = workdir / f"photo_{j:03d}.json"
                if scene.get("photo") == sc["thumbnail_photo"] and pj.exists():
                    cached = json.loads(pj.read_text(encoding="utf-8"))
                    if cached.get("credit"):
                        raw = next((p for p in workdir.glob(f"photo_{j:03d}.*") if p.suffix in (".jpg", ".png")
                                    and not p.name.endswith("_frame.png")), None)
                        if raw:
                            thumb_photo = raw
                            break
        if use_photos and sc.get("thumbnail_photo") and not thumb_photo:
            try:
                found = media.wikimedia_photo(sc["thumbnail_photo"], workdir / "thumb_photo", set())
                if found:
                    thumb_photo = found[0]
                    if found[1] not in credits:
                        credits.append(found[1])
            except Exception as e:
                log.warning("Foto de miniatura no disponible: %s", e)
        thumb = thumbnail.make_thumbnail(cfg, (sc.get("thumbnail_text") or sc["title"]).strip(), "" if use_cards else sc["thumbnail_query"], workdir,
                                         [] if use_cards else media_files, icon=sc.get("thumbnail_icon", ""),
                                         photo=thumb_photo, badge=sc.get("thumbnail_badge", ""))

        chap = video.chapters(starts, offset) if cfg["video"]["format"] == "long" else ""
        desc = sc["description"].strip()
        if chap:
            desc += "\n\nCapítulos:\n" + chap
        sources = sc.get("sources") or re.findall(r"^- (https?://\S+)", dossier, flags=re.M)
        if sources:
            desc += "\n\nFuentes:\n" + "\n".join(sources[:10])
        if credits:
            lines = [f"- {c['title']} — {c['author'][:60]} ({c['license']})" for c in credits]
            block = "\n\nImágenes: Wikimedia Commons\n" + "\n".join(lines)
            if len(desc) + len(block) > 4700:
                block = block[: 4700 - len(desc)].rsplit("\n", 1)[0]
            desc += block
        sub = cfg["channel"].get("subscribe_url")
        if sub:
            desc = desc.replace("\n\n", f"\n\n🔔 Suscríbete: {sub}\n\n", 1) if "\n\n" in desc else desc + f"\n\n🔔 Suscríbete: {sub}"
        desc += "\n\n" + " ".join(sc["hashtags"][:3])
        meta = {**sc, "full_description": desc, "duration_s": offset, "image_credits": credits}
        _save(workdir / "metadata.json", meta)
        db.update_video(vid, status="rendered", duration_s=offset)

        for p in [*workdir.glob("seg_*.mp4"), *workdir.glob("seg_*.txt"), workdir / "joined.mp4",
                  *workdir.glob("card_*.png")]:
            p.unlink(missing_ok=True)
        log.info("Vídeo listo en %s (miniatura: %s)", workdir, thumb.name)
        return workdir
    except Exception as e:
        db.update_video(vid, status="failed")
        db.log("render_failed", workdir=str(workdir), error=str(e)[:500])
        raise


def upload_dir(cfg: dict, db, workdir: Path, publish_at: str | None = None) -> dict:
    meta = json.loads((workdir / "metadata.json").read_text(encoding="utf-8"))
    res = uploader.upload(cfg, workdir / "video.mp4", workdir / "thumbnail.jpg", meta, publish_at=publish_at)
    row = db.conn.execute("SELECT id FROM videos WHERE workdir=?", (str(workdir),)).fetchone()
    fields = dict(youtube_id=res["youtube_id"], publish_at=res["publish_at"], status="uploaded", title=meta["title"])
    if row:
        db.update_video(row["id"], **fields)
    else:
        db.update_video(db.add_video(meta["title"], str(workdir)), **fields)
    db.log("uploaded", **res)
    return res
