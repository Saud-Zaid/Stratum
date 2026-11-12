# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Launch-discipline checks for subagent deliverables (RL-0030 support; plan
AI-Agent/scratch/20261030-vault-writing-fixes-plan.md, fixes F1+F2+F4).

Read-only. Never writes. Not part of the commit gate (RL-0017); the parent session
calls it BEFORE launching or resuming a subagent and AFTER it returns.

Why: session 20261030_1 (Mother Design Card) burned 12 launches for 4 files, ~63%
wasted: agents reported "completed" on skeletons, a retry overwrote a complete file,
and the final_output injection stopped agents early. Prose rules (SKILL.md) did not
hold; these checks are the scripted floor.

Usage:
  archclaim check <path>
      Reads the ownership claim line (F1): the subagent itself writes, as its FIRST
      line, `<!-- claim: <path> <- <subagent id> :: skeleton|partial|complete :: <bytes> -->`.
      Print: NONE (no file, launch ok) / NO-CLAIM (no claim line, launch ok with a
      fresh ownership note) / SKELETON or PARTIAL (exit 1: launch only with an
      explicit completion instruction) / COMPLETE (exit 2: launch blocked; compare
      the fingerprint; offer resume for failed/cancelled agents only).
      Exit 1 also covers: BYTES-MISMATCH (file changed since the claim was written),
      MULTIPLE-CLAIMS (stale claim line; remove it first), CLAIM-PATH-MISMATCH (the
      claim names a DIFFERENT file than the one checked — a copied stale claim is
      not ownership), NOT-UTF8 (binary/garbage file).
      Exit 2 also covers: IS-DIRECTORY (a directory is not a checkable target).
  archclaim verify <path> [--sections A,B,...] [--min-bytes N] [--targets N]
      The completion contract (F2): required section headings exist, no placeholder
      markers (TODO, TBD, FIXME, <placeholder>) OUTSIDE code fences (fenced
      examples like `example: TODO here` are legitimate), a `## Deliverable status`
      section with `targets: <confirmed>/<total>` consistent with the VERDICT entries
      (status-total == VERDICT target rows when VERDICT exists), and the sections the
      status line names all exist as headings. Exit 0 = pass, 1 = fail with FIND lines
      (also NOT-UTF8). Headings inside code fences do not count as sections.
  archclaim recipe [--dir .agents/recipes]
      F4 pre-launch check: every deliverable recipe file (*.yaml AND *.yml) must carry
      NO `response` block at any indentation, bare or as a list item (the injection
      source) and MUST carry the TR-0030 counter-rule text ("KNOWN INJECTION").
      FAILS CLOSED: a missing recipe directory is a finding, not a clean pass.
      Exit 0 = clean, 1 = findings.

Exit 2 = usage error (unknown command, wrong arg count, non-numeric --min-bytes/
--targets, or a flag given without a value). Fingerprint = archprint.fingerprint
(RL-0001 normalization).

Revision 3 (2026-10-30 adversarial round, OP-0059): flag-without-value = usage exit 2
(was an IndexError crash); non-numeric --min-bytes/--targets = usage exit 2 (was a
ValueError crash); recipe() fails closed on a missing dir and scans *.yml as well as
*.yaml; the response-block regex catches indented and list-item `response:` as well
as top-level; check() detects claim-path-mismatch (copied stale claims), not-utf8,
is-directory, and hints when the claim line is not the file's FIRST line; `targets:`
regex no longer crosses newlines (same class as the OP-0058 sections fix); the
placeholder scan and heading extraction skip fenced code blocks.

Revision 4 (2026-10-30 launch-pilot round, OP-0060): VERDICT-row counter accepts
"partially confirmed" / "not confirmed" prefixes (the pilot's file A reported
partially-confirmed G2 with targets 2/2 and the counter read 1 row — a mismatch warn
on a legitimate file; now such rows count); the claim line may be the first line AFTER
a frontmatter block (FM-required forces frontmatter on vault deliverables, so the
old "must be line 1" rule conflicted — the hint now fires only if the claim is not
the first content line).

Revision 5 (2026-10-30 self-critique round, OP-0061): first_content_line strips a
leading UTF-8 BOM (an editor's 'BOM + frontmatter + claim' must not raise a false
claim-not-first-line hint); check() adds an INDICATOR-ONLY missing-frontmatter hint
for AI-Agent/ files outside scripts/ — which keys a file needs stays frontmatter.yaml's
job (one source of truth, never a duplicated schema); the discipline "run the tests
after every code edit, not after the batch" is recorded here and in archclaim-tests.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _vaultlib import locale_value  # noqa: E402
from archprint import fingerprint  # noqa: E402

CLAIM = re.compile(r"<!--\s*claim:\s*(\S+[^\n]*?)\s*<-\s*(\S+)\s*::\s*(skeleton|partial|complete)\s*::\s*(\d+)\s*-->")
TOOL_ENV = re.compile(r"<!--\s*tool-env:\s*(.+?)\s*-->")
STATUS = "## Deliverable status"
TARGETS = re.compile(r"targets:[ \t]*(\d+)[ \t]*/[ \t]*(\d+)")
_VW = [locale_value("VERDICT_HEADING")] if locale_value("VERDICT_HEADING") else []
_VV = list(locale_value("VERDICT_WORDS", []))
VERDICT_ROW = re.compile(r"^#{2,3}\s*(?:VERDICT" + "".join("|" + re.escape(w) for w in _VW) + r")|^\s*[-*]\s*.*?(?:\s*:\s*)+\**\s*(?:partially\s+|not\s+)?(confirmed|uncertain|not-found" + "".join("|" + re.escape(w) for w in _VV) + r")\b", re.M)
PLACEHOLDERS = re.compile(r"\b(TODO|TBD|FIXME)\b|<placeholder>", re.I)
RESPONSE_BLOCK = re.compile(r"^\s*(?:-\s*)?response\s*:", re.M)
COUNTER_RULE = "KNOWN INJECTION"


def claim_line(text: str):
    m = CLAIM.search(text)
    if not m:
        return None
    return {"path": m.group(1), "agent": m.group(2), "state": m.group(3), "bytes": int(m.group(4))}


def tool_env(text: str):
    m = TOOL_ENV.search(text)
    return [s.strip() for s in m.group(1).split(",")] if m else None


def strip_fences(text: str) -> str:
    """Blank out fenced code blocks (``` or ~~~) so fenced examples do not
    count as headings or placeholders. One output line per input line."""
    out, fence = [], None
    for ln in text.splitlines():
        s = ln.lstrip()
        if fence:
            if s.startswith(fence):
                fence = None
            out.append("")
        elif s.startswith("```") or s.startswith("~~~"):
            fence = s[:3]
            out.append("")
        else:
            out.append(ln)
    return "\n".join(out)


def headings(text: str) -> set:
    return {ln.lstrip("#").strip() for ln in strip_fences(text).splitlines() if re.match(r"^#{2,3}\s+\S", ln)}


def first_content_line(text: str) -> str:
    """The first content line: after a leading frontmatter block (--- ... ---)
    if one exists, else line 1. A leading UTF-8 BOM (\ufeff) is stripped first —
    an editor saving 'BOM + --- ... --- + claim' must not produce a false
    claim-not-first-line hint. Claim lines must be here."""
    lines = text.lstrip("\ufeff").splitlines()
    i = 1 if lines and lines[0].strip() == "---" else 0
    if i:
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i += 1
    return lines[i].strip() if i < len(lines) else ""


def has_frontmatter(text: str) -> bool:
    """True when the text opens with a frontmatter block (a leading BOM ignored).
    Indicator only — which keys a file needs is frontmatter.yaml's job, never ours."""
    lines = text.lstrip("\ufeff").splitlines()
    return bool(lines) and lines[0].strip() == "---"


def check(path: str) -> tuple[int, list[str]]:
    p = Path(path)
    if p.is_dir():
        return 2, ["FIND\tfail\tis-directory\t" + str(p)]
    if not p.is_file():
        return 0, ["NONE\t" + str(p)]
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return 1, [f"FIND\tfail\tnot-utf8\t{p} is not UTF-8 text"]
    claims = CLAIM.findall(text)
    if not claims:
        return 0, ["NO-CLAIM\t" + str(p)]
    if len(claims) > 1:
        return 1, [f"FIND\tfail\tmultiple-claims\t{len(claims)} claim lines in one file; the first is stale ownership"]
    path_, agent, state, declared = claims[0]
    if Path(path_).resolve() != p.resolve():
        return 1, [f"FIND\tfail\tclaim-path-mismatch\tclaim names '{path_}' but the checked file is '{p}' — a copied stale claim is not ownership"]
    fp = fingerprint(text)
    size = len(text.encode("utf-8"))
    line = f"{state.upper()}\t{path_}\t{agent}\tbytes={declared}\tsize={size}\tfp={fp}"
    if int(declared) != size:
        line += "\tbytes-mismatch (file changed since the claim was written)"
        return 1, [line]
    first = first_content_line(text)
    if not first.startswith("<!-- claim:"):
        line += "\tclaim-not-first-line (the claim must be the file's FIRST line, or the first line after frontmatter)"
    parts = p.parts
    if "AI-Agent" in parts and "scripts" not in parts and not has_frontmatter(text):
        line += "\tmissing-frontmatter (indicator: no frontmatter — vault AI-Agent/ files need tags+created or the commit gate blocks; keys live in frontmatter.yaml)"
    return {"skeleton": 1, "partial": 1, "complete": 2}[state], [line]


def verify(path: str, sections: list[str], min_bytes: int, targets: int) -> tuple[int, list[str]]:
    out, p = [], Path(path)
    if not p.is_file():
        out.append("FIND\tfail\tmissing\t" + str(p))
        return 1, out
    try:
        text = p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        out.append("FIND\tfail\tnot-utf8\t" + str(p) + " is not UTF-8 text")
        return 1, out
    hs, fails = headings(text), 0
    for sec in sections:
        if sec not in hs:
            out.append(f"FIND\tfail\tmissing-section\t{sec}")
            fails += 1
    for n, ln in enumerate(strip_fences(text).splitlines(), 1):
        if PLACEHOLDERS.search(ln):
            out.append(f"FIND\tfail\tplaceholder\t{p}:{n}\t{ln.strip()[:60]}")
            fails += 1
    if len(text.encode("utf-8")) < min_bytes:
        out.append(f"FIND\tfail\tmin-bytes\t{len(text.encode('utf-8'))} < {min_bytes}")
        fails += 1
    if STATUS not in text:
        out.append("FIND\tfail\tno-status-section\t" + STATUS)
        fails += 1
        return 1, out
    body = text.split(STATUS, 1)[1]
    tm = TARGETS.search(body)
    if not tm:
        out.append("FIND\tfail\tno-targets-line\ttargets: <confirmed>/<total>")
        fails += 1
    else:
        conf, tot = int(tm.group(1)), int(tm.group(2))
        if targets and tot != targets:
            out.append(f"FIND\tfail\ttargets-total\t{tot} != scope {targets}")
            fails += 1
        v_rows = [ln for ln in text.splitlines() if VERDICT_ROW.match(ln) and VERDICT_ROW.match(ln).group(1)]
        if v_rows and len(v_rows) != tot:
            out.append(f"FIND\twarn\tverdict-mismatch\tVERDICT rows {len(v_rows)} != status total {tot}")
    named = re.search(r"sections:[ \t]*([^\n]+)", body)
    if named:
        for sec in [s.strip() for s in named.group(1).split(",")]:
            if sec and sec not in hs:
                out.append(f"FIND\tfail\tstatus-section-missing\t{sec}")
                fails += 1
    return 1 if fails else 0, out


def recipe(d: str = ".agents/recipes") -> tuple[int, list[str]]:
    out = []
    dd = Path(d)
    if not dd.is_dir():
        return 1, [f"FIND\tfail\tmissing-dir\t{dd} (fail-closed: a missing recipe dir must not pass clean)"]
    for p in sorted(set(dd.glob("*.yaml")) | set(dd.glob("*.yml"))):
        text = p.read_text(encoding="utf-8", errors="replace")
        if RESPONSE_BLOCK.search(text):
            out.append("FIND\tfail\tresponse-block\t" + str(p))
        if COUNTER_RULE not in text:
            out.append("FIND\tfail\tno-counter-rule\t" + str(p))
    return 1 if out else 0, out


def _flag(args: list[str], flag: str, default: str) -> str:
    if flag in args:
        i = args.index(flag)
        if i + 1 >= len(args) or args[i + 1].startswith("--"):
            raise ValueError(f"{flag} needs a value")
        return args[i + 1]
    return default


def main(argv) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    try:
        if cmd == "check" and len(argv) == 2:
            rc, out = check(argv[1])
        elif cmd == "verify" and len(argv) >= 2:
            args = argv[2:]
            secs = [s.strip() for s in _flag(args, "--sections", "").split(",") if s.strip()]
            minb = int(_flag(args, "--min-bytes", "0"))
            tg = int(_flag(args, "--targets", "0"))
            rc, out = verify(argv[1], secs, minb, tg)
        elif cmd == "recipe":
            rc, out = recipe(_flag(argv, "--dir", ".agents/recipes"))
        else:
            print(__doc__)
            return 2
    except ValueError:
        print(__doc__)
        return 2
    for line in out:
        print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
