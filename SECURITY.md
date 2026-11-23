# Security policy

## Supported versions

Stratum is in beta. Only the latest release receives security fixes; upgrade to it before you report.

| Version | Supported |
|---|---|
| latest `1.0.0-beta` release | yes |
| earlier betas | no |

## Reporting a vulnerability

Report it privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue, pull request or discussion for it.

Include what is affected (file, script or setting), the steps to reproduce it, and what an attacker gains. The maintainer aims to acknowledge a report within a week, agrees a disclosure date with you, and credits you in the release notes unless you prefer otherwise.

## Scope

In scope: the scripts under `AI-Agent/scripts/`, the setup scripts, the pre-commit hook, the plugin installer and its hash checks, and the release archives with their checksums and attestations. Obsidian itself and third-party plugins are out of scope; report those to their own projects.
