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


def render_scene(cfg: dict, media: Path | list[Path], audio: Path, duration: float, out: Path,
                 card: bool = False) -> float:
    """media: un vídeo, una imagen o una lista de imágenes que se revelan en secuencia."""
    w, h = dims(cfg)
    fps = cfg["video"]["fps"]
    total = duration + SCENE_GAP
    frames = int(total * fps) + 1
    if isinstance(media, list) and len(media) == 1:
        media = media[0]
    if isinstance(media, list):  # tarjeta con elementos que aparecen uno a uno
        lead = min(1.2, total * 0.25)  # el primer estado se ve algo menos
        per = (total - lead) / len(media)
        lst = out.with_suffix(".txt")
        lines = [f"file '{p.resolve()}'\nduration {lead + per if i == 0 else per:.3f}\n" for i, p in enumerate(media)]
        lst.write_text("".join(lines) + f"file '{media[-1].resolve()}'\n", encoding="utf-8")
        vin = ["-f", "concat", "-safe", "0", "-i", str(lst)]
        vf = f"scale={w}:{h},fps={fps}"
    elif card:  # tarjeta fija: zoom suave y centrado para no recortar texto
        vin = ["-loop", "1", "-framerate", str(fps), "-i", str(media)]
        vf = (f"scale={w * 2}:{h * 2},zoompan=z='1+0.05*on/{frames}':d=1:x='iw/2-(iw/zoom/2)':"
              f"y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}")
    elif media.suffix.lower() == ".mp4":
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


def render_segment(cfg: dict, kind: str, assets, audio: Path, duration: float, out: Path,
                   offset: float, total_video: float, bg_wide: Path | None, accent: str) -> float:
    """Escena con fondo animado continuo, fundido de entrada y barra de progreso.

    kind: "card" (PNG transparentes sobre fondo en movimiento), "photo" (imagen compuesta con
    zoom lento) o "stock" (vídeo/imagen de archivo).
    """
    if kind == "stock":
        return render_scene(cfg, assets, audio, duration, out)
    w, h = dims(cfg)
    fps = cfg["video"]["fps"]
    total = duration + SCENE_GAP
    frames = int(total * fps) + 1
    off, tot = f"{offset:.3f}", f"{max(total_video, 1):.3f}"
    bar_h = max(4, h // 180)
    color = "0x" + accent.lstrip("#")
    footage = None
    if kind == "footage":  # vídeo real de fondo (b-roll) oscurecido + tarjeta transparente encima
        footage, assets = assets
        kind = "card"
    if kind == "card":
        assets = assets if isinstance(assets, list) else [assets]
        if len(assets) == 1:
            fg_in = ["-loop", "1", "-framerate", str(fps), "-i", str(assets[0])]
        else:
            lead = min(1.2, total * 0.25)
            per = (total - lead) / len(assets)
            lst = out.with_suffix(".txt")
            lst.write_text("".join(f"file '{p.resolve()}'\nduration {lead + per if i == 0 else per:.3f}\n"
                                   for i, p in enumerate(assets)) + f"file '{assets[-1].resolve()}'\n",
                           encoding="utf-8")
            fg_in = ["-f", "concat", "-safe", "0", "-i", str(lst)]
        if footage is not None:
            inputs = ["-stream_loop", "-1", "-i", str(footage), *fg_in]
            bg = (f"[0:v]scale={int(w * 1.08)}:{int(h * 1.08)}:force_original_aspect_ratio=increase,"
                  f"crop={int(w * 1.08)}:{int(h * 1.08)},fps={fps},"
                  f"crop={w}:{h}:x='(iw-ow)*t/{total:.3f}':y='(ih-oh)/2',"
                  f"eq=brightness=-0.10:saturation=0.85,colorlevels=romax=0.62:gomax=0.62:bomax=0.66,"
                  f"vignette=PI/4,fade=t=in:st=0:d=0.3[bg];")
        else:
            inputs = ["-loop", "1", "-framerate", str(fps), "-i", str(bg_wide), *fg_in]
            bg = (f"[0:v]crop={w}:{h}:x='(iw-ow)/2*(1+sin(({off}+t)/9))':y='(ih-oh)/2*(1+cos(({off}+t)/13))'[bg];")
        vgraph = (bg +
                  f"[1:v]fps={fps},format=rgba,fade=t=in:st=0:d=0.4:alpha=1[fg];"
                  f"[bg][fg]overlay=0:0[v1]")
    else:  # photo
        inputs = ["-loop", "1", "-framerate", str(fps), "-i", str(assets)]
        vgraph = (f"[0:v]scale={w * 2}:{h * 2},zoompan=z='1+0.07*on/{frames}':d=1:x='iw/2-(iw/zoom/2)':"
                  f"y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps},fade=t=in:st=0:d=0.35[v1]")
        fg_in = []
    n_v = 2 if kind == "card" else 1
    run([
        "ffmpeg", "-y", *inputs, "-i", str(audio),
        "-f", "lavfi", "-i", f"color=c={color}:s={w}x{bar_h}:r={fps}",
        "-filter_complex",
        f"{vgraph};[v1][{n_v + 1}:v]overlay=x='-w+W*({off}+t)/{tot}':y=0:eval=frame,setsar=1,format=yuv420p[v];"
        f"[{n_v}:a]aresample=48000,apad[a]",
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
    margin_v = int(h * 0.22) if short else 70
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


def assemble(cfg: dict, workdir: Path, segments: list[Path], subs: Path | None, out: Path,
             music: Path | None = None) -> None:
    concat_list = workdir / "segments.txt"
    concat_list.write_text("".join(f"file '{s.name}'\n" for s in segments), encoding="utf-8")
    joined = workdir / "joined.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list.name, "-c", "copy", joined.name], cwd=workdir)

    music_dir = Path(cfg["video"]["music_dir"])
    tracks = sorted(p for p in music_dir.glob("*") if p.suffix.lower() in {".mp3", ".wav", ".m4a", ".ogg"}) \
        if music_dir.exists() else []
    inputs = ["-i", joined.name]
    vchain = f"[0:v]subtitles={subs.name}[v]" if subs else "[0:v]null[v]"
    track = str(random.choice(tracks).resolve()) if tracks else (str(Path(music).resolve()) if music else None)
    if track:
        inputs += ["-stream_loop", "-1", "-i", track]
        vol = cfg["video"].get("music_volume", 0.08)
        # la música baja automáticamente cuando habla la voz (ducking)
        achain = (f"[0:a]asplit=2[voz][key];[1:a]volume={vol},aresample=48000[m0];"
                  f"[m0][key]sidechaincompress=threshold=0.02:ratio=5:attack=40:release=700[m];"
                  f"[voz][m]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
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
