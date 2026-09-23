"""Sample-accurate clip boundaries by aligning decoded waveforms.

Fingerprints locate a clip to roughly ±1 s because each chromaprint value
covers ~2.6 s of audio. Inserted ads are the same audio file in every episode,
so the waveforms themselves line up closely. Working at 8 kHz mono:

* ``measure_pair``: given the same clip roughly located in two files, align
  them and find where the waveforms stop agreeing. That is the clip's true
  extent. It runs once, when a clip is created.
* ``make_refs`` stores a few seconds of audio around each true edge.
* ``locate_edge``: in any other episode, find the stored edge audio near the
  fingerprint estimate (normalised cross-correlation) and read off the exact
  edge. It runs for every occurrence.

Anything that doesn't align confidently returns None, and the caller keeps the
fingerprint estimate.
"""

import subprocess

import numpy as np

from .fingerprint import nice_prefix

SR = 8000
EDGE_CONTEXT = 3.0      # seconds of audio kept either side of each edge
INNER = 2.0             # seconds of clip audio used to find an edge
SEARCH = 2.5            # how far from the fingerprint estimate to look
MIN_PEAK = 0.6          # normalised correlation needed to trust an alignment
WINDOW = SR // 20       # 50 ms windows when measuring where two files diverge
AGREE = 0.85            # window correlation that counts as "same audio"
SILENCE = 60.0          # peak amplitude (of 32767) treated as silence
MAX_DROPOUT = 4         # disagreeing windows (200 ms) tolerated inside a clip
MIN_KEEP = 0.75         # a refined clip may not shrink below this share of its fingerprint length


def decode(path, start, duration, nice=0):
    """Mono float32 PCM at 8 kHz for [start, start + duration). Returns (pcm, actual_start)."""
    start = max(0.0, start)
    cmd = nice_prefix(nice) + ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}",
                               "-i", str(path), "-vn", "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"]
    out = subprocess.run(cmd, capture_output=True, timeout=120, check=False).stdout
    return np.frombuffer(out[: len(out) - len(out) % 2], "<i2").astype(np.float32), start


def ncc(template, signal):
    """Normalised cross-correlation of ``template`` at every offset in ``signal``."""
    n, m = len(template), len(signal)
    if n == 0 or m < n:
        return np.empty(0)
    t = template - template.mean()
    t_norm = np.sqrt(t @ t)
    if t_norm < 1e-3:
        return np.zeros(m - n + 1)
    size = 1 << int(np.ceil(np.log2(n + m)))
    raw = np.fft.irfft(np.fft.rfft(signal, size) * np.conj(np.fft.rfft(t, size)), size)[: m - n + 1]
    c1 = np.concatenate(([0.0], np.cumsum(signal, dtype=np.float64)))
    c2 = np.concatenate(([0.0], np.cumsum(signal.astype(np.float64) ** 2)))
    s1 = c1[n:] - c1[:-n]
    s2 = c2[n:] - c2[:-n]
    var = np.maximum(s2 - s1 * s1 / n, 1e-9)
    return raw / (t_norm * np.sqrt(var))


def _agreeing_run(a, b, lag, anchor):
    """Longest run of 50 ms windows where a[i] ~ b[i + lag] that contains ``anchor`` (index in a)."""
    lo, hi = max(0, -lag), min(len(a), len(b) - lag)
    starts = np.arange(lo, hi - WINDOW + 1, WINDOW)
    if len(starts) == 0:
        return None
    good = np.zeros(len(starts), bool)
    for k, i in enumerate(starts):
        x, y = a[i:i + WINDOW], b[i + lag:i + lag + WINDOW]
        if np.abs(x).max() < SILENCE and np.abs(y).max() < SILENCE:
            good[k] = True
            continue
        x = x - x.mean()
        y = y - y.mean()
        den = np.sqrt((x @ x) * (y @ y))
        good[k] = den > 0 and (x @ y) / den > AGREE
    k0 = int(np.clip((anchor - lo) // WINDOW, 0, len(starts) - 1))
    if not good[k0]:
        return None
    k1 = k0
    # Grow outwards, stepping over short dropouts (a codec glitch, a click)
    # as long as agreement resumes right after.
    while True:
        nxt = next((j for j in range(k0 - 1, max(-1, k0 - 2 - MAX_DROPOUT), -1) if good[j]), None)
        if nxt is None:
            break
        k0 = nxt
    while True:
        nxt = next((j for j in range(k1 + 1, min(len(good), k1 + 2 + MAX_DROPOUT)) if good[j]), None)
        if nxt is None:
            break
        k1 = nxt
    return starts[k0], starts[k1] + WINDOW


def measure_pair(path_a, start_a, end_a, path_b, start_b, end_b, nice=0, pad=4.0):
    """True extent (start, end) in file a of a clip roughly at [start_a, end_a] and [start_b, end_b]."""
    dur = end_a - start_a
    if dur < 2 * INNER:
        return None
    a, a0 = decode(path_a, start_a - pad, dur + 2 * pad, nice)
    b, _ = decode(path_b, start_b - pad - SEARCH, (end_b - start_b) + 2 * (pad + SEARCH), nice)
    # Align on a chunk from the middle of the clip, which is safely inside it.
    mid = int((start_a + dur / 2 - a0) * SR)
    half = int(min(4.0, dur / 2 - 0.5) * SR)
    template = a[mid - half: mid + half]
    corr = ncc(template, b)
    if len(corr) == 0 or corr.max() < MIN_PEAK:
        return None
    lag = int(np.argmax(corr)) - (mid - half)        # b[i + lag] ~ a[i]
    run = _agreeing_run(a, b, lag, mid)
    if run is None:
        return None
    start, end = a0 + run[0] / SR, a0 + run[1] / SR
    if abs(start - start_a) > pad - 0.25 or abs(end - end_a) > pad - 0.25:
        return None  # ran into the edge of what we decoded: not a clean clip boundary
    if end - start < MIN_KEEP * dur:
        return None  # only part of it lines up (e.g. a different cut of the same promo)
    return round(start, 3), round(end, 3)


def make_refs(path, start, end, nice=0):
    """Audio either side of both edges, for ``locate_edge``. Saved with ``np.savez``."""
    s_pcm, s0 = decode(path, start - EDGE_CONTEXT, 2 * EDGE_CONTEXT, nice)
    e_pcm, e0 = decode(path, end - EDGE_CONTEXT, 2 * EDGE_CONTEXT, nice)
    return {
        "start_pcm": s_pcm.astype(np.int16), "start_at": np.float64(start - s0),
        "end_pcm": e_pcm.astype(np.int16), "end_at": np.float64(end - e0),
    }


def locate_edge(path, estimate, refs, which, nice=0):
    """Exact time of a clip's ``which`` ('start' or 'end') edge near ``estimate`` in ``path``."""
    pcm = refs[f"{which}_pcm"].astype(np.float32)
    at = int(float(refs[f"{which}_at"]) * SR)
    inner_n = int(INNER * SR)
    # The clip-side audio next to the edge is what every copy has in common.
    template = pcm[at: at + inner_n] if which == "start" else pcm[max(0, at - inner_n): at]
    if len(template) < SR // 2:
        return None
    sig, t0 = decode(path, estimate - SEARCH - INNER, 2 * (SEARCH + INNER), nice)
    corr = ncc(template, sig)
    if len(corr) == 0 or corr.max() < MIN_PEAK:
        return None
    pos = int(np.argmax(corr))
    edge = t0 + (pos if which == "start" else pos + len(template)) / SR
    return round(edge, 3) if abs(edge - estimate) <= SEARCH else None
