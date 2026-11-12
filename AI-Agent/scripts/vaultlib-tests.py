# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for _vaultlib parsing; run after any change to _vaultlib. Usage: vaultlib-tests [--regress]"""

def _U(s):
    """ASCII-escaped test data: the shipped sources hold no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")


import subprocess
import sys
from datetime import date

from _vaultlib import VAULT, iter_md, rel, read, parse, sections, leaf_sections, inline_texts, normalize_ar, is_readme, pause_window, Pause


R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


S1 = _U(r'---\ntags: [a, b]\narea: "[[X]]"\n---\n# T\n## \u0625\u062f\u0627\u0631\u0629\u064f `#topic` \u0648 #real\ntext\n```\n## not heading\n```\n### sub\nline\n## Two\n')
d = parse(S1)
ok("front matter body_start", d.body_start == 5, d.body_start)
ok("front matter yaml", d.fm == {"tags": ["a", "b"], "area": "[[X]]"}, d.fm)
ok("headings skip fenced code", [h.title for h in d.headings] == ["T", _U(r"\u0625\u062f\u0627\u0631\u0629\u064f `#topic` \u0648 #real"), "sub", "Two"], [h.title for h in d.headings])
ok("heading lines file-absolute", [h.line for h in d.headings] == [5, 6, 11, 13], [h.line for h in d.headings])
h = d.headings[1]
ok("code span vs real tag", h.has_code and "#topic" not in h.plain and "#real" in h.plain, h.plain)
ok("sections compatible", sections(S1)[1] == (2, _U(r"\u0625\u062f\u0627\u0631\u0629\u064f `#topic` \u0648 #real"), 6, 7), sections(S1)[1])

S2 = "a\n%%\n## hidden\n%%\n## shown\n```\n%% not a comment %%\n```\n"
hs2 = parse(S2).headings
ok("obsidian %% comment hides heading, keeps lines", [(x.line, x.title) for x in hs2] == [(5, "shown")], [(x.line, x.title) for x in hs2])

S3 = "<!--\n## in html comment\n-->\n## real\n"
ok("html comment hides heading", [x.title for x in parse(S3).headings] == ["real"], [x.title for x in parse(S3).headings])

S4 = "Title\n=====\n\npara\nNot a rule\n---\n#tag not heading\n"
hs4 = parse(S4).headings
ok("setext headings detected", [(x.level, x.setext) for x in hs4] == [(1, True), (2, True)], [(x.level, x.title, x.setext) for x in hs4])

# GFM: a line right after a table continues the table, so the prose line needs a blank line before it
S5 = "## T\n| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\ntext\n## U\n"
ls = leaf_sections(S5)
ok("table share of leaf section", abs(ls[0]["atomic_share"] - 0.8) < 1e-9, ls[0])

S6 = "> [!note]\n> ## in callout\n\n- ## in list\n"
d6 = parse(S6)
# Obsidian's metadata cache ignores headings inside blockquotes (D9 cross-check, 11 Sep 2026)
ok("nested headings kept out of headings()", d6.headings == [] and len(d6.nested_headings) == 2 and all(x.nested for x in d6.nested_headings), ([x.title for x in d6.headings], [x.title for x in d6.nested_headings]))

S7 = "---\na: [unclosed\n---\n# x\n"
ok("yaml error captured", parse(S7).fm_error != "", parse(S7).fm_error)

ok("normalize_ar variants", normalize_ar(_U(r"\u0625\u062f\u0627\u0631\u0629\u064f")) == normalize_ar(_U(r"\u0627\u062f\u0627\u0631\u0647")))
ok("normalize_ar digits", normalize_ar(_U(r"\u0642\u0633\u0645 \u0661\u0662\u0663")) == normalize_ar(_U(r"\u0642\u0633\u0645 123")) == _U(r"\u0642\u0633\u0645 123"))
ok("inline_texts drops code spans", all("#topic" not in t for _, t in inline_texts(S1)), list(inline_texts(S1)))
S8 = "first line word\n[[link]] second line\n"
ok("inline_texts keeps soft line breaks", list(inline_texts(S8)) == [(1, "first line word\n[[link]] second line")], list(inline_texts(S8)))
files = list(iter_md())
ok("iter_md excludes README", files and not any(is_readme(p) for p in files), len(files))

# pause_window (D11, AD03 X03): the single reader of the club's seasonal pause line
def pw(text):
    w = []
    return pause_window(text, w), w


P_OK = _U(r"## \u0627\u0644\u0625\u064a\u0642\u0627\u0639\n\n- \u0625\u064a\u0642\u0627\u0641:: 2026-12-01 \u2192 2027-01-10\n")
r, w = pw(_U(r"## \u0627\u0644\u0625\u064a\u0642\u0627\u0639\n\n\u0646\u0635 \u0628\u0644\u0627 \u0625\u064a\u0642\u0627\u0641\n"))
ok("pause: no line -> None, no warning", r is None and w == [], (r, w))
r, w = pw(P_OK)
ok("pause: valid line", r == Pause(date(2026, 12, 1), date(2027, 1, 10)) and w == [], (r, w))
ok("pause: inside window (edges inclusive)", r and r.contains(date(2026, 12, 1)) and r.contains(date(2026, 12, 25)) and r.contains(date(2027, 1, 10)), r)
ok("pause: outside window", r and not r.contains(date(2026, 11, 30)) and not r.contains(date(2027, 1, 11)), r)
for label, bad in (("wrong arrow", "2026-12-01 - 2027-01-10"), ("impossible date", "2026-13-01 → 2027-01-10"),
                   ("start after end", "2027-02-01 → 2027-01-10"), ("empty value", "")):
    r, w = pw(_U(r"- \u0625\u064a\u0642\u0627\u0641:: ") + f"{bad}\n")
    ok(f"pause: malformed ({label}) -> None + warning", r is None and len(w) == 1 and "malformed" in w[0], (r, w))
r, w = pw(P_OK + _U(r"- \u0625\u064a\u0642\u0627\u0641:: 2027-06-01 \u2192 2027-06-10\n"))
ok("pause: two lines -> None + warning", r is None and len(w) == 1 and "expected one" in w[0], (r, w))
r, w = pw(_U(r"%% - \u0625\u064a\u0642\u0627\u0641:: 2026-12-01 \u2192 2027-01-10 %%\n\n```\n\u0625\u064a\u0642\u0627\u0641:: 2026-12-01 \u2192 2027-01-10\n```\n\n`\u0625\u064a\u0642\u0627\u0641:: 2026-12-01 \u2192 2027-01-10`\n"))
ok("pause: comment, code block and code span ignored", r is None and w == [], (r, w))
live_w = []
live = pause_window(warnings=live_w)
ok("pause: live club area parses without warning", live_w == [] and (live is None or isinstance(live, Pause)), (live, live_w))

if "--regress" in sys.argv:
    def git(*a):
        return subprocess.run(["git", "-C", str(VAULT), *a], capture_output=True, text=True).stdout
    revs = git("log", "--format=%H", "--", "AI-Agent/scripts/_vaultlib.py", "Claude/scripts/_vaultlib.py").split()
    old_ns = {"__name__": "_vaultlib_old"}
    has_new = subprocess.run(["git", "-C", str(VAULT), "cat-file", "-e", f"{revs[-1]}:AI-Agent/scripts/_vaultlib.py"]).returncode == 0
    old_path = "AI-Agent/scripts/_vaultlib.py" if has_new else "Claude/scripts/_vaultlib.py"
    exec(git("show", f"{revs[-1]}:{old_path}"), old_ns)
    diffs = []
    for p in iter_md(include_readme=True):
        t = read(p)
        old = set(old_ns["headings"](t))
        new = set((x.line, x.level, x.title) for x in parse(t).headings)
        if old != new:
            diffs.append((rel(p), sorted(old - new)[:2], sorted(new - old)[:2], len(old - new), len(new - old)))
    print(f"REGRESS vs {revs[-1][:10]}: files_differing={len(diffs)}")
    for r, only_old, only_new, n_old, n_new in diffs[:10]:
        print(f"  {r}: only_old={n_old} {only_old} | only_new={n_new} {only_new}")

failed = [x for x in R if not x[1]]
for name, passed, got in R:
    print(("PASS" if passed else "FAIL"), name, "" if passed else f"-> {got}")
print(f"{len(R) - len(failed)}/{len(R)} passed")
