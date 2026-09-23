"""End-to-end: synthetic library -> discover clips -> approve -> cut -> restore."""

import os
import shutil
import subprocess
import tempfile
import unittest

from synth import write_mp3

from snorkelwaffle import config, cutter, fingerprint
from snorkelwaffle.db import Database
from snorkelwaffle.engine import Engine

THEME, OUTRO, AD1, AD2, AD3 = 1000, 1001, 2001, 2002, 2003


class EngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sw-test-")
        cls.lib = os.path.join(cls.tmp, "podcasts")
        # Show A: theme + content + ads in varying positions.
        a = os.path.join(cls.lib, "Show A")
        os.makedirs(a)
        cls.layouts = {}
        plans = {
            "Show A/ep1.mp3": [(THEME, 12), (101, 150), (AD1, 30), (102, 200), (AD2, 20), (103, 60), (OUTRO, 10)],
            "Show A/ep2.mp3": [(THEME, 12), (201, 90), (AD2, 20), (202, 260), (AD1, 30), (203, 40), (OUTRO, 10)],
            "Show A/ep3.mp3": [(AD3, 25), (THEME, 12), (301, 120), (AD1, 30), (302, 180), (OUTRO, 10)],
            "Show B/b1.mp3": [(401, 100), (AD1, 30), (402, 150)],
        }
        os.makedirs(os.path.join(cls.lib, "Show B"))
        for i, (rel, pieces) in enumerate(plans.items()):
            cls.layouts[rel] = write_mp3(os.path.join(cls.lib, rel), pieces,
                                         bitrate=["128k", "96k", "64k", "112k"][i], lead_in=0.1 * i)
        # Give ep1 chapters so the remap is exercised.
        ep1 = os.path.join(cls.lib, "Show A/ep1.mp3")
        meta = os.path.join(cls.tmp, "ch.txt")
        with open(meta, "w") as f:
            f.write(";FFMETADATA1\ntitle=Episode One\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=192000\ntitle=Part 1\n"
                    "[CHAPTER]\nTIMEBASE=1/1000\nSTART=192000\nEND=482000\ntitle=Part 2\n")
        tagged = ep1 + ".tmp.mp3"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", ep1, "-i", meta, "-map", "0", "-map_metadata", "1",
                        "-map_chapters", "1", "-c", "copy", "-id3v2_version", "3", tagged], check=True)
        os.replace(tagged, ep1)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def make_engine(self):
        env = config.Env(library_dirs=[self.lib], data_dir=os.path.join(self.tmp, "data"), nice=0)
        db = Database(os.path.join(env.data_dir, "sw.db"))
        db.put_settings({"settle_minutes": 0})
        return db, Engine(db, env)

    def run_queue(self, db, eng):
        s = db.get_settings()
        while (row := eng.next_queued()):
            eng.analyze(row["id"], s)
        eng.sweep(s)

    def test_full_flow(self):
        db, eng = self.make_engine()
        s = db.get_settings()
        self.assertEqual(eng.scan(s), 4)
        self.run_queue(db, eng)

        clips = db.q("SELECT * FROM clips ORDER BY source_start")
        by_len = sorted(round(c["duration"]) for c in clips)
        # theme(12), outro(10), AD1(30), AD2(20) are repeated; AD3 appears once.
        self.assertEqual(len(clips), 4, [dict(c) for c in clips])
        for want in (10, 12, 20, 30):
            self.assertTrue(any(abs(d - want) <= 2 for d in by_len), (want, by_len))

        ad1 = min(clips, key=lambda c: abs(c["duration"] - 30))
        self.assertEqual(ad1["show_count"], 2)      # heard on Show A and Show B
        self.assertEqual(ad1["episode_count"], 4)
        self.assertIn("different shows", ad1["suggestion"])

        theme = min(clips, key=lambda c: abs(c["duration"] - 12))
        self.assertIn("intro", theme["suggestion"])

        # Boundaries: every occurrence of every clip within 0.6 s of the truth,
        # including the intro that follows a pre-roll ad in ep3.
        ad2 = min(clips, key=lambda c: abs(c["duration"] - 20))
        seeds = {ad1["id"]: AD1, ad2["id"]: AD2, theme["id"]: THEME}
        checked = 0
        for rel, layout in self.layouts.items():
            ep = db.q1("SELECT id FROM episodes WHERE path=?", (os.path.join(self.lib, rel),))
            for cid, seed in seeds.items():
                truth = next(((a, b) for sd, a, b in layout if sd == seed), None)
                occ = db.q1("SELECT start, end FROM occurrences WHERE clip_id=? AND episode_id=?", (cid, ep["id"]))
                self.assertEqual(truth is None, occ is None, (rel, seed))
                if truth:
                    self.assertAlmostEqual(occ["start"], truth[0], delta=0.6, msg=(rel, seed))
                    self.assertAlmostEqual(occ["end"], truth[1], delta=0.6, msg=(rel, seed))
                    checked += 1
        self.assertEqual(checked, 9)

        # Approve both ads, keep theme/outro; cut.
        db.x("UPDATE clips SET status='ad' WHERE id IN (?, ?)", (ad1["id"], ad2["id"]))
        db.x("UPDATE clips SET status='keep' WHERE id NOT IN (?, ?)", (ad1["id"], ad2["id"]))
        ep1 = os.path.join(self.lib, "Show A/ep1.mp3")
        ino_before = os.stat(ep1).st_ino
        dur_before = fingerprint.duration_of(ep1)
        n = 0
        while (row := eng.next_to_cut()):
            eng.cut(row["id"], s)
            n += 1
            self.assertLess(n, 10)
        self.assertEqual(n, 4)
        self.assertEqual(db.q1("SELECT count(*) n FROM episodes WHERE cut_failed=1")["n"], 0)
        self.assertEqual(os.stat(ep1).st_ino, ino_before)
        self.assertAlmostEqual(fingerprint.duration_of(ep1), dur_before - 50, delta=1.5)

        info = fingerprint.probe(ep1)
        self.assertEqual(info["format"]["tags"].get("title"), "Episode One")
        ch = info["chapters"]
        self.assertEqual(len(ch), 2)
        # Part 1 contained AD1 (30 s) so it shrinks; Part 2 contained AD2 (20 s).
        self.assertAlmostEqual(float(ch[0]["end_time"]), 162, delta=1.5)
        self.assertAlmostEqual(float(ch[1]["end_time"]), dur_before - 50, delta=2)

        # Nothing further to cut; theme/outro survived.
        self.assertIsNone(eng.next_to_cut())
        ep1_id = db.q1("SELECT id FROM episodes WHERE path=?", (ep1,))["id"]
        kept = db.q("SELECT clip_id FROM occurrences WHERE episode_id=?", (ep1_id,))
        self.assertEqual({r["clip_id"] for r in kept} & {ad1["id"], ad2["id"]}, set())
        self.assertGreaterEqual(len(kept), 2)

        # Rescanning sees our own edit as already analysed.
        self.assertEqual(eng.scan(s), 0)

        # Restore brings the original back, same inode, and excludes the episode.
        eng.restore(ep1_id)
        self.assertEqual(os.stat(ep1).st_ino, ino_before)
        self.assertAlmostEqual(fingerprint.duration_of(ep1), dur_before, delta=0.2)
        self.run_queue(db, eng)
        self.assertIsNone(eng.next_to_cut())

    def test_originals_cap(self):
        db, eng = self.make_engine()
        src = os.path.join(self.tmp, "orig_src.bin")
        with open(src, "wb") as f:
            f.write(b"x" * 1000)
        ep = db.x("INSERT INTO episodes (path, library, show, name, discovered_at) VALUES ('/x', '/', 's', 'x', 0)").lastrowid
        dest = cutter.backup(src, eng.originals_dir, ep)
        db.x("INSERT INTO originals VALUES (?, ?, 1000, 0)", (ep, dest))
        eng.enforce_originals_cap(db.put_settings({"originals_max_gb": 0}))
        self.assertFalse(os.path.exists(dest))
        self.assertEqual(eng.originals_usage(), (0, 0))


class CutterTest(unittest.TestCase):
    def test_m4a_with_cover(self):
        tmp = tempfile.mkdtemp(prefix="sw-cut-")
        try:
            mp3 = os.path.join(tmp, "a.mp3")
            write_mp3(mp3, [(1, 60)])
            png = os.path.join(tmp, "c.png")
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=red:s=64x64", "-frames:v", "1",
                            png], check=True)
            m4a = os.path.join(tmp, "a.m4a")
            subprocess.run(["ffmpeg", "-v", "error", "-i", mp3, "-i", png, "-map", "0:a", "-map", "1:v",
                            "-c:a", "aac", "-b:a", "64k", "-c:v", "copy", "-disposition:v", "attached_pic",
                            "-metadata", "title=T", m4a], check=True)
            out, dur, _ = cutter.cut_to_temp(m4a, [(10, 20), (40, 45)], tmp, nice=0)
            self.assertAlmostEqual(dur, 45, delta=0.5)
            info = fingerprint.probe(out)
            self.assertTrue(any(s["codec_type"] == "video" for s in info["streams"]))
            self.assertEqual(info["format"]["tags"].get("title"), "T")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_remap(self):
        removed = [(10, 20), (30, 35)]
        self.assertEqual(cutter.remap(5, removed), 5)
        self.assertEqual(cutter.remap(15, removed), 10)
        self.assertEqual(cutter.remap(25, removed), 15)
        self.assertEqual(cutter.remap(40, removed), 25)


if __name__ == "__main__":
    unittest.main()
