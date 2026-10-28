# TODO

## [IN PROGRESS]

- Real-episode validation, local copies in `testdata/` of 5 shows × 5
  episodes.
  - Detection, cutting, intro/outro hints and exact boundaries are confirmed.
- Keep reviewing pending clips (848 on 2026-10-28). Once many more are
  decided, re-run the refit check to tighten the precision bound.

## [PENDING]

- `multi_show` auto-approve has the same flaw the refit fixed: it fires on a
  show's own sting that one other show played (labelled: 85 ad / 9 keep).
  Either apply the same "no show holds 90%+" rule or drop the mode in favour of
  `confident`.
- Cut ads lose their occurrence rows when the episode is re-analysed, so their
  ad score and episode count in the UI drop to 0 afterwards. Keep the
  pre-cut stats or skip recomputing decided clips.
- Smaller image: Alpine's ffmpeg pulls in ~250 MB of codec libraries. A minimal
  static ffmpeg build (mp3/aac/opus/flac only) could get it under ~120 MB.
- Optional pluggable detectors for host-read ads (Whisper and an LLM, off by
  default and never required).
- UI: waveform view for adjusting a single occurrence's boundaries by hand.
- UI: merge two clips that turn out to be the same ad.
- Sweep performance for very large libraries (5,000+ episodes): an inverted
  index of fingerprint values instead of streaming every fingerprint per sweep.
- Submit the app to DockSTARTer's app catalogue, once it has been proven in
  use.

## [COMPLETED]

- [COMPLETED] 2026-10-28: ad-confidence refit on 526 reviewed clips; the default
  threshold is now 75 (71 ad / 0 keep at 75, was 85 / 9 at 85). See `CHANGELOG.md`.
- [COMPLETED] 2026-10-26: live trial on icebox (DockSTARTer, port 8484, v0.2.1 since
  2026-10-01). Audiobookshelf rescans confirmed on real cuts (logs 2026-10-23 and
  2026-10-25) after `SNORKELWAFFLE_ABS_TOKEN` was set (owner, 2026-10-19).
- Releases v0.1.0 to v0.2.1 (2026-09-23 to 2026-10-01): see `CHANGELOG.md`.
