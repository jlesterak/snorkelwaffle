# TODO

## [IN PROGRESS]

- Real-episode validation, local copies in `testdata/` of 5 shows × 5
  episodes.
  - Detection, cutting, intro/outro hints and exact boundaries are confirmed.
  - Still to do: tune confidence weights against more reviewed clips.
- Data-driven auto-approve, blocked until every clip has been reviewed by hand.
  Library scan is done (2026-10-26: 5,205 episodes analysed, none queued);
  review stands at 524 decided (268 ad / 256 keep) and 849 pending.
  - Copy icebox's `/config/snorkelwaffle.db` into `testdata/` (gitignored).
  - Analyse the user-decided clips (`ad` / `keep`) against confidence and
    each feature: shows, episodes, position, duration, BER, hint.
  - Refit the `ad_confidence` weights and pick a single default threshold
    with a strict precision target, since cutting real content costs more
    than a missed ad.
  - Ship the new weights and default with a before/after table in the
    changelog.
  - 2026-10-01: 454 clips user-decided (246 ad / 208 keep) and 800 pending,
    all of them scoring under 60. At the current weights, a threshold of 75
    gives 94% precision and 52% recall.
  - Leads for the refit:
    - The cross-show bonus fires on stings heard mostly on one show (all 8
      false positives above 75).
    - Duration is underweighted: clips under 20 s were 157 keep / 28 ad.
    - "4+ episodes" and "moves around" reward short jingles.

## [PENDING]

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

- [COMPLETED] 2026-10-26: live trial on icebox (DockSTARTer, port 8484, v0.2.1 since
  2026-10-01). Audiobookshelf rescans confirmed on real cuts (logs 2026-10-23 and
  2026-10-25) after `SNORKELWAFFLE_ABS_TOKEN` was set (owner, 2026-10-19).
- Releases v0.1.0 to v0.2.1 (2026-09-23 to 2026-10-01): see `CHANGELOG.md`.
