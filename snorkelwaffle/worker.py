"""Background worker: one thread, one job at a time, lowest-priority CPU/IO.

State lives in the database (queued episodes, unswept clips, approved ads not
yet cut), so a restart simply picks up where it left off.
"""

import collections
import logging
import os
import queue
import threading
import time

log = logging.getLogger(__name__)


class RingLog(logging.Handler):
    def __init__(self, size=500):
        super().__init__()
        self.records = collections.deque(maxlen=size)

    def emit(self, record):
        self.records.append({"ts": record.created, "level": record.levelname, "msg": self.format(record)})


class Worker(threading.Thread):
    def __init__(self, engine, db, abs_client):
        super().__init__(name="worker", daemon=True)
        self.engine = engine
        self.db = db
        self.abs = abs_client
        self.wake = threading.Event()
        self.actions = queue.Queue()
        self.state = {"job": "starting", "since": time.time(), "last_scan": None, "last_abs_scan": None}
        self._scan_requested = True
        self._stopping = False

    # --- called from web threads ---
    def request_scan(self):
        self._scan_requested = True
        self.wake.set()

    def submit(self, action, *args):
        """Queue an action for the worker. Returns an Event set when done; result in .result."""
        done = threading.Event()
        done.result = None
        self.actions.put((action, args, done))
        self.wake.set()
        return done

    def poke(self):
        self.wake.set()

    def stop(self):
        self._stopping = True
        self.wake.set()

    # --- worker thread ---
    def _set(self, job):
        self.state["job"] = job
        self.state["since"] = time.time()

    def run(self):
        try:
            os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), max(0, self.engine.env.nice))
        except (OSError, AttributeError):
            pass
        try:
            self.engine.refresh_all_stats(self.db.get_settings())
        except Exception:
            log.exception("Could not refresh clip stats")
        while not self._stopping:
            try:
                if not self._step():
                    self._set("idle")
                    self.wake.wait(timeout=30)
                    self.wake.clear()
            except Exception:  # keep the worker alive whatever happens
                log.exception("Worker error")
                self._set("error (retrying)")
                time.sleep(10)

    def _step(self):
        """Do one unit of work. Returns False when there was nothing to do."""
        eng = self.engine
        settings = self.db.get_settings()

        try:
            action, args, done = self.actions.get_nowait()
        except queue.Empty:
            action = None
        if action:
            self._set(f"{action}")
            try:
                done.result = getattr(eng, action)(*args)
            except Exception as exc:  # noqa: BLE001 - handed back to the web request
                done.result = exc
            finally:
                done.set()
            return True

        # During a long backlog, don't hold finished cuts back from Audiobookshelf.
        last_abs = self.state["last_abs_scan"] or 0
        if self.engine.changed_paths and time.time() - last_abs > 600 and self._abs_rescan(settings):
            return True

        interval = settings["scan_interval_minutes"] * 60
        last = self.state["last_scan"]
        if self._scan_requested or last is None or time.time() - last > interval:
            self._scan_requested = False
            self._set("scanning library")
            eng.scan(settings)
            self.state["last_scan"] = time.time()
            return True

        row = eng.next_queued()
        if row:
            name = self.db.q1("SELECT name FROM episodes WHERE id=?", (row["id"],))["name"]
            self._set(f"analysing {name}")
            eng.analyze(row["id"], settings)
            return True

        if eng.has_unswept():
            self._set("matching new clips across the library")
            eng.sweep(settings, should_stop=lambda: not self.actions.empty() or self._stopping)
            return True

        row = eng.next_unrefined_clip()
        if row:
            self._set(f"refining boundaries of clip #{row['id']}")
            eng.refine_clip(row["id"], settings)
            return True

        if settings["cutting_enabled"]:
            row = eng.next_to_cut()
            if row:
                name = self.db.q1("SELECT name FROM episodes WHERE id=?", (row["id"],))["name"]
                self._set(f"cutting {name}")
                eng.cut(row["id"], settings)
                return True

        eng.enforce_originals_cap(settings)
        return self._abs_rescan(settings)

    def _abs_rescan(self, settings):
        paths = self.engine.changed_paths
        if not paths:
            return False
        if not (settings["rescan_abs"] and self.abs.configured):
            paths.clear()
            return False
        self._set("asking Audiobookshelf to rescan")
        ids = self.abs.scan_for(paths)
        if ids:
            log.info("Audiobookshelf rescan triggered for library %s", ", ".join(ids))
        self.state["last_abs_scan"] = time.time()
        paths.clear()
        return True
