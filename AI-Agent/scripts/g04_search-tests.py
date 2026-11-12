# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for g04_search (term scoring, title bonus, all-in rule, scope filter, block
splitting of flat logs, live smoke on the real vault); run after any change to g04_search.py.
Usage: g04-search-tests"""

from __future__ import annotations

def _U(s):
    """ASCII-escaped test data: the shipped sources hold no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")

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
aok("terms: normalized token shapes", G.terms(_U(r"\u0627\u0644\u0637\u0628\u0642\u0629 \u0627\u0644\u062f\u0627\u0626\u0645\u0629 443")) == [_U(r"\u0627\u0644\u0637\u0628\u0642\u0647"), _U(r"\u0627\u0644\u062f\u0627\u064a\u0645\u0647"), "443"], G.terms(_U(r"\u0627\u0644\u0637\u0628\u0642\u0629 \u0627\u0644\u062f\u0627\u0626\u0645\u0629 443")))

# score_section(): all-in rule, body count, title bonus
ok("score: zero when a term is missing", G.score_section(_U(r"\u0639\u0646\u0648\u0627\u0646"), _U(r"\u0646\u0635 \u0641\u064a\u0647 \u0643\u0627\u0634"), [_U(r"\u0643\u0627\u0634"), _U(r"\u063a\u0627\u0626\u0628")]) == 0.0)
ok("score: counts body occurrences", G.score_section(_U(r"\u0639\u0646\u0648\u0627\u0646"), _U(r"\u0643\u0627\u0634 \u0643\u0627\u0634 \u0643\u0627\u0634"), [_U(r"\u0643\u0627\u0634")]) == 3.0)
ok("score: title bonus adds 3", G.score_section(_U(r"\u0627\u0644\u0643\u0627\u0634"), _U(r"\u0646\u0635 \u0643\u0627\u0634"), [_U(r"\u0643\u0627\u0634")]) == 4.0)
ok("score: empty query is zero", G.score_section(_U(r"\u0639\u0646\u0648\u0627\u0646"), _U(r"\u0646\u0635"), []) == 0.0)

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

FAILS = [t for t in T if not t[1]]
for name, cond, got in T:
    print(("PASS" if cond else "FAIL") + f" {name}" + (f" [{got}]" if got and not cond else ""))
print(f"G04-TESTS {len(T) - len(FAILS)}/{len(T)}")
if FAILS:
    raise SystemExit(1)
