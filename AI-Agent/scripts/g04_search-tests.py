# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for g04_search (term scoring, title bonus, all-in rule, scope filter, block
splitting of flat logs, live smoke on the real vault); run after any change to g04_search.py.
Usage: g04-search-tests"""

from __future__ import annotations

def _U(s):
    """ASCII-escaped test data: the shipped sources hold no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")

import os

import g04_search as G

T = []


def ok(name, cond, got=""):
    T.append((name, bool(cond), got))


HAS_AR = bool(G.locale_value("NORMALIZE", {}))


def aok(name, cond, got=""):
    """ok(), run only where the Arabic locale tables exist."""
    if HAS_AR:
        ok(name, cond, got)
    else:
        print(f"SKIP {name}: no Arabic locale in this tree")


# terms(): normalization folds hamza/diacritics so variants unify (-> is normalize_ar's real behavior)
ok("terms: hamza/diacritic variants unify", G.terms(_U(r"\u0628\u0650\u0633\u0652\u0645")) == G.terms(_U(r"\u0628\u0633\u0645")), G.terms(_U(r"\u0628\u0650\u0633\u0652\u0645")))
aok("terms: normalized token shapes", G.terms(_U(r"\u0627\u0644\u0637\u0628\u0642\u0629 \u0627\u0644\u062f\u0627\u0626\u0645\u0629 443")) == [_U(r"\u0637\u0628\u0642"), _U(r"\u062f\u0627\u064a\u0645"), "443"], G.terms(_U(r"\u0627\u0644\u0637\u0628\u0642\u0629 \u0627\u0644\u062f\u0627\u0626\u0645\u0629 443")))

# unit_stats() and bm25_rank() (AD13 B5): tf, length, title hits; rare terms outrank common ones, short beats long, tf saturates
def _rank(units, qs):
    cs = []
    df = [0] * len(qs)
    for title, body in units:
        tfs, dl, tt = G.unit_stats(title, body, qs)
        for k, tf in enumerate(tfs):
            df[k] += tf > 0
        cs.append({"tfs": tfs, "dl": dl, "tt": tt})
    G.bm25_rank(cs, df, len(units), sum(c["dl"] for c in cs) / len(cs))
    return [c["score"] for c in cs]


ok("bm25: stats count tf and flag a missing term", G.unit_stats("t", "a a b", ["a", "z"])[0] == [2, 0])
s_rare, s_common = _rank([("t", "rare common"), ("t", "common common"), ("t", "common x")], ["rare"])[0], _rank([("t", "rare common"), ("t", "common common"), ("t", "common x")], ["common"])[0]
ok("bm25: a rare term outscores a common one", s_rare > s_common, (s_rare, s_common))
sc = _rank([("t", "a " + "w " * 5), ("t", "a " + "w " * 200), ("t", "w")], ["a"])
ok("bm25: a short unit beats a long one with equal tf", sc[0] > sc[1], sc)
sc = _rank([("t", "a " * 5), ("t", "a " * 10), ("t", "a " * 20 + "x"), ("t", "w")], ["a"])
ok("bm25: tf saturates (doubling tf less than doubles the score)", sc[1] < 2 * sc[0], sc)
sc = _rank([("a", "a x"), ("t", "a x"), ("t", "w")], ["a"])
ok("bm25: title hit adds the bonus", abs((sc[0] - sc[1]) - G.TITLE_BONUS) < 1e-9, sc)
ok("bm25: empty query has no stats to rank", G.terms("") == [])
ok("files_line: counts, orders and caps", G.files_line([{"file": "b"}, {"file": "a"}, {"file": "a"}]) == "files 2: a(2), b(1)"
   and G.files_line([{"file": f"f{i}"} for i in range(10)]).endswith("+2 more"))

# relaxed fallback (AD13 A3 finding): a question with a word no note uses still finds units; a full match never relaxes
_rx = []
_h = G.search("commit gate zzqqxxnoword", "agent", 3, _rx)
ok("relaxed: unmatched word falls back to partial units", bool(_h) and _rx == [2, 3], (_rx, len(_h)))
_rx2 = []
G.search("commit gate", "agent", 3, _rx2)
ok("relaxed: a full match never relaxes", _rx2 == [], _rx2)
_rx3 = []
ok("relaxed: a single missing term stays empty", G.search("zzqqxxnoword", "agent", 3, _rx3) == [] and _rx3 == [])

# blocks_of(): flat bodies split on blank lines with correct 0-based line anchors
bodies = G.blocks_of([_U(r"\u0623"), _U(r"\u0628"), "", _U(r"\u062c")], 10)
ok("blocks: two blocks split on blank", len(bodies) == 2 and bodies[0][0] == 10 and bodies[1][0] == 13, bodies)
ok("blocks: single block keeps text", G.blocks_of([_U(r"\u0623"), _U(r"\u0628")], 5) == [(5, _U(r"\u0623\n\u0628"))], G.blocks_of([_U(r"\u0623"), _U(r"\u0628")], 5))
ok("blocks: blank head starts next block", G.blocks_of(["", _U(r"\u0623")], 0) == [(1, _U(r"\u0623"))], G.blocks_of(["", _U(r"\u0623")], 0))

MOTHER = (G.VAULT / "AI-Agent/config/export-manifest.yaml").is_file()   # the mother vault holds the AD06 notes and the operations history


def mok(name, cond, got=""):
    """ok(), run only against the mother vault's own content."""
    if MOTHER:
        ok(name, cond, got)
    else:
        print(f"SKIP {name}: the mother vault's content is not part of this tree")


# scope filter: real vault directories resolve and stay clean of excluded trees
ok("scope: agent files exist", len(G.iter_files("agent")) > (100 if MOTHER else 20), len(G.iter_files("agent")))
ok("scope: no scratch/fixtures/state leaks",
   not any(s in str(f) for f in G.iter_files("agent") for s in ("/scratch/", "/fixtures/", "/state/")))
mok("scope: ad06 hits the project dir",
   any("AD06" in str(f) for f in G.iter_files("ad06")), len(G.iter_files("ad06")))
mok("scope: operation log is indexed",
   any(str(f).endswith("AI-Agent/operations.md") for f in G.iter_files("agent")))

# search(): live smoke on the real vault, read-only
r1 = G.search("rolled_back", "agent")
mok("live: rolled_back -> operations.md", len(r1) > 0 and any("operations.md" in h["file"] for h in r1),
   [h["file"] for h in r1][:2])
r2 = G.search("OP-0002", "agent")
op_hits = [h for h in r2 if "operations.md" in h["file"]]
mok("live: OP-0002 -> one op block, not the 80KB log",
   len(op_hits) > 0 and all(h["bytes"] < 5000 for h in op_hits), [(h["bytes"]) for h in op_hits])
r3 = G.search("prefix caching", "ad06")
mok("live: prefix caching -> AD06 notes", len(r3) > 0, [h["file"] for h in r3][:2])
ok("live: gibberish -> no hits", G.search("xyzzyqq nonexistentzz") == [])
ok("live: top cap respected", len(G.search(_U(r"\u0627\u0644\u0637\u0628\u0642\u0629"), "agent", top=3)) <= 3)

# scope "stratum" is a real scope, only existing dirs are walked, hits carry forward-slash paths
ok("scope: stratum defined", "stratum" in G.SCOPES and set(G.SCOPES["stratum"]) <= set(G.SCOPES["all"]), G.SCOPES.get("stratum"))
ok("scope: stratum files are inside it", all(p.relative_to(G.VAULT).parts[0] in G.SCOPES["stratum"] for p in G.iter_files("stratum")))
ok("live: hit paths use /", all("\\" not in h["file"] for h in G.search(_U(r"\u0627\u0644\u0637\u0628\u0642\u0629"), "agent", top=3)))

# AD13 B retrofit: Lucene's Arabic light stemmer on query terms (Arabic written as escapes)
_LS = lambda s: G.light_stem(G.normalize_ar(_U(s)))
aok("stem: the article and the wa+article go", _LS(r"\u0627\u0644\u062d\u0627\u0631\u0633") == _U(r"\u062d\u0627\u0631\u0633") and _LS(r"\u0648\u0627\u0644\u062d\u0627\u0631\u0633") == _U(r"\u062d\u0627\u0631\u0633"))
aok("stem: one suffix goes (her, plural at)", _LS(r"\u062d\u0627\u0631\u0633\u0647\u0627") == _U(r"\u062d\u0627\u0631\u0633") and _LS(r"\u0627\u0644\u0645\u0643\u062a\u0628\u0627\u062a") == _U(r"\u0645\u0643\u062a\u0628"))
aok("stem: short words and words that would keep under two letters are left alone", _LS(r"\u0639\u0644\u0645") == _U(r"\u0639\u0644\u0645") and _LS(r"\u0648\u0632\u0646") == _U(r"\u0648\u0632\u0646") and _LS(r"\u0627\u0644\u0628") == _U(r"\u0627\u0644\u0628"))
aok("stem: a prefix that would leave one letter is skipped for the next rule", _LS(r"\u0648\u0627\u0644\u0628") == _U(r"\u0627\u0644\u0628"), _LS(r"\u0648\u0627\u0644\u0628"))
aok("stem: negative control, distinct roots stay distinct", _LS(r"\u0639\u0644\u0645") != _LS(r"\u0639\u0627\u0644\u0645") and _LS(r"\u0643\u062a\u0627\u0628") != _LS(r"\u0643\u0627\u062a\u0628"))
ok("stem: Latin and mixed tokens are untouched", G.terms("Search tools v2") == ["search", "tools", "v2"] and G.light_stem("ab12") == "ab12")
aok("terms: the query with the article equals the bare query", G.terms(_U(r"\u0627\u0644\u062d\u0627\u0631\u0633 \u0627\u0644\u0642\u0631\u0627\u0621\u0629")) == G.terms(_U(r"\u062d\u0627\u0631\u0633 \u0642\u0631\u0627\u0621")))
_body = _U(r"\u062d\u0627\u0631\u0633 \u0627\u0644\u0642\u0631\u0627\u0621\u0629 \u064a\u0639\u0645\u0644 \u0647\u0646\u0627")
_q = _U(r"\u0627\u0644\u062d\u0627\u0631\u0633 \u0627\u0644\u0642\u0631\u0627\u0621\u0629")
aok("recall: an article the text lacks no longer hides the unit", all(tf > 0 for tf in G.unit_stats("", _body, G.terms(_q))[0]), G.unit_stats("", _body, G.terms(_q)))
os.environ["STRATUM_ARABIC_STEM"] = "0"
_off = G.unit_stats("", _body, G.terms(_q))[0]
del os.environ["STRATUM_ARABIC_STEM"]
aok("kill switch: with STRATUM_ARABIC_STEM=0 the old behaviour returns", _off[0] == 0 and _off[1] > 0, _off)
_roots = G.unit_stats("", _U(r"\u0639\u0644\u0645 \u0627\u0644\u0646\u0627\u0633"), G.terms(_U(r"\u0639\u0627\u0644\u0645")))[0]
aok("precision: a different root does not match", _roots == [0], _roots)

# AD13 B retrofit: --json (qmd, grepdown and kbx have a machine-readable output for agents); the text output is untouched
import json as _json
import subprocess as _sp
import sys as _sys
_run = lambda *a: _sp.run([_sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "g04_search.py"), *a], capture_output=True, text=True, encoding="utf-8")
_pj = _run("--json", "--scope", "agent", "--top", "3", "ratchet", "commit")
try:
    _jo = _json.loads(_pj.stdout)
except ValueError:
    _jo = {}
ok("json: one parsable object with the documented keys", _pj.returncode == 0 and set(_jo) == {"query", "scope", "relaxed", "hits", "files", "files_total"} and _jo["query"] == "ratchet commit", _pj.stdout[:200])
ok("json: hits carry file, title, 1-based line, lines, scores in descending order, at most --top",
   0 < len(_jo.get("hits", [])) <= 3 and all({"file", "title", "line", "lines", "bytes", "file_bytes", "score", "snippet"} <= set(h) and h["line"] >= 1 for h in _jo["hits"])
   and [h["score"] for h in _jo["hits"]] == sorted((h["score"] for h in _jo["hits"]), reverse=True), _jo.get("hits", [])[:1])
_pt = _run("--scope", "agent", "--top", "3", "ratchet", "commit")
ok("json: the same hits in the same order as the text output", [h["file"] for h in _jo.get("hits", [])] == [l.split(" ")[2] for l in _pt.stdout.splitlines() if l.startswith("- ")][:len(_jo.get("hits", []))], (_pt.stdout[:160],))
import re as _re
_tx = [(int(m.group(1)), int(m.group(2))) for l in _pt.stdout.splitlines() if l.startswith("- ") for m in [_re.search(r"\(L(\d+)\+(\d+),", l)] if m]
ok("json: line and lines equal the L<line>+<lines> of the text output", [(h["line"], h["lines"]) for h in _jo.get("hits", [])] == _tx[:len(_jo.get("hits", []))] and bool(_tx), (_tx, [(h["line"], h["lines"]) for h in _jo.get("hits", [])]))
ok("json: the text output has no JSON and keeps its summary line", "G04A" in _pt.stdout and not _pt.stdout.lstrip().startswith("{"))
_pr = _run("--json", "--scope", "agent", "zzqxunmatchableone zzqxunmatchabletwo")
ok("json: a query with no hit is an empty list, not an error", _pr.returncode == 0 and _json.loads(_pr.stdout)["hits"] == [] and _json.loads(_pr.stdout)["relaxed"] is None, _pr.stdout[:160])
_pa = _run("--json", "--scope", "agent", "--top", "5", "ratchet", "zzqxunmatchable")
_ja = _json.loads(_pa.stdout)
ok("json: the relaxed fallback is reported as matched and total", _ja["relaxed"] == {"matched": 1, "total": 2} and _ja["hits"], _pa.stdout[:200])

FAILS = [t for t in T if not t[1]]
for name, cond, got in T:
    print(("PASS" if cond else "FAIL") + f" {name}" + (f" [{got}]" if got and not cond else ""))
print(f"G04-TESTS {len(T) - len(FAILS)}/{len(T)}")
if FAILS:
    raise SystemExit(1)
