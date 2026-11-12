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


def terms(query: str) -> list:
    """Normalized query terms (normalize_ar folds hamza/diacritics and Eastern Arabic-Indic digits)."""
    return [t for t in re.split(r"[^\w]+", normalize_ar(query)) if t]


def score_section(title: str, body: str, qs: list) -> float:
    """Term-frequency score with a title bonus; a hit must contain every term."""
    nb, nt = normalize_ar(body), normalize_ar(title)
    total, all_in = 0.0, True
    for q in qs:
        c = nb.count(q)
        if c == 0:
            all_in = False
        total += c + TITLE_BONUS * (1 if q in nt else 0)
    if not all_in or not qs:
        return 0.0
    return total


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


def search(query: str, scope: str = "all", top: int = TOP_DEFAULT) -> list:
    """Top units across the scope; hit keys: file,title,sline,nlines,bytes,fbytes,score,snippet."""
    qs = terms(query)
    if not qs:
        return []
    hits = []
    for p in iter_files(scope):
        try:
            text = read(p)
        except Exception:
            continue
        lines = text.splitlines()
        fbytes = len(text.encode())

        def unit(sline: int, nlines: int, body: str, title: str, sc: float) -> dict:
            snip = []
            for ln in body.splitlines():
                n = normalize_ar(ln)
                if any(q in n for q in qs) and len(snip) < SNIPPET_DEFAULT:
                    snip.append(ln[:110])
            return {"score": sc, "file": p.relative_to(VAULT).as_posix(), "title": title,
                    "sline": sline, "nlines": nlines, "bytes": len(body.encode()),
                    "fbytes": fbytes, "snippet": snip}

        for s in leaf_sections(text):
            body_lines = lines[s["line"]:s["line"] + s["lines"] - 1]
            body = "\n".join(body_lines)
            title = s["title"]
            if s["bytes"] > BLOCK_MAX:
                for bstart, btext in blocks_of(body_lines, s["line"]):
                    sc = score_section(title, btext, qs)
                    if sc > 0:
                        hits.append(unit(bstart, len(btext.splitlines()), btext, title, sc))
            else:
                sc = score_section(title, body, qs)
                if sc > 0:
                    hits.append(unit(s["line"], s["lines"] - 1, body, title, sc))
    hits.sort(key=lambda h: (-h["score"], h["file"], h["sline"]))
    return hits[:top]


def main(argv: list) -> None:
    """Flag values are parsed, never leaked into the query."""
    force_utf8_stdio()
    ap = standard_parser(__doc__, "g04-search")
    ap.add_argument("query", nargs="*")
    ap.add_argument("--scope", default="all", choices=sorted(SCOPES))
    ap.add_argument("--top", type=int, default=TOP_DEFAULT)
    ap.add_argument("--tokens", action="store_true")
    args = ap.parse_args(argv)
    query_parts, scope, top, want_tokens = args.query, args.scope, args.top, args.tokens
    query = " ".join(query_parts)
    if not query:
        print(__doc__)
        return
    hits = search(query, scope, top)
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
    print(f"G04A \"{query}\" -> {len(hits)} hits")


if __name__ == "__main__":
    main(sys.argv[1:])
