"""CLI de AutoTube.

  python -m autotube auth                 # conectar tu canal de YouTube (una sola vez)
  python -m autotube trends               # ver qué tema elegiría ahora
  python -m autotube create [--topic X] [--no-upload]
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
    u = sub.add_parser("upload")
    u.add_argument("workdir")
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
