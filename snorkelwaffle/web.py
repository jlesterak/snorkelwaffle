"""Web UI and JSON API (stdlib http.server; no framework, tiny footprint)."""

import base64
import hmac
import json
import logging
import mimetypes
import os
import re
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import __version__, config
from .db import now

log = logging.getLogger(__name__)
STATIC = os.path.join(os.path.dirname(__file__), "static")

CLIP_COLS = ("id, duration, status, decided_by, source_episode_id, source_show, source_start, note,"
             " episode_count, show_count, suggestion, confidence, ref_path IS NOT NULL AS exact, created_at, decided_at,"
             " swept, preview IS NOT NULL AS has_preview")
EP_COLS = ("id, path, show, name, size, mtime, duration, status, error, excluded, cut_failed, removed_seconds,"
           " note, discovered_at, analyzed_at, cut_at")


class HttpError(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


def _row(r):
    d = dict(r)
    if d.get("suggestion"):
        d["suggestion"] = json.loads(d["suggestion"])
    return d


class App:
    def __init__(self, db, engine, worker, abs_client, env, ring):
        self.db, self.engine, self.worker, self.abs, self.env, self.ring = db, engine, worker, abs_client, env, ring
        self.routes = []
        r = self.route
        r("GET", r"/api/status", self.status)
        r("GET", r"/api/settings", self.get_settings)
        r("POST", r"/api/settings", self.put_settings)
        r("GET", r"/api/clips", self.list_clips)
        r("POST", r"/api/clips/bulk", self.bulk_clips)
        r("GET", r"/api/clips/(\d+)", self.get_clip)
        r("POST", r"/api/clips/(\d+)", self.update_clip)
        r("DELETE", r"/api/clips/(\d+)", self.delete_clip)
        r("GET", r"/api/clips/(\d+)/preview", self.clip_preview)
        r("GET", r"/api/occurrences/(\d+)/audio", self.occurrence_audio)
        r("GET", r"/api/shows", self.list_shows)
        r("GET", r"/api/episodes", self.list_episodes)
        r("GET", r"/api/episodes/(\d+)", self.get_episode)
        r("POST", r"/api/episodes/(\d+)/restore", self.restore_episode)
        r("POST", r"/api/episodes/(\d+)/reprocess", self.reprocess_episode)
        r("POST", r"/api/episodes/(\d+)/exclude", self.exclude_episode)
        r("POST", r"/api/scan", self.scan)
        r("GET", r"/api/abs/ping", self.abs_ping)
        r("GET", r"/api/log", self.get_log)

    def route(self, method, pattern, fn):
        self.routes.append((method, re.compile(pattern + r"$"), fn))

    # ------------------------------------------------------------------ status
    def status(self, req):
        st = dict(self.worker.state)
        return {"version": __version__, "worker": st, "queue": self.db.q1(
            "SELECT count(*) AS n FROM episodes WHERE status='queued'")["n"],
            "stats": self.engine.stats(), "env": self.env.public(), "abs_configured": self.abs.configured,
            "settings": self.db.get_settings()}

    def get_settings(self, req):
        return {"values": self.db.get_settings(), "schema": config.SETTINGS, "env": self.env.public()}

    def put_settings(self, req):
        body = req.json()
        before = self.db.get_settings()
        try:
            values = self.db.put_settings(body)
        except ValueError as exc:
            raise HttpError(400, str(exc)) from exc
        if values["auto_approve"] != before["auto_approve"]:
            self.worker.submit("reapply_auto_rules", values)
        if values["scan_interval_minutes"] != before["scan_interval_minutes"]:
            self.worker.poke()
        log.info("Settings updated: %s", ", ".join(f"{k}={values[k]}" for k in body))
        return {"values": values}

    # ------------------------------------------------------------------- clips
    def list_clips(self, req):
        status = req.arg("status", "pending")
        order = {"confidence": "confidence DESC, episode_count DESC, id DESC",
                 "episodes": "episode_count DESC, id DESC", "newest": "id DESC", "duration": "duration DESC",
                 "shows": "show_count DESC, episode_count DESC"}.get(req.arg("sort", "confidence"),
                                                                     "confidence DESC, id DESC")
        where, args = [], []
        if status != "all":
            where.append("status=?")
            args.append(status)
        if req.arg("show"):
            where.append("id IN (SELECT o.clip_id FROM occurrences o JOIN episodes e ON e.id=o.episode_id"
                         " WHERE e.show=?)")
            args.append(req.arg("show"))
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        limit, offset = req.int_arg("limit", 50, 1, 500), req.int_arg("offset", 0, 0)
        rows = self.db.q(f"SELECT {CLIP_COLS} FROM clips {sql_where} ORDER BY {order} LIMIT ? OFFSET ?",
                         args + [limit, offset])
        total = self.db.q1(f"SELECT count(*) AS n FROM clips {sql_where}", args)["n"]
        counts = {r["status"]: r["n"] for r in self.db.q("SELECT status, count(*) AS n FROM clips GROUP BY status")}
        items = []
        for r in rows:
            d = _row(r)
            d["shows"] = [x["show"] for x in self.db.q(
                "SELECT DISTINCT e.show FROM occurrences o JOIN episodes e ON e.id=o.episode_id"
                " WHERE o.clip_id=? LIMIT 5", (r["id"],))]
            items.append(d)
        return {"items": items, "total": total, "counts": counts}

    def get_clip(self, req, cid):
        clip = self.db.q1(f"SELECT {CLIP_COLS} FROM clips WHERE id=?", (cid,))
        if clip is None:
            raise HttpError(404, "no such clip")
        occ = self.db.q("SELECT o.id, o.start, o.end, o.ber, o.refined, e.id AS episode_id, e.name, e.show,"
                        " e.duration"
                        " FROM occurrences o JOIN episodes e ON e.id=o.episode_id WHERE o.clip_id=?"
                        " ORDER BY e.show, e.mtime DESC LIMIT 500", (cid,))
        cut = self.db.q1("SELECT count(DISTINCT episode_id) AS n FROM cuts WHERE clip_id=?", (cid,))["n"]
        return {"clip": _row(clip), "occurrences": [dict(o) for o in occ], "cut_episodes": cut}

    def _set_clip(self, cid, body):
        sets, args = [], []
        if "status" in body:
            if body["status"] not in ("pending", "ad", "keep"):
                raise HttpError(400, "status must be pending, ad or keep")
            sets += ["status=?", "decided_by=?", "decided_at=?"]
            args += [body["status"], None if body["status"] == "pending" else "user",
                     None if body["status"] == "pending" else now()]
        if "note" in body:
            sets.append("note=?")
            args.append(str(body["note"])[:500])
        if not sets:
            raise HttpError(400, "nothing to update")
        cur = self.db.x(f"UPDATE clips SET {', '.join(sets)} WHERE id=?", args + [cid])
        if cur.rowcount == 0:
            raise HttpError(404, "no such clip")

    def update_clip(self, req, cid):
        body = req.json()
        self._set_clip(int(cid), body)
        if "status" in body:
            log.info("Clip %s marked %s", cid, body["status"])
        self.worker.poke()
        return {"ok": True}

    def bulk_clips(self, req):
        body = req.json()
        ids = [int(i) for i in body.get("ids", [])]
        for cid in ids:
            self._set_clip(cid, {"status": body.get("status")})
        log.info("%d clip(s) marked %s", len(ids), body.get("status"))
        self.worker.poke()
        return {"ok": True, "count": len(ids)}

    def delete_clip(self, req, cid):
        row = self.db.q1("SELECT preview FROM clips WHERE id=?", (cid,))
        if row is None:
            raise HttpError(404, "no such clip")
        self.db.x("DELETE FROM clips WHERE id=?", (cid,))
        if row["preview"]:
            try:
                os.remove(row["preview"])
            except OSError:
                pass
        log.info("Clip %s deleted", cid)
        return {"ok": True}

    def clip_preview(self, req, cid):
        row = self.db.q1("SELECT preview FROM clips WHERE id=?", (cid,))
        if row is None or not row["preview"] or not os.path.exists(row["preview"]):
            raise HttpError(404, "no preview")
        req.send_file(row["preview"], "audio/mpeg")

    def occurrence_audio(self, req, oid):
        row = self.db.q1("SELECT o.start, o.end, e.path FROM occurrences o JOIN episodes e ON e.id=o.episode_id"
                         " WHERE o.id=?", (oid,))
        if row is None or not os.path.exists(row["path"]):
            raise HttpError(404, "no such occurrence")
        pad = min(15.0, max(0.0, float(req.arg("pad", "3"))))
        start = max(0.0, row["start"] - pad)
        dur = row["end"] - row["start"] + 2 * pad
        proc = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
                               "-i", row["path"], "-vn", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "64k",
                               "-f", "mp3", "-"], capture_output=True, timeout=60, check=False)
        if proc.returncode != 0:
            raise HttpError(500, "could not extract audio")
        req.send_bytes(proc.stdout, "audio/mpeg")

    # ---------------------------------------------------------------- episodes
    def list_shows(self, req):
        rows = self.db.q("SELECT show, count(*) AS episodes, sum(removed_seconds) AS removed,"
                         " sum(CASE WHEN status='queued' THEN 1 ELSE 0 END) AS queued FROM episodes"
                         " GROUP BY show ORDER BY show COLLATE NOCASE")
        return {"items": [dict(r) for r in rows]}

    def list_episodes(self, req):
        where, args = [], []
        if req.arg("show"):
            where.append("show=?")
            args.append(req.arg("show"))
        if req.arg("q"):
            where.append("name LIKE ?")
            args.append(f"%{req.arg('q')}%")
        f = req.arg("filter", "all")
        if f == "cut":
            where.append("removed_seconds > 0")
        elif f == "problems":
            where.append("(status IN ('error', 'missing') OR cut_failed=1)")
        elif f == "queued":
            where.append("status='queued'")
        elif f == "pending_ads":
            where.append("id IN (SELECT o.episode_id FROM occurrences o JOIN clips c ON c.id=o.clip_id"
                         " WHERE c.status='ad')")
        elif f == "excluded":
            where.append("excluded=1")
        sql_where = ("WHERE " + " AND ".join(where)) if where else ""
        limit, offset = req.int_arg("limit", 50, 1, 500), req.int_arg("offset", 0, 0)
        rows = self.db.q(f"SELECT {EP_COLS}, (SELECT count(*) FROM occurrences o WHERE o.episode_id=episodes.id)"
                         f" AS clip_count, EXISTS(SELECT 1 FROM originals WHERE episode_id=episodes.id) AS has_original"
                         f" FROM episodes {sql_where} ORDER BY mtime DESC LIMIT ? OFFSET ?", args + [limit, offset])
        total = self.db.q1(f"SELECT count(*) AS n FROM episodes {sql_where}", args)["n"]
        return {"items": [dict(r) for r in rows], "total": total}

    def get_episode(self, req, eid):
        ep = self.db.q1(f"SELECT {EP_COLS} FROM episodes WHERE id=?", (eid,))
        if ep is None:
            raise HttpError(404, "no such episode")
        occ = self.db.q("SELECT o.id, o.clip_id, o.start, o.end, o.ber, o.refined, c.status, c.confidence,"
                        " c.duration AS clip_duration,"
                        " c.episode_count, c.show_count FROM occurrences o JOIN clips c ON c.id=o.clip_id"
                        " WHERE o.episode_id=? ORDER BY o.start", (eid,))
        cuts = self.db.q("SELECT clip_id, start, end, at FROM cuts WHERE episode_id=? ORDER BY at, start", (eid,))
        orig = self.db.q1("SELECT size, created_at FROM originals WHERE episode_id=?", (eid,))
        return {"episode": dict(ep), "occurrences": [dict(o) for o in occ], "cuts": [dict(c) for c in cuts],
                "original": dict(orig) if orig else None}

    def restore_episode(self, req, eid):
        done = self.worker.submit("restore", int(eid))
        if not done.wait(timeout=120):
            return {"ok": True, "pending": True}
        if isinstance(done.result, Exception):
            raise HttpError(400, str(done.result))
        return {"ok": True}

    def reprocess_episode(self, req, eid):
        self.db.x("UPDATE episodes SET status='queued', cut_failed=0, error=NULL WHERE id=?", (eid,))
        self.worker.poke()
        return {"ok": True}

    def exclude_episode(self, req, eid):
        excluded = bool(req.json().get("excluded", True))
        self.db.x("UPDATE episodes SET excluded=? WHERE id=?", (int(excluded), eid))
        self.worker.poke()
        return {"ok": True}

    # ------------------------------------------------------------------- misc
    def scan(self, req):
        self.worker.request_scan()
        return {"ok": True}

    def abs_ping(self, req):
        if not self.abs.configured:
            return {"ok": False, "message": "ABS_URL / ABS_TOKEN not set"}
        ok, msg = self.abs.ping()
        return {"ok": ok, "message": msg}

    def get_log(self, req):
        return {"items": list(self.ring.records)[-300:]}


class Handler(BaseHTTPRequestHandler):
    app = None
    server_version = "snorkelwaffle"

    def log_message(self, fmt, *args):
        log.debug("%s - %s", self.address_string(), fmt % args)

    # -- helpers used by App --
    def arg(self, name, default=""):
        return self._query.get(name, [default])[0]

    def int_arg(self, name, default, lo=None, hi=None):
        try:
            v = int(self.arg(name, str(default)))
        except ValueError:
            v = default
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        return v

    def json(self):
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise HttpError(415, "expected application/json")
        n = int(self.headers.get("Content-Length") or 0)
        if n > 1_000_000:
            raise HttpError(413, "body too large")
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError as exc:
            raise HttpError(400, "invalid JSON") from exc
        if not isinstance(data, dict):
            raise HttpError(400, "expected a JSON object")
        return data

    def send_bytes(self, data, ctype):
        start, end = 0, len(data) - 1
        rng = self.headers.get("Range")
        m = re.match(r"bytes=(\d*)-(\d*)$", rng or "")
        if m and data:
            if m.group(1):
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else end
            elif m.group(2):
                start = max(0, len(data) - int(m.group(2)))
            end = min(end, len(data) - 1)
            if start > end:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{len(data)}")
                self.end_headers()
                return
            self.send_response(HTTPStatus.PARTIAL_CONTENT)
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        else:
            self.send_response(HTTPStatus.OK)
        body = data[start:end + 1]
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_file(self, path, ctype=None):
        with open(path, "rb") as f:
            data = f.read()
        self.send_bytes(data, ctype or mimetypes.guess_type(path)[0] or "application/octet-stream")

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # -- dispatch --
    def _authorized(self):
        env = self.app.env
        if not env.web_password:
            return True
        header = self.headers.get("Authorization") or ""
        if not header.startswith("Basic "):
            return False
        try:
            user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return False
        return hmac.compare_digest(user, env.web_username or user) and hmac.compare_digest(pw, env.web_password)

    def _dispatch(self, method):
        url = urlparse(self.path)
        self._query = parse_qs(url.query)
        if url.path == "/healthz":  # unauthenticated, for Docker healthchecks
            self._send_json(200, {"ok": True})
            return
        if not self._authorized():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="snorkelwaffle"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            if url.path.startswith("/api/"):
                for m, pattern, fn in self.app.routes:
                    match = pattern.match(url.path)
                    if match and m == method:
                        result = fn(self, *match.groups())
                        if result is not None:
                            self._send_json(200, result)
                        return
                raise HttpError(404, "not found")
            if method not in ("GET", "HEAD"):
                raise HttpError(405, "method not allowed")
            name = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
            path = os.path.realpath(os.path.join(STATIC, name))
            if not path.startswith(os.path.realpath(STATIC) + os.sep) or not os.path.isfile(path):
                path = os.path.join(STATIC, "index.html")
            self.send_file(path)
        except HttpError as exc:
            self._send_json(exc.code, {"error": str(exc)})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            log.exception("Request failed: %s %s", method, self.path)
            try:
                self._send_json(500, {"error": str(exc)})
            except OSError:
                pass

    def do_GET(self):
        self._dispatch("GET")

    def do_HEAD(self):
        self._dispatch("HEAD")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")


def serve(app, host, port):
    handler = type("BoundHandler", (Handler,), {"app": app})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    log.info("Web UI on http://%s:%d", host, port)
    return server

