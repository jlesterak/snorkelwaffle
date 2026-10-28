"""Matcher behaviour on synthetic audio: no false positives, calibrated edges."""

import os
import shutil
import tempfile
import unittest

from synth import write_mp3

from snorkelwaffle import fingerprint
from snorkelwaffle.matcher import find_matches, subtract_ranges, union_ranges


class MatcherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="sw-match-")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fp(self, name, pieces, **kw):
        path = os.path.join(self.tmp, name)
        layout = write_mp3(path, pieces, **kw)
        return fingerprint.fingerprint_file(path, nice=0), layout

    def test_unrelated_audio_never_matches(self):
        a, _ = self.fp("u1.mp3", [(i, 60) for i in range(10, 20)])
        b, _ = self.fp("u2.mp3", [(i, 60) for i in range(30, 40)], bitrate="64k")
        self.assertEqual(find_matches(a, b), [])

    def test_shared_segment_edges(self):
        a, la = self.fp("s1.mp3", [(1, 95.3), (99, 41), (2, 120)])
        b, _ = self.fp("s2.mp3", [(3, 33.7), (99, 41), (4, 80)], bitrate="64k", lead_in=0.21)
        ms = find_matches(a, b)
        self.assertEqual(len(ms), 1)
        start, end = fingerprint.items_to_span(ms[0].a_start, ms[0].a_end)
        self.assertAlmostEqual(start, la[1][1], delta=0.5)
        self.assertAlmostEqual(end, la[1][2], delta=0.5)

    def test_ranges(self):
        self.assertEqual(union_ranges([(5, 8), (0, 3), (3, 4)]), [(0, 4), (5, 8)])
        self.assertEqual(subtract_ranges([(0, 10)], [(2, 4), (6, 12)]), [(0, 2), (4, 6)])


if __name__ == "__main__":
    unittest.main()


class HintTest(unittest.TestCase):
    def test_excerpt_hint(self):
        from snorkelwaffle.engine import ad_confidence, suggest
        rows = [{"start": 100, "end": 157.6, "duration": 3000, "ber": 0.05, "id": 1, "show": "A"},
                {"start": 2000, "end": 2057.6, "duration": 3600, "ber": 0.05, "id": 2, "show": "A"}]
        sugg = suggest(57.6, rows, 1, 2)
        self.assertEqual(sugg["kind"], "excerpt")
        self.assertLess(ad_confidence(57.6, rows, 1, 2, sugg), 50)
        # A real 60 s ad heard twice is not penalised.
        rows60 = [dict(r, end=r["start"] + 60.0) for r in rows]
        self.assertNotEqual(suggest(60.0, rows60, 1, 2)["kind"], "excerpt")

    def test_one_show_sting_heard_elsewhere_is_not_confident(self):
        # Real false positives before 0.3: a 16 s show sting, 11 episodes of
        # its own show plus one cross-promo elsewhere, scored 100.
        from snorkelwaffle.engine import ad_confidence, suggest
        rows = [{"start": 60 + 300 * i, "end": 76 + 300 * i, "duration": 3600, "ber": 0.04, "id": i,
                 "show": "Own" if i < 11 else "Other"} for i in range(12)]
        sugg = suggest(16.0, rows, 2, 12)
        self.assertLess(ad_confidence(16.0, rows, 2, 12, sugg), 75)
        # The same 30 s clip spread evenly over two shows is a network ad.
        even = [dict(r, end=r["start"] + 30, show="Own" if r["id"] % 2 else "Other") for r in rows]
        self.assertGreaterEqual(ad_confidence(30.0, even, 2, 12, suggest(30.0, even, 2, 12)), 75)


class TranscriptTest(unittest.TestCase):
    """Transcript scoring only; no Whisper needed."""

    def test_sponsor_read_lifts_one_show_clip(self):
        from snorkelwaffle.engine import ad_confidence
        from snorkelwaffle.transcribe import ad_word_hits
        ad = ("This episode is brought to you by Factor. Go to factormeals.com slash podcast "
              "and use code PODCAST for 50 percent off your first box.")
        mailbag = "Thanks for all your letters, and keep them coming."
        self.assertGreaterEqual(ad_word_hits(ad), 2)
        self.assertLess(ad_word_hits(mailbag), 2)
        rows = [{"start": 600 + 900 * i, "end": 630 + 900 * i, "duration": 3600, "ber": 0.04, "id": i,
                 "show": "Own"} for i in range(3)]
        self.assertLessEqual(ad_confidence(30.0, rows, 1, 3, None), 55)
        self.assertLessEqual(ad_confidence(30.0, rows, 1, 3, None, mailbag), 55)
        self.assertGreaterEqual(ad_confidence(30.0, rows, 1, 3, None, ad), 75)
        # Long in-character bits and intros never get the bonus.
        self.assertLess(ad_confidence(200.0, rows, 1, 3, None, ad), 75)
        self.assertEqual(ad_confidence(30.0, rows, 1, 3, {"kind": "theme"}, ad), 5)
