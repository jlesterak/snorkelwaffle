"""Configuration.

Two layers:

* Environment variables: deployment wiring that belongs in docker-compose /
  DockSTARTer (paths, port, Audiobookshelf URL and token, web login). Read-only
  at runtime.
* Settings: detection and cutting tunables stored in the database and edited
  from the web UI. An environment variable named ``SW_<KEY>`` (e.g.
  ``SW_AUTO_APPROVE=multi_show``) seeds the default until the UI saves a value.
"""

import os
from dataclasses import dataclass, field


def _env(name, default=""):
    return os.environ.get(name, default).strip()


@dataclass
class Env:
    library_dirs: list = field(default_factory=list)
    data_dir: str = "/config"
    host: str = "0.0.0.0"
    port: int = 8484
    abs_url: str = ""
    abs_token: str = ""
    abs_library_id: str = ""
    web_username: str = ""
    web_password: str = ""
    nice: int = 10
    log_level: str = "INFO"

    @classmethod
    def load(cls):
        dirs = [d.strip().rstrip("/") for d in _env("LIBRARY_DIRS", "/storage/media/podcasts").split(",")]
        return cls(
            library_dirs=[d for d in dirs if d],
            data_dir=_env("DATA_DIR", "/config"),
            host=_env("HOST", "0.0.0.0"),
            port=int(_env("PORT", "8484")),
            abs_url=_env("ABS_URL").rstrip("/"),
            abs_token=_env("ABS_TOKEN"),
            abs_library_id=_env("ABS_LIBRARY_ID"),
            web_username=_env("WEB_USERNAME"),
            web_password=_env("WEB_PASSWORD"),
            nice=int(_env("NICE", "10")),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
        )

    def public(self):
        """Values safe to show in the UI (secrets masked)."""
        return {
            "LIBRARY_DIRS": ",".join(self.library_dirs),
            "DATA_DIR": self.data_dir,
            "PORT": self.port,
            "ABS_URL": self.abs_url or "(not set)",
            "ABS_TOKEN": "(set)" if self.abs_token else "(not set)",
            "ABS_LIBRARY_ID": self.abs_library_id or "(auto)",
            "WEB_USERNAME": self.web_username or "(no login)",
            "WEB_PASSWORD": "(set)" if self.web_password else "(not set)",
            "NICE": self.nice,
            "LOG_LEVEL": self.log_level,
        }


# UI-editable settings. The web page renders its form from this list.
SETTINGS = [
    # --- Cutting ---
    dict(key="cutting_enabled", type="bool", default=True, group="Cutting",
         label="Cutting enabled",
         help="Master switch. When off, episodes are still analysed and clips still found, "
              "but no audio file is modified."),
    dict(key="auto_approve", type="choice", default="off", group="Cutting",
         choices=["off", "multi_show", "likely"],
         label="Auto-approve clips",
         help="off: every clip waits for your review. multi_show: clips heard on 2+ different "
              "shows are treated as ads automatically (network-inserted ads). likely: also "
              "auto-approve typical-length clips that move around mid-episode."),
    dict(key="pad_start", type="float", default=0.0, min=-5, max=5, group="Cutting",
         label="Start padding (s)",
         help="Extra seconds to cut before each ad. Negative values cut less."),
    dict(key="pad_end", type="float", default=0.0, min=-5, max=5, group="Cutting",
         label="End padding (s)",
         help="Extra seconds to cut after each ad. Negative values cut less."),
    dict(key="rescan_abs", type="bool", default=True, group="Cutting",
         label="Ask Audiobookshelf to rescan",
         help="After files change, trigger a library scan so durations update "
              "(needs ABS_URL and ABS_TOKEN)."),
    # --- Detection ---
    dict(key="min_clip_seconds", type="float", default=8, min=3, max=60, group="Detection",
         label="Shortest clip (s)",
         help="Repeated audio shorter than this is ignored (stings, short jingles)."),
    dict(key="max_clip_seconds", type="float", default=300, min=30, max=1800, group="Detection",
         label="Longest clip (s)",
         help="Repeated audio longer than this is ignored (re-runs, duplicate downloads)."),
    dict(key="sibling_count", type="int", default=6, min=1, max=50, group="Detection",
         label="Episodes to compare against",
         help="Each new episode is compared with this many nearby episodes of the same show "
              "to discover new repeated clips."),
    dict(key="min_repeats", type="int", default=1, min=1, max=10, group="Detection",
         label="Minimum repeats",
         help="A new clip must be found in at least this many other episodes."),
    dict(key="cross_show", type="bool", default=True, group="Detection",
         label="Match clips across shows",
         help="Look for known clips in every show, not only the one they were found in."),
    dict(key="max_bits", type="float", default=9.0, min=4, max=13, group="Detection",
         label="Match tolerance",
         help="Average differing fingerprint bits (of 32) allowed. Lower is stricter. "
              "7-10 works for most feeds."),
    # --- Library ---
    dict(key="scan_interval_minutes", type="int", default=30, min=1, max=1440, group="Library",
         label="Scan interval (min)", help="How often to look for new or changed episodes."),
    dict(key="settle_minutes", type="int", default=5, min=0, max=120, group="Library",
         label="Settle time (min)",
         help="Only touch files that have not changed for this long (lets downloads finish)."),
    dict(key="backlog_days", type="int", default=0, min=0, max=36500, group="Library",
         label="Backlog window (days)",
         help="Only process episodes modified within this many days. 0 = the whole library."),
    # --- Originals ---
    dict(key="originals_max_gb", type="float", default=10.0, min=0, max=10000, group="Originals",
         label="Originals cap (GB)",
         help="Uncut originals are kept so cuts can be undone. Oldest are deleted beyond this "
              "size. 0 = keep no originals (cuts cannot be undone)."),
    dict(key="originals_max_days", type="int", default=30, min=0, max=3650, group="Originals",
         label="Originals max age (days)", help="Originals older than this are deleted. 0 = no age limit."),
]

SETTINGS_BY_KEY = {s["key"]: s for s in SETTINGS}


def coerce(spec, value):
    """Convert ``value`` to the setting's type, clamped to bounds. Raises ValueError."""
    t = spec["type"]
    if t == "bool":
        if isinstance(value, str):
            v = value.strip().lower()
            if v in ("1", "true", "yes", "on"):
                return True
            if v in ("0", "false", "no", "off"):
                return False
            raise ValueError(f"{spec['key']}: not a boolean: {value!r}")
        return bool(value)
    if t == "choice":
        if value not in spec["choices"]:
            raise ValueError(f"{spec['key']}: must be one of {spec['choices']}")
        return value
    num = int(float(value)) if t == "int" else float(value)
    if "min" in spec:
        num = max(spec["min"], num)
    if "max" in spec:
        num = min(spec["max"], num)
    return num


def env_default(spec):
    raw = os.environ.get("SW_" + spec["key"].upper())
    if raw is None or raw.strip() == "":
        return spec["default"]
    try:
        return coerce(spec, raw.strip())
    except ValueError:
        return spec["default"]
