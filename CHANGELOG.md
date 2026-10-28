# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Commits follow [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

## [0.3.1] - 2026-10-28

### Fixed

- Works with ffmpeg 8. Known clips now only have to match all but their
  unreliable edge values (the same ~2 s allowance already used for edges),
  not the full minimum clip length. Under ffmpeg 8's MP3 decoding, a 9.9 s
  outro matched 64 of the 65 required values after a cut, so it stopped being
  recognised. Discovery of new clips still requires the full minimum. The test
  suite passes on ffmpeg 6.1, 7.1 (the image) and 8.0.
- v0.3.0 was tagged but never published: GitHub's `ubuntu-latest` moved to
  ffmpeg 8 and the release tests failed on the issue above. 0.3.1 includes
  everything listed under 0.3.0.

## [0.3.0] - 2026-10-28 [YANKED]

### Added

- Optional clip transcripts (Settings → Detection → Transcribe clips, off by
  default). Each clip preview is transcribed once with faster-whisper
  (`base.en`, CPU, int8, 1 thread, downloaded into `/config/models` on first
  use). A clip of 20–130 s with two or more sponsor phrases (promo code, URL,
  "sponsored by", "free trial", …) gets +35 ad score. That is enough for an
  ad heard on only one show to reach `confident` auto-approve. The clip page
  shows the transcript.

  Labelled clips (TP = ad cut, FP = real content cut), scored by the code in
  this release with and without transcripts:

  | Threshold | Without TP / FP | With TP / FP |
  |---|---|---|
  | 65 | 71 / 0 | 144 / 2 |
  | 70 | 71 / 0 | 143 / 2 |
  | **75 (default)** | **71 / 0** (26% of ads) | **140 / 1** (52% of ads, 99.3% precision) |
  | 85 | 44 / 0 | 89 / 1 |

  The one false positive is a song lyric ("go to …") in a show's own jingle.
  The keepers that hold sponsor phrases are mostly long in-character ads,
  which is why the bonus stops at 130 s.

- A startup warning when `ABS_URL` is set without `ABS_TOKEN` (or the other way
  round): Audiobookshelf rescans after cuts would otherwise never run, silently.

### Changed

- The image is now based on `python:3.12-slim` (Debian) instead of Alpine,
  because faster-whisper's engine (ctranslate2) ships only glibc wheels.
  Fingerprinting now uses Debian ffmpeg's chromaprint muxer instead of
  `fpcalc`, and `gosu` replaces `su-exec`. The image grows from 96 MB to
  360 MB compressed (378 MB to 1.44 GB unpacked): about half is Debian's
  ffmpeg, half is faster-whisper and its dependencies.

- Ad confidence refitted on 526 hand-reviewed clips (268 ad / 258 keep, icebox
  2026-10-28), and the default `confident` auto-approve threshold lowered from
  85 to 75. Target: at least 98% precision, because cutting real content costs
  more than missing an ad.
  - The cross-show bonus now needs the clip spread across shows: no single
    show may hold 90% or more of its occurrences. Every false positive at the
    old default was a show's own sting that one other show also played.
  - Clips under 20 s lose 20 points (214 of the 243 reviewed were keeps).
  - Dropped the "moves around" (+10) and "4+ episodes" (+5) bonuses:
    recurring show jingles do both, so they rewarded the wrong clips.
  - A clip heard on one show now tops out at 55 and always waits for review;
    no single-show rule reached the precision target (best: 94%).

  Labelled clips (TP = ad cut, FP = real content cut), old vs new scoring:

  | Threshold | Old TP / FP | New TP / FP |
  |---|---|---|
  | 65 | 117 / 44 | 71 / 0 |
  | 70 | 96 / 22 | 71 / 0 |
  | **75 (new default)** | 85 / 9 | **71 / 0** |
  | 85 (old default) | 85 / 9 | 44 / 0 |

  Recall at the new default is 26% (71 of 268 ads), and precision is 100% on
  this set. With 0 errors in 71, the false-cut rate is under about 4%
  (rule of three), and the bound tightens as more clips are reviewed. Cut ads
  lose their occurrences when the episode is re-analysed, so their features
  were rebuilt from the cuts log. A saved threshold in Settings is kept; only
  the default changes.

## [0.2.1] - 2026-10-01

### Changed
- Audio files under 100 KB are now marked "incomplete" instead of "error",
  so failed downloads stop filling the problems list. Audiobookshelf leaves
  0-byte `name (uuid).mp3` retries behind; on icebox, 42 of the 44 errors
  were small files like this. Such a file is analysed normally once it
  grows, and existing error rows for small files are reclassified on
  startup.

## [0.2.0] - 2026-09-23

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

[Unreleased]: https://github.com/jlesterak/snorkelwaffle/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/jlesterak/snorkelwaffle/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/jlesterak/snorkelwaffle/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/jlesterak/snorkelwaffle/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/jlesterak/snorkelwaffle/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jlesterak/snorkelwaffle/releases/tag/v0.1.0
