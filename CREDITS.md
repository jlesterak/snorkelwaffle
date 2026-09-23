# Credits

snorkelwaffle's own source code is released into the public domain under the
[Unlicense](LICENSE). No code was copied from the projects below. They are
credited because their ideas shaped this one, or because snorkelwaffle runs
them.

## Prior art and inspiration

- **[MinusPod](https://github.com/ttlequals0/minuspod)** (MIT, © Hemant Kumar and
  contributors; originally [hemant6488/podcast-server](https://github.com/hemant6488/podcast-server)).
  MinusPod showed that Chromaprint fingerprinting catches dynamically inserted
  ads well, and it introduced the idea of learning ad signatures once and
  reusing them across episodes. Its cross-episode "recurring body segment"
  discovery is the direct inspiration for snorkelwaffle's clip discovery.
  snorkelwaffle is an independent, fingerprint-only reimplementation for
  local libraries, with no transcription or LLM.
- **[Podcast_Free_Ads](https://github.com/georgewangyu/Podcast_Free_Ads)** by
  George Wang: an early prototype of storing fingerprints across episodes and
  treating repeated matches as ad candidates.
- **[Kuulla issue #779](https://github.com/two4suited/kuulla/issues/779)**:
  discusses detecting ads by fingerprinting segments that recur across a
  show's episodes.
- **[audfprint](https://github.com/dpwe/audfprint)** by Dan Ellis, and the
  landmark/"seed and extend" matching literature it comes from. The matcher's
  "exact-hash seeds vote for a time offset, then verify along it" design
  follows this well-known approach.
- **[Podly](https://github.com/podly-pure-podcasts/podly_pure_podcasts)** and
  **[Podcast Ad Remover](https://github.com/jdcb4/podcast-ad-remover)**: the
  transcription/LLM approach this project deliberately avoids. Worth a look if
  you want host-read ads removed too.

## Runtime dependencies

These are not part of this repository's source. The Docker image bundles them
under their own licenses:

- **[Chromaprint](https://acoustid.org/chromaprint)** (`fpcalc` / libchromaprint) by
  Lukáš Lalinský, LGPL-2.1: the audio fingerprints everything here is built on.
- **[FFmpeg](https://ffmpeg.org/)**, LGPL/GPL: decoding, lossless cutting, and previews.
- **[NumPy](https://numpy.org/)**, BSD-3-Clause: vectorised fingerprint matching.
- **[Python](https://www.python.org/)** and **[Alpine Linux](https://alpinelinux.org/)** base image.
- **[su-exec](https://github.com/ncopa/su-exec)**, MIT: drops privileges to PUID/PGID.

## Integrations

- **[Audiobookshelf](https://www.audiobookshelf.org/)** (GPL-3.0): snorkelwaffle
  only calls its HTTP API (`/api/libraries`, `/api/libraries/{id}/scan`).
- **[DockSTARTer](https://dockstarter.com/)**: the override file follows its
  variable conventions.
