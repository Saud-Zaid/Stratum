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
        ok("T64-session-db-xdg", L.session_db_path() == TMP / "xdg" / "goose" / "sessions" / "sessions.db", L.session_db_path())
        del os.environ["XDG_DATA_HOME"]
        ok("T65-session-db-default-under-home", L.session_db_path().parts[-3:] == ("goose", "sessions", "sessions.db") and ".local" in L.session_db_path().parts, L.session_db_path())
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
finally:
    L.VAULT = ORIG_VAULT
    L.CLUB_AREA = _U(r"02-Areas/\u0646\u0627\u062f\u064a-\u0637\u0648\u064a\u0642-\u062a\u0643.md")
    shutil.rmtree(TMP, ignore_errors=True)

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"VAULTLIB-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
