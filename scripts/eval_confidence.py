"""Offline check of the ad score against hand-reviewed clips.

Reads a copy of the database read-only and never writes to it:

    .venv/bin/python scripts/eval_confidence.py path/to/snorkelwaffle.db
    .venv/bin/python scripts/eval_confidence.py old-copy.db --transcripts transcripts.jsonl

Labels are the clips a person decided (ad or keep). They are split 60/40 into
a training and a held-out test set by a hash of the clip id, so the split
never changes. Tune on the training rows only and quote the test rows.

The 2026-11-11 spot-check of 20 "confident" pending clips is listed apart: it
was used to design the 2026-11-13 score, so it is not held-out evidence.

"Old" is the score shipped in 0.3.3, frozen below. "New" is whatever
snorkelwaffle.engine.ad_confidence does now.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from snorkelwaffle import transcribe
from snorkelwaffle.engine import ad_confidence, cross_show, is_standard_ad_length, suggest

THRESHOLDS = (65, 70, 75, 80, 85, 90)
CUT_BER = 0.05
# 2026-11-11 spot-check (transcripts only, not listened to). A later decision in the database wins.
SPOT_CHECK = {
    **dict.fromkeys((1427, 1460, 1350, 1351, 1373, 1274, 138, 140, 917, 1911, 1913, 1305, 1601, 1916), "ad"),
    365: "keep",    # Hey Riddle Riddle in-character bit (a Rocket Money read inside it)
    1639: "keep",   # S-Town theme song
    1630: "keep",   # S-Town theme song
    1533: "unsure",  # cross-promo for another show
    1782: "unsure",  # house membership appeal fused with a sponsor read
    1518: "unsure",  # the show's own Patreon pitch
}


def old_ad_confidence(duration, occ_rows, show_count, ep_count, sugg, transcript=None):
    """The 0.3.3 score, kept here unchanged as the baseline."""
    if sugg and sugg["kind"] == "theme":
        return 5
    score = 35
    if sugg and sugg["kind"] == "excerpt":
        score -= 10
    if cross_show(occ_rows, show_count):
        score += 35 + 5 * min(3, show_count - 2)
    if duration < 20:
        score -= 20
    elif is_standard_ad_length(duration):
        score += 15
    elif duration <= 130:
        score += 5
    elif duration > 180:
        score -= 15
    if transcript and 20 <= duration <= 130 and transcribe.ad_word_hits(transcript) >= 2:
        score += 35
    bers = [r["ber"] for r in occ_rows if r["ber"]]
    if bers:
        mean_ber = sum(bers) / len(bers)
        score += 5 if mean_ber < 0.08 else -10 if mean_ber > 0.18 else 0
    return max(0, min(100, int(score)))


def is_test(clip_id):
    return int(hashlib.sha1(str(clip_id).encode()).hexdigest(), 16) % 10 < 4


def load(db_path, transcript_files):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    has_text = any(r["name"] == "transcript" for r in db.execute("PRAGMA table_info(clips)"))
    texts = {}
    for path in transcript_files:
        with open(path) as f:
            for line in f:
                row = json.loads(line)
                texts[row["id"]] = row["text"]
    review_only = {r["show"] for r in db.execute("SELECT show FROM shows WHERE mode='review_only'")}
    clips = []
    for clip in db.execute(f"SELECT id, duration, status, decided_by, source_show,"
                           f" {'transcript' if has_text else 'NULL AS transcript'} FROM clips"):
        rows = [dict(r) for r in db.execute(
            "SELECT o.start, o.end, o.ber, e.show, e.duration, e.id FROM occurrences o"
            " JOIN episodes e ON e.id=o.episode_id WHERE o.clip_id=?", (clip["id"],))]
        # Cutting deletes an ad's occurrences: put them back from the cuts log
        # (pre-cut timeline). Their match quality is gone, so they are taken as
        # clean matches: 141 of 148 reviewed ads were, measured before cutting
        # (2026-09-26). That keeps these scores level with what a live pending
        # clip gets.
        seen = {r["id"] for r in rows}
        rows += [dict(r) for r in db.execute(
            "SELECT k.start, k.end, ? AS ber, e.show, e.duration + e.removed_seconds AS duration, e.id"
            " FROM cuts k JOIN episodes e ON e.id=k.episode_id WHERE k.clip_id=?", (CUT_BER, clip["id"]))
            if r["id"] not in seen]
        shows = {r["show"] for r in rows}
        eps = len({r["id"] for r in rows})
        sugg = suggest(clip["duration"], rows, len(shows), eps)
        text = clip["transcript"] or texts.get(clip["id"])
        args = (clip["duration"], rows, len(shows), eps, sugg, text)
        label = clip["status"] if clip["decided_by"] == "user" else None
        clips.append({
            "id": clip["id"], "label": label, "status": clip["status"], "show": clip["source_show"],
            "duration": clip["duration"], "shows": len(shows), "text": text,
            "old": old_ad_confidence(*args), "new": ad_confidence(*args),
            # Same gate as Engine.update_clip_stats: these never auto-approve.
            "eligible": not (sugg and sugg["kind"] in ("theme", "excerpt"))
            and not (shows and shows <= review_only)})
    return clips


def upper_bound(wrong, n, z=1.645):
    """One-sided 95% Wilson upper bound on the share of wrong cuts."""
    if not n:
        return 1.0
    p = wrong / n
    centre = p + z * z / (2 * n)
    spread = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return min(1.0, (centre + spread) / (1 + z * z / n))


def cell(rows, key, threshold, ads):
    picked = [c for c in rows if c["eligible"] and c[key] >= threshold]
    tp = sum(c["label"] == "ad" for c in picked)
    fp = len(picked) - tp
    precision = f"{tp / len(picked):.1%}" if picked else "n/a"
    return f"{tp} / {fp} ({precision}, recall {tp / max(1, ads):.0%})"


def table(title, rows):
    ads = sum(c["label"] == "ad" for c in rows)
    print(f"\n{title}: {len(rows)} clips, {ads} ad / {len(rows) - ads} keep")
    print("| Threshold | Old: ad / keep cut | New: ad / keep cut |")
    print("|---|---|---|")
    for t in THRESHOLDS:
        print(f"| {t} | {cell(rows, 'old', t, ads)} | {cell(rows, 'new', t, ads)} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("db", help="a copy of snorkelwaffle.db (opened read-only)")
    ap.add_argument("--transcripts", action="append", default=[],
                    help="JSON lines of {id, text} for clips whose transcript is not in the database")
    ap.add_argument("--threshold", type=int, default=75, help="threshold for the detail sections (default 75)")
    a = ap.parse_args()
    clips = load(a.db, a.transcripts)
    t = a.threshold
    labelled = [c for c in clips if c["label"]]
    train = [c for c in labelled if not is_test(c["id"])]
    test = [c for c in labelled if is_test(c["id"])]
    print(f"{len(clips)} clips, {len(labelled)} decided by hand, {sum(c['text'] is not None for c in clips)} with a transcript")
    table("Training set (tune on this)", train)
    table("Held-out test set (quote this)", test)
    table("All decided clips", labelled)

    for name, rows in (("training", train), ("test", test)):
        for key in ("old", "new"):
            wrong = [c["id"] for c in rows if c["eligible"] and c[key] >= t and c["label"] == "keep"]
            print(f"Keeps the {key} score would cut at {t} ({name}): {wrong or 'none'}")
    picked = [c for c in test if c["eligible"] and c["new"] >= t]
    wrong = sum(c["label"] == "keep" for c in picked)
    print(f"\nWrong cuts per 100 auto-approvals at {t} (new score, test set): {100 * wrong / max(1, len(picked)):.1f} measured"
          f" on {len(picked)} clips; up to {100 * upper_bound(wrong, len(picked)):.1f} at 95% confidence")

    by_id = {c["id"]: c for c in clips}
    found = [(cid, by_id[cid]) for cid in SPOT_CHECK if cid in by_id]
    print(f"\nSpot-check 2026-11-11 ({len(found)} of {len(SPOT_CHECK)} clips are in this database; design data, not held out)")
    print("| Clip | Call | Now | Show | Seconds | Old | New |")
    print("|---|---|---|---|---|---|---|")
    for cid, c in found:
        print(f"| {cid} | {SPOT_CHECK[cid]} | {c['status']} | {c['show']} | {c['duration']:.0f} | {c['old']} | {c['new']} |")
    for call in ("ad", "keep", "unsure"):
        rows = [c for cid, c in found if SPOT_CHECK[cid] == call]
        if rows:
            print(f"  {call}: {sum(c['old'] >= t for c in rows)} of {len(rows)} reach {t} on the old score,"
                  f" {sum(c['new'] >= t for c in rows)} on the new")

    pending = [c for c in clips if c["status"] == "pending" and c["eligible"]]
    print(f"\nPending clips auto-approve would cut ({sum(c['status'] == 'pending' for c in clips)} pending,"
          f" {sum(c['text'] is not None for c in pending)} of the eligible ones transcribed)")
    print("| Threshold | Old | New |")
    print("|---|---|---|")
    for th in THRESHOLDS:
        print(f"| {th} | {sum(c['old'] >= th for c in pending)} | {sum(c['new'] >= th for c in pending)} |")
    dropped = sorted(c["id"] for c in pending if c["old"] >= t > c["new"])
    print(f"Pending clips that no longer reach {t}: {dropped or 'none'}")


if __name__ == "__main__":
    main()
