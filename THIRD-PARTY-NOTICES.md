# Third-party notices

Stratum is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). It uses the third-party components below, each under its own license. This file records what they are, where they come from and which license applies; the license texts are in [LICENSES/](LICENSES/MIT.txt).

## Obsidian community plugins

**None of these plugins' code is part of this repository.** `.venv/bin/python AI-Agent/scripts/install_plugins.py` downloads each plugin from its upstream release over HTTPS and checks the SHA-256 of every file against `.obsidian/plugins.lock.json`. You receive each plugin under the license its author chose, directly from the author; those licenses (including the AGPL-3.0 and GPL-3.0 ones) apply to the plugin you install, not to this repository's own files. Check a plugin's own repository for its current license before you redistribute anything.

| Plugin | Version | Upstream | License (SPDX) | Copyright notice |
|---|---|---|---|---|
| `obsidian-git` | 2.39.0 | [vinzent03/obsidian-git](https://github.com/vinzent03/obsidian-git) | MIT | Copyright (c) 2020 Vinzent03, Denis Olehov |
| `mcp-tools-istefox` | 3.1.1 | [istefox/obsidian-mcp-connector](https://github.com/istefox/obsidian-mcp-connector) | MIT | Copyright (c) 2026 Stefano Ferri |
| `templater-obsidian` | 2.25.0 | [silentvoid13/Templater](https://github.com/silentvoid13/Templater) | AGPL-3.0 | see the author's own notice in the upstream repository |
| `dataview` | 0.5.68 | [blacksmithgu/obsidian-dataview](https://github.com/blacksmithgu/obsidian-dataview) | MIT | Copyright (c) 2021 Michael Brenan |
| `quickadd` | 2.24.2 | [chhoumann/quickadd](https://github.com/chhoumann/quickadd) | MIT | Copyright (c) 2021 Christian Bager Bach Houmann |
| `tag-wrangler` | 0.6.5 | [pjeby/tag-wrangler](https://github.com/pjeby/tag-wrangler) | ISC | Copyright 2021 PJ Eby |
| `colored-tags-wrangler` | 0.19.4 | [code-of-chaos/ColoredTagsWrangler.obmd](https://github.com/code-of-chaos/ColoredTagsWrangler.obmd) | GPL-3.0 | see the author's own notice in the upstream repository |
| `obsidian-linter` | 1.32.0 | [platers/obsidian-linter](https://github.com/platers/obsidian-linter) | MIT | Copyright (c) 2021-2022 Victor Tao |
| `obsidian-excalidraw-plugin` | 2.27.3 | [zsviczian/obsidian-excalidraw-plugin](https://github.com/zsviczian/obsidian-excalidraw-plugin) | AGPL-3.0 | see the author's own notice in the upstream repository |
| `obsidian-tasks-plugin` | 8.4.0 | [obsidian-tasks-group/obsidian-tasks](https://github.com/obsidian-tasks-group/obsidian-tasks) | MIT | Copyright (c) 2021 Clare Macrae, Ilyas Landikov and Martin Schenck |
| `omnisearch` | 1.31.0 | [scambier/obsidian-omnisearch](https://github.com/scambier/obsidian-omnisearch) | GPL-3.0 | see the author's own notice in the upstream repository |
| `consistent-attachments-and-links` | 4.0.0 | [dy-sh/obsidian-consistent-attachments-and-links](https://github.com/dy-sh/obsidian-consistent-attachments-and-links) | MIT | Copyright (C) 2021-2026 by Dmitry Savosh (d.savosh@gmail.com) |
| `advanced-rename-and-delete-handler` | 1.3.0 | [mnaoumov/obsidian-advanced-rename-and-delete-handler](https://github.com/mnaoumov/obsidian-advanced-rename-and-delete-handler) | MIT | Copyright (C) 2026 by Michael Naumov |
| `automatic-table-of-contents` | 1.8.0 | [johansatge/obsidian-automatic-table-of-contents](https://github.com/johansatge/obsidian-automatic-table-of-contents) | MIT | Copyright © 2023 Johan Satgé |

The license identifiers come from each repository's license file as reported by GitHub when the lock was written (2026-11-12); the copyright lines are copied from those files.

## License texts shipped in `LICENSES/`

| File | Used by |
|---|---|
| `PolyForm-Noncommercial-1.0.0.md` | this project |
| `MIT.txt`, `ISC.txt` | templates of the MIT and ISC licenses (the plugin authors' own copyright lines are in the table above) |
| `GPL-3.0.txt` | `colored-tags-wrangler`, `omnisearch` |
| `AGPL-3.0.txt` | `templater-obsidian`, `obsidian-excalidraw-plugin` |

## Python dependencies

The runtime is pinned in `uv.lock`; each package is installed from PyPI under its own license. The release's SBOM (`sbom.cdx.json`, CycloneDX) lists every package with its version and hash. This file does not restate those licenses.

This document is information for users and is not legal advice.
