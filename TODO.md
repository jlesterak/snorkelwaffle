# TODO

## [IN PROGRESS]

- Real-episode validation, local copies in `testdata/` of 5 shows × 5
  episodes.
  - Detection, cutting, intro/outro hints and exact boundaries are confirmed.
  - Still to do: tune confidence weights against more reviewed clips.

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
