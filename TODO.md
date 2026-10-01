# TODO

## [IN PROGRESS]

- Real-episode validation, local copies in `testdata/` of 5 shows × 5
  episodes.
  - Detection, cutting, intro/outro hints and exact boundaries are confirmed.
  - Still to do: tune confidence weights against more reviewed clips.
- Data-driven auto-approve, blocked until icebox finishes scanning and every
  clip has been reviewed by hand.
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
- Live trial on icebox (DockSTARTer, v0.2.1, port 8484), deployed 2026-09-24
  (v0.2.1 on 2026-10-01).
  - Still to do: set `SNORKELWAFFLE_ABS_TOKEN` in icebox's `.env` so cuts
    trigger Audiobookshelf rescans.

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

- 2026-10-01: Released v0.2.1.

- 2026-10-01: Files under 100 KB are marked "incomplete", not "error".
  - On icebox, 42 of the 44 errors were 0-byte or stub Audiobookshelf
    downloads. Only Dr. Gameshow "185. Sassy Caucus" has no good copy.
  - The other 2 errors are a partial E474 download and a Vogue promo file
    whose fingerprint came out empty. Both episodes already have a good copy.

- 2026-09-23: Released v0.2.0.

- 2026-09-23: Per-show modes (normal / review only / skip) and a "maybe a
  preview" hint.
  - Tested on the Magic Tavern ad-free feed: its Patreon-episode preview is
    now hinted, scored 45 and never auto-approved.
  - Checked edge-seam (energy dip) as an automatic preview detector on real
    episodes and rejected it. Previews are edited at pauses, just like ads.
- 2026-09-23: Exact boundaries, ad confidence score, `confident`
  auto-approve, cross-show discovery, and a schema v2 migration.
  - Waveform alignment gives about ±50 ms on real episodes; tests assert
    ±0.08 s.

- 2026-09-23: GitHub repo, CI (ruff + pytest), and a tag-driven release
  pipeline.
  - Images go to `ghcr.io/jlesterak/snorkelwaffle`, multi-arch.
  - Releases use SemVer, Keep a Changelog and Conventional Commits.

- 2026-09-23: Initial build (v0.1.0).
  - Chromaprint fingerprinting (ffmpeg muxer or fpcalc).
  - Seed-and-extend matcher.
  - Clip discovery, cross-library sweep and hints.
  - Lossless in-place cutting that keeps chapters, tags and cover art.
  - Originals with a size and age cap; restore.
  - Audiobookshelf rescan.
  - Web UI (overview, review, episodes, settings, log).
  - Docker image (Alpine, PUID/PGID), DockSTARTer override.
  - Unlicense and credits.
  - Test suite (7 tests, all passing locally and inside the image).
