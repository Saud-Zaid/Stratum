# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""G04-a on-demand retrieval index (AD06 C6 F1): when a question exceeds the 443-token
permanent layer, search the split memory files and retrieve only matching sections
instead of inflating the layer. Read-only: prints, never writes.

The split memory files are the knowledge the permanent layer deliberately defers
(permanent-layer.md, "Explicitly deferred"): the operation log (operations.md), rules,
protocols, traps and the AD06 decision notes. None loads whole; the index is built in
memory per run and only matching units are printed, with byte cost so retrieval stays
measurable against loading the whole file. Sections larger than BLOCK_MAX bytes are split
into blank-line blocks first, so a flat log like operations.md yields one op block per
hit instead of the whole file.

Usage:
  g04-search <query> [--scope agent|ad06|stratum|all] [--top N] [--tokens]
Output rows: - <score> <relpath> :: <section> (L<start>+<nlines>, <bytes>B of <fbytes>B)
             snippet lines "  | <text>" (lines containing query terms)
             final: G04A "<query>" -> <n> hits over <f> files
"""
from __future__ import annotations

import math
import os
import re
import sys

from _vaultlib import VAULT, force_utf8_stdio, leaf_sections, locale_value, normalize_ar, read, standard_parser

SCOPES = {
    "agent": ["AI-Agent"],
    **({"ad06": [locale_value("AD06_SCOPE")]} if locale_value("AD06_SCOPE") else {}),
    "stratum": ["AI-Agent", "01-Projects", "03-Resources", "Templates"],
    "all": [
        "AI-Agent", "01-Projects", "02-Areas", "03-Resources", "04-Archive",
        "05-Zettelkasten", "06-MOCs", "00-Inbox", "Templates", "card-template",
    ],
}
SKIP = ("/scratch/", "/fixtures/", "__pycache__", "/pylib/", "/state/")
BLOCK_MAX = 3000   # a section larger than this is searched block-by-block, not whole
TITLE_BONUS = 3.0
K1, B = 1.2, 0.75     # BM25 (AD13 B5): standard Robertson parameters
FILES_LISTED = 8       # narrowing line: the files holding the hits, with counts
TOP_DEFAULT = 5
SNIPPET_DEFAULT = 2


def iter_files(scope: str = "all") -> list:
    """Every .md in the scope dirs, scratch/fixtures/state excluded."""
    out = []
    for d in SCOPES.get(scope, SCOPES["all"]):
        base = VAULT / d
        if not base.is_dir():
            continue
        for p in base.rglob("*.md"):
            if any(s in p.as_posix() for s in SKIP):
                continue
            out.append(p)
    return sorted(set(out))


# AD13 B retrofit: Lucene's Arabic light stemmer (ArabicStemmer.java, Apache-2.0: the prefixes and suffixes below, one of each at most,
# never leaving fewer than two letters), kept in `_locale_ar` (a release script holds no Arabic). Applied to QUERY terms only: matching
# here is by substring, so a stem finds every text form that contains it, and the index needs no change. Rules run after normalize_ar,
# which has already turned the teh marbuta into heh and the alef maksura into yeh, as Lucene's normalizer does.
_PREFIXES = locale_value("LIGHT_STEM_PREFIXES", ())      # the tables live in _locale_ar (the mother vault); a release has none
_SUFFIXES = locale_value("LIGHT_STEM_SUFFIXES", ())
_ARABIC_WORD = re.compile(locale_value("ARABIC_WORD", r"(?!)"))      # never matches without the locale: every term is left alone


def light_stem(term: str) -> str:
    """The term without one Arabic prefix and one suffix (the first that fits), or the term itself; Latin terms, short words and
    STRATUM_ARABIC_STEM=0 are left alone."""
    if os.environ.get("STRATUM_ARABIC_STEM") == "0" or len(term) < 4 or not _ARABIC_WORD.match(term):
        return term
    for p in _PREFIXES:
        if term.startswith(p) and len(term) >= len(p) + 2:
            term = term[len(p):]
            break
    for s in _SUFFIXES:
        if term.endswith(s) and len(term) >= len(s) + 2:
            term = term[:-len(s)]
            break
    return term


def terms(query: str) -> list:
    """Normalized query terms (normalize_ar folds hamza/diacritics and Eastern Arabic-Indic digits; light_stem trims one Arabic affix)."""
    return [light_stem(t) for t in re.split(r"[^\w]+", normalize_ar(query)) if t]


def unit_stats(title: str, body: str, qs: list):
    """(tf per term, length in words, title-hit count) of one unit."""
    nb, nt = normalize_ar(body), normalize_ar(title)
    return [nb.count(q) for q in qs], max(1, len(nb.split())), sum(1 for q in qs if q in nt)


def bm25_rank(cands: list, df: list, n_units: int, avgdl: float) -> None:
    """Set cand['score'] = BM25 over the terms plus the title bonus; df = units holding each term."""
    for c in cands:
        sc = 0.0
        for tf, d in zip(c["tfs"], df):
            idf = math.log(1 + (n_units - d + 0.5) / (d + 0.5))
            sc += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * c["dl"] / avgdl))
        c["score"] = sc + TITLE_BONUS * c["tt"]


def blocks_of(body_lines: list, start0: int) -> list:
    """(start0, text) per blank-line-separated block; start0 = file 0-based line index."""
    out, cur, cur_start = [], [], start0
    for idx, ln in enumerate(body_lines):
        if not ln.strip():
            if cur:
                out.append((cur_start, "\n".join(cur)))
                cur = []
            cur_start = start0 + idx + 1
        else:
            cur.append(ln)
    if cur:
        out.append((cur_start, "\n".join(cur)))
    return out


def snippet_of(body: str, qs: list) -> list:
    snip = []
    for ln in body.splitlines():
        n = normalize_ar(ln)
        if any(q in n for q in qs) and len(snip) < SNIPPET_DEFAULT:
            snip.append(ln[:110])
    return snip


def search(query: str, scope: str = "all", top: int = TOP_DEFAULT, relaxed_out: list = None) -> list:
    """Top units across the scope, ranked by BM25. A hit holds every term; when no unit does (a natural-language
    question carries words no note uses) the units holding at least half of the terms are ranked instead and
    `relaxed_out` (a list) receives [matched, total]. Hit keys: file,title,sline,nlines,bytes,fbytes,score,snippet."""
    qs = terms(query)
    if not qs:
        return []
    cands, df, n_units, total_len = [], [0] * len(qs), 0, 0
    for p in iter_files(scope):
        try:
            text = read(p)
        except Exception:
            continue
        lines = text.splitlines()
        fbytes = len(text.encode())
        rel = p.relative_to(VAULT).as_posix()

        def add(sline: int, nlines: int, body: str, title: str) -> None:
            nonlocal n_units, total_len
            tfs, dl, tt = unit_stats(title, body, qs)
            n_units += 1
            total_len += dl
            for i, tf in enumerate(tfs):
                df[i] += tf > 0
            if not any(tfs):
                return
            cands.append({"tfs": tfs, "dl": dl, "tt": tt, "file": rel, "title": title, "sline": sline,
                          "nlines": nlines, "bytes": len(body.encode()), "fbytes": fbytes, "body": body})

        for s in leaf_sections(text):
            body_lines = lines[s["line"]:s["line"] + s["lines"] - 1]
            body = "\n".join(body_lines)
            if s["bytes"] > BLOCK_MAX:
                for bstart, btext in blocks_of(body_lines, s["line"]):
                    add(bstart, len(btext.splitlines()), btext, s["title"])
            else:
                add(s["line"], s["lines"] - 1, body, s["title"])
    pool = [c for c in cands if 0 not in c["tfs"]]
    if not pool and len(qs) > 1:
        need = -(-len(qs) // 2)
        pool = [c for c in cands if sum(1 for tf in c["tfs"] if tf) >= need]
        if pool and relaxed_out is not None:
            relaxed_out[:] = [need, len(qs)]
    bm25_rank(pool, df, n_units, (total_len / n_units) if n_units else 1.0)
    pool.sort(key=lambda h: (-h["score"], h["file"], h["sline"]))
    out = pool[:top]
    for h in out:
        h["snippet"] = snippet_of(h.pop("body"), qs)
    return out


def files_line(hits_all: list) -> str:
    """Narrowing line: files holding the hits, most hits first, capped."""
    counts = {}
    for h in hits_all:
        counts[h["file"]] = counts.get(h["file"], 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = ", ".join(f"{f}({n})" for f, n in top[:FILES_LISTED])
    return f"files {len(counts)}: {shown}" + (f", +{len(counts) - FILES_LISTED} more" if len(counts) > FILES_LISTED else "")


def main(argv: list) -> None:
    """Flag values are parsed, never leaked into the query."""
    force_utf8_stdio()
    ap = standard_parser(__doc__, "g04-search")
    ap.add_argument("query", nargs="*")
    ap.add_argument("--scope", default="all", choices=sorted(SCOPES))
    ap.add_argument("--top", type=int, default=TOP_DEFAULT)
    ap.add_argument("--tokens", action="store_true")
    ap.add_argument("--json", action="store_true", help="one JSON object (query, scope, relaxed, hits, files) instead of the text lines; AD13 B retrofit")
    args = ap.parse_args(argv)
    query_parts, scope, top, want_tokens = args.query, args.scope, args.top, args.tokens
    query = " ".join(query_parts)
    if not query:
        print(__doc__)
        return
    relaxed = []
    hits = search(query, scope, 10 ** 9, relaxed)
    narrowing = files_line(hits)
    if args.json:                # qmd, grepdown and kbx all offer a machine-readable form for agents; same hits, same order
        import json
        counts = {}
        for h in hits:
            counts[h["file"]] = counts.get(h["file"], 0) + 1
        print(json.dumps({"query": query, "scope": scope, "relaxed": ({"matched": relaxed[0], "total": relaxed[1]} if relaxed and hits else None),
                          "hits": [{"file": h["file"], "title": h["title"], "line": h["sline"] + 1, "lines": h["nlines"], "bytes": h["bytes"],
                                    "file_bytes": h["fbytes"], "score": round(h["score"], 3), "snippet": h["snippet"]} for h in hits[:top]],
                          "files": [{"file": f, "hits": n} for f, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:FILES_LISTED]],
                          "files_total": len(counts)}, ensure_ascii=False))
        return
    hits = hits[:top]
    if relaxed and hits:
        print(f"# no unit holds all {relaxed[1]} terms; showing units with at least {relaxed[0]} of them")
    for h in hits:
        print(f"- {h['score']:.1f} {h['file']} :: {h['title']} (L{h['sline'] + 1}+{h['nlines']}, {h['bytes']}B of {h['fbytes']}B)")
        for ln in h["snippet"]:
            print(f"  | {ln}")
    if want_tokens and hits:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        text = read(VAULT / hits[0]["file"])
        sec = "\n".join(text.splitlines()[hits[0]["sline"]:hits[0]["sline"] + hits[0]["nlines"]])
        print(f"cost: top hit {len(enc.encode(sec))} tok vs whole file {len(enc.encode(text))} tok")
    print(narrowing if hits else "files 0")
    print(f"G04A \"{query}\" -> {len(hits)} hits")


if __name__ == "__main__":
    main(sys.argv[1:])
