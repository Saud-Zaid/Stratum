# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0-beta.2] - 2026-11-19

### Added
- A privacy ratchet in the release export: a build fails when any file carries a personal path, a mother-vault name or a secret-shaped value.
- The release carries `.vault-release/installed.json` and `.vault-release/base/`, so an upgrade has a base to merge against from the first day.
- The audit rule `FM-nonlatin-digit`: a date key written with non-Latin digits is a string that date queries skip.
- The folders `Literature/`, `Experiments/` and `Permanent/` under `05-Zettelkasten/`.
- Regression guards in the test suite for editable installs, bare commands in the docs, raw SQLite file URIs, the paths that workflow steps run, and `requirements.txt` against `uv.lock`.
- CI steps for the setup scripts, a hidden `.venv` on macOS, a Windows run without UTF-8 mode, and the pre-commit hook.

### Changed
- Upgrading from 1.0.0-beta.1: run `git pull` first, then `upgrade_core.py`. The beta.1 copy of `upgrade_core.py` does not know the fixes below, so it must not be the one that performs the upgrade.
- A clone made with `git clone` has no `.vault-release/installed.json`; the upgrade now reads `release_manifest.json` instead and reports `source=release_manifest`.
- The runtime installs with `uv sync --locked --no-dev --no-editable` (setup scripts, upgrade and CI), so the fragile editable `.pth` file does not come back. `uv_build` may be any 0.12 to 0.14 release.
- `base.zip` is capped at 1 MB.
- The setup scripts look for `uv` in its usual folders, check that `stratum_cli` imports, and restore `PYTHONPATH` when they finish. `vault-python`, `vault-python.ps1` and the pre-commit hook set `PYTHONUTF8=1`; the hook no longer sets `PYTHONPATH`.
- The commands in the documentation use `.venv/bin/python` and `.venv/bin/stratum-*`; `GETTING-STARTED.md` gives the Windows equivalents and the `win_arm64` limit.
- The `Fleeting` template writes `created` as a plain date, like every other template.
- GitHub Actions use `actions/checkout@v7` and `astral-sh/setup-uv@v7`.

### Fixed
- `state.py` honours `STRATUM_SKIP_NET=1` (no network probes; the preflight line still prints `state=skipped`), skips the IPv6 probe once IPv4 answers, and reads dates written with any script's digits.
- Rotating the injection log keeps its `static_childhood` first line, so the ledger self-check still passes afterwards.
- The agent-config check finds the agent's Windows config folder.
- `tokmeter.py`, `mediator.py`, `audit.py` and `jev_client.py` open SQLite through a quoted file URI, so paths with spaces or drive letters work.
- `agent_digest.py`: home-folder scrubbing for `C--Users-<name>-` paths, POSIX paths for git, quoted Windows and macOS schedule templates, and a clear refusal when `.gitignore` ignores the archive.
- Test suites that failed on Windows (permission bits, symlink privilege, CRLF in shell hooks) and on a fresh release tree (optional extractor, finding floor, upgrade copy, a parallel race) now pass or skip with a stated reason.
- Every subprocess call in text mode names its UTF-8 encoding, and the git calls turn path quoting off, so output and non-ASCII file names no longer depend on the console code page.
- The front matter parser uses libyaml when the install has it, with the same results and a pure-Python fallback.
- A corrupt vault index store is rebuilt on Windows too: no connection is left open on the file when it is deleted.
- `vault_mv.py` keeps CRLF line endings, so moving a note in a Windows vault no longer fails the apply guard.
- Tests that assumed Linux paths (`/proc`, `.local`, XDG) now follow the platform, so macOS and Windows runs measure the code and not the test.
- Five traps no longer cite fixture files that the release does not ship, and the `obsidian-markdown` skill no longer carries a placeholder link.

### Security
- The release export refuses to ship personal data, and its own tests carry no personal paths.

## [1.0.0-beta.1] - 2026-11-12

### Added
- The vault layout: PARA and Zettelkasten folders, twelve templates, a dashboard and an Active Work base.
- The agent layer: handoff, rules registry, sixteen skills, thirty-one documented traps, the frontmatter schema, and the decision ledger.
- The commit gate (`audit.py --ratchet`) and the pre-commit hook that also runs the tests of staged files.
- A shared command-line contract: every tool answers `--help` with exit code 0 and an unknown flag with exit code 2.
- Setup scripts for macOS, Linux and Windows, built on a locked `uv` environment.

### Changed
- Not applicable for the first release.

### Security
- Plugin code is fetched over HTTPS and verified against pinned SHA-256 hashes; no plugin token is stored in the repository.

[Unreleased]: https://github.com/Saud-Zaid/Stratum/compare/v1.0.0-beta.2...HEAD
[1.0.0-beta.2]: https://github.com/Saud-Zaid/Stratum/compare/v1.0.0-beta.1...v1.0.0-beta.2
[1.0.0-beta.1]: https://github.com/Saud-Zaid/Stratum/releases/tag/v1.0.0-beta.1
