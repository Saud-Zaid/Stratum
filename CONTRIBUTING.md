# Contributing to Stratum

Thank you for helping. This file describes how a change reaches `main` and how a release is made. Report a bug or ask a question in the [issue tracker](https://github.com/Saud-Zaid/Stratum/issues); report a security problem as [SECURITY.md](SECURITY.md) describes, not in a public issue.

## How a change reaches `main`

`main` is protected: nobody pushes to it directly, the maintainer included. Every change goes through a pull request.

1. **Branch from an up-to-date `main`**, one branch per logical change. Name it after the kind of change: `feat/…`, `fix/…`, `docs/…`, `ci/…` or `chore/…` (`release/…` is kept for releases, below).
2. **Open a pull request** and fill in the template: what changed, why, how it was tested, and the changelog line.
3. **Title it `type: description`**, for example `fix: retry a locked index store`. The type is one of `feat`, `fix`, `docs`, `ci`, `chore`, `refactor`, `test`, `perf`, `build` or `release`. A check enforces it, because the squash merge makes the title the commit message on `main`.
4. **Add a line under `## [Unreleased]`** in [CHANGELOG.md](CHANGELOG.md) when users will notice the change, using the headings of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) (`Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`).
5. **CI must pass** on Ubuntu and macOS. Windows runs too; it is experimental during the beta, so its result is shown but does not block.
6. **The maintainer labels and merges.** Labels (`feature`, `fix`, `docs`, `ci`, `release`) group the pull request in the release notes. Merges are squash merges, and the branch is deleted after the merge.

Before you push, `.venv/bin/stratum-audit --ratchet` must print `GATE CLEAR`; the pre-commit hook runs it for you once `setup.sh` has enabled it.

No commit message or pull request may name an AI model as an author or helper: no `Co-Authored-By:` trailer for a model and no "Generated with …" line. A check rejects such a pull request.

Stratum is built from a source tree that the maintainer keeps. An accepted change is applied there and arrives here in a maintainer pull request that links yours.

## How a release is made

Every version from `1.0.0-beta.5` on has its own release branch, `release/<version>` (for example `release/1.0.0-beta.5`).

1. The maintainer creates `release/<version>` from an up-to-date `main` and opens a pull request from it titled `release: <version>`. It moves the `[Unreleased]` lines under the new version and raises the version in `VERSION`, `CITATION.cff`, `CHANGELOG.md`, `pyproject.toml` and `uv.lock`.
2. After the squash merge, the maintainer tags the merge commit on `main` with `v<version>`. The release branch is kept, not deleted: its last commit holds the same files as the tag. The release workflow builds the archives, checksums, SBOM and attestation, and publishes the release with this version's changelog section and the merged pull requests since the last published release.
3. Versions follow [Semantic Versioning](https://semver.org/): `-beta.N`, then `-rc.N`, then the final `X.Y.Z`. A tag with a hyphen is published as a pre-release.
4. Tags cannot be moved or deleted; release branches cannot be deleted or rewritten. A broken release is never retagged: its changelog heading is marked `[YANKED]` and the fix ships as a new version.

## Branches that stay

Change branches are deleted after the merge; the pull request is the record. Two kinds of branch stay:

- `main`, where all work lands.
- `release/<version>`, one per version from `1.0.0-beta.5` on, holding the files that version shipped. A fix for users who cannot upgrade goes to that branch through a pull request and ships as a new version; every other fix goes to `main` and ships in the next version.
