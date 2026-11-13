# TODO

## [IN PROGRESS]

- Jake decides whether to set auto-approve to `confident` (still `off`). The
  ad score was tightened on 2026-11-13 (unreleased, not deployed): see the
  completed entry below for the numbers. Before deciding:
  1. Re-run `scripts/eval_confidence.py` on a fresh copy of the live database.
     The 2026-11-13 numbers come from the 2026-10-28 copy because the server
     was unreachable. That copy has only 9 of the 20 spot-check clips and none
     of the S-Town, Radiolab, Bitcherton or Srsly Wrong ones, so the theme-song
     and house-pitch rules are covered by unit tests only, not by real clips.
  2. Clip 365 (Hey Riddle Riddle, 122 s): its transcript is an in-character
     Rocket Money read ending in a URL. Similar clips 379 and 415 were marked
     Ad, 395 and 400 Keep. Decide it; if it is an ad, the 100 s limit on
     one-show reads (`ONE_SHOW_READ_SECONDS`) can go, which also gets back real
     ads such as pending clips 130 and 1325.
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
  (14 ads, 3 wrong, 3 unsure of 20). Held-out test set (216 reviewed clips) at
  75: 48 ads / 0 keeps cut, recall 44% (was 58 / 0, 54%); all 526: 124 / 0 (was
  140 / 1). At most 5.3 wrong cuts per 100 at 95% confidence. Pending clips in
  the 2026-10-28 copy reaching 75: 33 of 848 (was 44); 2 of the 33 look
  doubtful by transcript (was 8 of 44). Threshold stays 75. Eval:
  `scripts/eval_confidence.py`. See `CHANGELOG.md`.
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
