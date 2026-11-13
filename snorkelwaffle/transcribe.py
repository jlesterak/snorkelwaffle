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

# Cues only an ad uses: a URL, a promo code, a sponsor credit, offer small
# print. The looser AD_WORDS also fire on song lyrics and banter ("go to",
# "deal"), so a sponsor read needs at least one of these too (2026-11-13).
SPONSOR_CUES = re.compile(r"(\.com|\.org|\bdot (com|org)\b|\bslash\b|\bpromo\b|\bcode\b|\bsponsor\w*|"
                          r"\bbrought to you\b|\b(message|support) (for [\w' ]{1,40} )?comes from\b|"
                          r"\bsupported by\b|\bterms (and conditions )?apply\b|\bpercent off\b|% off|"
                          r"\bfree trial\b|\bfree shipping\b)", re.IGNORECASE)
# A show talking about itself uses the same URL-and-sign-up wording as a
# sponsor: a Patreon, membership or donation pitch, or its sign-off ("thanks
# for listening ... show notes at ...", "is a production of"). Those wait for review.
HOUSE_WORDS = re.compile(r"\b(patreon|support the show|listener[- ]supported|donations?|membership|"
                         r"bonus (episodes?|room|content)|discord|thank(s| you)( so much)? for listening|"
                         r"show notes|on this episode|that's all for|is a production of)\b", re.IGNORECASE)
# Ads are dense talk: 90% of reviewed ads ran at 2.2+ words a second. Songs and
# stings transcribe to far fewer words.
TALK_WORDS_PER_SECOND = 2.0

_model = None


def available():
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def ad_word_hits(text):
    return len(AD_WORDS.findall(text or ""))


def is_sponsor_read(text):
    """True when a transcript reads like a paid sponsor message, not the show talking about itself."""
    text = text or ""
    return ad_word_hits(text) >= 2 and bool(SPONSOR_CUES.search(text)) and not is_house_talk(text)


def is_house_talk(text):
    return bool(HOUSE_WORDS.search(text or ""))


def words_per_second(text, duration):
    return len(re.findall(r"[A-Za-z0-9']+", text or "")) / duration if duration else 0.0


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
