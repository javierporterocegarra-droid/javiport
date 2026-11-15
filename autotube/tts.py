"""Voz en off (edge-tts, Kokoro local o ElevenLabs) + tiempos de subtítulos."""

import asyncio
import json
import re
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


KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
_kokoro = None


def _kokoro_model(cfg: dict):
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro

        mdir = Path(cfg["tts"].get("kokoro_dir", "models"))
        if not mdir.is_absolute():
            mdir = Path(__file__).resolve().parent.parent / mdir
        mdir.mkdir(parents=True, exist_ok=True)
        files = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
        for name in files:
            if not (mdir / name).exists():
                r = requests.get(KOKORO_URL + name, timeout=600)
                r.raise_for_status()
                (mdir / name).write_bytes(r.content)
        _kokoro = Kokoro(str(mdir / files[0]), str(mdir / files[1]))
    return _kokoro


def _kokoro_tts(cfg: dict, text: str, out: Path) -> None:
    import soundfile as sf

    tts = cfg["tts"]
    samples, sr = _kokoro_model(cfg).create(
        text, voice=tts.get("kokoro_voice", "em_alex"), speed=float(tts.get("kokoro_speed", 1.0)), lang="es")
    wav = out.with_suffix(".wav")
    sf.write(wav, samples, sr)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "192k", str(out)], check=True)
    wav.unlink()


def spoken(cfg: dict, text: str) -> str:
    """Aplica el diccionario de pronunciación (solo al audio, no a los subtítulos)."""
    for word, say in sorted(cfg["tts"].get("pronunciations", {}).items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", say, text)
    return text


def synthesize(cfg: dict, text: str, out: Path) -> tuple[float, list[dict]]:
    """Genera el audio de una escena. Devuelve (duración, palabras con tiempos)."""
    tts = cfg["tts"]
    words: list[dict] = []
    say = spoken(cfg, text)
    if tts["engine"] == "elevenlabs":
        _elevenlabs(say, tts["elevenlabs_voice_id"], out)
    elif tts["engine"] == "kokoro":
        _kokoro_tts(cfg, say, out)
    else:
        words = asyncio.run(_edge(say, tts["voice"], tts.get("rate", "+0%"), out))
        if say != text:
            words = []  # los tiempos de palabra no coinciden con el texto mostrado
    duration = audio_duration(out)
    if not words:
        words = _even_words(text, duration)
    return duration, words
