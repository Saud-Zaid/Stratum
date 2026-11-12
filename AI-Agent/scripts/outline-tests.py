# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for outline (2026-10-23, AD10 C15 stage 1): validates the sections()
parser from _vaultlib on controlled markdown text -- heading extraction, level
ordering, and the level/line/lines/title TSV shape that outline.py prints --
plus the CLI layer: vault-relative path resolution, exact TSV rendering against
a real vault file, and 'not found: X' + exit 1 on a missing path.
Usage: outline-tests"""
import os
import subprocess
import sys
from pathlib import Path

from _vaultlib import VAULT, read, sections

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(Path(__file__).parent / "outline.py"), *args],
        capture_output=True, text=True,
        env={**os.environ, "VAULT": str(VAULT)})


TEXT = """# Main title
Text under the title.
## First section
First section content.
### First branch
Branch content.
### Second branch
Second branch content.
## Second section
Second section content.
### Third branch
Third branch content.
# Second main title
Text under the second title.
"""

# T1: sections() returns all 7 headings in order
out = list(sections(TEXT))
ok("T1-count", len(out) == 7, f"got {len(out)}")

# T2: titles are in document order (depth-first, not level-sorted)
ok("T2-order", [t[1] for t in out] == ["Main title", "First section", "First branch", "Second branch", "Second section", "Third branch", "Second main title"], str([t[1] for t in out]))

# T3: levels are preserved (1, 2, 3, 3, 2, 3, 1)
ok("T3-levels", [t[0] for t in out] == [1, 2, 3, 3, 2, 3, 1], str([t[0] for t in out]))

# T4: section sizes are correct (size = next heading line of same/higher level minus current line, else EOF)
# H1 line 1 -> next H1 at 13 -> 12, H2 line 3 -> next H2 at 9 -> 6, H3 line 5 -> next H3 at 7 -> 2,
# H3 line 7 -> next H2 at 9 -> 2, H2 line 9 -> next H1 at 13 -> 4, H3 line 11 -> next H1 at 13 -> 2,
# H1 line 13 -> EOF (15) -> 3
ok("T4-sizes", [t[3] for t in out] == [12, 6, 2, 2, 4, 2, 3], str([t[3] for t in out]))

# T5: start lines are correct (1, 3, 5, 7, 9, 11, 13)
ok("T5-lines", [t[2] for t in out] == [1, 3, 5, 7, 9, 11, 13], str([t[2] for t in out]))

# T6: sections() on empty text returns no sections
ok("T6-empty", len(list(sections(""))) == 0, "expected empty")

# T7: no false heading inside code fences
TEXT_FENCE = "```\n# not a heading\n```\n## real heading\n"
out7 = list(sections(TEXT_FENCE))
ok("T7-code-fence", len(out7) == 1 and out7[0][1] == "real heading", str(out7))

# T8: CLI on a real vault file renders exact TSV -- header + H{level}\t{line}\t{count}\t{title}
# (expected computed from sections() itself; content-level assertions live in T1-T7)
REAL = "AI-Agent/handoff.md"
expected = "level\tline\tlines\ttitle\n" + "".join(
    f"H{lv}\t{ln}\t{ct}\t{ti}\n" for lv, ti, ln, ct in sections(read(VAULT / REAL)))
r = run_cli(REAL)
ok("T8-cli-tsv", r.returncode == 0 and r.stdout == expected and r.stderr == "",
   f"rc={r.returncode} stdout={r.stdout[:150]!r} stderr={r.stderr[:150]!r}")

# T9: CLI TSV rows are 4 tab-separated fields, level starts with 'H', line/count digits
rows = r.stdout.splitlines()[1:]
ok("T9-cli-shape", len(rows) > 0 and all(
    len(f := line.split("\t")) == 4 and f[0].startswith("H") and f[1].isdigit()
    and f[2].isdigit() for line in rows), str(rows[:2]))

# T10: CLI missing path -> exit 1, 'not found: X' on stderr, empty stdout
MISSING = "no/such/file-XYZ-123.md"
r = run_cli(MISSING)
ok("T10-cli-missing", r.returncode == 1 and r.stdout == ""
   and f"not found: {MISSING}" in r.stderr, f"rc={r.returncode} out={r.stdout!r} err={r.stderr!r}")

# --- T-11 additions (FX07: outline refuses itself on small files) ---

# T11: small file (real vault template, 702B) -> refusal message, exit 0
r = run_cli("Templates/Permanent.md")
ok("T11-small-refused", "outline refused" in r.stdout and r.returncode == 0,
   f"rc={r.returncode} out={r.stdout[:150]!r}")

# T12: refusal mentions direct reading guidance
ok("T12-refusal-guides", "Read the file directly" in r.stdout, f"out={r.stdout[:200]!r}")

# T13: big file with many headings -> outline still prints TSV
r = run_cli("03-Resources/Second-Brain-User-Guide.md")
ok("T13-big-prints", r.stdout.startswith("level\tline\tlines\ttitle") and r.returncode == 0,
   f"rc={r.returncode} out={r.stdout[:80]!r}")

# T14: --all forces outline even on a small file
r = run_cli("Templates/Permanent.md", "--all")
ok("T14-all-forces", r.stdout.startswith("level\tline\tlines\ttitle"), f"rc={r.returncode} out={r.stdout[:80]!r}")

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"OUTLINE-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
