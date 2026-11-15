import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Carga variables de un .env sencillo (KEY=VALUE) sin pisar las existentes."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def load_config(path: str | os.PathLike = ROOT / "config.yaml") -> dict:
    load_dotenv()
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for key, rel in cfg.get("paths", {}).items():
        p = Path(rel)
        cfg["paths"][key] = str(p if p.is_absolute() else ROOT / p)
    music = Path(cfg["video"].get("music_dir", "assets/music"))
    cfg["video"]["music_dir"] = str(music if music.is_absolute() else ROOT / music)
    return cfg


def env(name: str, required: bool = False) -> str | None:
    value = os.environ.get(name) or None
    if required and not value:
        raise SystemExit(f"Falta la variable de entorno {name} (ver .env.example)")
    return value
