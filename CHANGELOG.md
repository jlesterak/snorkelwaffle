# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Commits follow [Conventional Commits](https://www.conventionalcommits.org/).

## [Unreleased]

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
