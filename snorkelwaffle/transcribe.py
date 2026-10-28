"""Optional clip transcripts (faster-whisper), used as an ad signal.

Off by default. The model (base.en, ~145 MB) downloads into DATA_DIR/models the
first time a clip is transcribed. Clips are short, so this is cheap after the
one-off backlog: about 12x real time on 4 threads, slower on 1.
"""

import logging
import os
import re
import subprocess

import numpy as np

log = logging.getLogger(__name__)

MODEL = "base.en"

# Phrases sponsor reads use. Kept verbatim from the 2026-10-28 prototype that
# measured the 20-130 s, 2+ hits rule (77 ad / 3 keep on one-show clips).
AD_WORDS = re.compile(r"\b(promo|code|dot com|\.com|slash|sponsor\w*|brought to you|free trial|"
                      r"terms (and conditions )?apply|percent off|% off|discount|subscribe now|"
                      r"download|app store|sign up|first (month|order)|visit|go to|shipping|"
                      r"offer|deal|save \d+|limited time|available (now|wherever))\b", re.IGNORECASE)

_model = None


def available():
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def ad_word_hits(text):
    return len(AD_WORDS.findall(text or ""))


def _load_audio(path):
    # Decode with ffmpeg: faster-whisper's own PyAV path breaks on av 19.
    raw = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-f", "f32le", "-ac", "1",
                          "-ar", "16000", "-"], check=True, capture_output=True, timeout=120).stdout
    return np.frombuffer(raw, np.float32)


def load_model(data_dir):
    """Load (and on first use download) the model. Raises if that fails."""
    global _model
    if _model is None:
        # The container user's HOME is "/", so keep Hugging Face's cache with the model.
        os.environ.setdefault("HF_HOME", os.path.join(data_dir, "models", "hf"))
        os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
        for noisy in ("httpx", "httpx2", "huggingface_hub"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        from faster_whisper import WhisperModel
        log.info("Loading transcription model %s (downloads once into %s/models)", MODEL, data_dir)
        _model = WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=1,
                              download_root=os.path.join(data_dir, "models"))
    return _model


def transcribe(path, data_dir):
    """Text of the speech in ``path``. Over music Whisper may invent a line such
    as "Thanks for watching!"; that is harmless here, as it holds no ad words."""
    segments, _info = load_model(data_dir).transcribe(_load_audio(path), beam_size=1, vad_filter=False,
                                                      condition_on_previous_text=False)
    return " ".join(s.text.strip() for s in segments)
