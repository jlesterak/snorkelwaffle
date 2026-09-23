# TODO

## [IN PROGRESS]

- Validate on real episodes from nicebox (`/storage/media/podcasts`).
  Synthetic tests put boundaries within ±0.6 s, with one outlier at +0.9 s.
  Real dynamically inserted ads may behave differently. Suggested check: copy
  3–4 episodes of one show locally, run `python -m snorkelwaffle compare
  *.mp3`, and listen at the reported times.

## [PENDING]

- Boundary refinement: after a fingerprint match, align the decoded audio
  (~8 kHz, ±3 s) around each edge to get cut points to tens of milliseconds.
  The ±1 s fingerprint resolution comes from chromaprint's ~2.6 s window.
- Publish the image to a registry (GHCR) so the NAS can pull it rather than
  build it. Needs a repo and push approval.
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
