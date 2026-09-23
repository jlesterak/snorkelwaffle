"""Synthetic podcast episodes for tests: unique "content" plus shared "ads".

Each segment is a seeded random melody (harmonic notes with envelopes plus a
little noise), which gives chromaprint the pitch variety real audio has.
"""

import subprocess
import wave

import numpy as np

RATE = 22050


def segment(seed, seconds):
    rng = np.random.default_rng(seed)
    out = np.zeros(int(seconds * RATE), dtype=np.float64)
    pos = 0
    while pos < len(out):
        dur = int(rng.uniform(0.08, 0.45) * RATE)
        n = min(dur, len(out) - pos)
        t = np.arange(n) / RATE
        f0 = 440.0 * 2 ** ((rng.integers(40, 80) - 69) / 12)
        tone = sum(np.sin(2 * np.pi * f0 * h * t) / h for h in (1, 2, 3))
        env = np.minimum(1, np.minimum(t / 0.01, (n / RATE - t) / 0.03 + 1e-9))
        out[pos:pos + n] += 0.25 * tone * env
        pos += dur
    out += 0.01 * rng.standard_normal(len(out))
    return out


def write_mp3(path, pieces, bitrate="96k", lead_in=0.0):
    """Concatenate (seed, seconds) pieces and encode to mp3 at ``path``.

    Returns a list of (seed, start_s, end_s) for each piece as placed.
    """
    audio = [np.zeros(int(lead_in * RATE))]
    layout = []
    t = lead_in
    for seed, secs in pieces:
        audio.append(segment(seed, secs))
        layout.append((seed, t, t + secs))
        t += secs
    pcm = np.clip(np.concatenate(audio), -1, 1)
    wav = str(path) + ".wav"
    with wave.open(wav, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((pcm * 32000).astype("<i2").tobytes())
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", wav,
                    "-c:a", "libmp3lame", "-b:a", bitrate, str(path)], check=True)
    subprocess.run(["rm", "-f", wav], check=True)
    return layout
