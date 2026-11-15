"""Montaje del vídeo con ffmpeg: escenas + voz + subtítulos + música."""

import logging
import random
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)
SCENE_GAP = 0.25  # pausa entre escenas (s)


def run(cmd: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg falló:\n{' '.join(cmd)}\n{proc.stderr[-3000:]}")


def dims(cfg: dict) -> tuple[int, int]:
    return (1080, 1920) if cfg["video"]["format"] == "short" else (1920, 1080)


def render_scene(cfg: dict, media: Path, audio: Path, duration: float, out: Path) -> float:
    w, h = dims(cfg)
    fps = cfg["video"]["fps"]
    total = duration + SCENE_GAP
    frames = int(total * fps) + 1
    if media.suffix.lower() == ".mp4":
        vin = ["-stream_loop", "-1", "-i", str(media)]
        vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps}"
    else:  # imagen fija con efecto Ken Burns
        vin = ["-loop", "1", "-framerate", str(fps), "-i", str(media)]
        direction = random.choice(["iw/2-(iw/zoom/2)", "0", "iw-iw/zoom"])
        vf = (f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
              f"zoompan=z='1+0.18*on/{frames}':d=1:x='{direction}':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}")
    run([
        "ffmpeg", "-y", *vin, "-i", str(audio),
        "-filter_complex", f"[0:v]{vf},setsar=1,format=yuv420p[v];[1:a]aresample=48000,apad[a]",
        "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(fps),
        "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-ar", "48000", str(out),
    ])
    return total


def _ts(t: float) -> str:
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(cfg: dict, scenes: list[dict], out: Path) -> None:
    """scenes: [{'offset': float, 'words': [{'start','end','text'}]}]"""
    w, h = dims(cfg)
    short = cfg["video"]["format"] == "short"
    size = 88 if short else 62
    margin_v = int(h * 0.30) if short else 70
    max_words = 3 if short else 7
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Default,DejaVu Sans,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,60,60,{margin_v},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for sc in scenes:
        chunk: list[dict] = []
        for i, word in enumerate(sc["words"]):
            chunk.append(word)
            last = i == len(sc["words"]) - 1
            if last or len(chunk) >= max_words or word["text"][-1:] in ".,;:?!":
                start = sc["offset"] + chunk[0]["start"]
                end = sc["offset"] + chunk[-1]["end"] + (0.15 if last else 0)
                text = " ".join(c["text"] for c in chunk).replace("{", "").replace("}", "")
                if short:
                    text = text.upper()
                lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Default,,0,0,0,,{text}")
                chunk = []
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assemble(cfg: dict, workdir: Path, segments: list[Path], subs: Path | None, out: Path) -> None:
    concat_list = workdir / "segments.txt"
    concat_list.write_text("".join(f"file '{s.name}'\n" for s in segments), encoding="utf-8")
    joined = workdir / "joined.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list.name, "-c", "copy", joined.name], cwd=workdir)

    music_dir = Path(cfg["video"]["music_dir"])
    tracks = sorted(p for p in music_dir.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}) \
        if music_dir.exists() else []
    inputs = ["-i", joined.name]
    vchain = f"[0:v]subtitles={subs.name}[v]" if subs else "[0:v]null[v]"
    if tracks:
        inputs += ["-stream_loop", "-1", "-i", str(random.choice(tracks))]
        vol = cfg["video"].get("music_volume", 0.08)
        achain = (f"[1:a]volume={vol},aresample=48000[m];"
                  f"[0:a][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    else:
        achain = "[0:a]loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    run([
        "ffmpeg", "-y", *inputs, "-filter_complex", f"{vchain};{achain}",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(out.resolve()),
    ], cwd=workdir)


def chapters(scene_starts: list[tuple[float, str]], total: float) -> str:
    """Capítulos para la descripción (YouTube exige 0:00, >= 3 y >= 10 s cada uno)."""
    chaps: list[list] = []
    for start, section in scene_starts:
        if not chaps or chaps[-1][1] != section:
            chaps.append([start, section])
    merged: list[list] = []
    for i, (start, name) in enumerate(chaps):
        end = chaps[i + 1][0] if i + 1 < len(chaps) else total
        if merged and end - start < 10:
            continue  # se absorbe en el capítulo anterior
        merged.append([start, name])
    if len(merged) < 3:
        return ""
    merged[0][0] = 0
    fmt = lambda t: f"{int(t // 60)}:{int(t % 60):02d}"
    return "\n".join(f"{fmt(s)} {n}" for s, n in merged)
