"""SQLite storage. One connection per thread, WAL mode."""

import json
import os
import sqlite3
import threading
import time

from . import config

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    library TEXT NOT NULL,
    show TEXT NOT NULL,
    name TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    duration REAL NOT NULL DEFAULT 0,
    fp BLOB,
    status TEXT NOT NULL DEFAULT 'queued',   -- queued | analyzed | error | missing
    error TEXT,
    excluded INTEGER NOT NULL DEFAULT 0,     -- never cut this episode
    cut_failed INTEGER NOT NULL DEFAULT 0,
    removed_seconds REAL NOT NULL DEFAULT 0,
    note TEXT,
    discovered_at REAL NOT NULL,
    analyzed_at REAL,
    cut_at REAL
);
CREATE INDEX IF NOT EXISTS episodes_show ON episodes (show, mtime);
CREATE INDEX IF NOT EXISTS episodes_status ON episodes (status);

CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY,
    fp BLOB NOT NULL,
    fp_offset REAL NOT NULL DEFAULT 0,       -- source-episode time of fp item 0
    duration REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | ad | keep
    decided_by TEXT,                         -- user | auto
    source_episode_id INTEGER,
    source_show TEXT,
    source_start REAL,
    preview TEXT,
    note TEXT,
    swept INTEGER NOT NULL DEFAULT 0,
    episode_count INTEGER NOT NULL DEFAULT 0,
    show_count INTEGER NOT NULL DEFAULT 0,
    suggestion TEXT,
    confidence INTEGER NOT NULL DEFAULT 0,   -- 0-100, how likely this is an ad
    ref_path TEXT,                           -- edge audio for exact boundaries
    refine_tried INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    decided_at REAL
);
CREATE INDEX IF NOT EXISTS clips_status ON clips (status);

CREATE TABLE IF NOT EXISTS occurrences (
    id INTEGER PRIMARY KEY,
    clip_id INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    start REAL NOT NULL,
    end REAL NOT NULL,
    ber REAL NOT NULL DEFAULT 0,
    refined INTEGER NOT NULL DEFAULT 0       -- boundaries from waveform alignment
);
CREATE INDEX IF NOT EXISTS occ_clip ON occurrences (clip_id);
CREATE INDEX IF NOT EXISTS occ_episode ON occurrences (episode_id);

CREATE TABLE IF NOT EXISTS cuts (
    id INTEGER PRIMARY KEY,
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    clip_id INTEGER,
    start REAL NOT NULL,
    end REAL NOT NULL,
    at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS cuts_episode ON cuts (episode_id);

CREATE TABLE IF NOT EXISTS originals (
    episode_id INTEGER PRIMARY KEY REFERENCES episodes(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    created_at REAL NOT NULL
);
"""


class Database:
    def __init__(self, path):
        self.path = path
        self._local = threading.local()
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn.executescript(SCHEMA)  # executescript manages its own transaction
        self._migrate()
        self.x("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))

    def _migrate(self):
        """Add columns introduced after v0.1.0 to existing databases."""
        added = {
            "clips": [("confidence", "INTEGER NOT NULL DEFAULT 0"), ("ref_path", "TEXT"),
                      ("refine_tried", "INTEGER NOT NULL DEFAULT 0")],
            "occurrences": [("refined", "INTEGER NOT NULL DEFAULT 0")],
        }
        for table, cols in added.items():
            have = {r["name"] for r in self.q(f"PRAGMA table_info({table})")}
            for name, ddl in cols:
                if name not in have:
                    self.x(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

    @property
    def conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.conn = c
        return c

    def tx(self):
        return _Tx(self.conn)

    def q(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    def q1(self, sql, args=()):
        return self.conn.execute(sql, args).fetchone()

    def x(self, sql, args=()):
        return self.conn.execute(sql, args)

    # --- settings ---
    def get_settings(self):
        stored = {r["key"]: json.loads(r["value"]) for r in self.q("SELECT key, value FROM settings")}
        out = {}
        for spec in config.SETTINGS:
            if spec["key"] in stored:
                try:
                    out[spec["key"]] = config.coerce(spec, stored[spec["key"]])
                    continue
                except (ValueError, TypeError):
                    pass
            out[spec["key"]] = config.env_default(spec)
        return out

    def put_settings(self, values):
        clean = {}
        for key, value in values.items():
            spec = config.SETTINGS_BY_KEY.get(key)
            if spec is None:
                raise ValueError(f"unknown setting {key!r}")
            clean[key] = config.coerce(spec, value)
        with self.tx() as c:
            for key, value in clean.items():
                c.execute("INSERT INTO settings VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                          (key, json.dumps(value)))
        return self.get_settings()


class _Tx:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        self.conn.execute("BEGIN IMMEDIATE")
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        self.conn.execute("ROLLBACK" if exc_type else "COMMIT")
        return False


def now():
    return time.time()
