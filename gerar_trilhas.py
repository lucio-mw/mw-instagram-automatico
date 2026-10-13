#!/usr/bin/env python3
"""Compõe trilhas instrumentais simples (livres de direitos) para os reels.

Uso: python3 gerar_trilhas.py <pasta-de-saída>

Cada trilha tem ~16s: pad de acordes + piano/rhodes em arpejo + baixo, com
reverb. Gera .m4a (AAC) via ffmpeg. Requer numpy.
"""

import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

SR = 44100
rng = np.random.default_rng(7)

NOTES = {n: i for i, n in enumerate("C C# D D# E F F# G G# A A# B".split())}


def freq(note):
    """'A4' -> 440 Hz; aceita sustenidos ('F#3')."""
    name, octave = note[:-1], int(note[-1])
    return 440.0 * 2 ** ((NOTES[name] - 9) / 12 + (octave - 4))


def envelope(n, attack, release):
    env = np.ones(n)
    a, r = int(attack * SR), int(release * SR)
    if a:
        env[:a] = np.linspace(0, 1, a)
    if r:
        env[-r:] *= np.linspace(1, 0, r)
    return env


def lowpass(x, cutoff):
    alpha = 1 - np.exp(-2 * np.pi * cutoff / SR)
    out = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):  # trilhas curtas: o loop é rápido o bastante
        acc += alpha * (v - acc)
        out[i] = acc
    return out


def pad(notes, dur, brightness=1200):
    t = np.arange(int(dur * SR)) / SR
    x = np.zeros_like(t)
    for note in notes:
        f = freq(note)
        for detune in (-0.12, 0.0, 0.12):
            ff = f * 2 ** (detune / 12)
            for h in range(1, 6):
                x += np.sin(2 * np.pi * ff * h * t + rng.uniform(0, 6.28)) / h ** 1.6
    x = lowpass(x, brightness)
    return x * envelope(len(t), dur * 0.35, dur * 0.35)


def piano(note, dur, decay=1.6, rhodes=False):
    t = np.arange(int(dur * SR)) / SR
    f = freq(note)
    partials = [(1, 1.0), (2, 0.45), (3, 0.18), (4, 0.08)] if not rhodes else [(1, 1.0), (2, 0.15), (7, 0.03)]
    x = sum(a * np.sin(2 * np.pi * f * k * t) * np.exp(-t * (1 / decay) * (1 + 0.6 * k)) for k, a in partials)
    if rhodes:
        x *= 1 + 0.25 * np.sin(2 * np.pi * 4.5 * t)  # tremolo
    return x * envelope(len(t), 0.004, 0.08)


def reverb(x, seconds=2.6, mix=0.32):
    n = int(seconds * SR)
    ir_t = np.arange(n) / SR
    out = []
    for ch in range(2):
        ir = rng.standard_normal(n) * np.exp(-ir_t * 6.5 / seconds)
        ir = lowpass(ir, 5000)
        ir /= np.sqrt(np.sum(ir ** 2))
        size = len(x) + n
        wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size)[: len(x)]
        out.append((1 - mix) * x + mix * wet * 3)
    return np.stack(out, axis=1)


def place(track, sound, start, gain=1.0):
    i = int(start * SR)
    end = min(len(track), i + len(sound))
    track[i:end] += sound[: end - i] * gain


def compose(chords, bass, bpm, arp, voice="piano", pad_gain=0.10, bars_per_chord=1, decay=1.6):
    beat = 60 / bpm
    bar = 4 * beat
    chord_dur = bar * bars_per_chord
    total = chord_dur * len(chords) + 2.5
    track = np.zeros(int(total * SR))
    for ci, (chord, root) in enumerate(zip(chords, bass)):
        t0 = ci * chord_dur
        place(track, pad(chord, chord_dur + 1.2), t0, pad_gain)
        place(track, piano(root, chord_dur + 1.0, decay=2.5), t0, 0.18)
        steps = int(chord_dur / (beat * arp[0]))
        for s in range(steps):
            note = arp[1](chord, s)
            place(track, piano(note, 2.5, decay=decay, rhodes=voice == "rhodes"), t0 + s * beat * arp[0], 0.30)
    stereo = reverb(track)
    stereo /= np.max(np.abs(stereo)) * 1.12
    fade = int(2.0 * SR)
    stereo[-fade:] *= np.linspace(1, 0, fade)[:, None]
    return stereo


def up(chord, s):
    return chord[s % len(chord)]


def updown(chord, s):
    seq = chord + chord[-2:0:-1]
    return seq[s % len(seq)]


def sparse(chord, s):
    return chord[(s * 2) % len(chord)]


TRACKS = {
    "01-elegante": dict(
        chords=[["C4", "E4", "G4", "B4"], ["A3", "C4", "E4", "G4"], ["F3", "A3", "C4", "E4"], ["G3", "B3", "D4", "E4"]],
        bass=["C2", "A1", "F1", "G1"], bpm=78, arp=(0.5, up)),
    "02-cinematico": dict(
        chords=[["D4", "F4", "A4"], ["A#3", "D4", "F4"], ["F3", "A3", "C4"], ["C4", "E4", "G4"]],
        bass=["D2", "A#1", "F1", "C2"], bpm=64, arp=(1, sparse), pad_gain=0.16, decay=2.4),
    "03-luxo-noturno": dict(
        chords=[["E4", "G4", "B4", "F#5"], ["C4", "E4", "G4", "B4"], ["A3", "C4", "E4", "B4"], ["B3", "E4", "F#4", "A4"]],
        bass=["E2", "C2", "A1", "B1"], bpm=72, arp=(0.5, updown), voice="rhodes"),
    "04-corporativo-leve": dict(
        chords=[["G4", "B4", "D5"], ["D4", "F#4", "A4"], ["E4", "G4", "B4"], ["C4", "E4", "G4"]],
        bass=["G1", "D2", "E2", "C2"], bpm=96, arp=(0.5, updown), pad_gain=0.08),
    "05-esperanca": dict(
        chords=[["F4", "A4", "C5"], ["E4", "G4", "C5"], ["D4", "F4", "A4"], ["A#3", "D4", "F4"]],
        bass=["F1", "E2", "D2", "A#1"], bpm=70, arp=(0.5, up), decay=2.0),
}


def save(stereo, path):
    pcm = (np.clip(stereo, -1, 1) * 32767).astype("<i2")
    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        with wave.open(tmp.name, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", tmp.name,
             "-af", "highpass=f=60,equalizer=f=3500:t=q:w=1:g=4", "-c:a", "aac", "-b:a", "192k", str(path)],
            check=True,
        )


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for name, spec in TRACKS.items():
        path = out / f"{name}.m4a"
        save(compose(**spec), path)
        print(f"{path}")


if __name__ == "__main__":
    main()
