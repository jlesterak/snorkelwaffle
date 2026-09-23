"""Audio fingerprinting via ffmpeg's built-in chromaprint muxer.

Chromaprint (algorithm 1, the default) resamples to 11025 Hz mono and emits one
32-bit sub-fingerprint per 1365-sample hop, i.e. ~8.08 values per second. Each
value summarises a window of audio ~2.6 s long, and a value whose window only
partly overlaps a matched span still tends to match. Measured against
synthetic episodes, raw item ranges start ~1 s early and end ~1.7 s short of
the window tail; the calibration constants below correct for both.
"""

import functools
import json
import os
import shutil
import subprocess

import numpy as np

SAMPLE_RATE = 11025
HOP = 1365
ITEM_SECONDS = HOP / SAMPLE_RATE  # ~0.1238 s per fingerprint value
# Boundary calibration (see module docstring; checked by tests/test_matcher.py).
START_BIAS_SECONDS = 0.95
END_TAIL_SECONDS = 0.85
ALGORITHM = 1


class FingerprintError(RuntimeError):
    pass


def nice_prefix(nice):
    """Command prefix that runs a child at low CPU (and, if available, idle IO) priority."""
    if not nice:
        return []
    prefix = ["nice", "-n", str(nice)]
    if shutil.which("ionice"):
        prefix += ["ionice", "-c", "3"]
    return prefix


@functools.lru_cache(maxsize=1)
def backend():
    """'ffmpeg' when ffmpeg has the chromaprint muxer, else 'fpcalc' (chromaprint's CLI).

    Both produce the same values (checked: 99.9% identical, mean 0.0006 bit
    difference). Override with SW_FP_BACKEND.
    """
    forced = os.environ.get("SW_FP_BACKEND", "").strip()
    if forced:
        return forced
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-muxers"], capture_output=True, timeout=20, check=False).stdout
        if b"chromaprint" in out:
            return "ffmpeg"
    except (OSError, subprocess.SubprocessError):
        pass
    if shutil.which("fpcalc"):
        return "fpcalc"
    raise FingerprintError("need ffmpeg built with chromaprint, or fpcalc")


def fingerprint_file(path, nice=10, timeout=1800):
    """Return the raw chromaprint fingerprint of ``path`` as a uint32 array."""
    if backend() == "fpcalc":
        # fpcalc numbers algorithms from 1, so ffmpeg's 1 (TEST2) is fpcalc's 2.
        cmd = ["fpcalc", "-raw", "-length", "0", "-algorithm", str(ALGORITHM + 1), str(path)]
    else:
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-vn", "-ac", "1",
               "-f", "chromaprint", "-algorithm", str(ALGORITHM), "-fp_format", "raw", "-"]
    try:
        proc = subprocess.run(nice_prefix(nice) + cmd, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise FingerprintError(f"timed out fingerprinting {path}") from exc
    if proc.returncode != 0:
        raise FingerprintError(proc.stderr.decode(errors="replace").strip()[-500:])
    if backend() == "fpcalc":
        for line in proc.stdout.decode().splitlines():
            if line.startswith("FINGERPRINT="):
                values = line[12:].strip()
                return np.array(values.split(",") if values else [], dtype=np.uint64).astype(np.uint32)
        raise FingerprintError("fpcalc returned no fingerprint")
    data = proc.stdout
    return np.frombuffer(data[: len(data) - len(data) % 4], dtype="<u4").astype(np.uint32)


def probe(path, timeout=60):
    """Return ffprobe's format/streams/chapters JSON for ``path``."""
    cmd = ["ffprobe", "-v", "error", "-print_format", "json", "-show_format",
           "-show_streams", "-show_chapters", str(path)]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise FingerprintError(proc.stderr.decode(errors="replace").strip()[-500:])
    return json.loads(proc.stdout or b"{}")


def duration_of(path):
    info = probe(path)
    try:
        return float(info["format"]["duration"])
    except (KeyError, ValueError, TypeError):
        return 0.0


def to_bytes(fp):
    return np.asarray(fp, dtype="<u4").tobytes()


def from_bytes(blob):
    return np.frombuffer(blob, dtype="<u4").astype(np.uint32)


def item_to_start(i):
    """Start time (s) of the audio described by fingerprint item ``i``."""
    return i * ITEM_SECONDS


def items_to_span(i_start, i_end):
    """Map a matched item range [i_start, i_end) to an audio span in seconds."""
    start = i_start * ITEM_SECONDS + START_BIAS_SECONDS
    end = i_end * ITEM_SECONDS + END_TAIL_SECONDS
    return max(0.0, start), end


def seconds_to_items(seconds):
    return round(seconds / ITEM_SECONDS)
