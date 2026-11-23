# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for _vaultlib (2026-10-23, AD10 C15 stage 6): the shared parsing
library every other suite builds on -- Arabic normalization, README/iter_md
filtering, rel() safety, parse() structure (headings, nested, code/table lines,
front matter), Obsidian %% comment masking, sections/leaf_sections/inline_texts,
and pause_window (single reader of the club pause line). VAULT is monkeypatched
to a temp dir; the real vault is never touched.
Usage: _vaultlib-tests"""

def _U(s):
    """ASCII-escaped test data: the shipped sources hold no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")

import copy
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

import _vaultlib as L
L.scrub_git_env()   # hook variables must not reach temporary repositories below (T53)

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))

HAS_AR = bool(L.locale_value("NORMALIZE", {}))   # the Arabic tables exist only in the mother vault; a release normalizes nothing


def aok(name, cond, detail=""):
    """ok(), run only where the Arabic locale tables are present."""
    if HAS_AR:
        ok(name, cond, detail)
    else:
        print(f"SKIP {name}: no Arabic locale in this tree")



ORIG_VAULT = L.VAULT
TMP = Path(tempfile.mkdtemp(prefix="vaultlib-tests-"))
try:
    # T1: normalize_ar strips tashkeel only
    ok("T1-normalize-tashkeel", L.normalize_ar(_U(r"\u0645\u064f\u062d\u064e\u0645\u064e\u0651\u062f")) == _U(r"\u0645\u062d\u0645\u062f")
       and L.normalize_ar(_U(r"\u064B\u0651")) == "", L.normalize_ar(_U(r"\u0645\u064f\u062d\u064e\u0645\u064e\u0651\u062f")))

    # T2: letter variants all map
    aok("T2-normalize-letters",
       L.normalize_ar(_U(r"\u0623")) == _U(r"\u0627") and L.normalize_ar(_U(r"\u0625")) == _U(r"\u0627")
       and L.normalize_ar(_U(r"\u0622")) == _U(r"\u0627") and L.normalize_ar(_U(r"\u0671")) == _U(r"\u0627")
       and L.normalize_ar(_U(r"\u0629")) == _U(r"\u0647") and L.normalize_ar(_U(r"\u0649")) == _U(r"\u064a")
       and L.normalize_ar(_U(r"\u0624")) == _U(r"\u0648") and L.normalize_ar(_U(r"\u0626")) == _U(r"\u064a"))

    # T3: Arabic-Indic digits to ASCII + casefold
    aok("T3-normalize-digits-casefold",
       L.normalize_ar(_U(r"\u0665\u0662")) == "52" and L.normalize_ar("Hello") == "hello",
       L.normalize_ar(_U(r"\u0665\u0662")) + "|" + L.normalize_ar("Hello"))

    # T4: tatweel (\u0640) is part of the tashkeel class
    ok("T4-normalize-tatweel", L.normalize_ar(_U(r"\u0645\u0640\u0640\u062f")) == _U(r"\u0645\u062f"), L.normalize_ar(_U(r"\u0645\u0640\u0640\u062f")))

    # T5: is_readme matches any case, full path or name
    ok("T5-is_readme", L.is_readme("README.md") and L.is_readme("readme.md")
       and L.is_readme(Path("/x/ReadMe.MD")) and not L.is_readme("notes.md")
       and not L.is_readme("readme.txt"))

    # --- filesystem layer: VAULT monkeypatched ---
    L.VAULT = TMP
    (TMP / "a.md").write_text(_U(r"\u0623"), encoding="utf-8")
    (TMP / "b.txt").write_text("x", encoding="utf-8")
    (TMP / "README.md").write_text("x", encoding="utf-8")
    (TMP / "sub").mkdir()
    (TMP / "sub" / "c.md").write_text("x", encoding="utf-8")
    (TMP / ".obsidian").mkdir()
    (TMP / ".obsidian" / "x.md").write_text("x", encoding="utf-8")
    (TMP / ".git").mkdir()
    (TMP / ".git" / "y.md").write_text("x", encoding="utf-8")
    (TMP / ".trash").mkdir()
    (TMP / ".trash" / "z.md").write_text("x", encoding="utf-8")
    (TMP / "node_modules").mkdir()
    (TMP / "node_modules" / "w.md").write_text("x", encoding="utf-8")

    # T6: iter_md default yields .md only, skips README and system dirs
    got = {L.rel(p) for p in L.iter_md()}
    ok("T6-iter_md-default", got == {"a.md", "sub/c.md"}, str(sorted(got)))

    # T7: iter_md(include_readme=True) adds README.md, still skips system dirs
    got = {L.rel(p) for p in L.iter_md(include_readme=True)}
    ok("T7-iter_md-readme", got == {"a.md", "README.md", "sub/c.md"}, str(sorted(got)))

    # T8: rel() gives vault-relative paths
    ok("T8-rel-basic", L.rel(TMP / "x.md") == "x.md"
       and L.rel(TMP / "sub" / "y.md") == "sub/y.md", L.rel(TMP / "sub" / "y.md"))

    # T9: rel() crashes loudly (ValueError) on paths outside the vault
    try:
        L.rel(Path(TMP).parent / "outside.md")
        ok("T9-rel-outside", False, "no exception")
    except ValueError:
        ok("T9-rel-outside", True)

    # T10: parse() front matter block + structure
    FM_TEXT = _U(r"---\ntitle: \u062a\u062c\u0631\u0628\u0629\nstatus: active\n---\n# \u0639\u0646\u0648\u0627\u0646\n## \u0641\u0631\u0639\n")
    d = L.parse(FM_TEXT)
    ok("T10-parse-fm", d.has_fm and d.body_start == 5
       and d.fm == {"title": _U(r"\u062a\u062c\u0631\u0628\u0629"), "status": "active"} and d.fm_error == ""
       and d.total_lines == 7 and [(h.line, h.level, h.title) for h in d.headings]
       == [(5, 1, _U(r"\u0639\u0646\u0648\u0627\u0646")), (6, 2, _U(r"\u0641\u0631\u0639"))], str(d.fm) + "|" + str(d.headings))

    # T11: heading fields -- plain strips code spans, setext detected
    SETEXT = _U(r"# `\u0639\u0646\u0648\u0627\u0646` \u0646\u0635\n\n\u062e\u0627\u062a\u0645\u0629\n===\n")
    d = L.parse(SETEXT)
    h1, h2 = d.headings
    ok("T11-heading-fields",
       h1.line == 1 and h1.level == 1 and h1.title == _U(r"`\u0639\u0646\u0648\u0627\u0646` \u0646\u0635")
       and h1.plain == _U(r" \u0646\u0635") and h1.has_code and not h1.nested and not h1.setext
       and h2.line == 3 and h2.level == 1 and h2.setext and not h2.has_code,
       # plain joins text-token children only: markdown-it splits heading inline
       # into [code_inline, text ' '], so plain carries the leading space
       str((h1, h2)))

    # T12: code_lines and table_lines are exact 1-based ranges; heading after table
    CT = "```py\nx=1\n```\n| a | b |\n|---|---|\n| 1 | 2 |\n# H\n"
    d = L.parse(CT)
    ok("T12-code-table-lines", d.code_lines == {1, 2, 3} and d.table_lines == {4, 5, 6}
       and [(h.line, h.title) for h in d.headings] == [(7, "H")],
       str((set(d.code_lines), set(d.table_lines), d.headings)))

    # T13: headings inside blockquotes/list items are nested, not top-level
    NEST = "# a\n> ## quoted\n- # listitem\n## real\n"
    d = L.parse(NEST)
    ok("T13-nested-headings", [h.line for h in d.headings] == [1, 4]
       and [h.line for h in d.nested_headings] == [2, 3]
       and all(h.nested for h in d.nested_headings),
       str((d.headings, d.nested_headings)))

    # T14: non-mapping front matter -> fm_error set, fm empty
    d = L.parse("---\n- item\n---\n# h\n")
    ok("T14-fm-not-mapping", d.has_fm and d.fm == {} and d.fm_error == "front matter is not a mapping",
       str((d.fm, d.fm_error)))

    # T15: broken YAML -> fm_error = first line of the error
    d = L.parse("---\ntitle: [unclosed\n---\n# h\n")
    ok("T15-fm-yaml-error", d.has_fm and d.fm == {} and d.fm_error != ""
       and d.fm_error != "front matter is not a mapping", str(d.fm_error))

    # T16: %% comments are masked -- fake heading inside ignored
    d = L.parse("# real\n%% # fake %%\n")
    ok("T16-obs-comment", [(h.line, h.title) for h in d.headings] == [(1, "real")],
       str(d.headings))

    # T17: multi-line %% comment fully masked
    d = L.parse("%%\n# fake\n%%\n# real\n")
    ok("T17-obs-comment-multiline", [(h.line, h.title) for h in d.headings] == [(4, "real")],
       str(d.headings))

    # T18: %% comment inside a code fence is NOT masked (code kept intact)
    d = L.parse("```\n%% x %%\n```\n# real\n")
    ok("T18-obs-comment-in-code", d.code_lines == {1, 2, 3}
       and [(h.line, h.title) for h in d.headings] == [(4, "real")],
       str((set(d.code_lines), d.headings)))

    # T19: split_frontmatter with fm -> raw, body from body_start
    fm_raw, body, bs = L.split_frontmatter(FM_TEXT)
    ok("T19-split-fm", fm_raw == _U(r"title: \u062a\u062c\u0631\u0628\u0629\nstatus: active")
       and body == _U(r"# \u0639\u0646\u0648\u0627\u0646\n## \u0641\u0631\u0639\n") and bs == 5, str((fm_raw, body, bs)))

    # T20: no front matter -> empty raw, body unchanged, start 1
    fm_raw, body, bs = L.split_frontmatter("plain")
    ok("T20-split-no-fm", fm_raw == "" and body == "plain" and bs == 1, str((fm_raw, body, bs)))

    # T21: frontmatter() dict / non-mapping -> {}
    ok("T21-frontmatter", L.frontmatter(FM_TEXT) == {"title": _U(r"\u062a\u062c\u0631\u0628\u0629"), "status": "active"}
       and L.frontmatter("- x") == {}, str(L.frontmatter("- x")))

    # T22: frontmatter_keys valid / non-mapping / YAML-error regex fallback
    ok("T22-fm-keys", L.frontmatter_keys("title: T\nstatus: active\n") == ["title", "status"]
       and L.frontmatter_keys("- item\n") == []
       and L.frontmatter_keys("title: [unclosed\n") == ["title"],
       str((L.frontmatter_keys("title: T\nstatus: active\n"),
            L.frontmatter_keys("- item\n"), L.frontmatter_keys("title: [unclosed\n"))))

    # T23: headings() skips nested and %%-comment fake headings
    ok("T23-headings-skip", L.headings("# h\n> # fake\n%% # fake2 %%\n# real2\n")
       == [(1, 1, "h"), (4, 1, "real2")], str(L.headings("# h\n> # fake\n%% # fake2 %%\n# real2\n")))

    # T24: sections() nesting -- section ends at next heading of same/higher level
    SEC = "# A\n## B\n### C\n## D\n# E"
    ok("T24-sections-nesting", L.sections(SEC)
       == [(1, "A", 1, 4), (2, "B", 2, 2), (3, "C", 3, 1), (2, "D", 4, 1), (1, "E", 5, 1)],
       str(L.sections(SEC)))

    # T25: leaf_sections basic -- bytes/lines over own content, blank lines excluded from body
    LEAF = "# A\nl1\n\nl2\n## B\nbody"
    ls = L.leaf_sections(LEAF)
    ok("T25-leaf-basic", ls[0] == {"level": 1, "title": "A", "line": 1, "lines": 4,
       "bytes": 11, "atomic_share": 0.0}
       and ls[1] == {"level": 2, "title": "B", "line": 5, "lines": 2,
       "bytes": 9, "atomic_share": 0.0}, str(ls))

    # T26: leaf atomic_share == 1.0 when the whole body is a code fence
    ls = L.leaf_sections("# A\n```py\nx=1\n```\n## B\ntail")
    ok("T26-leaf-atomic", ls[0]["lines"] == 4 and ls[0]["bytes"] == 18
       and ls[0]["atomic_share"] == 1.0 and ls[1]["atomic_share"] == 0.0,
       str(ls))

    # T27: inline_texts -- code spans dropped, softbreak/hardbreak become \n
    IT = "# H\npara `code` rest\n\nl1\nl2\n\nhard  \nbreak\n"
    got = list(L.inline_texts(IT))
    # heading text is emitted too: the heading's inline token has a map, and
    # docstring says "every inline block" -- headings count as inline blocks
    ok("T27-inline-texts", got == [(1, "H"), (2, "para  rest"), (4, "l1\nl2"), (7, "hard\nbreak")],
       str(got))

    # --- pause_window: the single reader of the club pause line ---
    W = []
    p = L.pause_window(_U(r"- \u0625\u064a\u0642\u0627\u0641:: 2026-01-01 \u2192 2026-01-31"), warnings=W)
    aok("T28-pause-valid", p == L.Pause(date(2026, 1, 1), date(2026, 1, 31)) and W == []
       and p.contains(date(2026, 1, 15)) and not p.contains(date(2026, 2, 1)),
       str((p, W)))

    W = []
    p = L.pause_window(_U(r"- \u0625\u064a\u0642\u0627\u0641:: not-a-date"), warnings=W)
    # part.strip() removes the leading '- ' before embedding in the message
    aok("T29-pause-malformed", p is None and W == [_U(r"pause line malformed, ignored (line 1: \u0625\u064a\u0642\u0627\u0641:: not-a-date)")],
       str(W))

    W = []
    p = L.pause_window(_U(r"- \u0625\u064a\u0642\u0627\u0641:: 2026-02-01 \u2192 2026-01-01"), warnings=W)
    aok("T30-pause-reversed", p is None
       and W == [_U(r"pause line malformed, ignored (line 1: \u0625\u064a\u0642\u0627\u0641:: 2026-02-01 \u2192 2026-01-01)")],
       str(W))

    W = []
    p = L.pause_window(_U(r"- \u0625\u064a\u0642\u0627\u0641:: 2026-01-01 \u2192 2026-01-31\n- \u0625\u064a\u0642\u0627\u0641:: 2026-02-01 \u2192 2026-02-28"), warnings=W)
    aok("T31-pause-two-lines", p is None and W == ["2 pause lines, expected one; none applied"],
       str(W))

    # T32: pause lines inside code fences or %% comments are ignored silently
    W = []
    p1 = L.pause_window(_U(r"```\n- \u0625\u064a\u0642\u0627\u0641:: 2026-01-01 \u2192 2026-01-31\n```\n# h"), warnings=W)
    p2 = L.pause_window(_U(r"%% - \u0625\u064a\u0642\u0627\u0641:: 2026-01-01 \u2192 2026-01-31 %%\n# h"), warnings=W)
    ok("T32-pause-ignored", p1 is None and p2 is None and W == [], str(W))

    # T33: file mode reads VAULT/CLUB_AREA (both monkeypatched)
    L.CLUB_AREA = "club.md"
    (TMP / "club.md").write_text(_U(r"- \u0625\u064a\u0642\u0627\u0641:: 2026-03-01 \u2192 2026-03-15\n"), encoding="utf-8")
    p = L.pause_window()
    aok("T33-pause-file", p == L.Pause(date(2026, 3, 1), date(2026, 3, 15)), str(p))

    # T34: missing club area -> None, no crash
    (TMP / "club.md").unlink()
    ok("T34-pause-missing-file", L.pause_window() is None)

    # T35: determinism -- parse() is lru_cached (same object), pause repeats equal
    ok("T35-determinism", L.parse("## x\n") is L.parse("## x\n")
       and L.pause_window(_U(r"- \u0625\u064a\u0642\u0627\u0641:: 2026-01-01 \u2192 2026-01-31"), warnings=[])
       == L.pause_window(_U(r"- \u0625\u064a\u0642\u0627\u0641:: 2026-01-01 \u2192 2026-01-31"), warnings=[]))

    # T36: read() replaces invalid utf-8 bytes instead of crashing
    (TMP / "good.txt").write_text(_U(r"\u0646\u0635"), encoding="utf-8")
    (TMP / "bad.bin").write_bytes(b"\xff")
    ok("T36-read", L.read(TMP / "good.txt") == _U(r"\u0646\u0635")
       and L.read(TMP / "bad.bin") == "\ufffd", repr(L.read(TMP / "bad.bin")))

    # T37-T44: release profile (T-02a)
    import yaml as _y
    prof_dir = TMP / "AI-Agent" / "config"
    prof_dir.mkdir(parents=True)
    ok("T37-profile-missing-defaults", L.load_profile(TMP)["mode"] == "vault")
    real = _y.safe_load((ORIG_VAULT / L.PROFILE_REL).read_text(encoding="utf-8"))
    ok("T38-shipped-profile-valid", L.validate_profile(L.load_profile(ORIG_VAULT)) == []
       and real["mode"] in ("vault", "release"), real.get("mode"))
    (prof_dir / "release_profile.yaml").write_text("mode: vault\nlanguage: ar\n", encoding="utf-8")
    ok("T39-partial-profile-filled", L.load_profile(TMP)["paths"]["system_homes"] == [])
    (prof_dir / "release_profile.yaml").write_text("mode: nope\n", encoding="utf-8")
    try:
        L.load_profile(TMP)
        raised = False
    except ValueError:
        raised = True
    ok("T40-bad-mode-raises", raised)
    (prof_dir / "release_profile.yaml").write_text("checks:\n  disabled: [secrets]\n", encoding="utf-8")
    try:
        L.load_profile(TMP)
        raised = False
    except ValueError as e:
        raised = "secrets" in str(e)
    ok("T41-untouchable-check-rejected", raised)
    (prof_dir / "release_profile.yaml").write_text("bogus: 1\n", encoding="utf-8")
    ok("T42-unknown-key-reported", any("bogus" in e for e in L.validate_profile(
        L._merge_patch(L._PROFILE_DEFAULTS, {"bogus": 1}))))
    (prof_dir / "release-patches").mkdir()
    (prof_dir / "release_profile.yaml").write_text("mode: release\nlanguage: en\n", encoding="utf-8")
    (prof_dir / "release-patches" / "release_profile.patch.yaml").write_text(
        "checks:\n  disabled: [arch, club]\nowner:\n  name: ''\n  aliases: []\n", encoding="utf-8")
    pr = L.load_profile(TMP)
    ok("T43-release-patch-applied", pr["checks"]["disabled"] == ["arch", "club"] and pr["owner"]["name"] == "", pr["checks"])
    bad_limits = [L.validate_profile(L._merge_patch(L._PROFILE_DEFAULTS, {"limits": {"read_cap_bytes": v}})) for v in (-1, True, "9")]
    ok("T45-limits-must-be-nonneg-int", all(any("read_cap_bytes" in e for e in errs) for errs in bad_limits), bad_limits)
    ok("T46-limits-valid-value", L.validate_profile(L._merge_patch(L._PROFILE_DEFAULTS, {"limits": {"read_cap_bytes": 16384}})) == [])
    # T47-T52: tiktoken cache (U-45), no network in tests
    import hashlib as _h
    _env = dict(L.os.environ)
    try:
        L.os.environ["TIKTOKEN_CACHE_DIR"] = str(TMP / "tk")
        ok("T47-cache-dir-env", L.default_tiktoken_cache_dir() == TMP / "tk")
        del L.os.environ["TIKTOKEN_CACHE_DIR"]
        L.os.environ.pop("LOCALAPPDATA", None)   # Windows reads this instead of the XDG variables
        L.os.environ["XDG_CACHE_HOME"] = str(TMP / "xdgc")
        ok("T48-cache-dir-xdg", L.default_tiktoken_cache_dir() == TMP / "xdgc" / "tiktoken")
        L.os.environ["TIKTOKEN_CACHE_DIR"] = str(TMP / "tk")
        L.os.environ["STRATUM_SKIP_NET"] = "1"
        ok("T49-skip-net-missing-file-false", L.ensure_o200k_cache(timeout=0.1) is False)
        (TMP / "tk").mkdir()
        _t = TMP / "tk" / _h.sha1(L._O200K_URL.encode()).hexdigest()
        _t.write_bytes(b"corrupt")
        ok("T50-wrong-hash-rejected", L.ensure_o200k_cache(timeout=0.1) is False)
        _real = Path(_env.get("TIKTOKEN_CACHE_DIR") or Path.home() / ".cache" / "tiktoken") / _t.name
        if _real.is_file():
            _t.write_bytes(_real.read_bytes())
            ok("T51-real-vocab-accepted", L.ensure_o200k_cache(timeout=0.1) is True)
        L.os.environ.pop("STRATUM_SKIP_NET")
        L.os.environ["TIKTOKEN_CACHE_DIR"] = str(TMP / "tk2")      # empty dir, unroutable host: bounded, returns False
        _orig_url = L._O200K_URL
        L._O200K_URL = "https://127.0.0.1:9/o200k"
        import time as _tm
        _t0 = _tm.perf_counter()
        _res = L.ensure_o200k_cache(timeout=1.0)
        L._O200K_URL = _orig_url
        ok("T52-download-failure-bounded-false", _res is False and _tm.perf_counter() - _t0 < 5, _tm.perf_counter() - _t0)
        if _real.is_file():                                          # download path end to end, via a file:// URL
            L._O200K_URL = _real.resolve().as_uri()
            L.os.environ["TIKTOKEN_CACHE_DIR"] = str(TMP / "tk3")
            _got = L.ensure_o200k_cache(timeout=5.0)
            _dst = TMP / "tk3" / _h.sha1(L._O200K_URL.encode()).hexdigest()
            L._O200K_URL = _orig_url
            ok("T53-download-verifies-and-writes-atomically", _got is True and _dst.is_file()
               and _h.sha256(_dst.read_bytes()).hexdigest() == L._O200K_SHA256 and not [x for x in (TMP / "tk3").iterdir() if x != _dst])
    finally:
        L.os.environ.clear()
        L.os.environ.update(_env)
    # T54-T62: shared CLI contract (U-47)
    import argparse as _ap
    import contextlib as _cl
    import io as _io

    def _run(parser, argv):
        out, err = _io.StringIO(), _io.StringIO()
        try:
            with _cl.redirect_stdout(out), _cl.redirect_stderr(err):
                ns = parser.parse_args(argv)
            return 0, out.getvalue(), err.getvalue(), ns
        except SystemExit as e:
            return e.code, out.getvalue(), err.getvalue(), None

    _p = L.standard_parser("Demo tool: does a thing.\n\nUsage: demo [--n N]", prog="demo")
    _p.add_argument("--n", type=int, default=1)
    _rc, _o, _e, _ = _run(_p, ["--help"])
    ok("T54-help-exits-0-on-stdout", _rc == 0 and "Demo tool" in _o and _e == "", (_rc, _o[:60], _e))
    _rc, _o, _e, _ = _run(_p, ["-h"])
    ok("T55-short-help-exits-0", _rc == 0 and "--n" in _o)
    _rc, _o, _e, _ = _run(_p, ["--bogus"])
    ok("T56-unknown-flag-exits-2-on-stderr", _rc == 2 and _o == "" and "--bogus" in _e, (_rc, _o, _e[:80]))
    _rc, _o, _e, _ns = _run(_p, ["--n", "3"])
    ok("T57-valid-args-unchanged", _rc == 0 and _ns.n == 3 and _o == "" and _e == "")
    _rc, _o, _e, _ = _run(L.standard_parser(None), ["-h"])
    ok("T58-empty-doc-ok", _rc == 0)
    _d = L.standard_parser("D", prog="d")
    _d.add_argument("--new", action="store_true", dest="new")
    _d.add_argument("--old", action=L.DeprecatedFlagAction, new_flag="--new", new_dest="new")
    _rc, _o, _e, _ns = _run(_d, ["--old"])
    ok("T59-deprecated-flag-warns-and-maps", _rc == 0 and _ns.new is True and "--old is deprecated; use --new" in _e and _o == "", (_rc, _e, _ns))
    _rc, _o, _e, _ns = _run(_d, ["--new"])
    ok("T60-new-flag-silent", _rc == 0 and _ns.new is True and _e == "")
    _err = _io.StringIO()
    try:
        with _cl.redirect_stderr(_err):
            L.cli_migration_error("--old", "--new", "2.0")
        _code = None
    except SystemExit as e:
        _code = e.code
    ok("T61-migration-error-exits-2", _code == 2 and "--old no longer exists (removed in 2.0); use --new" in _err.getvalue(), (_code, _err.getvalue()))
    class _Fake:
        def __init__(self): self.calls = []
        def reconfigure(self, **kw): self.calls.append(kw)
    _so, _se = L.sys.stdout, L.sys.stderr
    L.sys.stdout, L.sys.stderr = _Fake(), _Fake()
    try:
        L.force_utf8_stdio()
        _calls = (L.sys.stdout.calls, L.sys.stderr.calls)
    finally:
        L.sys.stdout, L.sys.stderr = _so, _se
    ok("T62-utf8-reconfigure-both-streams", _calls == ([{"encoding": "utf-8", "errors": "replace"}],) * 2, _calls)
    # T63-T67: session_db_path precedence, CLUB_AREA=None / non-file guard
    _env = dict(os.environ)
    try:
        for k in ("STRATUM_SESSION_DB", "XDG_DATA_HOME", "LOCALAPPDATA"):
            os.environ.pop(k, None)
        os.environ["STRATUM_SESSION_DB"] = str(TMP / "x.db")
        ok("T63-session-db-env-wins", L.session_db_path() == TMP / "x.db", L.session_db_path())
        del os.environ["STRATUM_SESSION_DB"]
        os.environ["XDG_DATA_HOME"] = str(TMP / "xdg")
        if sys.platform.startswith("linux"):   # XDG_DATA_HOME leads the candidates only on Linux; macOS and Windows use their own folders first
            ok("T64-session-db-xdg", L.session_db_path() == TMP / "xdg" / "goose" / "sessions" / "sessions.db", L.session_db_path())
        else:
            print("SKIP T64-session-db-xdg: XDG_DATA_HOME does not lead the candidates on this platform")
        del os.environ["XDG_DATA_HOME"]
        _home_marker = {"win32": "AppData", "darwin": "Application Support"}.get(sys.platform, ".local")
        ok("T65-session-db-default-under-home", L.session_db_path().parts[-2:] == ("sessions", "sessions.db") and "goose" in L.session_db_path().parts and _home_marker in L.session_db_path().parts, L.session_db_path())
    finally:
        os.environ.clear(); os.environ.update(_env)
    L.CLUB_AREA = None
    ok("T66-club-area-none-no-pause", L.pause_window() is None)
    L.CLUB_AREA = "02-Areas"                     # a directory, not a file
    (TMP / "02-Areas").mkdir(exist_ok=True)
    ok("T67-club-area-directory-no-crash", L.pause_window() is None)

    # T68-T90: hybrid release patch engine (RFC 7396 merge + RFC 6902 subset + add_unique / remove_match)
    def _raises(fn, *a):
        try:
            fn(*a)
        except L.PatchError as e:
            return str(e)
        return None
    _base = {"keys": {"club": {"t": "x"}, "area": {"t": "w"}}, "l": ["a", "b", {"id": 1, "n": "x"}, {"id": 2, "n": "y"}], "n": 1}
    _snap = copy.deepcopy(_base)
    _o = L.apply_ops(_base, [{"op": "remove", "path": "/keys/club"}])
    ok("T68-remove-key", "club" not in _o["keys"] and "club" in _base["keys"] and _base == _snap, _o)
    ok("T69-add-key", L.apply_ops(_base, [{"op": "add", "path": "/keys/license", "value": {"t": "s"}}])["keys"]["license"] == {"t": "s"})
    ok("T70-replace", L.apply_ops(_base, [{"op": "replace", "path": "/n", "value": 2}])["n"] == 2)
    _l = L.apply_ops(_base, [{"op": "add", "path": "/l/0", "value": "z"}, {"op": "add", "path": "/l/-", "value": "e"}])["l"]
    ok("T71b-list-add-index-and-end", _l[0] == "z" and _l[-1] == "e" and len(_l) == 6, _l)
    ok("T72-test-passes", L.apply_ops(_base, [{"op": "test", "path": "/n", "value": 1}]) == _base)
    ok("T73-test-fails-closed", "test failed" in (_raises(L.apply_ops, _base, [{"op": "test", "path": "/n", "value": 9}]) or ""))
    ok("T74-missing-path-fails", "path not found" in (_raises(L.apply_ops, _base, [{"op": "remove", "path": "/keys/gone"}]) or ""))
    ok("T75-optional-remove-absent-ok", L.apply_ops(_base, [{"op": "remove", "path": "/keys/gone", "optional": True}]) == _base)
    ok("T76-add-unique-appends-once", L.apply_ops(_base, [{"op": "add_unique", "path": "/l", "value": "c"}, {"op": "add_unique", "path": "/l", "value": "c"}])["l"].count("c") == 1)
    ok("T77-add-unique-existing-noop", L.apply_ops(_base, [{"op": "add_unique", "path": "/l", "value": "a"}]) == _base)
    ok("T78-remove-match-value", "a" not in L.apply_ops(_base, [{"op": "remove_match", "path": "/l", "value": "a"}])["l"])
    _rm = L.apply_ops(_base, [{"op": "remove_match", "path": "/l", "match": {"n": "x"}}])["l"]
    ok("T79-remove-match-dict-subset", {"id": 1, "n": "x"} not in _rm and {"id": 2, "n": "y"} in _rm, _rm)
    ok("T80-remove-match-nothing-fails", "matched nothing" in (_raises(L.apply_ops, _base, [{"op": "remove_match", "path": "/l", "value": "nope"}]) or ""))
    ok("T81-remove-match-optional", L.apply_ops(_base, [{"op": "remove_match", "path": "/l", "value": "nope", "optional": True}]) == _base)
    ok("T82-remove-match-needs-one-selector", _raises(L.apply_ops, _base, [{"op": "remove_match", "path": "/l"}]) is not None and _raises(L.apply_ops, _base, [{"op": "remove_match", "path": "/l", "value": 1, "match": {}}]) is not None)
    ok("T83-add-unique-on-non-list", "needs a list" in (_raises(L.apply_ops, _base, [{"op": "add_unique", "path": "/n", "value": 1}]) or ""))
    ok("T84-pointer-escapes", L.apply_ops({"a/b": {"c~d": 1}}, [{"op": "replace", "path": "/a~1b/c~0d", "value": 2}]) == {"a/b": {"c~d": 2}})
    ok("T85-unknown-op-and-bad-pointer", _raises(L.apply_ops, _base, [{"op": "move", "path": "/n"}]) is not None and _raises(L.apply_ops, _base, [{"op": "remove", "path": "n"}]) is not None)
    ok("T86-list-index-out-of-range", _raises(L.apply_ops, _base, [{"op": "remove", "path": "/l/9"}]) is not None and _raises(L.apply_ops, _base, [{"op": "replace", "path": "/l/4", "value": 1}]) is not None)
    _p = L.apply_patch(_base, {"merge": {"n": None, "keys": {"club": None}}, "ops": [{"op": "add_unique", "path": "/l", "value": "q"}]})
    ok("T87-apply-patch-merge-then-ops", "n" not in _p and "club" not in _p["keys"] and "q" in _p["l"] and "area" in _p["keys"], _p)
    ok("T88-apply-patch-unknown-key-fails", "unknown patch keys" in (_raises(L.apply_patch, _base, {"mrge": {}}) or ""))
    ok("T89-apply-patch-does-not-mutate", _base == _snap)
    _y = L.dump_yaml_block({"b": ["x", "y"], "a": _U(r"\u0633\u0639\u0648\u062f")})
    ok("T90-dump-block-lists-order-utf8", _y == _U(r"b:\n- x\n- y\na: \u0633\u0639\u0648\u062f\n"), _y)

    # T91-T102: schema class resolution (extends, cycles) and class precedence (U-27, U-34)
    _cl = {"para": {"when": {"path_prefix": ["01-Projects/"]}, "required": ["area", "tags"], "optional": ["status"], "status_enum": ["active"]},
           "archive": {"when": {"path_prefix": ["04-Archive/"]}, "extends": "para", "required": ["tags"], "optional": ["archived_on"]}}
    _res, _pr = L.resolve_classes(_cl)
    ok("T91-extends-inherits-parent-required-as-optional", "area" in _res["archive"]["optional"] and "area" not in _res["archive"]["required"] and "status" in _res["archive"]["optional"], _res["archive"])
    ok("T92-extends-keeps-own-keys-and-required", _res["archive"]["required"] == ["tags"] and "archived_on" in _res["archive"]["optional"] and "tags" not in _res["archive"]["optional"])
    ok("T93-extends-does-not-inherit-status-enum-or-when", "status_enum" not in _res["archive"] and _res["archive"]["when"] == {"path_prefix": ["04-Archive/"]} and "extends" not in _res["archive"] and not _pr)
    _, _pr = L.resolve_classes({"a": {"extends": "b"}, "b": {"extends": "a"}})
    ok("T94-cycle-reported", any(r == "FM-schema-cycle" for r, _, _ in _pr), _pr)
    _, _pr = L.resolve_classes({"a": {"extends": "a"}})
    ok("T95-self-extends-is-a-cycle", any(r == "FM-schema-cycle" for r, _, _ in _pr), _pr)
    _res2, _pr = L.resolve_classes({"a": {"extends": "ghost", "optional": ["x"]}, "b": {"optional": ["y"]}})
    ok("T96-unknown-parent-reported-others-intact", [r for r, _, _ in _pr] == ["FM-schema-extends"] and _res2["a"]["optional"] == ["x"] and _res2["b"]["optional"] == ["y"], _pr)
    ok("T97-resolve-does-not-mutate-input", "extends" in _cl["archive"] and _cl["archive"]["optional"] == ["archived_on"])
    _c3 = {"para": {"when": {"path_prefix": ["01-Projects/", "02-Areas/"]}}, "person": {"when": {"path_prefix": ["02-Areas/People/"]}},
           "excalidraw": {"when": {"path_suffix": [".excalidraw.md"]}}, "moc": {"when": {"fm_eq": {"type": "moc"}}}}
    ok("T98-fm-selector-wins-over-path", L.class_of("01-Projects/x.md", {"type": "moc"}, _c3, []) == "moc")
    ok("T99-longest-prefix-wins", L.class_of("02-Areas/People/p.md", {}, _c3, []) == "person" and L.class_of("02-Areas/a.md", {}, _c3, []) == "para")
    ok("T100-suffix-beats-prefix", L.class_of("01-Projects/d.excalidraw.md", {}, _c3, []) == "excalidraw")
    ok("T101-unclassed-ok-beats-prefix", L.class_of("02-Areas/People/p.md", {}, _c3, ["02-Areas/People/"]) is None)
    ok("T102-no-match-is-none", L.class_of("Stray.md", {}, _c3, []) is None)

    # T103-T118: secrets, entropy and hidden-text scanning (T-05). Fake credentials are assembled at run time so this file stays clean.
    _tok = lambda *parts: "".join(parts)
    _gh = _tok("gh", "p_", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8")
    kinds = lambda t, **kw: [k for k, _, _ in L.scan_secrets(t, **kw)]
    ok("T103-known-credential-shapes-are-found", kinds(f"x = {_gh}") == ["pattern:2"] and kinds(_tok("sk-", "ant-", "a" * 30)) == ["pattern:0"] and kinds(_tok("AK", "IA", "A" * 16)) == ["pattern:5"] and kinds(_tok("-----BEGIN ", "PRIVATE KEY-----")) == ["pattern:8"], kinds(f"x = {_gh}"))
    ok("T104-github-fine-grained-token-shape", kinds(_tok("github", "_pat_", "A1b2C3d4" * 6)) == ["pattern:4"])
    _hi = _tok("Zx9Qp", "L2mVb", "7TnR4", "sKc8W", "dE1yU", "h5Jg3Aa")
    ok("T105-a-high-entropy-value-under-a-secret-name-is-found", kinds(_tok("API", "_KEY = ", chr(34), _hi, chr(34))) == ["entropy"] and kinds(_tok("token", ": ", _hi)) == ["entropy"] and kinds(_tok("Authorization", ": Bearer ", _hi)) == ["entropy"], [kinds(_tok("Authorization", ": Bearer ", _hi))])
    ok("T106-bearer-form-with-a-keyword-and-equals", kinds(_tok("pass", "word=", _hi)) == ["entropy"])
    ok("T107-placeholders-environment-references-and-low-entropy-are-not-findings",
       not kinds(_tok("API", "_KEY = ", '"your-api-key-goes-here-xxxx"')) and not kinds("token: ${GITHUB_TOKEN_VALUE_FROM_ENV}") and not kinds("secret: <paste-your-secret-here-please>") and not kinds("token: aaaaaaaaaaaaaaaaaaaaaaaaaaaa") and not kinds("api_key: abcdefghijklmnopqrstuvwxyzabcdef"))
    ok("T108-a-hash-without-a-secret-name-is-not-a-finding", not kinds("sha256: " + "ab12cd34" * 8) and not kinds("secret_hash: " + "ab12cd34" * 8))
    ok("T109-entropy-can-be-switched-off-for-narrow-scopes", kinds(_tok("API", "_KEY = ", _hi), entropy=False) == [])
    ok("T110-bidi-controls-are-found-with-their-line", L.scan_secrets("ok\nuser = 'a\u202eb'\n") == [("bidi", 2, "bidirectional control U+202E (Trojan Source, CVE-2021-42574)")], L.scan_secrets("ok\nuser = 'a\u202eb'\n"))
    ok("T111-every-trojan-source-control-is-covered", all(kinds(f"a{c}b") == ["bidi"] for c in L.BIDI_CONTROLS) and len(L.BIDI_CONTROLS) == 9)
    ok("T112-directional-marks-used-in-real-arabic-text-are-not-findings", not kinds("abc\u200fdef\u200e"))
    ok("T113-a-leading-bom-is-fine-a-middle-one-is-not", not kinds("\ufeffhello") and kinds("hel\ufefflo") == ["bom"])
    ok("T114-hidden-scan-can-be-switched-off", kinds("a\u202eb", hidden=False) == [])
    _t = Path(tempfile.mkdtemp(prefix="scantree-"))
    try:
        (_t / "a").mkdir()
        (_t / "a" / "x.json").write_text('{"token": "' + _hi + '"}', encoding="utf-8")
        (_t / "a" / "y.py").write_text("s = 'a\u202eb'\n", encoding="utf-8")
        (_t / "a" / "z.png").write_bytes(b"\x89PNG" + _gh.encode())
        (_t / ".git").mkdir()
        (_t / ".git" / "cfg").write_text(_gh, encoding="utf-8")
        (_t / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        got = sorted((p, k) for p, k, _, _ in L.scan_tree(_t))
        ok("T115-scan-tree-reads-every-text-file-and-skips-binaries-and-git", got == [("a/x.json", "entropy"), ("a/y.py", "bidi")], got)
        (_t / "a" / "bad.md").write_bytes(b"\xff\xfe not utf8")
        ok("T116-scan-tree-skips-an-undecodable-file-instead-of-crashing", sorted(p for p, *_ in L.scan_tree(_t)) == ["a/x.json", "a/y.py"])
    finally:
        shutil.rmtree(_t, ignore_errors=True)
    ok("T117-entropy-measure", L.shannon_entropy("aaaa") == 0.0 and abs(L.shannon_entropy("abcd") - 2.0) < 1e-9 and L.shannon_entropy("") == 0.0)
    ok("T44-defaults-not-mutated", L._PROFILE_DEFAULTS["checks"]["disabled"] == [])
    # AD13 B3: Persian letters, presentation forms and invisible joiners fold; distinct roots stay distinct (no stemming)
    aok("T45-b3-persian-and-presentation-forms",
       L.normalize_ar(_U(r"\u06a9\u062a\u0627\u0628")) == L.normalize_ar(_U(r"\u0643\u062a\u0627\u0628"))
       and L.normalize_ar(_U(r"\ufefb")) == L.normalize_ar(_U(r"\u0644\u0627"))
       and L.normalize_ar(_U(r"\u0643\u200c\u062a\u0627\u0628")) == L.normalize_ar(_U(r"\u0643\u062a\u0627\u0628")))
    ok("T46-b3-negative-control-roots-not-merged",
       L.normalize_ar(_U(r"\u0639\u0644\u0645")) != L.normalize_ar(_U(r"\u0639\u0627\u0644\u0645"))
       and L.normalize_ar(_U(r"\u0643\u062a\u0627\u0628")) != L.normalize_ar(_U(r"\u0643\u0627\u062a\u0628")))
    os.environ["STRATUM_NORMALIZE_EXTRA"] = "0"
    off = L.normalize_ar(_U(r"\u06a9")) == _U(r"\u06a9")
    del os.environ["STRATUM_NORMALIZE_EXTRA"]
    aok("T47-b3-kill-switch", off and L.normalize_ar(_U(r"\u06a9")) == _U(r"\u0643"))
    # AD13 E7: one import policy and parser shared by audit and impact
    src = '"""from fakepkg import x"""\nimport os.path\nfrom yaml import safe_load\nfrom . import sibling\nfrom mediator import m\n'
    ok("T48-e7-roots-real-imports-only", L.script_import_roots(src) == {"os", "yaml", "mediator"}, str(L.script_import_roots(src)))
    ok("T49-e7-syntax-error-fallback-and-none",
       L.script_import_roots("import json\ndef (:\n") == {"json"} and L.script_import_roots("def (:\n", fallback=False) is None)
    ok("T50-e7-policy-negative-and-positive",
       L.unapproved_imports({"os", "yaml", "mediator", "decision_ledger", "_vaultlib", "sib"}, {"sib"}) == []
       and L.unapproved_imports({"requests", "yaml", "optmod"}, set(), {"optmod"}) == ["requests"])
    _real_map = dict(L.SCRIPT_THIRD_PARTY)
    L.SCRIPT_THIRD_PARTY.clear()
    L.SCRIPT_THIRD_PARTY["demo_script"] = {"libone", "libtwo"}   # a synthetic mapping: the rule is tested, not any real script
    try:
        ok("T50b-adr021-per-script-libraries-stay-scoped",
           L.unapproved_imports({"libone", "libtwo"}, set(), script="demo_script") == []
           and L.unapproved_imports({"libone", "libtwo"}, set(), script="other") == ["libone", "libtwo"]
           and L.unapproved_imports({"libone"}, set()) == ["libone"])
    finally:
        L.SCRIPT_THIRD_PARTY.clear()
        L.SCRIPT_THIRD_PARTY.update(_real_map)
    # Fable review: an impossible calendar date makes PyYAML raise ValueError (not YAMLError); it is that note's
    # front matter error, never a crash of every tool that parses the vault
    def _fm_or_exc(raw):
        try:
            return L.load_frontmatter(raw)
        except Exception as exc:   # noqa: BLE001
            return exc
    _bad = _fm_or_exc("due: 2026-11-31\n")
    ok("T51-impossible-date-is-an-fm-error-not-a-crash", isinstance(_bad, tuple) and _bad[0] == {} and "out of range" in _bad[1], repr(_bad))
    _bad = _fm_or_exc("at: 2026-11-30 25:00:00\n")
    ok("T52-impossible-time-is-an-fm-error-not-a-crash", isinstance(_bad, tuple) and _bad[0] == {} and _bad[1], repr(_bad))
    try:
        _d = L.parse("---\ncreated: 2026-02-30\n---\n# a\n")
        ok("T53-parse-survives-an-impossible-date", _d.has_fm and _d.fm == {} and _d.fm_error and [h.title for h in _d.headings] == ["a"], repr(_d.fm_error))
    except Exception as exc:   # noqa: BLE001
        ok("T53-parse-survives-an-impossible-date", False, repr(exc))
    try:
        ok("T54-frontmatter-keys-survives-an-impossible-date", L.frontmatter_keys("created: 2026-02-30\ntags: [a]\n") == ["created", "tags"], L.frontmatter_keys("created: 2026-02-30\ntags: [a]\n"))
    except Exception as exc:   # noqa: BLE001
        ok("T54-frontmatter-keys-survives-an-impossible-date", False, repr(exc))
    ok("T55-control-a-valid-date-still-loads", L.load_frontmatter("due: 2026-11-30\n") == ({"due": date(2026, 11, 30)}, ""))
finally:
    L.VAULT = ORIG_VAULT
    L.CLUB_AREA = _U(r"02-Areas/\u0646\u0627\u062f\u064a-\u0637\u0648\u064a\u0642-\u062a\u0643.md")
    shutil.rmtree(TMP, ignore_errors=True)

    # AD13 D7: more credential shapes, placeholder-aware scanning, people-data shapes. Fakes are assembled at run time.
    def names(t, **kw):
        return [d for _, _, d in L.scan_secrets(t, **kw)]
    A28 = "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
    shapes = {
        "OpenAI key (legacy shape)": _tok("sk", "-", A28),
        "OpenRouter key": _tok("sk-", "or-", "v1-", A28),
        "Google API key": _tok("AI", "za", "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6q"),
        "Stripe live key": _tok("sk", "_live", "_", A28),
        "JSON Web Token": _tok("ey", "J", "hbGciOiJIUzI1NiJ9", ".", "ey", "J", "zdWIiOiIxMjM0NTY3ODkwIn0", ".", "abcDEF123_-xyz789"),
        "database URL with a password": _tok("post", "gres://", "app:", "Tr0ub4dor3xyz", "@db.internal.corp.net/main"),
        "Slack webhook": _tok("https://hooks", ".slack.com/services/", "T0ABC123/B0DEF456/", A28[:24]),
        "Hugging Face token": _tok("hf", "_", A28),
        "SendGrid key": _tok("SG", ".", "A1b2C3d4E5f6G7h8", ".", "I9j0K1l2M3n4O5p6"),
        "Telegram bot token": _tok("123456789", ":", "AA", "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6q"),
        "GitHub app or refresh token": _tok("gh", "s_", A28 + "7r8"),
    }
    got = {k: names(v) for k, v in shapes.items()}
    ok("T51-d7-each-new-shape-is-found-once-by-name", all(got[k] == [k] for k in shapes), {k: v for k, v in got.items() if v != [k]})
    ok("T52-d7-existing-shape-numbers-did-not-move", [L.SECRET_PATTERNS[i][1] for i in (0, 2, 4, 5)] == ["Anthropic key", "GitHub token", "GitHub fine-grained token", "AWS access key"]
       and names(_tok("sk-", "ant-", "a" * 30)) == ["Anthropic key"] and names(_tok("sk-", "proj-", "a" * 30)) == ["OpenAI project key"])
    ok("T53-d7-lookalikes-are-not-findings",
       not names("pip install scikit-learn sk-learn hf_model_name task-12345678901234567890") and not names(_tok("ey", "J", "abc.", "ey", "J", "def")) and not names(_tok("AI", "za", "short"))
       and not names("postgres://localhost/main") and not names("https://example.com/services/T1/B2/c3"))
    ok("T54-d7-placeholder-is-skipped-only-when-asked",
       names(_tok("sk", "_live", "_", "x" * 24)) == ["Stripe live key"] and names(_tok("sk", "_live", "_", "x" * 24), placeholders_ok=True) == []
       and names(_tok("sk", "_live", "_", A28), placeholders_ok=True) == ["Stripe live key"])
    ok("T55-d7-documentation-database-urls-skipped-real-ones-kept",
       names(_tok("post", "gres://user:pass@localhost/db"), placeholders_ok=True) == [] and names(_tok("redis://", "default:pass", "word@127.0.0.1:6379"), placeholders_ok=True) == []
       and names(shapes["database URL with a password"], placeholders_ok=True) == ["database URL with a password"])
    _jwt_sample = _tok("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", ".", "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ", ".", "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
    ok("T56b-d7-public-documentation-samples-are-skipped-only-in-the-wide-scope",
       names(_jwt_sample, placeholders_ok=True) == [] and names(_jwt_sample) == ["JSON Web Token"]
       and names(_tok("AI", "za", "SyDaGmWKa4JsXZ-HjGw7ISLn_3namBGewQe"), placeholders_ok=True) == []
       and names(_tok("AI", "za", "SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6q"), placeholders_ok=True) == ["Google API key"])
    ok("T56-d7-detail-never-holds-the-secret", all(v[:30] not in " ".join(names(v)) for v in shapes.values()))
    # people data
    pii = lambda t: [(k, n) for k, n, _ in L.scan_pii(t)]
    ok("T57-d7-iban-contiguous-and-spaced", pii("iban " + _tok("SA", "03", "8000", "0000", "6080", "1016", "7519")) == [("iban", 1)]
       and pii(_tok("SA", "03 8000 0000 6080 1016 7519")) == [("iban", 1)] and not pii("SA03 8000"))
    ok("T58-d7-mobile-forms", all(pii(f"call {m} now") == [("mobile", 1)] for m in ("0512345678", "+966512345678", "00966512345678", "966512345678"))
       and not pii("order 05123456789") and not pii("0412345678") and not pii("x 1051234567800"))
    ok("T59-d7-national-id-needs-a-context-word-on-its-line",
       pii("id number: 1234567890") == [("national-id", 1)] and pii("iqama 2123456789\nnote") == [("national-id", 1)]
       and not pii("epoch 1700000000") and not pii("id number: 12345678901") and not pii("ten digits 1234567890 only"))
    aok("T60-d7-arabic-context-word-counts", pii(_U(r"\u0631\u0642\u0645 \u0627\u0644\u0647\u0648\u064a\u0629: 1098765432")) == [("national-id", 1)])
    ok("T61-d7-people-folder-name-is-the-real-folder-name", L.locale_value("PEOPLE_DIR") in (None, _U(r"02-Areas/\u0627\u0644\u0623\u0634\u062e\u0627\u0635")))

    # AD13 D7 retrofit: shapes adapted from gitleaks (MIT), kept in AI-Agent/schema/secret-shapes.json. Fakes are assembled at run time.
    import json as _json
    import warnings as _w
    doc = _json.loads(L._SHAPES_FILE.read_text(encoding="utf-8"))
    ok("T62-d7-shapes-file-says-where-it-came-from",
       all(k in doc for k in ("source", "license", "retrieved", "source_sha256", "changes")) and "MIT" in doc["license"] and doc["source"].startswith("https://github.com/gitleaks/gitleaks"), list(doc))
    ids = [r["id"] for r in doc["rules"]]
    ok("T63-d7-every-rule-compiles-on-this-python-and-ids-are-unique", len(L.adapted_shapes()) == len(doc["rules"]) == len(set(ids)) and len(ids) >= 200,
       (len(L.adapted_shapes()), len(doc["rules"]), len(set(ids))))
    ok("T64-d7-the-two-dropped-or-patched-rules", "generic-api-key" not in ids and not [r for r in doc["rules"] if r["id"] == "sourcegraph-access-token" and "{40})\\b)" in r["regex"] and "|[a-fA-F0-9]{40}" in r["regex"]])
    AA = lambda n: ("A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2W3x4Y5z6" * 3)[:n]
    HH = lambda n: ("a1b2c3d4e5f60718293a4b5c6d7e8f90" * 4)[:n]
    fam = {"npm-access-token": _tok("npm", "_", AA(36)), "digitalocean-pat": _tok("dop", "_v1_", HH(64)), "shopify-access-token": _tok("shp", "at_", HH(32)),
           "linear-api-key": _tok("lin", "_api_", AA(40)), "perplexity-api-key": _tok("ppl", "x-", AA(48)), "doppler-api-token": _tok("dp", ".pt.", AA(43)),
           "sourcegraph-access-token": _tok("sg", "p_", HH(40)), "huggingface-access-token": _tok("hf", "_", "aBcDeFgHiJkLmNoPqRsTuVwXyZaBcDeFgH")}
    gotf = {k: [d for _, _, d in L.scan_secrets("key = " + v)] for k, v in fam.items()}
    ok("T65-d7-each-sampled-family-is-found-once-and-named-by-rule", all(len(v) == 1 and (k in v[0] or (k == "huggingface-access-token" and v[0] == "Hugging Face token")) for k, v in gotf.items()),
       {k: v for k, v in gotf.items() if len(v) != 1 or not (k in v[0] or v[0] == "Hugging Face token")})
    ok("T66-d7-a-bare-forty-hex-id-is-not-a-finding", not L.scan_secrets("commit " + HH(40)) and not L.scan_secrets("sha1: " + HH(40) + "\n"))
    ok("T67-d7-a-token-the-builtin-list-names-is-not-named-twice", [k for k, _, _ in L.scan_secrets(_tok("gh", "p_", AA(36)))] == ["pattern:2"])
    ok("T68-d7-entropy-gate-and-placeholders-apply-to-adapted-shapes",
       not L.scan_secrets(_tok("npm", "_", "a" * 36)) and L.scan_secrets(fam["npm-access-token"]) and not L.scan_secrets(_tok("npm", "_", "x" * 36), placeholders_ok=True))
    ok("T69-d7-lookalikes-are-not-findings", not L.scan_secrets("npm_install npm_config_cache dp.pt.js lin_api_docs") and not L.scan_secrets("pplx-style sgp_ in prose"))
    big = fam["npm-access-token"] + "\n" + "filler " * (L.ADAPTED_MAX_CHARS // 6) + "\n" + _tok("gh", "p_", AA(36))
    ok("T70-d7-a-text-over-the-cap-keeps-the-builtin-shapes-only", [k for k, _, _ in L.scan_secrets(big)] == ["pattern:2"] and len(big) > L.ADAPTED_MAX_CHARS)
    keep_file, keep_cache = L._SHAPES_FILE, L._SHAPES_CACHE
    try:
        L._SHAPES_FILE, L._SHAPES_CACHE = L._SHAPES_FILE.with_name("nope.json"), None
        miss = L.scan_secrets(fam["npm-access-token"] + "\n" + _tok("gh", "p_", AA(36)))
        bad = L._SHAPES_FILE.with_name("secret-shapes-broken.json")
        bad.write_text("{not json", encoding="utf-8")
        try:
            L._SHAPES_FILE, L._SHAPES_CACHE = bad, None
            brk = L.scan_secrets(fam["npm-access-token"] + "\n" + _tok("gh", "p_", AA(36)))
        finally:
            bad.unlink()
    finally:
        L._SHAPES_FILE, L._SHAPES_CACHE = keep_file, keep_cache
    ok("T71-d7-a-missing-or-broken-shapes-file-leaves-the-builtin-scan-running", [k for k, _, _ in miss] == ["pattern:2"] and [k for k, _, _ in brk] == ["pattern:2"], (miss, brk))
    class _Count:
        def __init__(self, rx):
            self.rx, self.calls = rx, 0

        def finditer(self, text):
            self.calls += 1
            return self.rx.finditer(text)
    shapes_now = L.adapted_shapes()
    saved = [s["rx"] for s in shapes_now]
    counters = [_Count(s["rx"]) for s in shapes_now]
    try:
        for s, c in zip(shapes_now, counters):
            s["rx"] = c
        L.scan_secrets("plain prose about the weather and a long lunch on a quiet friday " * 50)
        idle = sum(c.calls for c in counters)
        L.scan_secrets(fam["npm-access-token"])
        busy = {s["id"] for s, c in zip(shapes_now, counters) if c.calls}
    finally:
        for s, rx in zip(shapes_now, saved):
            s["rx"] = rx
    ok("T72-d7-the-keyword-prefilter-keeps-regexes-from-running-on-plain-text",
       idle == sum(1 for s in shapes_now if not s["kw"]) and "npm-access-token" in busy and len(busy) < 20, (idle, len(busy)))

    # AD13 E7 prior-art retrofit (deptry's rules DEP001, DEP002, DEP005 and the dynamic-import blind spot)
    dyn_src = ("import importlib\nimportlib.import_module('requests.adapters')\n__import__('numpy')\noptional_module('pandas')\n"
               "name = 'x'\nimportlib.import_module(name)\nimportlib.import_module('')\nprint('json')\n")
    ok("T73-e7-string-literal-dynamic-imports-are-seen-only-when-asked",
       L.script_import_roots(dyn_src) == {"importlib"} and L.script_import_roots(dyn_src, dynamic=True) == {"importlib", "requests", "numpy", "pandas"},
       (L.script_import_roots(dyn_src), L.script_import_roots(dyn_src, dynamic=True)))
    ok("T74-e7-a-dynamic-import-of-an-unapproved-module-is-unapproved",
       L.unapproved_imports(L.script_import_roots(dyn_src, dynamic=True), set()) == ["numpy", "pandas", "requests"])
    import importlib.metadata as _md
    import re as _re
    from pathlib import Path as _P

    def _pins(path):
        out = []
        for ln in _P(path).read_text(encoding="utf-8").splitlines():
            ln = ln.split("#")[0].strip()
            if ln and not ln.startswith("-"):      # option lines (--hash=...) of a uv lock export are not pins
                out.append(_re.sub(r"[-_.]+", "-", _re.split(r"[\[<>=!~; ]", ln)[0]).lower())
        return out
    mod_dists = {}
    for mod, dists in _md.packages_distributions().items():
        for dname in dists:
            mod_dists.setdefault(_re.sub(r"[-_.]+", "-", dname).lower(), set()).add(mod)
    schema_dir = _P(L.__file__).resolve().parent.parent
    _RF = next(iter(sorted(schema_dir.glob("requirements-*.txt"))), None)      # the pins of the per-script libraries; a tree without such a script has no such file
    main_pins, extra_pins = _pins(schema_dir / "requirements.txt"), (_pins(_RF) if _RF is not None else [])
    def mods_of(dname):
        """Modules a pinned distribution provides: its installed metadata when this interpreter has it, plus the naming convention
        (`libname` provides `libname`) for distributions that live in another environment (the per-script libraries, the Jev client's `mcp`)."""
        return mod_dists.get(dname, set()) | {dname.replace("-", "_")}
    allowed = set(L.ALLOWED_THIRD_PARTY) - {"_vaultlib"}
    provided = set().union(*(mods_of(d) for d in main_pins))
    # a library must be pinned when a script of THIS tree imports it (a release has no script that imports mcp, so its lock omits it)
    _used = set()
    for _sf in _P(L.__file__).resolve().parent.glob("*.py"):
        if not _sf.name.endswith("-tests.py"):
            _used |= set(L.script_import_roots(_sf.read_text(encoding="utf-8", errors="replace")))
    _supplied_per_run = {"mcp", "httpx"}   # the Jev client and server: the jev extra (mcp<2, which brings httpx) or `uv run --with` supplies them, not a requirements pin
    ok("T75-e7-every-allowed-library-a-script-imports-is-pinned-in-requirements (DEP001)", (allowed & _used) - _supplied_per_run <= provided, sorted((allowed & _used) - _supplied_per_run - provided))
    transitive_ok = {"mdurl"}      # pinned because markdown-it-py needs it; no script imports it
    unused = [d for d in main_pins if d not in transitive_ok and not (mods_of(d) & allowed)]
    if "--hash=" in (schema_dir / "requirements.txt").read_text(encoding="utf-8"):
        print("SKIP T76: requirements.txt is a hash-pinned lock export (the whole closure is pinned, not only the allowed libraries)")
    else:
        ok("T76-e7-every-pin-is-an-allowed-library-or-a-named-transitive-one (DEP002)", not unused, unused)
    extra_mods = {m for ms in L.SCRIPT_THIRD_PARTY.values() for m in ms}
    extra_provided = set().union(*(mods_of(d) for d in extra_pins))
    if _RF is not None:
        ok("T77-e7-per-script-libraries-are-pinned-in-their-own-requirements-file (DEP001)", extra_mods - _supplied_per_run <= extra_provided, sorted(extra_mods - _supplied_per_run - extra_provided))
    else:
        print("SKIP T77: no per-script requirements file in this tree (no script here has per-script libraries)")
    stdlib_pins = [d for d in main_pins + extra_pins if d.replace("-", "_") in sys.stdlib_module_names]
    ok("T78-e7-no-pin-names-a-standard-library-module (DEP005)", not stdlib_pins, stdlib_pins)
    ok("T79-e7-negative-control-an-unpinned-allowed-module-would-be-found", {"pyyaml_missing_mod"} - provided == {"pyyaml_missing_mod"} and "yaml" in provided)

    # Step 1 helpers (run_utf8, run_git, sqlite_ro_uri, goose dirs/configs, ensure_o200k_cache, scan_tree, stdlib isolation)
    import hashlib as _hl
    import sqlite3 as _sq
    import subprocess as _sp
    _ar_word = _U(r"\u0645\u0631\u062d\u0628\u0627")
    _r80 = L.run_utf8([sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.argv[1].encode('utf-8'))", _ar_word])
    ok("T80-run-utf8-decodes-unicode", _r80.returncode == 0 and _r80.stdout == _ar_word, _r80.stdout)

    _grepo = Path(tempfile.mkdtemp(prefix="vlib-git-"))
    try:
        _sp.run(["git", "init", "-q"], cwd=_grepo, check=True)
        (_grepo / f"{_ar_word}.md").write_text("hi\n", encoding="utf-8")
        _rg = L.run_git(_grepo, "status", "--porcelain")
        ok("T81-run-git-preserves-utf8-paths", _rg.returncode == 0 and f"{_ar_word}.md" in _rg.stdout, _rg.stdout)
    finally:
        shutil.rmtree(_grepo, ignore_errors=True)

    _sqdir = Path(tempfile.mkdtemp(prefix="vlib db space "))
    try:
        _dbp = _sqdir / "test.sqlite3"
        _wc = _sq.connect(_dbp)
        _wc.execute("CREATE TABLE t (x INT)")
        _wc.execute("INSERT INTO t VALUES (42)")
        _wc.commit()
        _wc.close()
        _rc = _sq.connect(L.sqlite_ro_uri(_dbp), uri=True)
        _got_x = _rc.execute("SELECT x FROM t").fetchone()[0]
        try:
            _rc.execute("INSERT INTO t VALUES (99)")
            _ro_blocked = False
        except _sq.OperationalError:
            _ro_blocked = True
        _rc.close()
        ok("T82-sqlite-ro-uri-with-spaces", _got_x == 42 and _ro_blocked, (_got_x, _ro_blocked))
    finally:
        shutil.rmtree(_sqdir, ignore_errors=True)

    _l_dirs = [p.as_posix() for p in L.goose_session_dirs("linux", {"XDG_DATA_HOME": "/xdg"}, Path("/home/u"))]
    _m_dirs = [p.as_posix() for p in L.goose_session_dirs("darwin", {}, Path("/Users/u"))]
    _w_dirs = [str(p) for p in L.goose_session_dirs("win32", {"APPDATA": r"C:\AppData", "LOCALAPPDATA": r"C:\Local"}, Path(r"C:\Users\u"))]
    _w_cfgs = [str(p) for p in L.goose_config_paths("win32", {"APPDATA": r"C:\AppData", "LOCALAPPDATA": r"C:\Local"}, Path(r"C:\Users\u"))]
    ok("T83-goose-dirs-and-configs-cross-os",
       _l_dirs[0] == "/xdg/goose/sessions"
       and "/Users/u/Library/Application Support/Block/goose/sessions" in _m_dirs
       and "/Users/u/Library/Application Support/goose/sessions" in _m_dirs
       and any("Block" in p and "goose" in p for p in _w_dirs)
       and any("Block" in p and "config.yaml" in p for p in _w_cfgs),
       (_l_dirs, _m_dirs, _w_dirs))

    _tcache = Path(tempfile.mkdtemp(prefix="vlib-tik-"))
    _orig_tik = os.environ.get("TIKTOKEN_CACHE_DIR")
    _orig_sha = L._O200K_SHA256
    _orig_skip = os.environ.get("STRATUM_SKIP_NET")
    try:
        os.environ["TIKTOKEN_CACHE_DIR"] = str(_tcache)
        os.environ["STRATUM_SKIP_NET"] = "1"
        _key = _tcache / _hl.sha1(L._O200K_URL.encode("utf-8")).hexdigest()
        _key.write_bytes(b"ok-vocab")
        L._O200K_SHA256 = _hl.sha256(b"ok-vocab").hexdigest()
        os.environ.pop("TIKTOKEN_CACHE_DIR", None)
        _orig_default = L.default_tiktoken_cache_dir
        L.default_tiktoken_cache_dir = lambda: _tcache
        _ok84a = L.ensure_o200k_cache()
        _env_set = os.environ.get("TIKTOKEN_CACHE_DIR") == str(_tcache)
        # Verify temp cleanup when os.replace fails on Windows-like lock
        _key.unlink()
        os.environ.pop("STRATUM_SKIP_NET", None)
        import urllib.request as _ur
        class _Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b"ok-vocab"
        _orig_open, _orig_rep = _ur.urlopen, os.replace
        _calls84 = [0]
        def _flaky_rep(a, b):
            _calls84[0] += 1
            if _calls84[0] < 2:
                raise PermissionError("locked")
            return _orig_rep(a, b)
        try:
            _ur.urlopen = lambda *a, **k: _Resp()
            os.replace = _flaky_rep
            _ok84b = L.ensure_o200k_cache(retries=3, sleeper=lambda _: None)
        finally:
            _ur.urlopen, os.replace = _orig_open, _orig_rep
            L.default_tiktoken_cache_dir = _orig_default
        ok("T84-ensure-o200k-sets-env-retries-and-no-leftover-tmp",
           _ok84a and _env_set and _ok84b and _calls84[0] == 2 and not list(_tcache.glob(".o200k-*")),
           (_ok84a, _env_set, _ok84b, _calls84[0]))
    finally:
        L._O200K_SHA256 = _orig_sha
        if _orig_tik is None:
            os.environ.pop("TIKTOKEN_CACHE_DIR", None)
        else:
            os.environ["TIKTOKEN_CACHE_DIR"] = _orig_tik
        if _orig_skip is None:
            os.environ.pop("STRATUM_SKIP_NET", None)
        else:
            os.environ["STRATUM_SKIP_NET"] = _orig_skip
        shutil.rmtree(_tcache, ignore_errors=True)

    _scdir = Path(tempfile.mkdtemp(prefix="vlib-scan-"))
    try:
        _tok_dyn = "ghp_" + "A" * 36
        (_scdir / "AI-Agent" / "schema").mkdir(parents=True)
        (_scdir / "AI-Agent" / "schema" / "secret-shapes.json").write_text(_tok_dyn, encoding="utf-8")
        (_scdir / "notes").mkdir()
        (_scdir / "notes" / "secret-shapes.json").write_text(_tok_dyn, encoding="utf-8")
        _hits = L.scan_tree(_scdir)
        _hits_sub = L.scan_tree(_scdir / "AI-Agent" / "schema")
        ok("T85-scan-tree-skips-only-ai-agent-schema-secret-shapes",
           [h[0] for h in _hits] == ["notes/secret-shapes.json"] and _hits_sub == [],
           (_hits, _hits_sub))
    finally:
        shutil.rmtree(_scdir, ignore_errors=True)

    _scripts_dir = Path(L.__file__).resolve().parent
    _stdlib_ok = True
    _bad_imps = {}
    for _sf_name in ("upgrade_core.py", "restore_pre_upgrade.py", "install_plugins.py", "enable_mcp.py"):
        _roots = set(L.script_import_roots((_scripts_dir / _sf_name).read_text(encoding="utf-8")))
        _extra = sorted(_roots - set(sys.stdlib_module_names) - {"__future__", "upgrade_core"})
        if _extra:
            _stdlib_ok = False
            _bad_imps[_sf_name] = _extra
    ok("T86-stdlib-only-recovery-scripts-stay-pure", _stdlib_ok, _bad_imps)

# T87: a corrupt index store must not leave its connection open (Windows cannot delete an open file, so the store was never rebuilt)
import sqlite3 as _sq


class _TrackedConn(_sq.Connection):
    closed_count = 0

    def close(self):
        _TrackedConn.closed_count += 1
        super().close()


_corrupt = Path(tempfile.mkdtemp(prefix="vaultlib-corrupt-")) / "corrupt-index.sqlite3"
_corrupt.write_bytes(b"this is not a sqlite database" * 200)
_real_connect = _sq.connect
_sq.connect = lambda *a, **k: _real_connect(*a, factory=_TrackedConn, **k)
try:
    try:
        L._open_index(_corrupt)
        _raised = False
    except _sq.DatabaseError:
        _raised = True
finally:
    _sq.connect = _real_connect
ok("T87-corrupt-index-open-closes-its-connection-before-raising", _raised and _TrackedConn.closed_count == 1, (_raised, _TrackedConn.closed_count))

# T88: a store locked by another process is retried, not given up on; other errors still raise at once
_calls = []
def _locked_twice():
    _calls.append(1)
    if len(_calls) < 3:
        raise _sq.OperationalError("database is locked")
    return "opened"
ok("T88-retry-locked-waits-out-a-lock-and-returns", L.retry_locked(_locked_twice, pause=0.0) == "opened" and len(_calls) == 3, len(_calls))
def _other():
    raise _sq.OperationalError("no such table: x")
try:
    L.retry_locked(_other, pause=0.0); _other_raised = False
except _sq.OperationalError:
    _other_raised = True
_n = []
def _always_locked():
    _n.append(1); raise _sq.OperationalError("database is locked")
try:
    L.retry_locked(_always_locked, attempts=3, pause=0.0); _gave_up = False
except _sq.OperationalError:
    _gave_up = len(_n) == 3
ok("T88b-other-errors-raise-at-once-and-a-lasting-lock-gives-up-after-the-attempts", _other_raised and _gave_up, (_other_raised, _gave_up))
F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"VAULTLIB-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
