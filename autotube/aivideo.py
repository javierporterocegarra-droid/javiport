"""Clips de vídeo generados con IA (Google Veo, API de Gemini) para recrear escenas.

Reglas del canal (también en docs/GUIA_CONTENIDO.md):
- Solo personas INVENTADAS y genéricas («una ingeniera en una oficina de 1997»). Nunca personas reales,
  famosos ni marcas reconocibles: YouTube lo considera contenido engañoso.
- Todo vídeo con clips de IA se sube con `containsSyntheticMedia: true` (ya activado en config.yaml).
- Presupuesto limitado: `ai_video.max_clips_per_video` clips de `ai_video.seconds` segundos como mucho.

La clave se lee de GEMINI_API_KEY (GitHub Actions). En las sesiones de Claude la inyecta el proxy, así que
basta con GEMINI_API_KEY=proxy-injected.
"""

import logging
import time
from pathlib import Path

import requests

from .config import env

log = logging.getLogger(__name__)
API = "https://generativelanguage.googleapis.com/v1beta"
SAFE_SUFFIX = (" Fictional anonymous people only, no celebrities, no real public figures, no logos or brand names, "
               "no text on screen. Cinematic, realistic, natural lighting.")


def _headers() -> dict | None:
    key = env("GEMINI_API_KEY")
    return {"x-goog-api-key": key} if key else None


def pick_model(cfg: dict) -> str | None:
    """Modelo de vídeo a usar: el de config.yaml o, si no está, el primero de vídeo disponible (prefiere los baratos)."""
    want = (cfg.get("ai_video") or {}).get("model")
    if want:
        return want
    h = _headers()
    if not h:
        return None
    r = requests.get(f"{API}/models", headers=h, params={"pageSize": 200}, timeout=30)
    r.raise_for_status()
    names = [m["name"] for m in r.json().get("models", [])
             if "predictLongRunning" in m.get("supportedGenerationMethods", []) and "veo" in m["name"]]
    if not names:
        return None
    for pref in ("lite", "fast"):
        for n in names:
            if pref in n:
                return n.split("/")[-1]
    return names[0].split("/")[-1]


def generate_clip(cfg: dict, prompt: str, out: Path, vertical: bool) -> Path | None:
    """Genera un clip y lo guarda en `out` (mp4). Devuelve None si no hay clave o algo falla."""
    if out.exists() and out.stat().st_size > 0:
        return out
    h = _headers()
    conf = cfg.get("ai_video") or {}
    if not h or not conf.get("enabled", False):
        return None
    model = pick_model(cfg)
    if not model:
        log.warning("No hay ningún modelo de vídeo Veo disponible en esta cuenta")
        return None
    body = {
        "instances": [{"prompt": prompt.strip() + SAFE_SUFFIX}],
        "parameters": {
            "aspectRatio": "9:16" if vertical else "16:9",
            "durationSeconds": int(conf.get("seconds", 6)),
            "negativePrompt": "celebrity, famous person, logo, brand, text, watermark, cartoon",
            "personGeneration": "allow_all",
        },
    }
    r = requests.post(f"{API}/models/{model}:predictLongRunning", headers=h, json=body, timeout=60)
    if r.status_code == 400 and "durationSeconds" in r.text:  # algunos modelos no aceptan duración
        body["parameters"].pop("durationSeconds")
        r = requests.post(f"{API}/models/{model}:predictLongRunning", headers=h, json=body, timeout=60)
    r.raise_for_status()
    op = r.json()["name"]
    deadline = time.time() + 600
    while time.time() < deadline:
        time.sleep(10)
        st = requests.get(f"{API}/{op}", headers=h, timeout=30)
        st.raise_for_status()
        data = st.json()
        if data.get("done"):
            if "error" in data:
                raise RuntimeError(data["error"])
            resp = data.get("response", {})
            samples = (resp.get("generateVideoResponse", {}).get("generatedSamples")
                       or resp.get("generatedVideos") or [])
            if not samples:
                log.warning("Veo no devolvió vídeo (posible filtro de seguridad): %s", str(resp)[:300])
                return None
            uri = samples[0].get("video", {}).get("uri")
            v = requests.get(uri, headers=h, timeout=300, allow_redirects=True)
            v.raise_for_status()
            out.write_bytes(v.content)
            log.info("Clip de IA generado con %s (%s)", model, out.name)
            return out
    log.warning("Veo tardó demasiado; se sigue sin el clip")
    return None
