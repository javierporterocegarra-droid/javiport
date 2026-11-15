"""CLI de AutoTube.

  python -m autotube auth                 # conectar tu canal de YouTube (una sola vez)
  python -m autotube trends               # ver qué tema elegiría ahora
  python -m autotube create [--topic X] [--no-upload]
  python -m autotube render output/<carpeta>  # vídeo a partir de un script.json (escrito o editado a mano)
  python -m autotube upload output/<carpeta>
  python -m autotube manage               # estadísticas + responder comentarios
  python -m autotube report               # informe de aprendizajes (alimenta la elección de temas)
  python -m autotube autopilot            # todo: gestionar, crear y subir
"""

import argparse
import logging
import sys
from pathlib import Path

from .config import load_config


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="autotube", description="Canal de YouTube automatizado")
    p.add_argument("--config", default=None, help="ruta a config.yaml")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth")
    sub.add_parser("trends")
    c = sub.add_parser("create")
    c.add_argument("--topic")
    c.add_argument("--no-upload", action="store_true")
    r = sub.add_parser("render", help="renderiza un vídeo a partir de output/<carpeta>/script.json")
    r.add_argument("workdir")
    u = sub.add_parser("upload")
    u.add_argument("workdir")
    sc = sub.add_parser("schedule", help="sube varios vídeos y programa uno al día")
    sc.add_argument("workdirs", nargs="+")
    sc.add_argument("--start", required=True, help="fecha del primero, AAAA-MM-DD")
    sc.add_argument("--time", default="17:00", help="hora local de publicación, HH:MM")
    sc.add_argument("--tz", default="Europe/Madrid", help="zona horaria")
    sc.add_argument("--every-days", type=int, default=1)
    pr = sub.add_parser("produce", help="renderiza guiones (videos/NN-*) y los sube programados, uno por día")
    pr.add_argument("scripts", nargs="+", help="carpetas con script.json")
    pr.add_argument("--start", required=True, help="fecha de publicación del primero, AAAA-MM-DD")
    pr.add_argument("--time", default="17:00")
    pr.add_argument("--tz", default="Europe/Madrid")
    pr.add_argument("--no-upload", action="store_true")
    pr.add_argument("--reuse", action="store_true", help="no volver a renderizar si ya existe el vídeo")
    sub.add_parser("manage")
    sub.add_parser("report")
    a = sub.add_parser("autopilot")
    a.add_argument("--videos", type=int, default=1)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("googleapiclient", "httpx", "httpx2", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    cfg = load_config(args.config) if args.config else load_config()

    from .db import DB
    db = DB(cfg["paths"]["database"])

    if args.cmd == "auth":
        from .youtube_api import get_credentials, youtube_oauth
        get_credentials(cfg, interactive=True)
        ch = youtube_oauth(cfg).channels().list(part="snippet", mine=True).execute()["items"][0]
        print(f"Conectado al canal: {ch['snippet']['title']}")
        return 0

    if args.cmd == "render":
        import json
        from . import pipeline
        wd = Path(args.workdir)
        sc = json.loads((wd / "script.json").read_text(encoding="utf-8"))
        dossier = (wd / "research.md").read_text(encoding="utf-8") if (wd / "research.md").exists() else ""
        pipeline.render_from_script(cfg, db, wd, sc, dossier)
        print(f"Vídeo listo: {wd / 'video.mp4'}")
        return 0

    from .llm import LLM
    llm = LLM(cfg)

    if args.cmd == "trends":
        from .trends import pick_topic
        t = pick_topic(cfg, llm, db)
        print(f"\nTema: {t['topic']}\nEnfoque: {t['angle']}\nTítulo: {t['working_title']}\nPor qué: {t['why']}")
        return 0

    from . import manager, pipeline

    if args.cmd == "create":
        wd = pipeline.create_video(cfg, llm, db, args.topic)
        if cfg["upload"]["enabled"] and not args.no_upload:
            res = pipeline.upload_dir(cfg, db, wd)
            print(f"Subido: https://youtu.be/{res['youtube_id']}")
        else:
            print(f"Vídeo generado (sin subir): {wd}")
        return 0
    if args.cmd == "upload":
        res = pipeline.upload_dir(cfg, db, Path(args.workdir))
        print(f"Subido: https://youtu.be/{res['youtube_id']}")
        return 0
    if args.cmd == "schedule":
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo
        first = datetime.fromisoformat(f"{args.start}T{args.time}").replace(tzinfo=ZoneInfo(args.tz))
        for k, wd in enumerate(args.workdirs):
            when = (first + timedelta(days=k * args.every_days)).astimezone(timezone.utc)
            iso = when.strftime("%Y-%m-%dT%H:%M:%SZ")
            res = pipeline.upload_dir(cfg, db, Path(wd), publish_at=iso)
            local = when.astimezone(ZoneInfo(args.tz)).strftime("%d/%m/%Y %H:%M")
            print(f"{local} ({args.tz}) -> https://youtu.be/{res['youtube_id']}  [{Path(wd).name}]", flush=True)
        return 0
    if args.cmd == "produce":
        import json as _json
        import shutil
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo
        from googleapiclient.errors import HttpError
        first = datetime.fromisoformat(f"{args.start}T{args.time}").replace(tzinfo=ZoneInfo(args.tz))
        upload_ok = not args.no_upload
        for k, src in enumerate(args.scripts):
            src = Path(src)
            wd = Path(cfg["paths"]["output"]) / src.name
            wd.mkdir(parents=True, exist_ok=True)
            shutil.copy(src / "script.json", wd / "script.json")
            sc = _json.loads((wd / "script.json").read_text(encoding="utf-8"))
            if (wd / "uploaded.json").exists():
                print(f"[{src.name}] ya subido, se omite", flush=True)
                continue
            try:
                if not (args.reuse and (wd / "video.mp4").exists() and (wd / "metadata.json").exists()):
                    pipeline.render_from_script(cfg, db, wd, sc)
            except Exception as e:
                print(f"[{src.name}] ERROR al renderizar: {e}", flush=True)
                continue
            for f in ("metadata.json", "thumbnail.jpg"):
                shutil.copy(wd / f, src / f)
            when = (first + timedelta(days=k)).astimezone(timezone.utc)
            if not upload_ok:
                print(f"[{src.name}] renderizado (sin subir)", flush=True)
                continue
            try:
                res = pipeline.upload_dir(cfg, db, wd, publish_at=when.strftime("%Y-%m-%dT%H:%M:%SZ"))
            except HttpError as e:
                if "quota" in str(e).lower():
                    upload_ok = False
                    print(f"[{src.name}] CUOTA AGOTADA: se sigue renderizando y se suben más tarde", flush=True)
                    continue
                print(f"[{src.name}] ERROR al subir: {e}", flush=True)
                continue
            info = {**res, "publish_local": when.astimezone(ZoneInfo(args.tz)).strftime("%Y-%m-%d %H:%M"),
                    "title": sc["title"]}
            (wd / "uploaded.json").write_text(_json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
            shutil.copy(wd / "uploaded.json", src / "uploaded.json")
            print(f"[{src.name}] SUBIDO https://youtu.be/{res['youtube_id']} -> se publica {info['publish_local']} ({args.tz})", flush=True)
        return 0
    if args.cmd == "manage":
        manager.sync_stats(cfg, db)
        n = manager.handle_comments(cfg, db, llm)
        print(f"Estadísticas sincronizadas. Comentarios respondidos: {n}")
        return 0
    if args.cmd == "report":
        manager.sync_stats(cfg, db)
        print(manager.performance_report(cfg, db, llm))
        return 0
    if args.cmd == "autopilot":
        log = logging.getLogger("autopilot")
        try:
            manager.sync_stats(cfg, db)
            manager.handle_comments(cfg, db, llm)
            if len(db.videos("public")) + len(db.videos("uploaded")) >= 3:
                manager.performance_report(cfg, db, llm)
        except Exception as e:  # la gestión no debe bloquear la creación
            log.warning("Gestión del canal con errores: %s", e)
        for _ in range(args.videos):
            wd = pipeline.create_video(cfg, llm, db)
            if cfg["upload"]["enabled"]:
                res = pipeline.upload_dir(cfg, db, wd)
                print(f"Subido: https://youtu.be/{res['youtube_id']}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
