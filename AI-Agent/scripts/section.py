# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Print one section (or a line range) with line numbers and context protection.
Usage: section <path> <heading-query | L<start>-<end>> [max_lines] [--all] [--bytes N]

T-11 (FX06): borrowed ceiling — the output is capped at MAX_BYTES (default 4000),
the remaining size is printed explicitly so the agent knows what is left to fetch.
"""
import sys
from _vaultlib import VAULT, normalize_ar, read, sections, standard_parser

# T-11: borrowed ceiling in bytes (default 3500; --bytes overrides, --all lifts the cap)
MAX_BYTES = 3500

_ap = standard_parser(__doc__, "section")
_ap.add_argument("path", help="vault-relative path")
_ap.add_argument("query", help="heading query, or L<start>-<end>")
_ap.add_argument("max_lines", nargs="?", type=int, default=200)
_ap.add_argument("--all", action="store_true", dest="show_all", help="lift the byte and table ceilings")
_ap.add_argument("--bytes", type=int, default=MAX_BYTES, dest="max_bytes", help="byte ceiling (default %d)" % MAX_BYTES)
_ns = _ap.parse_args()
show_all, MAX_BYTES, max_lines, query = _ns.show_all, _ns.max_bytes, _ns.max_lines, _ns.query

path = VAULT / _ns.path
if not path.is_file():
    sys.exit(f"not found: {_ns.path}")
text = read(path)
lines = text.splitlines()

if query.startswith("L") and "-" in query[1:]:
    a, b = query[1:].split("-", 1)
    start, end = int(a), min(int(b), len(lines))
else:
    q = normalize_ar(query)
    hits = [s for s in sections(text) if q in normalize_ar(s[1])]
    if not hits:
        sys.exit(f"no heading matches: {query}. Run outline first.")
    if len(hits) > 1:
        print("multiple headings match; refine the query or use L<start>-<end>:")
        for level, title, line, count in hits:
            print(f"H{level}\t{line}\t{count}\t{title}")
        sys.exit(0)
    _, _, start, count = hits[0]
    end = min(start + count - 1, len(lines))

shown_end = min(end, start + max_lines - 1)
byte_count = 0

# T-11: total section size computed first, so the remaining bytes can be printed
total_section_bytes = sum(len(lines[i - 1].encode("utf-8")) + 1 for i in range(start, end + 1))

table_rows = 0
table_truncated = False

output_lines = []
for i in range(start, shown_end + 1):
    ln = lines[i - 1]
    is_tbl = ln.strip().startswith("|") and ln.strip().endswith("|")
    
    if not show_all and is_tbl:
        table_rows += 1
        if table_rows > 25:
            if not table_truncated:
                output_lines.append(f"[{i}..{end}: table truncated at 25 rows to protect context. Use --all to view]")
                table_truncated = True
            continue
    else:
        table_rows = 0

    ln_bytes = len(ln.encode("utf-8")) + 1
    if not show_all and byte_count + ln_bytes > MAX_BYTES and len(output_lines) > 5:
        output_lines.append(f"[{i}..{end}: section truncated at {MAX_BYTES}B context ceiling. Use --all or L{i}-{end} to continue]")
        break

    byte_count += ln_bytes
    output_lines.append(f"{i}\t{ln}")

for ol in output_lines:
    print(ol)

if shown_end < end and not show_all and not table_truncated and byte_count <= MAX_BYTES:
    print(f"[{end - shown_end} more lines: rerun with L{shown_end + 1}-{end} or --all]")

# T-11 (FX06): print the remaining bytes explicitly — what is still owed after the ceiling
if not show_all and total_section_bytes > byte_count:
    print(f"[SECTION-BYTES total={total_section_bytes} returned={byte_count} remaining={total_section_bytes - byte_count} ceiling={MAX_BYTES}]")
