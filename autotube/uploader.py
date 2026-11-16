"""Subida de vídeos, miniaturas, playlists y comentario del canal."""

import logging
import random
import time
from datetime import datetime, timedelta, timezone

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from .youtube_api import youtube_oauth

log = logging.getLogger(__name__)
RETRY_STATUS = {500, 502, 503, 504}


def _clean(s: str) -> str:
    return s.replace("<", "").replace(">", "")


def _tags(tags: list[str]) -> list[str]:
    out, total = [], 0
    for t in tags:
        t = _clean(t).strip().strip("#")
        cost = len(t) + (2 if " " in t else 0) + 1
        if t and total + cost <= 480:
            out.append(t)
            total += cost
    return out


def upload(cfg: dict, video_path, thumb_path, meta: dict, publish_at: str | None = None) -> dict:
    """publish_at: fecha ISO 8601 en UTC (p. ej. 2026-11-16T16:00:00Z) para programar la publicación."""
    up = cfg["upload"]
    yt = youtube_oauth(cfg)
    status = {
        "privacyStatus": up["privacy"],
        "selfDeclaredMadeForKids": up["made_for_kids"],
        "containsSyntheticMedia": up.get("contains_synthetic_media", True),
    }
    if publish_at:
        status.update(privacyStatus="private", publishAt=publish_at)
    elif up.get("schedule_hours_ahead", 0) > 0:
        publish_at = (datetime.now(timezone.utc) + timedelta(hours=up["schedule_hours_ahead"])) \
            .replace(microsecond=0).isoformat().replace("+00:00", "Z")
        status.update(privacyStatus="private", publishAt=publish_at)

    title = _clean(meta["title"])[:100]
    if cfg["video"]["format"] == "short" and "#shorts" not in title.lower() and len(title) < 92:
        title += " #shorts"
    body = {
        "snippet": {
            "title": title,
            "description": _clean(meta["full_description"])[:4900],
            "tags": _tags(meta["tags"]),
            "categoryId": up["category_id"],
            "defaultLanguage": cfg["channel"]["language"],
            "defaultAudioLanguage": cfg["channel"]["language"],
        },
        "status": status,
    }
    request = yt.videos().insert(
        part="snippet,status", body=body,
        media_body=MediaFileUpload(str(video_path), chunksize=16 * 1024 * 1024, resumable=True,
                                   mimetype="video/mp4"),
    )
    response, retries = None, 0
    while response is None:
        try:
            progress, response = request.next_chunk()
            if progress:
                log.info("Subiendo… %d%%", int(progress.progress() * 100))
        except HttpError as e:
            if e.resp.status not in RETRY_STATUS or retries >= 8:
                raise
            retries += 1
            time.sleep(min(60, 2 ** retries + random.random()))
    video_id = response["id"]
    log.info("Vídeo subido: https://youtu.be/%s", video_id)

    try:
        yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb_path))).execute()
    except HttpError as e:
        log.warning("No se pudo poner la miniatura (¿canal verificado por teléfono?): %s", e)

    if up.get("playlist_id"):
        try:
            yt.playlistItems().insert(part="snippet", body={"snippet": {
                "playlistId": up["playlist_id"],
                "resourceId": {"kind": "youtube#video", "videoId": video_id}}}).execute()
        except HttpError as e:
            log.warning("No se pudo añadir a la playlist: %s", e)

    if up.get("post_comment") and meta.get("pinned_comment"):
        try:
            yt.commentThreads().insert(part="snippet", body={"snippet": {
                "videoId": video_id,
                "topLevelComment": {"snippet": {"textOriginal": meta["pinned_comment"]}}}}).execute()
        except HttpError as e:
            log.warning("No se pudo publicar el comentario (normal si el vídeo aún es privado): %s", e)

    return {"youtube_id": video_id, "publish_at": publish_at}
