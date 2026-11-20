# Third-party notices

Upmix51's own source code (the `app/` folder, `Dockerfile` and documentation) is released under the [MIT licence](LICENSE). It has **no third-party Python dependencies**: it uses only the Python standard library.

The Docker image built from the `Dockerfile` downloads and includes the following third-party software. Upmix51 does **not** ship these components in this repository.

| Component | Where it comes from | Licence |
|---|---|---|
| Python 3.12 | `python:3.12-slim` official Docker image | [PSF License](https://docs.python.org/3/license.html) |
| Debian base system | included in `python:3.12-slim` | various free licences, see `/usr/share/doc/*/copyright` in the image |
| FFmpeg / FFprobe (static build) | [`mwader/static-ffmpeg`](https://github.com/wader/static-ffmpeg) Docker image | FFmpeg is LGPL 2.1+, but this build enables GPL components (e.g. x264, x265), so the binaries are distributed under the **GPL v2+**. Source code: https://ffmpeg.org and https://github.com/wader/static-ffmpeg |

## If you redistribute a built image

Building the image yourself from this repository is not a redistribution. If you **publish a built image** (for example on Docker Hub or GHCR), that image contains GPL-licensed FFmpeg binaries, so you must:

1. include the FFmpeg licence and this notice;
2. offer the corresponding source code (a link to the exact `mwader/static-ffmpeg` tag and its sources is the usual way);
3. not add restrictions beyond those of the GPL.

## Online services

Cover search contacts third-party services (iTunes Search API, Deezer API, MusicBrainz / Cover Art Archive and, optionally, TMDB). No data from those services is included in this repository. See [LEGAL.md](LEGAL.md) for their terms of use.
