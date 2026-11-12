# Changelog

All notable changes to this project are documented in this file. The format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and the project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/Saud-Zaid/Stratum/compare/v1.0.0-beta.1...HEAD
[1.0.0-beta.1]: https://github.com/Saud-Zaid/Stratum/releases/tag/v1.0.0-beta.1
