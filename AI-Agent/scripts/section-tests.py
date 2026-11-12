# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for section (2026-10-23, AD10 C15 stage 2): heading query resolution,
line-range extraction, table truncation (25 rows), and the 3500B context ceiling.
Tests the core logic in-process against controlled text -- the real vault is not
written to. Usage: section-tests"""

def _U(s):
    """ASCII-escaped test data: the shipped sources hold no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")

import sys
from pathlib import Path

from _vaultlib import VAULT, normalize_ar, sections

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


TEXT = """# Overview
intro line
## Section A
A body line 1
A body line 2
### Sub A1
sub body
## Section B
B body line 1
## Section A (again)
duplicated heading body
"""
LINES = TEXT.splitlines()


def resolve(query):
    """Mirror section.py heading resolution (single hit -> (start, end))."""
    q = normalize_ar(query)
    hits = [s for s in sections(TEXT) if q in normalize_ar(s[1])]
    if not hits:
        return None
    if len(hits) > 1:
        return hits
    _, _, start, count = hits[0]
    end = min(start + count - 1, len(LINES))
    return start, end


def extract(start, end, max_lines=200, show_all=False):
    """Mirror section.py extraction: table cap 25 rows, byte cap 3500B."""
    shown_end = min(end, start + max_lines - 1)
    byte_count = 0
    MAX_BYTES = 3500
    table_rows = 0
    table_truncated = False
    out = []
    for i in range(start, shown_end + 1):
        ln = LINES[i - 1]
        is_tbl = ln.strip().startswith("|") and ln.strip().endswith("|")
        if not show_all and is_tbl:
            table_rows += 1
            if table_rows > 25:
                if not table_truncated:
                    out.append(f"[{i}..{end}: TABLE_TRUNCATED]")
                    table_truncated = True
                continue
        else:
            table_rows = 0
        ln_bytes = len(ln.encode("utf-8")) + 1
        if not show_all and byte_count + ln_bytes > MAX_BYTES and len(out) > 5:
            out.append(f"[{i}..{end}: BYTE_CEILING]")
            break
        byte_count += ln_bytes
        out.append(f"{i}\t{ln}")
    return out, table_truncated


# T1: unique heading "Section B" resolves to one hit at line 8
r = resolve("Section B")
ok("T1-unique-hit", r == (8, 9), str(r))

# T2: ambiguous query "Section A" matches 2 headings -> returns hits list
r = resolve("Section A")
ok("T2-ambiguous", isinstance(r, list) and len(r) == 2, str(r))

# T3: Arabic normalization -- "" == "" (diacritics stripped)
ok("T3-normalize", normalize_ar(_U(r"\u0627\u0644\u0634\u064f\u0639\u0628\u0629")) == normalize_ar(_U(r"\u0627\u0644\u0634\u0639\u0628\u0629")), f"{normalize_ar(_U(r'\u0627\u0644\u0634\u064f\u0639\u0628\u0629'))!r} vs {normalize_ar(_U(r'\u0627\u0644\u0634\u0639\u0628\u0629'))!r}")

# T4: no match -> None
ok("T4-no-match", resolve("Nonexistent Section XYZ") is None, str(resolve("Nonexistent Section XYZ")))

# T5: substring-boundary behavior -- "Section A " (with trailing space) matches ONLY
# "Section A (again)" (line 10), not "Section A" (line 3), because the space acts as a boundary.
r = resolve("Section A ")
start, end = r
out, trunc = extract(start, end)
ok("T5-extract-lines", out[0].startswith("10\t") and out[-1].startswith("11\t") and not trunc, str(out))

# T6: table truncation at 25 rows -- non-table lines after the table still print
LINES = ["## T"] + [f"| r{i} | x |" for i in range(30)] + ["after table"]
out, trunc = extract(1, len(LINES))
tbl_idx = next((i for i, o in enumerate(out) if "TABLE_TRUNCATED" in o), None)
ok("T6-table-cap", trunc and tbl_idx is not None and len(out) - tbl_idx == 2, f"trunc={trunc} tail={out[-2:] if len(out) >= 2 else out}")

# T7: --all bypasses table cap
out, trunc = extract(1, len(LINES), show_all=True)
ok("T7-table-all", not trunc and len(out) == len(LINES), f"trunc={trunc} n={len(out)}")

# T8: byte ceiling triggers on long lines
LINES = ["## Big"] + ["x" * 200 for _ in range(40)]
out, trunc = extract(1, len(LINES))
ceiling = any("BYTE_CEILING" in o for o in out)
ok("T8-byte-cap", ceiling, f"lines={len(out)}")

# T9: --all bypasses byte ceiling
out, trunc = extract(1, len(LINES), show_all=True)
ok("T9-byte-all", not any("BYTE_CEILING" in o for o in out) and len(out) == 41, f"n={len(out)}")

# T10: max_lines param limits output
LINES = ["## Many"] + [f"line {i}" for i in range(50)]
out, trunc = extract(1, len(LINES), max_lines=10)
ok("T10-max-lines", len(out) == 10 and out[-1].startswith("10\t"), f"n={len(out)} last={out[-1] if out else '-'}")

# --- T-11 additions (FX06: borrowed ceiling prints remaining bytes) ---

def run_section(*args):
    import subprocess as _sp
    r = _sp.run([sys.executable, str(Path(__file__).parent / "section.py"), *args],
                capture_output=True, text=True)
    return r

import tempfile as _tf
from pathlib import Path as _Path

_tmpdir = _tf.mkdtemp(prefix="sec-t11-")
_big = _Path(_tmpdir) / "big-t11.md"
_big.write_text("\n".join(["## Big Section"] + ["x" * 180 for _ in range(40)]) + "\n", encoding="utf-8")
_rel = str(_big.relative_to(VAULT)) if str(_big).startswith(str(VAULT)) else str(_big)

# T11: SECTION-BYTES line present with total/returned/remaining fields
r = run_section(_rel, "L1-40")
sb = [l for l in r.stdout.splitlines() if "SECTION-BYTES" in l]
ok("T11-section-bytes-printed", bool(sb) and all(k in sb[0] for k in ("total=", "returned=", "remaining=")), f"stdout={r.stdout[-200:]!r}")

# T12: remaining == total - returned (arithmetic)
if sb:
    import re as _re
    m = _re.search(r"total=(\d+) returned=(\d+) remaining=(\d+)", sb[0])
    ok("T12-remaining-arithmetic", m and int(m.group(1)) == int(m.group(2)) + int(m.group(3)), f"line={sb[0] if sb else '-'}")
else:
    ok("T12-remaining-arithmetic", False, "no SECTION-BYTES line")

# T13: small section fits under ceiling -> no SECTION-BYTES noise
_small = _Path(_tmpdir) / "small-t11.md"
_small.write_text("## Tiny\njust a few lines\n", encoding="utf-8")
_small_rel = str(_small.relative_to(VAULT)) if str(_small).startswith(str(VAULT)) else str(_small)
r = run_section(_small_rel, "L1-5")
ok("T13-small-no-bytes-line", "SECTION-BYTES" not in r.stdout, f"stdout={r.stdout[:150]!r}")

# T14: --all lifts the ceiling -> no SECTION-BYTES line
r = run_section(_rel, "L1-40", "--all")
ok("T14-all-no-bytes-line", "SECTION-BYTES" not in r.stdout, f"stdout={r.stdout[-120:]!r}")

# T15: --bytes override works (small ceiling forces the line)
r = run_section(_rel, "L1-40", "--bytes", "500")
ok("T15-bytes-override", "SECTION-BYTES" in r.stdout and "ceiling=500" in r.stdout, f"stdout={r.stdout[-150:]!r}")

import shutil as _sh
_sh.rmtree(_tmpdir, ignore_errors=True)

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"SECTION-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
