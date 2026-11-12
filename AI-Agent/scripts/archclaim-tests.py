# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for archclaim (plan AI-Agent/scratch/20261030-vault-writing-fixes-plan.md, F1+F2+F4).
Revision 2 (2026-10-30 critique): CLI-surface coverage via main(), bytes-mismatch,
multiple-claims, paths with spaces, word-boundary placeholders.
Revision 3 (2026-10-30 adversarial round, OP-0059): claim lines must name the CHECKED
file (claim-path-mismatch fires BEFORE bytes checks — ownership first); flag-without-value
and non-numeric flags = usage exit 2; recipe fail-closed on missing dir; *.yml scanned;
indented/list `response:` caught; not-utf8; is-directory; fenced TODO ignored; fenced
heading not a section; targets regex line-bound; claim-not-first-line hint. Usage: archclaim-tests
Revision 4 (2026-10-30 launch-pilot round, OP-0060): claim right after frontmatter = no
hint (pilot finding 2), claim late = hint; "partially confirmed" / "not confirmed yet"
verdict rows count toward the status total (pilot finding 1). Usage: archclaim-tests
Revision 5 (2026-10-30 self-critique round, OP-0061): BOM + frontmatter + claim parses
(no false hint); CRLF frontmatter; unclosed/double/blank-line/inside-FM cases KEEP the
hint; the missing-frontmatter indicator is path-scoped (AI-Agent/ minus scripts/) and
fires through the CLI too. Harness discipline (OP-0059 lesson): external behavior via
main()/CLI, direct function calls only for unit contracts — the harness must not
re-implement production assumptions. Usage: archclaim-tests"""

def _U(s):
    """ASCII-escaped test data: the shipped sources hold no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")

import contextlib
import io
import sys
import tempfile
from pathlib import Path

import archclaim

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


def w(path: str, text: str) -> Path:
    p = Path(tempfile.mkdtemp()) / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="")
    return p


def claim(state: str, b: int, path: str) -> str:
    return f"<!-- claim: {path} <- 20261030_13 :: {state} :: {b} -->"


def cli(argv):
    """Silent CLI runner: returns (exit code, captured stdout)."""
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        rc = archclaim.main(argv)
    return rc, buf.getvalue()


TOOL = "<!-- tool-env: fetch, gitmcp, execute_javascript, shell -->"
base = "# T\n## SOURCES\n## CONCEPTS\n## VERDICT\n## Deliverable status\n- targets: 2/2\n"


def sized(text: str) -> int:
    return len(text.encode("utf-8"))


def claimed(state: str, first=True) -> Path:
    """File whose claim line names its own path with exact bytes (fixpoint)."""
    p = w("d.md", base)
    pre = claim(state, 0, str(p)) + "\n" if first else base + claim(state, 0, str(p)) + "\n"
    p.write_text(pre, encoding="utf-8", newline="")
    for _ in range(5):                     # the bytes string changes the size; iterate to the fixpoint
        real = sized(p.read_text(encoding="utf-8"))
        body = claim(state, real, str(p)) + "\n" if first else base + claim(state, real, str(p)) + "\n"
        p.write_text(body, encoding="utf-8", newline="")
        if sized(p.read_text(encoding="utf-8")) == real:
            return p
    return p


def claimed_after(state: str, pre: str, name: str = "d.md") -> Path:
    """Claim placed AFTER `pre` (e.g. frontmatter), names its own path, exact bytes.
    `name` may carry a subdir (created by w()); used for path-scoped rules."""
    p = w(name, pre)                       # create first so the claim can name the real path
    p.write_text(pre + claim(state, 0, str(p)) + "\n" + base, encoding="utf-8", newline="")
    for _ in range(5):
        real = sized(p.read_text(encoding="utf-8"))
        p.write_text(pre + claim(state, real, str(p)) + "\n" + base, encoding="utf-8", newline="")
        if sized(p.read_text(encoding="utf-8")) == real:
            return p
    return p


def claimed_wrapped(state: str, pre: str, post: str, name: str = "d.md") -> Path:
    """Claim placed INSIDE `pre` (e.g. between the frontmatter fences), names its
    own path, exact bytes; the body continues with `post`."""
    p = w(name, pre)
    p.write_text(pre + claim(state, 0, str(p)) + post, encoding="utf-8", newline="")
    for _ in range(5):
        real = sized(p.read_text(encoding="utf-8"))
        p.write_text(pre + claim(state, real, str(p)) + post, encoding="utf-8", newline="")
        if sized(p.read_text(encoding="utf-8")) == real:
            return p
    return p


def rules(out):
    return [ln.split("\t")[2] for ln in out]


# --- claim_line parsing
c = archclaim.claim_line(claim("complete", 4592, "deliverable.md"))
ok("claim-parse", c == {"path": "deliverable.md", "agent": "20261030_13", "state": "complete", "bytes": 4592}, c)
ok("claim-none", archclaim.claim_line("# no claim here\n") is None)
ok("claim-invalid-state", archclaim.claim_line("<!-- claim: d.md <- a1 :: done :: 1 -->") is None)

# --- check: missing file, directory, no claim, each state with MATCHING bytes
rc, out = archclaim.check("/nonexistent/x.md")
ok("check-missing", rc == 0 and out[0].startswith("NONE"))
dtmp = Path(tempfile.mkdtemp()) / "sub"
dtmp.mkdir()
ok("check-directory-exit2", archclaim.check(str(dtmp))[0] == 2 and cli(["check", str(dtmp)])[0] == 2)
rc, out = archclaim.check(w("a.md", base))
ok("check-no-claim", rc == 0 and out[0].startswith("NO-CLAIM"))
ok("check-skeleton-exit1", archclaim.check(w("a.md", claim("skeleton", 0, "a.md") + "\n" + base))[0] == 1)
ok("check-partial-exit1", archclaim.check(w("a.md", claim("partial", 0, "a.md") + "\n" + base))[0] == 1)
rc, out = archclaim.check(claimed("complete"))
ok("check-complete-exit2", rc == 2 and "fp=" in out[0], out)
rc, out = archclaim.check(claimed("skeleton"))
ok("check-skeleton-exit1-exact", rc == 1 and "SKELETON\t" in out[0], out)

# --- check (rev4): claim line right after frontmatter = no hint (pilot finding 2)
FM = "---\ntags: [ai-agent]\ncreated: 2026-10-30\n---\n"
rc, out = archclaim.check(claimed_after("complete", FM))
ok("check-after-fm-no-hint", rc == 2 and "claim-not-first-line" not in out[0], out)
rc, out = archclaim.check(claimed_after("partial", FM + "# intro\n"))
ok("check-after-fm-late-hint", rc == 1 and "claim-not-first-line" in out[0], out)

# --- check (rev5, OP-0061): frontmatter adversarial round + BOM/CRLF + FM indicator
# BOM editor save: 'BOM + frontmatter + claim' must NOT raise a false hint
rc, out = archclaim.check(claimed_after("complete", "\ufeff" + FM))
ok("check-bom-after-fm-no-hint", rc == 2 and "claim-not-first-line" not in out[0], out)
# CRLF frontmatter: \r\n line endings must still be recognized (strip() handles \r)
rc, out = archclaim.check(claimed_after("complete", FM.replace("\n", "\r\n")))
ok("check-crlf-after-fm-no-hint", rc == 2 and "claim-not-first-line" not in out[0], out)
# unclosed frontmatter: no closing ---, the claim can never be the first content line
rc, out = archclaim.check(claimed_after("complete", "---\ntags: [ai-agent]\ncreated: 2026-10-30\n"))
ok("check-fm-unclosed-hint", rc == 2 and "claim-not-first-line" in out[0], out)
# claim INSIDE the frontmatter fences: not the first content line
rc, out = archclaim.check(claimed_wrapped("complete", "---\n", "\n---\n" + base))
ok("check-fm-inside-hint", rc == 2 and "claim-not-first-line" in out[0], out)
# double frontmatter: only ONE leading FM block is recognized — strict
rc, out = archclaim.check(claimed_after("complete", FM + FM))
ok("check-fm-double-hint", rc == 2 and "claim-not-first-line" in out[0], out)
# blank line between FM and the claim: strict (no blank lines) — the hint stays
rc, out = archclaim.check(claimed_after("complete", FM + "\n"))
ok("check-fm-blank-hint", rc == 2 and "claim-not-first-line" in out[0], out)
# unit contracts for the two helpers
ok("has-frontmatter-basic", archclaim.has_frontmatter(FM + "# x\n") is True)
ok("has-frontmatter-bom", archclaim.has_frontmatter("\ufeff" + FM) is True)
ok("has-frontmatter-none", archclaim.has_frontmatter("# T\n") is False)
ok("fcl-bom", archclaim.first_content_line("\ufeff---\nt: 1\n---\n# T\n") == "# T")
ok("fcl-crlf", archclaim.first_content_line("---\r\nt: 1\r\n---\r\n# T\r\n") == "# T")
ok("fcl-unclosed-empty", archclaim.first_content_line("---\nt: 1\n# T\n") == "")
# missing-frontmatter indicator: path-scoped to AI-Agent/ minus scripts/
rc, out = archclaim.check(claimed_after("complete", "", name="AI-Agent/d.md"))
ok("check-ai-agent-missing-fm-hint", rc == 2 and "missing-frontmatter" in out[0], out)
rc, out = archclaim.check(claimed_after("complete", FM, name="AI-Agent/d.md"))
ok("check-ai-agent-fm-no-hint", rc == 2 and "missing-frontmatter" not in out[0], out)
rc, out = archclaim.check(claimed_after("complete", "", name="AI-Agent/scripts/d.md"))
ok("check-scripts-exempt-no-fm-hint", rc == 2 and "missing-frontmatter" not in out[0], out)
rc, out = archclaim.check(claimed("complete"))
ok("check-outside-vault-no-fm-hint", rc == 2 and "missing-frontmatter" not in out[0], out)
# CLI surface: the indicator fires through main() too, exit code unchanged
rc, out = cli(["check", str(claimed_after("complete", "", name="AI-Agent/d.md"))])
ok("cli-missing-fm-hint", rc == 2 and "missing-frontmatter" in out, out)

# --- check: bytes mismatch (file changed since the claim was written) -> exit 1
p = claimed("complete")
p.write_text(p.read_text(encoding="utf-8") + "\nextra line\n", encoding="utf-8", newline="")
rc, out = archclaim.check(str(p))
ok("check-bytes-mismatch", rc == 1 and "bytes-mismatch" in out[0], out)

# --- check: multiple claim lines -> exit 1 (stale ownership)
two = claim("complete", 0, "d.md") + "\n" + claim("partial", 0, "d.md") + "\n" + base
rc, out = archclaim.check(w("d.md", two))
ok("check-multiple-claims", rc == 1 and "multiple-claims" in out[0], out)

# --- check (rev3): claim names a DIFFERENT file than the one checked -> exit 1 (before bytes checks)
other = claim("complete", 0, "03-Resources/Authoritative References.md")
rc, out = archclaim.check(w("d.md", other + "\n" + base))
ok("check-claim-path-mismatch", rc == 1 and "claim-path-mismatch" in out[0] and "Authoritative References.md" in out[0], out)

# --- check (rev3): claim not the FIRST line -> exit code unchanged + hint
rc, out = archclaim.check(claimed("partial", first=False))
ok("check-not-first-line-partial", rc == 1 and "claim-not-first-line" in out[0], out)
rc, out = archclaim.check(claimed("complete", first=False))
ok("check-not-first-line-complete", rc == 2 and "claim-not-first-line" in out[0], out)

# --- check (rev3): binary file -> exit 1 not-utf8, no crash (check + verify + CLI)
binp = Path(tempfile.mkdtemp()) / "bin.md"
binp.write_bytes(b"\xff\xfe\x00bad")
rc, out = archclaim.check(str(binp))
ok("check-not-utf8", rc == 1 and "not-utf8" in rules(out), out)
rc, out = archclaim.verify(str(binp), [], 0, 0)
ok("verify-not-utf8", rc == 1 and "not-utf8" in rules(out), out)
ok("cli-not-utf8", cli(["check", str(binp)])[0] == 1)

# --- tool_env
ok("tool-env", archclaim.tool_env(TOOL + "\ntext") == ["fetch", "gitmcp", "execute_javascript", "shell"])
ok("tool-env-absent", archclaim.tool_env(base) is None)

# --- verify: passing file
good = (claim("complete", 0, "good.md") + "\n" + TOOL + "\n# T\n## SOURCES\n## CONCEPTS\n## VERDICT\n"
        "- **swarm:** confirmed\n- **autogen:** uncertain\n"
        "## Deliverable status\n- targets: 2/2\n- sections: SOURCES, CONCEPTS, VERDICT\n")
rc, out = archclaim.verify(str(w("good.md", good)), ["SOURCES", "CONCEPTS", "VERDICT"], 100, 2)
ok("verify-pass", rc == 0 and not out, out)

# --- verify: failing file
bad = (claim("partial", 300, "bad.md") + "\n## SOURCES\nsome TODO left\n")
rc, out = archclaim.verify(str(w("bad.md", bad)), ["SOURCES", "CONCEPTS"], 1000, 0)
ok("verify-fail", rc == 1)
ok("verify-missing-section", "missing-section" in rules(out))
ok("verify-placeholder", "placeholder" in rules(out))
ok("verify-fail-min-bytes", "min-bytes" in rules(archclaim.verify(str(w("b.md", bad)), ["SOURCES"], 1000, 0)[1]))
ok("verify-no-status", "no-status-section" in rules(archclaim.verify(str(w("b.md", "# t\n## SOURCES\n")), [], 0, 0)[1]))

# --- verify: placeholder word boundaries (critique fix: "todoist" must NOT match)
p = w("wb.md", "## Deliverable status\n- targets: 1/1\n- sections: \ntodoist app reviewed\n")
rc, out = archclaim.verify(str(p), [], 0, 0)
ok("verify-placeholder-boundary", rc == 0 and not out, out)

# --- verify (rev3): TODO inside a code fence is a legitimate example, not a defect
p = w("f.md", "## Deliverable status\n- targets: 1/1\n- sections: \n```\nexample: TODO here\n```\ndone\n")
rc, out = archclaim.verify(str(p), [], 0, 0)
ok("verify-fenced-todo-ok", rc == 0 and not out, out)
# ...but a fenced fake heading must NOT satisfy a required section
p = w("f2.md", "```\n## SOURCES\n```\n## Deliverable status\n- targets: 1/1\n")
rc, out = archclaim.verify(str(p), ["SOURCES"], 0, 0)
ok("verify-fenced-heading-not-section", rc == 1 and "missing-section" in rules(out), out)

# --- verify (rev3): `targets:` regex no longer crosses newlines ("1/\n\n3" is not a valid pair)
p = w("st.md", "## Deliverable status\n- targets: 1/\n\n3\n")
rc, out = archclaim.verify(str(p), [], 0, 0)
ok("verify-targets-newline", rc == 1 and "no-targets-line" in rules(out), out)
ok("targets-regex-linebound", archclaim.TARGETS.search("- targets: 1/\n\n3") is None)
ok("targets-regex-spaced", archclaim.TARGETS.search("targets: 1 / 2").groups() == ("1", "2"))

# --- verify: status present, targets line read; VERDICT rows != total is a warn only
bad2 = ("## SOURCES\n## VERDICT\n- **swarm:** confirmed\n- **autogen:** uncertain\n"
        "## Deliverable status\n- targets: 1/5\n- sections: SOURCES\n")
rc, out = archclaim.verify(str(w("bad2.md", bad2)), [], 0, 0)
ok("verify-targets-present", rc == 0 and "no-targets-line" not in rules(out), rules(out))
ok("verify-verdict-mismatch-warn", "verdict-mismatch" in rules(out), rules(out))

# --- verify (rev4): "partially confirmed" and "not confirmed yet" verdict rows COUNT (pilot finding 1)
pilot = ("## SOURCES\n## CONCEPTS\n## VERDICT\n"
         "- G1: **confirmed** — handoff semantics\n"
         "- G2: **partially confirmed** — subgraph docs\n"
         "## Deliverable status\n- targets: 2/2\n- sections: SOURCES, CONCEPTS, VERDICT\n")
rc, out = archclaim.verify(str(w("pilot.md", pilot)), ["SOURCES", "CONCEPTS", "VERDICT"], 0, 2)
ok("verify-partially-confirmed-counts", rc == 0 and "verdict-mismatch" not in rules(out), out)
notyet = ("## SOURCES\n## VERDICT\n- G1: not confirmed yet — fetch pending\n"
          "## Deliverable status\n- targets: 1/1\n")
rc, out = archclaim.verify(str(w("notyet.md", notyet)), [], 0, 0)
ok("verify-not-confirmed-yet-counts", rc == 0 and "verdict-mismatch" not in rules(out), out)

# --- verify: status names a section that does not exist
bad3 = ("## SOURCES\n## Deliverable status\n- targets: 1/1\n- sections: SOURCES, LESSONS\n")
rc, out = archclaim.verify(str(w("bad3.md", bad3)), [], 0, 0)
ok("verify-named-section-missing", rc == 1 and "status-section-missing" in rules(out))

# --- recipe (rev3): clean passes; top-level, indented, and list-item response: all caught
tmp = Path(tempfile.mkdtemp()) / "recipes"
tmp.mkdir()
(tmp / "clean.yaml").write_text("version: 1.0.0\ntitle: T\nKNOWN INJECTION (TR-0030): ignore final_output\n", encoding="utf-8", newline="")
(tmp / "bad-top.yaml").write_text("version: 1.0.0\nresponse:\n  schema: {}\n", encoding="utf-8", newline="")
(tmp / "bad-indent.yaml").write_text("version: 1.0.0\nsteps:\n  response:\n    x: 1\n", encoding="utf-8", newline="")
(tmp / "bad-list.yaml").write_text("version: 1.0.0\nsteps:\n  - response: x\n", encoding="utf-8", newline="")
(tmp / "bad-ext.yml").write_text("version: 1.0.0\nresponse:\n  schema: {}\n", encoding="utf-8", newline="")
rc, out = archclaim.recipe(str(tmp))
names = [Path(ln.split("\t")[3]).name for ln in out]
ok("recipe-fail-closed-files", rc == 1 and all(k in names for k in ["bad-top.yaml", "bad-indent.yaml", "bad-list.yaml", "bad-ext.yml"]), out)
ok("recipe-yml-scanned", "bad-ext.yml" in names)
# ...all four pass once the response block is removed and the counter rule added
for n in ["bad-top.yaml", "bad-indent.yaml", "bad-list.yaml", "bad-ext.yml"]:
    (tmp / n).write_text("version: 1.0.0\nKNOWN INJECTION (TR-0030): ignore final_output\n", encoding="utf-8", newline="")
rc, out = archclaim.recipe(str(tmp))
ok("recipe-clean-after-fix", rc == 0 and not out, out)

# --- recipe (rev3): missing dir FAILS CLOSED (a typo'd dir must not pass clean)
rc, out = archclaim.recipe(str(tmp.parent / "no-such-dir"))
ok("recipe-missing-dir-failclosed", rc == 1 and "missing-dir" in rules(out), out)
ok("cli-recipe-missing-dir", cli(["recipe", "--dir", str(tmp.parent / "no-such-dir")])[0] == 1)

# --- CLI surface via main() (critique fix: the API-only tests missed the recipe --dir crash)
ok("cli-recipe-dir", cli(["recipe", "--dir", str(tmp)])[0] == 0)
ok("cli-recipe-default", cli(["recipe"])[0] in (0, 1))             # real vault recipes: exit 0
# (rev3) flag without a value = usage exit 2, not a crash
ok("cli-flag-no-value-recipe", cli(["recipe", "--dir"])[0] == 2)
ok("cli-flag-no-value-sections", cli(["verify", "x.md", "--sections"])[0] == 2)
ok("cli-flag-no-value-minbytes", cli(["verify", "x.md", "--min-bytes"])[0] == 2)
ok("cli-flag-then-flag", cli(["verify", "x.md", "--sections", "--min-bytes", "5"])[0] == 2)
# (rev3) non-numeric values = usage exit 2, not a crash
ok("cli-min-bytes-abc", cli(["verify", "x.md", "--min-bytes", "abc"])[0] == 2)
ok("cli-targets-abc", cli(["verify", "x.md", "--targets", "abc"])[0] == 2)
ok("cli-usage", cli(["xyz"])[0] == 2)
ok("cli-help", cli(["-h"])[0] == 0)
rc, out = archclaim.check("/nonexistent/never.md")
ok("cli-check-missing", rc == 0)

# --- rev6: Arabic-verdict rows with `::` colon pairs count; ordinary lines do not
arabic = (_U(r"## SOURCES\n## VERDICT\n- \u06331: **\u0645\u0624\u0643\u062f** \u2014 \u062f1 \u0628\u0628\u0648\u0627\u0628\u0629 \u0645\u0633\u062c\u0644\u0629\n"
          r"- \u06332: \u063a\u064a\u0631 \u0645\u0624\u0643\u062f \u2014 \u064a\u0646\u062a\u0638\u0631 \u062a\u0623\u0643\u064a\u062f \u0633\u0639\u0648\u062f\n"
          r"- \u06333: :: \u063a\u064a\u0631 \u0645\u0648\u062c\u0648\u062f \u2014 \u0644\u0627 \u0623\u062b\u0631 \u0639\u0644\u0649 \u0627\u0644\u0642\u0631\u0635\n"
          r"## Deliverable status\n- targets: 3/3\n"))
rc, out = archclaim.verify(str(w("arabic.md", arabic)), ["SOURCES"], 0, 3)
ok("rev6-arabic-verdict-rows-count", rc == 0 and "verdict-mismatch" not in rules(out), out)
noac = (_U(r"## SOURCES\n## VERDICT\n- \u0627\u0644\u063a\u0631\u0636: \u0645\u0646 \u0627\u0644\u062d\u0645\u0627\u0634\u0627\u062a \u0644\u0627 \u0627\u0644\u0627\u062f\u0639\u0627\u0621\u0627\u062a\n"
        r"## Deliverable status\n- targets: 2/2\n"))
rc, out = archclaim.verify(str(w("noac.md", noac)), ["SOURCES"], 0, 2)
ok("rev6-colon-pair-no-verdict-not-counted", rc == 0 and "verdict-mismatch" not in rules(out), out)

# --- summary
fails = [n for n, c, _ in R if not c]
print(f"archclaim-tests: {len(R) - len(fails)}/{len(R)} ok")
if fails:
    print("FAILED:", ", ".join(fails))
sys.exit(1 if fails else 0)
