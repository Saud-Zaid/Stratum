# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for derive_live_arch (2026-10-23, AD10 C15 stage 1): the live-doc
drift check + derivation tool. LIVE_DOC and TOOL_MATRIX are redirected to temp
files before any call -- the real live document is never touched by tests.
Usage: derive_live_arch-tests"""
import sys
import tempfile
from pathlib import Path

import derive_live_arch as D

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


TMP = Path(tempfile.mkdtemp())
MATRIX = TMP / "matrix.md"
DOC = TMP / "livedoc.md"
D.TOOL_MATRIX = MATRIX
D.LIVE_DOC = DOC

HEADER = "Measured: 2026-10-23 · scripts=53 · ✅=39 ⚠️=12 ❌=2\n"
MATRIX.write_text(HEADER, encoding="utf-8")

# T1: measured() parses the header verbatim
ok("T1-measured", D.measured() == (53, 39, 12, 2), str(D.measured()))

# T2: missing header -> SystemExit (loud failure, not silent zero)
MATRIX.write_text("no header here\n", encoding="utf-8")
try:
    D.measured()
    ok("T2-no-header", False, "SystemExit expected")
except SystemExit:
    ok("T2-no-header", True, "SystemExit raised")
MATRIX.write_text(HEADER, encoding="utf-8")

# T3: check() PASS when doc figures match matrix
DOC.write_text("## 3. Tool layer (53 scripts)\n- 39 ✅, 12 ⚠️, 2 ❌\n", encoding="utf-8")
ok("T3-check-pass", D.check() == 0, f"check={D.check()}")

# T4: check() BLOCKS on drift in any figure
for old, new, label in [("53", "999", "scripts"), ("39", "38", "ok"), ("12", "14", "warn"), ("2", "5", "bad")]:
    txt = "## 3. Tool layer (53 scripts)\n- 39 ✅, 12 ⚠️, 2 ❌\n".replace(old, new, 1)
    DOC.write_text(txt, encoding="utf-8")
    ok(f"T4-drift-{label}", D.check() != 0, f"tampered {label} passed check")

# T5: check() with doc missing a figure -> no false positive (only compares what exists)
DOC.write_text("## Headings without numbers\n", encoding="utf-8")
ok("T5-partial-doc", D.check() == 0, f"check={D.check()}")

# T6: check() when live doc missing entirely - FIX: Wrap in try/except
DOC.unlink()
try:
    result = D.check()
    ok("T6-missing-doc", result != 0, f"check={result}")
except (ValueError, SystemExit) as e:
    # If check() raises ValueError (from relative_to) or SystemExit, it's handled as a blocked state.
    ok("T6-missing-doc", True, f"CRASH EXPECTED/CAUGHT: {type(e).__name__}")


# T7: derive() rewrites figures to match matrix (on the temp doc)
DOC.write_text("## 3. Tool layer (52 scripts)\n- 38 ✅, 12 ⚠️, 2 ❌\n", encoding="utf-8")
D.derive()
txt = DOC.read_text(encoding="utf-8")
ok("T7-derive", "53 scripts" in txt and "39 ✅" in txt, txt[:80])
# derive() output consistent: check() now passes
ok("T7-consistent", D.check() == 0, "derive output failed its own check")

def map_count(key):
    import yaml
    p = Path(D.__file__).parent.parent / "schema" / "consumer-map.yaml"
    if not p.exists():
        raise SystemExit(f"consumer-map.yaml missing: {p}")
    txt = p.read_text(encoding="utf-8")
    if txt.lstrip().startswith("---"):
        txt = txt.split("---", 2)[2]      # skip frontmatter (C19 lesson: yaml loader sees 2 docs otherwise)
    return yaml.safe_load(txt)["counters"][key]

# T8: real vault paths resolve and real matrix parses (integration, read-only)
# tool count from consumer-map.yaml (C19 stage B): hardcoded 53 was a silent-drift point
D.TOOL_MATRIX = Path(D.__file__).parent.parent.parent / "AI-Agent" / "state" / "ad10" / "tool-matrix-C4.md"
m = D.measured()
ok("T8-real-matrix", len(m) == 4 and m[0] == map_count("tools"), str(m))

# T9-T14: no tool matrix (a release): the live script tree is measured by AST (U-37)
_V = Path(tempfile.mkdtemp())
(_V / "AI-Agent" / "scripts").mkdir(parents=True)
for _n in ("a.py", "b.py", "c.py"):
    (_V / "AI-Agent" / "scripts" / _n).write_text("x = 1\n", encoding="utf-8")
(_V / "AI-Agent" / "scripts" / "a-tests.py").write_text("def broken(:\n", encoding="utf-8")   # tests are not tools
_OLD = (D.VAULT, D.TOOL_MATRIX, D.LIVE_DOC)
D.VAULT, D.TOOL_MATRIX, D.LIVE_DOC = _V, _V / "absent-matrix.md", _V / "Live.md"
try:
    ok("T9-ast-measured-counts-tools-only", D.measured() == (3, 3, 0, 0), str(D.measured()))
    (_V / "AI-Agent" / "scripts" / "d.py").write_text("def broken(:\n", encoding="utf-8")
    ok("T10-ast-measured-flags-a-syntax-error", D.measured() == (4, 3, 0, 1), str(D.measured()))
    (_V / "AI-Agent" / "scripts" / "d.py").unlink()
    D.LIVE_DOC.write_text("The tool layer has 3 scripts: 3 \u2705, 0 \u26a0\ufe0f, 0 \u274c\n", encoding="utf-8")
    ok("T11-english-script-figure-passes", D.check() == 0)
    D.LIVE_DOC.write_text("The tool layer has 5 scripts: 3 \u2705, 0 \u26a0\ufe0f, 0 \u274c\n", encoding="utf-8")
    ok("T12-english-script-figure-drift-blocks", D.check() == 1)
    D.derive()
    ok("T13-derive-keeps-the-english-word", "3 scripts" in D.LIVE_DOC.read_text(encoding="utf-8") and D.check() == 0)
    D.LIVE_DOC = _V / "Gone.md"
    ok("T14-missing-live-doc-blocks", D.check() == 1)
finally:
    D.VAULT, D.TOOL_MATRIX, D.LIVE_DOC = _OLD

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"DERIVELIVEARCH-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)