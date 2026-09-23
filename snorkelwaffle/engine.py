"""Library scanning, clip discovery, and cutting.

Vocabulary:

* episode: an audio file in the library.
* clip: a unique piece of audio heard in more than one place (an ad, an intro,
  a jingle). Found by comparing an episode with nearby episodes of its show.
  Each clip is reviewed once: ``ad`` (cut it everywhere) or ``keep``.
* occurrence: where a clip was heard in a particular episode.
"""

import json
import logging
import os
import shutil
import statistics
import subprocess
from collections import namedtuple

from . import cutter, fingerprint
from .db import now
from .matcher import MatchParams, Prepared, find_matches, subtract_ranges

log = logging.getLogger(__name__)

# A match that gets within this many items (~2 s) of a clip's edge counts as
# reaching it: the first/last few values of a clip describe windows that
# straddle its boundary and rarely match elsewhere.
EDGE_ITEMS = 16
# A run starting within the first ~1 s of a file was cut off by the file start
# (encoder priming makes the first few values unreliable), so it can't carry
# the usual ~1 s calibration lead.
START_EDGE_ITEMS = 8

ClipRef = namedtuple("ClipRef", "id fp show fp_offset start duration")
Occ = namedtuple("Occ", "clip_id s_item e_item start end ber")
Piece = namedtuple("Piece", "s_item e_item start end siblings")  # siblings: set of episode ids


class Engine:
    def __init__(self, db, env):
        self.db = db
        self.env = env
        self.originals_dir = os.path.join(env.data_dir, "originals")
        self.previews_dir = os.path.join(env.data_dir, "previews")
        self.tmp_dir = os.path.join(env.data_dir, "tmp")
        for d in (self.originals_dir, self.previews_dir, self.tmp_dir):
            os.makedirs(d, exist_ok=True)
        self._clips = {}  # id -> (fp array, source_show)
        self.changed_paths = set()

    # ------------------------------------------------------------------ helpers
    def params(self, settings):
        return MatchParams(min_items=max(8, fingerprint.seconds_to_items(settings["min_clip_seconds"])),
                           max_bits=settings["max_bits"])

    def _locate(self, path):
        for root in self.env.library_dirs:
            if path == root or path.startswith(root + "/"):
                rel = os.path.relpath(path, root)
                parts = rel.split(os.sep)
                show = parts[0] if len(parts) > 1 else "(library root)"
                return root, show
        return None, None

    def _span_seconds(self, s_item, e_item, fp_len, duration):
        """Audio span of a matched item run, snapped to the file edges."""
        start, end = fingerprint.items_to_span(s_item, e_item)
        if s_item < START_EDGE_ITEMS:
            start = 0.0
        if duration and (e_item >= fp_len - 2 or end > duration):
            end = duration if e_item >= fp_len - 2 else min(end, duration)
        return round(start, 3), round(end, 3)

    def _occurrence_span(self, clip, m, fp_len, duration):
        """Where clip ``clip`` sits in an episode, given match ``m`` (a = clip, b = episode).

        When the match reaches the clip's edges the clip's own span is placed
        along the matched diagonal, so every occurrence gets the clip's exact
        boundaries. A side the match doesn't reach (a partial occurrence) falls
        back to run-edge calibration.
        """
        run_start, run_end = self._span_seconds(m.b_start, m.b_end, fp_len, duration)
        shift = (m.b_start - m.a_start) * fingerprint.ITEM_SECONDS - clip.fp_offset
        start = clip.start + shift if m.a_start <= EDGE_ITEMS else run_start
        end = clip.start + clip.duration + shift if m.a_end >= len(clip.fp) - EDGE_ITEMS else run_end
        start = max(0.0, start)
        end = min(duration, end) if duration else end
        return round(start, 3), round(end, 3)

    def refresh_clip_cache(self):
        rows = self.db.q("SELECT id, source_show, fp_offset, source_start, duration FROM clips")
        ids = {r["id"] for r in rows}
        for cid in list(self._clips):
            if cid not in ids:
                del self._clips[cid]
        for r in rows:
            if r["id"] not in self._clips:
                blob = self.db.q1("SELECT fp FROM clips WHERE id=?", (r["id"],))["fp"]
                self._clips[r["id"]] = ClipRef(r["id"], fingerprint.from_bytes(blob), r["source_show"],
                                               r["fp_offset"], r["source_start"], r["duration"])
        return self._clips

    # --------------------------------------------------------------------- scan
    def scan(self, settings):
        """Find new, changed and missing files. Returns number queued."""
        t_now = now()
        settle = settings["settle_minutes"] * 60
        backlog = settings["backlog_days"] * 86400
        known = {r["path"]: r for r in self.db.q(
            "SELECT id, path, size, mtime, status, library FROM episodes")}
        seen = set()
        queued = 0
        scanned_roots = []
        for root in self.env.library_dirs:
            if not os.path.isdir(root):
                log.warning("Library folder %s does not exist (is the volume mounted?)", root)
                continue
            found_any = False
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fn in filenames:
                    if fn.startswith(".") or os.path.splitext(fn)[1].lower() not in cutter.AUDIO_EXTS:
                        continue
                    path = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    found_any = True
                    seen.add(path)
                    if t_now - st.st_mtime < settle:
                        continue
                    if backlog and st.st_mtime < t_now - backlog and path not in known:
                        continue
                    row = known.get(path)
                    _, show = self._locate(path)
                    if row is None:
                        self.db.x("INSERT INTO episodes (path, library, show, name, size, mtime, status, discovered_at)"
                                  " VALUES (?, ?, ?, ?, ?, ?, 'queued', ?)",
                                  (path, root, show, fn, st.st_size, st.st_mtime, t_now))
                        queued += 1
                    elif row["status"] == "missing" or (row["size"], row["mtime"]) != (st.st_size, st.st_mtime):
                        if row["status"] != "missing":
                            log.info("%s changed on disk; re-analysing", path)
                            self._drop_original(row["id"])
                        self.db.x("UPDATE episodes SET status='queued', cut_failed=0, error=NULL, size=?, mtime=?"
                                  " WHERE id=?", (st.st_size, st.st_mtime, row["id"]))
                        queued += 1
            if found_any:
                scanned_roots.append(root)
        # Only mark files missing under roots that were actually readable, so an
        # unmounted share doesn't flag the whole library.
        for path, row in known.items():
            if path not in seen and row["status"] != "missing" and row["library"] in scanned_roots:
                self.db.x("UPDATE episodes SET status='missing' WHERE id=?", (row["id"],))
        if queued:
            log.info("Scan queued %d episode(s)", queued)
        return queued

    # ------------------------------------------------------------------ analyse
    def next_queued(self):
        return self.db.q1("SELECT id FROM episodes WHERE status='queued' ORDER BY show, mtime DESC LIMIT 1")

    def analyze(self, ep_id, settings, discover=True):
        ep = self.db.q1("SELECT * FROM episodes WHERE id=?", (ep_id,))
        path = ep["path"]
        if not os.path.exists(path):
            self.db.x("UPDATE episodes SET status='missing' WHERE id=?", (ep_id,))
            return
        try:
            st = os.stat(path)
            fp = fingerprint.fingerprint_file(path, nice=self.env.nice)
            duration = fingerprint.duration_of(path)
        except (fingerprint.FingerprintError, OSError, subprocess.SubprocessError) as exc:
            self.db.x("UPDATE episodes SET status='error', error=?, analyzed_at=? WHERE id=?",
                      (f"fingerprint failed: {exc}", now(), ep_id))
            log.warning("Fingerprint failed for %s: %s", path, exc)
            return
        params = self.params(settings)
        prep = Prepared(fp)
        occs = self._match_library(prep, len(fp), duration, ep["show"], settings, params)

        new_clips, note = [], None
        if discover and len(fp) >= params.min_items:
            new_clips, note = self._discover(ep, fp, duration, occs, settings, params)

        with self.db.tx() as c:
            c.execute("DELETE FROM occurrences WHERE episode_id=?", (ep_id,))
            for o in occs:
                c.execute("INSERT INTO occurrences (clip_id, episode_id, start, end, ber) VALUES (?, ?, ?, ?, ?)",
                          (o.clip_id, ep_id, o.start, o.end, o.ber))
            c.execute("UPDATE episodes SET fp=?, duration=?, size=?, mtime=?, status='analyzed', error=NULL,"
                      " analyzed_at=?, note=? WHERE id=?",
                      (fingerprint.to_bytes(fp), duration, st.st_size, st.st_mtime, now(), note, ep_id))

        for piece in new_clips:
            self._create_clip(ep, fp, piece, settings, params)
        self.update_clip_stats({o.clip_id for o in occs}, settings)
        if occs or new_clips:
            log.info("%s: %d known clip(s), %d new clip(s)", ep["name"], len(occs), len(new_clips))

    def _match_library(self, prep, fp_len, duration, show, settings, params):
        out = []
        for clip in self.refresh_clip_cache().values():
            if not settings["cross_show"] and clip.show != show:
                continue
            for m in find_matches(clip.fp, prep, params):
                start, end = self._occurrence_span(clip, m, fp_len, duration)
                out.append(Occ(clip.id, m.b_start, m.b_end, start, end, m.ber))
        return out

    def _discover(self, ep, fp, duration, occs, settings, params):
        """Compare with nearby episodes of the same show; return candidate new clips.

        Audio already explained by a known clip is subtracted first. Where a new
        piece butts up against a known clip, it starts/ends exactly where that
        clip's occurrence does rather than at a calibrated run edge.
        """
        max_items = fingerprint.seconds_to_items(settings["max_clip_seconds"])
        sibs = self.db.q(
            "SELECT id, fp, duration FROM episodes WHERE show=? AND id!=? AND status='analyzed' AND fp IS NOT NULL"
            " ORDER BY abs(mtime - ?) LIMIT ?",
            (ep["show"], ep["id"], ep["mtime"], settings["sibling_count"]))
        claimed = [(o.s_item, o.e_item) for o in occs]
        occ_end = {o.e_item: o.end for o in occs}
        occ_start = {o.s_item: o.start for o in occs}
        pieces = []  # Piece(s, e, start_sec, end_sec, {sibling})
        note = None
        for sib in sibs:
            sfp = fingerprint.from_bytes(sib["fp"])
            for m in find_matches(fp, sfp, params):
                if m.length > max_items:
                    if m.length > 0.8 * len(fp):
                        note = f"Looks like a duplicate of episode #{sib['id']}"
                    continue
                m_start, m_end = self._pair_span(m, len(fp), duration, len(sfp), sib["duration"])
                for s, e in subtract_ranges([(m.a_start, m.a_end)], claimed):
                    if e - s < params.min_items:
                        continue
                    start = m_start if s == m.a_start else occ_end.get(s)
                    end = m_end if e == m.a_end else occ_start.get(e)
                    cal_start, cal_end = self._span_seconds(s, e, len(fp), duration)
                    pieces.append(Piece(s, e, cal_start if start is None else start,
                                        cal_end if end is None else end, {sib["id"]}))
        # Cluster pieces that describe the same stretch of this episode; the
        # longest piece in a cluster defines its bounds.
        clusters = []
        for pc in sorted(pieces, key=lambda p: p.s_item - p.e_item):
            for cl in clusters:
                ov = min(pc.e_item, cl.e_item) - max(pc.s_item, cl.s_item)
                if ov > 0.5 * min(pc.e_item - pc.s_item, cl.e_item - cl.s_item):
                    cl.siblings.update(pc.siblings)
                    break
            else:
                clusters.append(pc)
        chosen = sorted((c for c in clusters if len(c.siblings) >= settings["min_repeats"]),
                        key=lambda c: c.s_item)
        # Clusters that still overlap (e.g. one sibling shares ad A+B, another only
        # A) are trimmed so each piece of audio belongs to one clip.
        final = []
        for c in chosen:
            if final and c.s_item < final[-1].e_item:
                c = c._replace(s_item=final[-1].e_item, start=final[-1].end)
            if c.e_item - c.s_item >= params.min_items and c.end - c.start >= settings["min_clip_seconds"] * 0.8:
                final.append(c)
        return final, note

    def _pair_span(self, m, a_len, a_duration, b_len, b_duration):
        """Span of pair match ``m`` in episode a, in seconds.

        Normally the run edges get the calibrated bias. But when the run was cut
        off by the *other* file's start or end, the shared audio really begins
        (or ends) there, so that edge maps exactly instead.
        """
        start, end = self._span_seconds(m.a_start, m.a_end, a_len, a_duration)
        item = fingerprint.ITEM_SECONDS
        if m.b_start < START_EDGE_ITEMS <= m.a_start:
            start = (m.a_start - m.b_start) * item
        if b_duration and m.b_end >= b_len - 2 and m.a_end < a_len - 2:
            end = m.a_start * item + (b_duration - m.b_start * item)
            end = min(end, a_duration) if a_duration else end
        return round(start, 3), round(end, 3)

    def _create_clip(self, ep, fp, piece, settings, params):
        cfp = fp[piece.s_item:piece.e_item].copy()
        start, end = piece.start, piece.end
        fp_offset = piece.s_item * fingerprint.ITEM_SECONDS
        with self.db.tx() as c:
            cur = c.execute(
                "INSERT INTO clips (fp, fp_offset, duration, source_episode_id, source_show, source_start,"
                " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (fingerprint.to_bytes(cfp), fp_offset, round(end - start, 3), ep["id"], ep["show"], start, now()))
            cid = cur.lastrowid
            c.execute("INSERT INTO occurrences (clip_id, episode_id, start, end, ber) VALUES (?, ?, ?, ?, 0)",
                      (cid, ep["id"], start, end))
        clip = ClipRef(cid, cfp, ep["show"], fp_offset, start, round(end - start, 3))
        self._clips[cid] = clip
        # Record where the supporting siblings have it too, so the review page is
        # useful before the next full sweep.
        for sid in piece.siblings:
            row = self.db.q1("SELECT fp, duration FROM episodes WHERE id=?", (sid,))
            if row and row["fp"]:
                self._record_matches(clip, sid, fingerprint.from_bytes(row["fp"]), row["duration"], params)
        preview = os.path.join(self.previews_dir, f"clip_{cid}.mp3")
        try:
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{start:.3f}", "-t",
                            f"{end - start:.3f}", "-i", ep["path"], "-vn", "-ac", "1", "-c:a", "libmp3lame",
                            "-b:a", "64k", preview], check=True, capture_output=True, timeout=120)
            self.db.x("UPDATE clips SET preview=? WHERE id=?", (preview, cid))
        except (subprocess.SubprocessError, OSError) as exc:
            log.warning("Could not write preview for clip %d: %s", cid, exc)
        self.update_clip_stats([cid], settings)
        return cid

    def _record_matches(self, clip, ep_id, efp, duration, params, prep=None):
        """Insert occurrences of ``clip`` in episode ``ep_id`` that aren't recorded yet."""
        ms = find_matches(clip.fp, prep if prep is not None else efp, params)
        if not ms:
            return 0
        existing = self.db.q("SELECT start, end FROM occurrences WHERE clip_id=? AND episode_id=?", (clip.id, ep_id))
        added = 0
        for m in ms:
            start, end = self._occurrence_span(clip, m, len(efp), duration)
            if any(min(end, r["end"]) - max(start, r["start"]) > 0.5 * (end - start) for r in existing):
                continue
            self.db.x("INSERT INTO occurrences (clip_id, episode_id, start, end, ber) VALUES (?, ?, ?, ?, ?)",
                      (clip.id, ep_id, start, end, m.ber))
            added += 1
        return added

    # -------------------------------------------------------------------- sweep
    def has_unswept(self):
        return self.db.q1("SELECT 1 FROM clips WHERE swept=0 LIMIT 1") is not None

    def sweep(self, settings, should_stop=lambda: False):
        """Look for newly discovered clips in every analysed episode."""
        rows = self.db.q("SELECT id FROM clips WHERE swept=0")
        if not rows:
            return
        cache = self.refresh_clip_cache()
        todo = [cache[r["id"]] for r in rows if r["id"] in cache]
        params = self.params(settings)
        ids = [r["id"] for r in self.db.q("SELECT id FROM episodes WHERE status='analyzed' AND fp IS NOT NULL")]
        log.info("Sweeping %d new clip(s) across %d episode(s)", len(todo), len(ids))
        added = 0
        for ep_id in ids:
            if should_stop():
                return
            row = self.db.q1("SELECT show, fp, duration FROM episodes WHERE id=?", (ep_id,))
            if row is None or row["fp"] is None:
                continue
            efp = fingerprint.from_bytes(row["fp"])
            prep = Prepared(efp)
            for clip in todo:
                if not settings["cross_show"] and row["show"] != clip.show:
                    continue
                added += self._record_matches(clip, ep_id, efp, row["duration"], params, prep)
        self.db.x(f"UPDATE clips SET swept=1 WHERE id IN ({','.join('?' * len(todo))})", [c.id for c in todo])
        self.update_clip_stats([c.id for c in todo], settings)
        log.info("Sweep done: %d additional occurrence(s)", added)

    # ------------------------------------------------------- stats & auto rules
    def update_clip_stats(self, clip_ids, settings):
        for cid in clip_ids:
            clip = self.db.q1("SELECT * FROM clips WHERE id=?", (cid,))
            if clip is None:
                continue
            rows = self.db.q("SELECT o.start, o.end, e.show, e.duration, e.id FROM occurrences o"
                             " JOIN episodes e ON e.id=o.episode_id WHERE o.clip_id=?", (cid,))
            ep_count = len({r["id"] for r in rows})
            show_count = len({r["show"] for r in rows})
            sugg = suggest(clip["duration"], rows, show_count, ep_count)
            status, decided_by, decided_at = clip["status"], clip["decided_by"], clip["decided_at"]
            if status == "pending" and sugg and sugg["kind"] == "ad":
                mode = settings["auto_approve"]
                if (mode == "multi_show" and show_count >= 2) or mode == "likely":
                    status, decided_by, decided_at = "ad", "auto", now()
                    log.info("Auto-approved clip %d as ad (%s)", cid, sugg["reason"])
            self.db.x("UPDATE clips SET episode_count=?, show_count=?, suggestion=?, status=?, decided_by=?,"
                      " decided_at=? WHERE id=?",
                      (ep_count, show_count, json.dumps(sugg) if sugg else None, status, decided_by,
                       decided_at, cid))

    def reapply_auto_rules(self, settings):
        ids = [r["id"] for r in self.db.q("SELECT id FROM clips WHERE status='pending'")]
        self.update_clip_stats(ids, settings)

    # ---------------------------------------------------------------- cutting
    def next_to_cut(self):
        return self.db.q1(
            "SELECT DISTINCT e.id FROM occurrences o JOIN clips c ON c.id=o.clip_id"
            " JOIN episodes e ON e.id=o.episode_id"
            " WHERE c.status='ad' AND e.status='analyzed' AND e.excluded=0 AND e.cut_failed=0 LIMIT 1")

    def cut(self, ep_id, settings):
        ep = self.db.q1("SELECT * FROM episodes WHERE id=?", (ep_id,))
        path = ep["path"]
        try:
            st = os.stat(path)
        except OSError:
            self.db.x("UPDATE episodes SET status='missing' WHERE id=?", (ep_id,))
            return
        if (st.st_size, st.st_mtime) != (ep["size"], ep["mtime"]):
            self.db.x("UPDATE episodes SET status='queued' WHERE id=?", (ep_id,))
            return
        if not cutter.can_cut(path):
            self._cut_failed(ep_id, f"cutting {os.path.splitext(path)[1]} files is not supported")
            return
        occs = self.db.q("SELECT o.clip_id, o.start, o.end FROM occurrences o JOIN clips c ON c.id=o.clip_id"
                         " WHERE o.episode_id=? AND c.status='ad'", (ep_id,))
        spans = [(o["start"] - settings["pad_start"], o["end"] + settings["pad_end"]) for o in occs]
        try:
            tmp, _new_duration, removed = cutter.cut_to_temp(path, spans, self.tmp_dir, self.env.nice)
        except (cutter.CutError, fingerprint.FingerprintError, OSError, subprocess.SubprocessError) as exc:
            self._cut_failed(ep_id, f"cut failed: {exc}")
            return

        has_original = self.db.q1("SELECT 1 FROM originals WHERE episode_id=?", (ep_id,)) is not None
        if not has_original:
            # Always back up before overwriting, even with a 0 GB cap; the cap is
            # applied afterwards so a crash mid-write never loses the only copy.
            backup = cutter.backup(path, self.originals_dir, ep_id)
            self.db.x("INSERT INTO originals (episode_id, path, size, created_at) VALUES (?, ?, ?, ?)",
                      (ep_id, backup, os.path.getsize(backup), now()))
        cutter.replace_in_place(path, tmp)
        removed_total = sum(e - s for s, e in removed)
        with self.db.tx() as c:
            for s, e in removed:
                cids = [o["clip_id"] for o in occs if o["start"] < e and o["end"] > s]
                c.execute("INSERT INTO cuts (episode_id, clip_id, start, end, at) VALUES (?, ?, ?, ?, ?)",
                          (ep_id, cids[0] if cids else None, s, e, now()))
            c.execute("UPDATE episodes SET removed_seconds=removed_seconds+?, cut_at=? WHERE id=?",
                      (removed_total, now(), ep_id))
        log.info("Cut %.1fs from %s (%d span(s))", removed_total, ep["name"], len(removed))
        self.changed_paths.add(path)

        self.analyze(ep_id, settings, discover=False)
        left = self.db.q1("SELECT count(*) AS n FROM occurrences o JOIN clips c ON c.id=o.clip_id"
                          " WHERE o.episode_id=? AND c.status='ad'", (ep_id,))["n"]
        if left:
            self._cut_failed(ep_id, "ad audio still detected after cutting; check the boundaries")
        self.enforce_originals_cap(settings)

    def _cut_failed(self, ep_id, msg):
        log.warning("Episode %d: %s", ep_id, msg)
        self.db.x("UPDATE episodes SET cut_failed=1, error=? WHERE id=?", (msg, ep_id))

    def restore(self, ep_id):
        ep = self.db.q1("SELECT * FROM episodes WHERE id=?", (ep_id,))
        orig = self.db.q1("SELECT * FROM originals WHERE episode_id=?", (ep_id,))
        if ep is None or orig is None or not os.path.exists(orig["path"]):
            raise FileNotFoundError("no original kept for this episode")
        shutil.copyfile(orig["path"], ep["path"])
        self._drop_original(ep_id)
        with self.db.tx() as c:
            c.execute("DELETE FROM cuts WHERE episode_id=?", (ep_id,))
            c.execute("UPDATE episodes SET excluded=1, removed_seconds=0, cut_at=NULL, cut_failed=0, error=NULL,"
                      " status='queued' WHERE id=?", (ep_id,))
        self.changed_paths.add(ep["path"])
        log.info("Restored original of %s (episode excluded from cutting)", ep["name"])

    # --------------------------------------------------------------- originals
    def _drop_original(self, ep_id):
        row = self.db.q1("SELECT path FROM originals WHERE episode_id=?", (ep_id,))
        if row:
            try:
                os.remove(row["path"])
            except FileNotFoundError:
                pass
            self.db.x("DELETE FROM originals WHERE episode_id=?", (ep_id,))

    def originals_usage(self):
        r = self.db.q1("SELECT count(*) AS n, coalesce(sum(size), 0) AS bytes FROM originals")
        return r["n"], r["bytes"]

    def enforce_originals_cap(self, settings):
        cap = settings["originals_max_gb"] * 1024 ** 3
        max_age = settings["originals_max_days"] * 86400
        rows = self.db.q("SELECT episode_id, size, created_at FROM originals ORDER BY created_at")
        total = sum(r["size"] for r in rows)
        t_now = now()
        for r in rows:
            too_old = max_age and t_now - r["created_at"] > max_age
            if total > cap or too_old:
                self._drop_original(r["episode_id"])
                total -= r["size"]

    # -------------------------------------------------------------------- stats
    def stats(self):
        q1 = self.db.q1
        by_status = {r["status"]: r["n"] for r in self.db.q("SELECT status, count(*) AS n FROM episodes GROUP BY status")}
        clips = {r["status"]: r["n"] for r in self.db.q("SELECT status, count(*) AS n FROM clips GROUP BY status")}
        n_orig, orig_bytes = self.originals_usage()
        return {
            "episodes": by_status,
            "episodes_total": sum(by_status.values()),
            "episodes_cut": q1("SELECT count(*) AS n FROM episodes WHERE removed_seconds > 0")["n"],
            "cut_failed": q1("SELECT count(*) AS n FROM episodes WHERE cut_failed=1")["n"],
            "removed_seconds": q1("SELECT coalesce(sum(removed_seconds), 0) AS s FROM episodes")["s"],
            "clips": clips,
            "originals": {"count": n_orig, "bytes": orig_bytes},
            "shows": q1("SELECT count(DISTINCT show) AS n FROM episodes")["n"],
        }


def suggest(duration, occ_rows, show_count, ep_count):
    """Heuristic hint for the reviewer. Returns {kind, reason} or None."""
    if show_count >= 2:
        return {"kind": "ad", "reason": f"heard on {show_count} different shows"}
    if ep_count < 2 or not occ_rows:
        return None
    starts = [r["start"] for r in occ_rows]
    from_end = [r["duration"] - r["end"] for r in occ_rows if r["duration"]]
    spread = statistics.pstdev(starts) if len(starts) > 1 else 0
    if ep_count >= 3 and _mostly_fixed(starts) and statistics.median(starts) < 180:
        return {"kind": "theme", "reason": "same spot near the start of most episodes (intro?)"}
    if ep_count >= 3 and _mostly_fixed(from_end) and statistics.median(from_end) < 180:
        return {"kind": "theme", "reason": "same spot near the end of most episodes (outro?)"}
    if 12 <= duration <= 130 and spread > 30:
        return {"kind": "ad", "reason": "typical ad length and moves around between episodes"}
    return None


def _mostly_fixed(values, tolerance=5.0, share=0.6):
    """True when most values sit within ``tolerance`` of their median.

    Pre-roll ads push an intro later in some episodes, so this is deliberately
    looser than "identical position everywhere".
    """
    if not values:
        return False
    med = statistics.median(values)
    return sum(abs(v - med) <= tolerance for v in values) >= share * len(values)


def fmt_time(seconds):
    seconds = round(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

