# snorkelwaffle

Finds audio that repeats across your podcast episodes, such as the same ads
stitched into every file your podcast server downloaded. You review each
repeated clip **once**, and it cuts the ads out of every episode in place.

- **No cloud, no GPU, no LLM, no transcription.** It works from Chromaprint
  audio fingerprints and plain numpy.
- **Built for a NAS.** One worker runs one job at a time at idle CPU and IO
  priority. Idle memory is ~30 MB. A one-hour episode takes a few seconds to
  fingerprint, and comparing two episodes takes milliseconds.
- **Works on the library you already have.** Point it at the folder
  Audiobookshelf downloads into. There are no feeds to swap and no apps to
  change.
- **Exact cuts.** Fingerprints find a clip to about ±1 s. The edges are then
  pinned to about ±50 ms by lining up the actual audio, so no clipped words
  and no ad tails.
- **Lossless and reversible.** Cuts use stream copy with no re-encode. Tags,
  cover art and (remapped) chapters are kept. The file is overwritten in
  place, keeping its inode, so Audiobookshelf sees the same file. Originals are
  kept up to a size and age cap so any episode can be restored.
- **Web UI** for reviewing clips (with keyboard shortcuts), browsing episodes
  with a timeline, restoring originals, and changing settings.

It catches ads that are **the same audio** in more than one place:
dynamically inserted ads, network promos, and pre-recorded sponsor reads
reused across episodes. It **can't** catch host-read ads that are different
every time; that needs transcription, which this project deliberately leaves
out. See [CREDITS.md](CREDITS.md) for tools that do it.

## How it works

1. **Fingerprint.** Each episode gets a Chromaprint fingerprint (~8 values per
   second).
2. **Discover.** The episode is compared with its nearest 8 episodes from the
   same show, and with 4 episodes of other shows downloaded around the same
   time. Any stretch of audio shared between them (8 s to 5 min by default)
   becomes a **clip**. Two occurrences are enough.
3. **Pin the edges.** The clip's two copies are lined up sample by sample to
   find exactly where the shared audio starts and ends. A few seconds around
   each edge are kept so every later occurrence can be placed just as exactly.
4. **Sweep.** New clips are looked for across the whole library, including
   other shows. Network ads often turn up on several shows.
5. **Review.** Each clip gets a hint:
   - *Likely ad*: heard on 2 or more shows, or typical ad length and moves around.
   - *Likely intro/outro*: sits at the same spot in most episodes.

   It also gets an **ad score** from 0 to 100. You mark it **Ad** (cut
   everywhere) or **Keep**. With auto-approve set to `confident`, clips
   scoring 85 or more are cut without asking and the rest wait for you.
6. **Cut.** Every episode containing an approved ad is cut losslessly. It is
   then re-fingerprinted to confirm the ad is gone, and Audiobookshelf is asked
   to rescan.

## Quick start (DockSTARTer)

1. The image is published as `ghcr.io/jlesterak/snorkelwaffle` (amd64 and arm64).
   Tags: `latest`, `0.1`, `0.1.0`. Pin a version with `SNORKELWAFFLE_IMAGE` if you prefer.
2. Merge [`dockstarter/docker-compose.override.yml`](dockstarter/docker-compose.override.yml)
   into `~/.docker/compose/docker-compose.override.yml`.
3. Optional: add the variables from [`dockstarter/env.example`](dockstarter/env.example)
   to `~/.docker/compose/.env`. At minimum, set `SNORKELWAFFLE_ABS_TOKEN` so it
   can trigger Audiobookshelf rescans.
4. `ds -c up snorkelwaffle` (or `docker compose up -d snorkelwaffle` in `~/.docker/compose`).
5. Open `http://<nas>:8484`.

The override mounts DockSTARTer's storage folder at `/storage` (the same path
Audiobookshelf sees), so `/storage/media/podcasts` works unchanged.

Standalone compose: see [`docker-compose.yml`](docker-compose.yml).

### First run

A fresh install starts with **auto-approve off**. Nothing is cut until you mark
a clip as an ad. Let it work through the library (the Overview page shows
progress), then open **Review**:

- `↑`/`↓` move, `Space` plays the clip, `A` marks it as an ad, `K` keeps it,
  `U` undoes the decision.
- **Where?** lists every episode containing the clip. Its play buttons add 3 s
  either side so you can check the boundaries.
- Once you trust it, set **Auto-approve** to `confident`. Clips with an ad
  score of 85 or more are then cut without asking, and lower scores wait for
  review. `multi_show` is a stricter option: it only auto-cuts clips heard on
  2 or more shows.

To see what it would do before any file changes, turn **Cutting enabled** off
in Settings. Everything else (analysis, discovery, review) keeps working.

## Configuration

### Environment (deployment wiring, read-only in the UI)

| Variable | Default | Purpose |
|---|---|---|
| `LIBRARY_DIRS` | `/storage/media/podcasts` | Comma-separated podcast folders. Each sub-folder is treated as a show. |
| `DATA_DIR` | `/config` | Database, originals, previews. |
| `PORT` | `8484` | Web UI port. |
| `ABS_URL` | (empty) | Audiobookshelf URL, e.g. `http://audiobookshelf:80`. |
| `ABS_TOKEN` | (empty) | Audiobookshelf API token (Settings → Users → your user). |
| `ABS_LIBRARY_ID` | auto | Library to rescan. By default it's worked out from the edited file's path. |
| `WEB_USERNAME` / `WEB_PASSWORD` | (empty) | Optional HTTP basic auth for the UI. |
| `PUID` / `PGID` / `UMASK` | `1000` / `1000` / `002` | User that runs the app and owns `/config`. Use the same values as Audiobookshelf. |
| `NICE` | `10` | CPU niceness for the worker and ffmpeg (IO always uses the idle class). |
| `SW_<SETTING>` | (none) | Seeds a UI setting until it's changed in the UI, e.g. `SW_AUTO_APPROVE=multi_show`. |

### Settings (web UI)

| Group | Settings |
|---|---|
| Cutting | Cutting enabled, auto-approve (`off` / `multi_show` / `confident`) and its threshold, start/end padding, Audiobookshelf rescan |
| Detection | Shortest and longest clip, same-show and other-show episodes to compare, minimum repeats, exact boundaries, match across shows, match tolerance |
| Library | Scan interval, settle time (skip files still downloading), backlog window |
| Originals | Size cap (GB) and maximum age (days). A cap of 0 keeps nothing, which means cuts can't be undone. |

## Resource notes for a QNAP (or any small NAS)

- The compose files cap the container at 1 CPU and 512 MB. Real use is far
  below that.
- The first pass over a big back catalogue is the heaviest step, because every
  file is decoded once. Expect roughly 5–15 s per hour of audio on a Celeron,
  running in the background at idle priority. After that, only new episodes
  are processed.
- Fingerprints take ~115 KB per hour of audio in the SQLite database.
- Originals take as much space as the files they back up, which is why the cap
  exists.

## CLI

```sh
python -m snorkelwaffle                 # web UI + worker (what the container runs)
python -m snorkelwaffle compare a.mp3 b.mp3 c.mp3   # print audio shared between files; no database
```

## Development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q          # synthetic-audio tests; needs ffmpeg (+ chromaprint muxer or fpcalc)
```

It needs Python 3.12 or later, ffmpeg, and either ffmpeg's chromaprint muxer
or `fpcalc`.

## Versioning and releases

- Versions follow [SemVer](https://semver.org/), and changes are recorded in
  [CHANGELOG.md](CHANGELOG.md).
- To cut a release:
  1. Bump `__version__` in `snorkelwaffle/__init__.py`.
  2. Move the `Unreleased` notes into a new version section.
  3. Commit and tag `vX.Y.Z`.
- Pushing the tag builds and publishes the image and creates a GitHub Release.
  CI refuses a tag that doesn't match `__version__`.

## License

[Unlicense](LICENSE) (public domain). Credits and third-party licenses are in
[CREDITS.md](CREDITS.md).
