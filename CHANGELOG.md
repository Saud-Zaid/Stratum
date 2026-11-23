# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `jev_calibrate.py`, a question registry (`AI-Agent/config/jev-questions.yaml`) and a synthetic example case file: calibrate a recurring Jev question on your own labelled cases before relying on it (no false accept, at most 15% false rejects, a certified threshold from 29 deceptive cases). It plans and prices a run before sending anything.
- The Jev decision server `AI-Agent/scripts/jev_mcp.py` ships next to its client, and the README explains how to enable the Jev gate with one OpenRouter API key.

### Fixed
- `jev_client.py` passes `OPENROUTER_API_KEY` (and `JEV_MODEL`, `JEV_TIMEOUT`) to the server it starts, so a key exported in the shell works on any machine, and it runs the server with the locked environment when `--extra jev` is installed.

## [1.0.0-beta.6] - 2026-11-23

### Fixed
- `1.0.0-beta.5` was tagged but never published: two seeded files under `AI-Agent/state/` kept the previous release date while `release_manifest.json` listed the new one, so the release build refused the tree. This version publishes the same changes as `1.0.0-beta.5` with a matching manifest.
- The pull request list in release notes starts at the last published release, so a tag that was never published does not hide the pull requests merged before it.

## [1.0.0-beta.5] - 2026-11-23 [YANKED]

### Added
- `CONTRIBUTING.md` (how a change reaches `main`, how a release is made, and the release branch every version has from `1.0.0-beta.5` on) and `SECURITY.md` (private vulnerability reporting through GitHub).
- A pull request template, and a check that a pull request title reads `type: description` and that the pull request carries no AI co-author or attribution line.

### Changed
- CI builds a pushed branch only when it is `main`; a pull request runs its own build once instead of twice.
- Release notes are the version's section of this file followed by the merged pull requests, grouped by label.

## [1.0.0-beta.4] - 2026-11-20

### Added
- The `stratum-iso-dates` plugin (fourteen community plugins are enabled now). When the interface language prints Arabic-Indic or Persian digits, Obsidian's date formatting wrote the date `2026-11-19` in Arabic-Indic digits, a string that date queries skip; the plugin converts the digits of every formatted date to ASCII. Install it with `install_plugins.py`; it is MIT licensed and published at https://github.com/Saud-Zaid/stratum-iso-dates.

### Changed
- New Fleeting is `Mod+Shift+K` instead of `Mod+Shift+I`, which opens the developer tools on Windows and Linux. No Obsidian default or shipped plugin uses `Mod+Shift+K`; rebind it in Settings, Hotkeys if you prefer another key. A new install gets the new key; an upgrade leaves your own hotkeys file as it is, so an existing vault keeps `Mod+Shift+I` until you change it.

### Fixed
- The `vault_mv` tests no longer copy the runtime state folder, whose SQLite files another test may hold open on Windows.

## [1.0.0-beta.3] - 2026-11-20

### Added
- `enable_mcp.py --status` shows the port written to `.mcp.json` next to the port the plugin last bound, and warns when they differ (Obsidian rebinds within 27200 to 27212), so a stale connection URL is visible.

### Removed
- Optional tooling that is distributed separately, its tests and its CI step are no longer part of the free release. An upgrade removes the files that were not modified.

### Fixed
- An upgrade removes the empty folders that a file removed upstream leaves behind (a folder that still holds a local file stays).
- An upgrade also replaces the installed `release_manifest.json`; before, it kept the previous release's file list and version.
- A test of the test runner's lane order no longer loses a line when two scripts write at once on Windows.
- GETTING-STARTED says that the setup scripts and the whole test suite pass on Windows in CI.

### Changed
- The audit runs about 20% faster on a warm cache: the architecture secret scan checks each note once before reading it line by line, and the deferral scan skips notes that cannot produce a finding. The findings are identical.

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
- Two audits started together on a new index store wait out each other's lock instead of dropping the cache (Windows ignores the busy timeout while a store switches to WAL).
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

[Unreleased]: https://github.com/Saud-Zaid/Stratum/compare/v1.0.0-beta.6...HEAD
[1.0.0-beta.6]: https://github.com/Saud-Zaid/Stratum/compare/v1.0.0-beta.4...v1.0.0-beta.6
[1.0.0-beta.5]: https://github.com/Saud-Zaid/Stratum/compare/v1.0.0-beta.4...v1.0.0-beta.5
[1.0.0-beta.4]: https://github.com/Saud-Zaid/Stratum/compare/v1.0.0-beta.3...v1.0.0-beta.4
[1.0.0-beta.3]: https://github.com/Saud-Zaid/Stratum/compare/v1.0.0-beta.2...v1.0.0-beta.3
[1.0.0-beta.2]: https://github.com/Saud-Zaid/Stratum/compare/v1.0.0-beta.1...v1.0.0-beta.2
[1.0.0-beta.1]: https://github.com/Saud-Zaid/Stratum/releases/tag/v1.0.0-beta.1
