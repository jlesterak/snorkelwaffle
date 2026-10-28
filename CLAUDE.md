# Snorkelwaffle (podcast ad cutter)

Public GitHub repo (`origin`, no icebox mirror). Keep private hostnames out of commits.

- Python (`snorkelwaffle/`), tests in `tests/` (`pytest`, lint with `ruff`), Docker image published to GHCR on a version tag (SemVer, Keep a Changelog).
- Real-episode test data lives in gitignored `testdata/`; never commit episodes or the live database.
- Cutting content costs more than missing an ad: any confidence change needs a precision target and a before/after table in the changelog.
- Runs on the home server as a DockSTARTer app (`dockstarter/` has the override and env example).
- Image is Debian slim, not Alpine: faster-whisper's ctranslate2 ships only glibc wheels. CI runs on `ubuntu-latest` (ffmpeg 8); keep the suite green on ffmpeg 6–8.
- Confidence/transcript analysis scripts live in `testdata/refit-2026-10-28/` and `testdata/whisper-proto/` (`eval_real.py` gives the before/after table).
