# TODO

## [IN PROGRESS]

- Jake decides whether to set auto-approve to `confident` (still `off`). The
  ad score was tightened on 2026-11-13 (unreleased, not deployed): see the
  completed entry below for the numbers. Before deciding:
  1. Clip 365 (Hey Riddle Riddle, 122 s): its transcript is an in-character
     Rocket Money read ending in a URL. Similar clips 379 and 415 were marked
     Ad, 395 and 400 Keep. Decide it; if it is an ad, the 100 s limit on
     one-show reads (`ONE_SHOW_READ_SECONDS`) can go, which also gets back real
     ads such as pending clips 130 and 1325.
  2. Trailers for other podcasts: decided clip 317 (Keep) still scores 90, and
     pending clip 1547 is the same kind. Other trailers were marked Ad. If
     they should be kept, the score needs a rule for them.
  3. Release, deploy, then look at what the Review page lists at 75 or more.
- Real-episode validation, local copies in `testdata/` of 5 shows × 5
  episodes.
  - Detection, cutting, intro/outro hints and exact boundaries are confirmed.
- Keep reviewing pending clips (1,392 pending, 526 decided on 2026-11-11; 848
  pending on 2026-10-28). Once many more are decided, re-run the refit check to
  tighten the precision bound.

## [PENDING]

- Smaller image (now 1.44 GB unpacked since the Debian switch): a
  static ffmpeg build with chromaprint, and installing faster-whisper without
  onnxruntime (68 MB, only used for VAD, which is off). Only if size matters.
- Optional pluggable detectors for host-read ads (Whisper and an LLM, off by
  default and never required).
- UI: waveform view for adjusting a single occurrence's boundaries by hand.
- UI: merge two clips that turn out to be the same ad.
- Sweep performance for very large libraries (5,000+ episodes): an inverted
  index of fingerprint values instead of streaming every fingerprint per sweep.
- Submit the app to DockSTARTer's app catalogue, once it has been proven in
  use.

## [COMPLETED]

- [COMPLETED] 2026-11-13: ad score tightened after the 2026-11-11 spot-check
  (14 ads, 3 wrong, 3 unsure of 20). On the live database, held-out test set
  (216 reviewed clips) at 75: 47 ads / 1 keep cut, recall 44% (was 57 / 1,
  53%); all 526: 124 / 1 (was 140 / 2). 2.1 wrong cuts per 100 measured, at
  most 8.8 at 95% confidence. Spot-check: 14 of 14 ads still reach 75, 0 of
  the 3 wrong and 0 of the 3 unsure. Pending clips reaching 75: 76 of 1,393
  (was 98). Threshold stays 75. Eval: `scripts/eval_confidence.py`. See
  `CHANGELOG.md`.
- [COMPLETED] 2026-11-03: `multi_show` auto-approve now requires that no one
  show holds 90%+ of a clip's occurrences (same rule as the ad score).
- [COMPLETED] 2026-11-03: decided clips keep their counts and ad score after a
  cut episode is re-analysed (counts never go down for ad/keep clips).
- [COMPLETED] 2026-10-28: released v0.3.1 and v0.3.2 (refit, optional clip transcripts, ffmpeg 8 matching fix, 1 GB memory default); v0.3.0 tag never published. icebox on 0.3.2 with transcripts on.
- [COMPLETED] 2026-10-28: optional clip transcripts (faster-whisper `base.en`), giving
  a +35 ad-score bonus for sponsor phrases. Labelled: 140 ad / 1 keep at 75 (was
  71 / 0). Image moved to Debian slim. Prototype and evaluation scripts are in
  `testdata/whisper-proto/`.
- [COMPLETED] 2026-10-28: ad-confidence refit on 526 reviewed clips; the default
  threshold is now 75 (71 ad / 0 keep at 75, was 85 / 9 at 85). See `CHANGELOG.md`.
- [COMPLETED] 2026-10-26: live trial on icebox (DockSTARTer, port 8484); Audiobookshelf rescans confirmed on real cuts.
- Releases v0.1.0 to v0.2.1 (2026-09-23 to 2026-10-01): see `CHANGELOG.md`.
