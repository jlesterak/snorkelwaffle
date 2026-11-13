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

    # The next four are the wrong or doubtful "confident" clips from the 2026-11-11 spot-check.
    @staticmethod
    def _rows(seconds, shows, n=6):
        return [{"start": 600 + 700 * i, "end": 600 + 700 * i + seconds, "duration": 3600, "ber": 0.04, "id": i,
                 "show": shows[i % len(shows)]} for i in range(n)]

    def test_theme_song_on_two_feeds_is_not_confident(self):
        # A show's closing song, heard in two feeds of the same podcast (clips 1639, 1630).
        from snorkelwaffle.engine import ad_confidence, suggest
        lyrics = "The summer is here at last, the sky is overcast, and no one brings a rose for her. " * 2
        promo = ("Hi, I'm Sam, and I'm Alex, and we host Round the Table, a new show about board games. "
                 "Every week we sit down with a designer and pull apart one game, rule by rule, to find out why it "
                 "works and where it falls over. We have covered classics, new releases and a few total disasters. "
                 "If that sounds like your kind of thing, find Round the Table wherever you listen. " * 2)
        for seconds in (32.0, 49.0):
            rows = self._rows(seconds, ["Serial", "S-Town"])
            sugg = suggest(seconds, rows, 2, 6)
            self.assertLess(ad_confidence(seconds, rows, 2, 6, sugg, lyrics), 75)
        # A network promo is dense talk, so it stays confident without any sponsor wording.
        rows = self._rows(49.0, ["Serial", "S-Town"])
        self.assertGreaterEqual(ad_confidence(49.0, rows, 2, 6, suggest(49.0, rows, 2, 6), promo), 75)

    def test_song_lyrics_with_loose_ad_words_are_not_a_sponsor_read(self):
        # Clip 89: a theme song whose lyrics hit "go to" three times.
        from snorkelwaffle.engine import ad_confidence
        from snorkelwaffle.transcribe import ad_word_hits, is_sponsor_read
        lyrics = "Tonight we go to town, we go to make some noise, we go to turn it up loud."
        self.assertGreaterEqual(ad_word_hits(lyrics), 2)
        self.assertFalse(is_sponsor_read(lyrics))
        self.assertLess(ad_confidence(30.0, self._rows(30.0, ["Own"]), 1, 6, None, lyrics), 75)

    def test_long_one_show_read_waits_for_review(self):
        # Clip 365: a 122 s in-character bit with a sponsor read inside it.
        from snorkelwaffle.engine import ad_confidence
        bit = ("Well guys, I gotta go, I'm taking my new best friend out to a very fancy dinner because I saved a "
               "bunch of money. Join at budgetbear.com. That's budgetbear.com slash riddle. Let the bear pay.")
        self.assertLess(ad_confidence(122.0, self._rows(122.0, ["Own"]), 1, 6, None, bit), 75)
        self.assertGreaterEqual(ad_confidence(60.0, self._rows(60.0, ["Own"]), 1, 6, None, bit), 75)

    def test_house_pitch_is_not_a_sponsor_read(self):
        # Clips 1518 and 1782: the show's own Patreon or membership appeal, also when a sponsor read follows it.
        from snorkelwaffle.engine import ad_confidence, suggest
        from snorkelwaffle.transcribe import is_sponsor_read
        patreon = ("This is an independent, listener supported podcast. We rely on donations. Sign up at "
                   "patreon.com slash ourshow for a bonus episode every month and access to the discord.")
        fused = ("Thanks to Rebecca, a member of our membership program. Sign up at ourshow.org slash join. "
                 "This episode is sponsored by Acme. Go to acme.com slash show for 20 percent off.")
        # A sign-off two sister feeds share (pending clip 1290; clip 1297 was marked Keep).
        signoff = ("Thank you for listening to the Island Spanish podcast. To get access to show notes for all of "
                   "our lessons, visit islandspanish.com and sign up so you hear about it every time a new lesson "
                   "is available. We will see you in the next one, and until then keep practising every day.")
        # A show's closing credits (pending clips 1420, 1568).
        credits = ("Our Show is a production of Big Network Media. For more podcasts from Big Network, visit "
                   "bignetwork.com, or find us in the app, on Apple Podcasts, or wherever you get your podcasts.")
        for text in (patreon, fused, signoff, credits):
            self.assertFalse(is_sponsor_read(text))
            self.assertLess(ad_confidence(43.0, self._rows(43.0, ["Own"]), 1, 6, None, text), 75)
        rows = self._rows(43.0, ["Island Spanish", "Sister Feed"])
        self.assertLess(ad_confidence(43.0, rows, 2, 6, suggest(43.0, rows, 2, 6), signoff), 75)

    def test_only_scorable_clips_are_transcribed(self):
        import tempfile

        from snorkelwaffle import config
        from snorkelwaffle.db import Database
        from snorkelwaffle.engine import Engine
        with tempfile.TemporaryDirectory() as d:
            db = Database(f"{d}/t.db")
            eng = Engine(db, config.Env(library_dirs=[d], data_dir=d, nice=0))
            for cid, dur in ((1, 12.0), (2, 200.0), (3, 30.0)):
                db.x("INSERT INTO clips (id, fp, duration, preview, created_at) VALUES (?, x'00', ?, 'p.mp3', 0)", (cid, dur))
            self.assertEqual(eng.next_untranscribed_clip()["id"], 3)
