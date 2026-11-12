# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Print a file's sections as TSV: level, line, line_count, title.
Usage: outline <vault-relative-path> [--all]

T-11 (FX07): the outline refuses itself on small files — a no-worse gate measured
in bytes (not a percentage of file size). A file under MIN_BYTES or with fewer
than MIN_HEADINGS gains nothing from an outline call: reading it whole costs one
call and returns everything, so the outline would equal the reading it exists
to avoid.
"""
import sys
from _vaultlib import VAULT, read, sections, standard_parser

MIN_BYTES = 2000
MIN_HEADINGS = 3

_ap = standard_parser(__doc__, "outline")
_ap.add_argument("path", help="vault-relative path")
_ap.add_argument("--all", action="store_true", dest="force", help="outline even a small file")
_ns = _ap.parse_args()

force = _ns.force
path = VAULT / _ns.path
if not path.is_file():
    sys.exit(f"not found: {_ns.path}")
text = read(path)
size = len(text.encode("utf-8"))
secs = sections(text)

if not force and (size < MIN_BYTES or len(secs) < MIN_HEADINGS):
    reason = (f"file {size}B < {MIN_BYTES}B" if size < MIN_BYTES
              else f"only {len(secs)} headings < {MIN_HEADINGS}")
    print(f"# outline refused: {reason}. Read the file directly — it is small.")
    sys.exit(0)

print("level\tline\tlines\ttitle")
for level, title, line, count in secs:
    print(f"H{level}\t{line}\t{count}\t{title}")
