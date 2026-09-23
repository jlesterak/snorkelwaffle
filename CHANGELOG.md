# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Commits follow [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

### Added
- Exact boundaries: when a clip is created, its edges are measured by lining
  up the decoded audio of two episodes. Every occurrence is then placed by
  cross-correlating a few seconds of audio around each edge. On real episodes
  that gives about ±50 ms, down from about ±1 s. It can be turned off in
  Settings ("Exact boundaries"). Clips from earlier versions are refined in
  the background, and times that are still approximate show as "≈" in the UI.
- Ad confidence score (0–100) for every clip, built from:
  - how many shows it's heard on;
  - whether it's a standard ad length (15/30/45/60/90/120 s);
  - whether it moves between or within episodes;
  - match quality and number of repeats.

  The review list sorts by score, and each clip shows it.
- `confident` auto-approve mode with a threshold (default 85). Clips at or
  above it are cut automatically. Anything below, including clips heard only
  a couple of times, waits for review. Clips that look like intros or outros
  are never auto-approved.
- Per-show modes in Settings → Shows:
  - **Normal**;
  - **Review only**: clips heard only in that show are never auto-approved,
    for ad-free and Patreon feeds where repeats are usually previews or plugs;
  - **Skip**: the show is never analysed, matched or cut.
- "Maybe a preview" hint: a clip found in only 2 episodes of one show at a
  non-standard length is flagged as a possible preview or excerpt of the show
  itself. It loses 10 points and is never auto-approved.
- Cross-show discovery: each new episode is also compared with a few episodes
  of other shows downloaded around the same time (default 4), to catch ads a
  network runs across several shows.

### Changed
- Compare each new episode against 8 same-show episodes by default (was 6).
- The `likely` auto-approve mode is replaced by `confident`. A saved `likely`
  setting carries over as `confident`.
- Database schema v2, migrated automatically on start.

## [0.1.0] - 2026-09-23

### Added
- Chromaprint fingerprinting through ffmpeg's muxer, with `fpcalc` as a fallback.
- Seed-and-extend matcher with calibrated boundaries.
- Clip discovery against nearby episodes of the same show, then a sweep across
  the whole library, including other shows.
- Review hints ("heard on N shows", "likely intro/outro"). Optional
  auto-approve (`multi_show` / `likely`).
- Lossless in-place cutting (same inode) that keeps tags and cover art and
  remaps chapters.
- Originals kept under a size and age cap; one-click restore.
- Audiobookshelf library rescan via its API.
- Web UI: overview, keyboard-driven review, episodes with a timeline,
  settings, log. Optional basic auth.
- Alpine Docker image (amd64/arm64) with PUID/PGID, a DockSTARTer override, and
  a `/healthz` endpoint.
- Released under the Unlicense, with credits for prior art (MinusPod and
  others).

[Unreleased]: https://github.com/jlesterak/snorkelwaffle/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jlesterak/snorkelwaffle/releases/tag/v0.1.0
