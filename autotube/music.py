"""Música ambiental generada por código (sin derechos de autor) para usar de fondo.

Pad suave con progresión de acordes, bajo y pequeñas notas de campana, con reverberación sintética.
"""

import random
import wave
from pathlib import Path

import numpy as np

SR = 44100
A4 = 440.0
NOTE = {"C": -9, "C#": -8, "D": -7, "Eb": -6, "E": -5, "F": -4, "F#": -3, "G": -2, "Ab": -1, "A": 0, "Bb": 1, "B": 2}

# progresiones "documental": (nombre de acorde, notas relativas a la raíz)
PROGRESSIONS = [
    [("A", "m"), ("F", ""), ("C", ""), ("G", "")],
    [("D", "m"), ("Bb", ""), ("F", ""), ("C", "")],
    [("E", "m"), ("C", ""), ("G", ""), ("D", "")],
    [("A", "m"), ("E", "m"), ("F", ""), ("C", "")],
    [("C", ""), ("A", "m"), ("F", ""), ("G", "")],
]


def _freq(name: str, octave: int) -> float:
    return A4 * 2 ** ((NOTE[name] + 12 * (octave - 4)) / 12)


def _chord(root: str, quality: str) -> list[float]:
    third = 3 if quality == "m" else 4
    base = NOTE[root]
    semis = [0, 7, 12, third + 12, 19]  # raíz, quinta, octava, tercera, quinta alta
    return [A4 * 2 ** ((base + s - 24) / 12) for s in semis]  # alrededor de la octava 2-3


def generate(duration: float, out: Path, seed: int = 0, chord_seconds: float = 8.0) -> Path:
    rnd = random.Random(seed)
    prog = rnd.choice(PROGRESSIONS)
    n = int((duration + 3) * SR)
    t = np.arange(n) / SR
    left = np.zeros(n)
    right = np.zeros(n)

    n_chords = int(np.ceil((duration + 3) / chord_seconds)) + 1
    fade = 2.5
    for i in range(n_chords):
        root, quality = prog[i % len(prog)]
        start = i * chord_seconds - fade
        a = max(0, int(start * SR))
        b = min(n, int((start + chord_seconds + 2 * fade) * SR))
        if a >= b:
            continue
        seg_t = t[a:b] - start
        env = np.clip(seg_t / fade, 0, 1) * np.clip((chord_seconds + 2 * fade - seg_t) / fade, 0, 1)
        env = env ** 1.5
        for j, f in enumerate(_chord(root, quality)):
            amp = 0.16 / (1 + 0.35 * j)
            for k, det in enumerate((-0.12, 0.0, 0.13)):  # voces desafinadas = coro suave
                wave_ = np.sin(2 * np.pi * (f + det) * seg_t + rnd.random() * 6.28)
                wave_ += 0.18 * np.sin(2 * np.pi * 2 * (f + det) * seg_t)
                pan = 0.5 + (k - 1) * 0.25
                left[a:b] += amp * env * wave_ * (1 - pan) / 3
                right[a:b] += amp * env * wave_ * pan / 3
        # bajo
        fb = _freq(root, 2)
        bass = 0.18 * env * np.sin(2 * np.pi * fb * seg_t)
        left[a:b] += bass
        right[a:b] += bass
        # campanitas: notas del acorde en la octava alta, con caída exponencial
        tones = _chord(root, quality)
        for _ in range(2):
            ts = start + fade + rnd.uniform(0.5, chord_seconds - 1)
            ca = int(ts * SR)
            cb = min(n, ca + int(3 * SR))
            if ca >= n or ca < 0:
                continue
            bt = t[ca:cb] - ts
            fbell = rnd.choice(tones) * 8
            bell = 0.05 * np.exp(-bt * 1.8) * np.sin(2 * np.pi * fbell * bt)
            p = rnd.random()
            left[ca:cb] += bell * (1 - p)
            right[ca:cb] += bell * p

    # reverberación: convolución con ruido que decae (distinto por canal = estéreo amplio)
    ir_len = int(2.8 * SR)
    ir_t = np.arange(ir_len) / SR
    rng = np.random.default_rng(seed)
    out_ch = []
    for ch in (left, right):
        ir = rng.standard_normal(ir_len) * np.exp(-ir_t * 2.2)
        ir[0] = 1.0
        size = 1 << int(np.ceil(np.log2(n + ir_len)))
        wet = np.fft.irfft(np.fft.rfft(ch, size) * np.fft.rfft(ir * 0.06, size), size)[:n]
        out_ch.append(0.65 * ch + 0.35 * wet)
    stereo = np.stack(out_ch, axis=1)[: int(duration * SR)]
    fade_n = int(3 * SR)
    stereo[:fade_n] *= np.linspace(0, 1, fade_n)[:, None]
    stereo[-fade_n:] *= np.linspace(1, 0, fade_n)[:, None]
    stereo /= max(1e-9, np.abs(stereo).max()) / 0.85
    pcm = (stereo * 32767).astype(np.int16)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return out
