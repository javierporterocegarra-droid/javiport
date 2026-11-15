"""Voz en off (edge-tts gratis o ElevenLabs) + tiempos de subtítulos."""

import asyncio
import json
import subprocess
from pathlib import Path

import requests

from .config import env


def audio_duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


async def _edge(text: str, voice: str, rate: str, out: Path) -> list[dict]:
    import edge_tts

    comm = edge_tts.Communicate(text, voice, rate=rate, boundary="WordBoundary")
    words = []
    with open(out, "wb") as f:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                f.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7
                words.append({"start": start, "end": start + chunk["duration"] / 1e7, "text": chunk["text"]})
    return words


def _elevenlabs(text: str, voice_id: str, out: Path) -> None:
    r = requests.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": env("ELEVENLABS_API_KEY", required=True)},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
        timeout=300,
    )
    r.raise_for_status()
    out.write_bytes(r.content)


def _even_words(text: str, duration: float) -> list[dict]:
    """Reparte las palabras en el tiempo proporcionalmente a su longitud."""
    tokens = text.split()
    total = sum(len(t) + 1 for t in tokens) or 1
    t, words = 0.0, []
    for tok in tokens:
        d = duration * (len(tok) + 1) / total
        words.append({"start": t, "end": t + d, "text": tok})
        t += d
    return words


def synthesize(cfg: dict, text: str, out: Path) -> tuple[float, list[dict]]:
    """Genera el audio de una escena. Devuelve (duración, palabras con tiempos)."""
    tts = cfg["tts"]
    words: list[dict] = []
    if tts["engine"] == "elevenlabs":
        _elevenlabs(text, tts["elevenlabs_voice_id"], out)
    else:
        words = asyncio.run(_edge(text, tts["voice"], tts.get("rate", "+0%"), out))
    duration = audio_duration(out)
    if not words:
        words = _even_words(text, duration)
    return duration, words
