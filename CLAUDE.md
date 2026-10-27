# Snorkelwaffle (podcast ad cutter)

Public GitHub repo (`origin`, no icebox mirror). Keep private hostnames out of commits.

- Python (`snorkelwaffle/`), tests in `tests/` (`pytest`, lint with `ruff`), Docker image published to GHCR on a version tag (SemVer, Keep a Changelog).
- Real-episode test data lives in gitignored `testdata/`; never commit episodes or the live database.
- Cutting content costs more than missing an ad: any confidence change needs a precision target and a before/after table in the changelog.
- Runs on the home server as a DockSTARTer app (`dockstarter/` has the override and env example).
