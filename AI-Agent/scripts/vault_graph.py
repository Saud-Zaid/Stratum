#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""vault_graph.py - the link graph of the notes, without Obsidian (AD13 F2). Read-only.

usage:
  vault_graph.py in NOTE [--depth N]         notes that link to NOTE (zk --link-to, "backlinks"), with the line and its text
  vault_graph.py out NOTE [--depth N]        notes NOTE links to (zk --linked-by); unresolved targets are listed as "? target"
  vault_graph.py orphans [--scope PREFIX]    notes no other note links to (zk --orphan)
  vault_graph.py unreciprocated NOTE         notes NOTE links to that do not link back (zk --missing-backlink)
  any command: --json for one JSON object; NOTE is a path or a note name (case-insensitive, with or without .md)

Links counted, as Obsidian's graph does: [[wikilinks]] and ![[embeds]] of notes (alias, #heading and #^block parts ignored, a path
form is matched by its path), links in the frontmatter (area: "[[X]]"), and inline Markdown links `[t](path.md)` to a note
(relative, ./ and ../, from the vault root, or a bare note name). Fenced code and code spans are ignored. A name shared by several
notes resolves like Obsidian: the same folder first, else the shortest path. Links to other files (images, scripts) are not edges.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import _vaultlib as V  # noqa: E402
except ModuleNotFoundError as _e:   # a fresh machine without the pinned libraries: this tool needs only the standard library
    if _e.name not in ("yaml", "markdown_it", "mdit_py_plugins", "mdurl"):
        raise

    class V:   # the three things it takes from _vaultlib (a test keeps them equal to _vaultlib's)
        VAULT = Path(os.environ.get("VAULT") or Path(__file__).resolve().parents[2])
        SKIP_DIRS = {".git", ".obsidian", ".trash", "node_modules", ".venv", ".vault-release"}

        @staticmethod
        def force_utf8_stdio():
            for stream in (sys.stdout, sys.stderr):
                if getattr(stream, "reconfigure", None):
                    stream.reconfigure(encoding="utf-8", errors="replace")

WIKI = re.compile(r"(!?)\[\[([^\]\n]+?)\]\]")
MDLINK = re.compile(r"(?<!!)\[[^\]\n]*\]\(\s*(<[^>\n]+>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
FENCE = re.compile(r"^(```|~~~).*?^\1[^\n]*$", re.S | re.M)
CODESPAN = re.compile(r"`[^`\n]*`")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


def _blank(m) -> str:
    return "\n" * m.group(0).count("\n")


def split_note(text: str):
    """(frontmatter text, its line count, body text with code removed, newlines kept so line numbers stay true)."""
    fm, n = "", 0
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            close = text.find("\n", end + 1)
            fm = text[:close if close != -1 else len(text)]
            n = fm.count("\n") + 1
    body_start = len(fm)
    body = text[body_start:]
    body = FENCE.sub(_blank, body)
    body = CODESPAN.sub(lambda m: " " * len(m.group(0)), body)
    return fm, n, body


class Graph:
    def __init__(self, vault: Path | None = None):
        self.vault = Path(vault) if vault else V.VAULT
        self.files = []
        for dp, dn, fn in os.walk(self.vault):
            dn[:] = sorted(d for d in dn if d not in V.SKIP_DIRS and d != "__pycache__")
            for f in sorted(fn):
                if f.endswith(".md"):
                    self.files.append((Path(dp) / f).relative_to(self.vault).as_posix())
        self.fileset = set(self.files)
        self.stems = defaultdict(list)
        for r in self.files:
            self.stems[r.rsplit("/", 1)[-1][:-3].casefold()].append(r)
        self._assets = None
        self.out = defaultdict(list)       # src -> [(dst or None, target text, line)]
        self.inn = defaultdict(list)       # dst -> [(src, line, context)]
        for r in self.files:
            self._scan(r)

    def pick(self, cands, src: str):
        """Obsidian's choice among notes of the same name: the source's own folder first, else the shortest path."""
        if len(cands) == 1:
            return cands[0]
        folder = src.rsplit("/", 1)[0] if "/" in src else ""
        same = [c for c in cands if (c.rsplit("/", 1)[0] if "/" in c else "") == folder]
        return sorted(same or cands, key=lambda c: (c.count("/"), c))[0]

    def resolve_wiki(self, target: str, src: str):
        t = target.strip().rstrip("\\").strip()
        t = t.split("#", 1)[0].strip()
        if not t:
            return src
        low = t.casefold()
        if low.endswith(".md"):
            low = low[:-3]
        cands = self.stems.get(low.rsplit("/", 1)[-1], [])
        if "/" in low:                                   # a path form: the candidates that end with that path
            tail = ("/" + low + ".md")
            narrowed = [c for c in cands if ("/" + c.casefold()).endswith(tail)]
            cands = narrowed or cands
        if cands:
            return self.pick(cands, src)
        return False if self.is_asset(t) else None

    def is_asset(self, t: str) -> bool:
        """A target that names an existing file that is not a note (an image, a script): a link, but not an edge and not broken."""
        if self._assets is None:
            self._assets = set()
            for dp, dn, fn in os.walk(self.vault):
                dn[:] = [d for d in dn if d not in V.SKIP_DIRS and d != "__pycache__"]
                self._assets.update(f.casefold() for f in fn if not f.endswith(".md"))
        return t.rsplit("/", 1)[-1].casefold() in self._assets

    def resolve_md(self, href: str, src: str):
        href = href[1:-1].strip() if href.startswith("<") and href.endswith(">") else href
        if not href or href.startswith("#") or SCHEME.match(href) or href.startswith("//"):
            return False
        path = urllib.parse.unquote(href.split("#", 1)[0].split("?", 1)[0]).strip()
        if not path:
            return False
        base = src.rsplit("/", 1)[0] if "/" in src else ""
        for cand in (os.path.normpath(os.path.join(base, path)).replace(os.sep, "/"), path.lstrip("/")):
            for c in (cand, cand + ".md"):
                if c in self.fileset:
                    return c
        if "." not in Path(path).name:                    # a bare note name
            cands = self.stems.get(path.rsplit("/", 1)[-1].casefold(), [])
            return self.pick(cands, src) if cands else None
        if path.lower().endswith(".md"):
            return None                                   # a note link that points nowhere
        return False                                      # a link to some other file: not an edge

    def _scan(self, src: str):
        try:
            text = (self.vault / src).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        fm, fm_lines, body = split_note(text)
        lines_fm = fm.split("\n") if fm else []
        seen = set()

        def edge(dst, target, line, ctx):
            if dst is False:
                return
            if dst is None:
                self.out[src].append((None, target, line))
                return
            if dst == src or (dst, line) in seen:
                return
            seen.add((dst, line))
            self.out[src].append((dst, target, line))
            self.inn[dst].append((src, line, ctx.strip()[:100]))

        for i, ln in enumerate(lines_fm, 1):
            for m in WIKI.finditer(ln):
                tgt = re.split(r"\\?\|", m.group(2), maxsplit=1)[0]
                edge(self.resolve_wiki(tgt, src), tgt.strip(), i, ln)
        body_lines = body.split("\n")
        for j, ln in enumerate(body_lines):
            line = fm_lines + j if fm else j + 1
            if "[[" in ln:
                for m in WIKI.finditer(ln):
                    tgt = re.split(r"\\?\|", m.group(2), maxsplit=1)[0]            # a table escapes the alias bar as \|
                    edge(self.resolve_wiki(tgt, src), tgt.strip(), line, ln)
            if "](" in ln:
                for m in MDLINK.finditer(ln):
                    dst = self.resolve_md(m.group(1), src)
                    if dst is False:
                        continue
                    edge(dst, m.group(1), line, ln)

    def find_note(self, name: str):
        n = name.strip().strip('"')
        if n in self.fileset:
            return n
        if n + ".md" in self.fileset:
            return n + ".md"
        base = n[:-3] if n.lower().endswith(".md") else n
        cands = self.stems.get(base.rsplit("/", 1)[-1].casefold(), [])
        if "/" in base:
            tail = "/" + base.casefold() + ".md"
            cands = [c for c in cands if ("/" + c.casefold()).endswith(tail)] or cands
        return sorted(cands, key=lambda c: (c.count("/"), c))[0] if cands else None

    def neighbours(self, note: str, direction: str):
        if direction == "in":
            return sorted({s for s, _l, _c in self.inn.get(note, [])})
        return sorted({d for d, _t, _l in self.out.get(note, []) if d})

    def walk(self, note: str, direction: str, depth: int):
        """[(distance, path)] breadth first, nearest first, never the start itself."""
        seen, queue, out = {note}, deque([(note, 0)]), []
        while queue:
            cur, dist = queue.popleft()
            if dist >= depth:
                continue
            for n in self.neighbours(cur, direction):
                if n not in seen:
                    seen.add(n)
                    out.append((dist + 1, n))
                    queue.append((n, dist + 1))
        return out

    def orphans(self, scope: str = ""):
        return [r for r in self.files if r.startswith(scope) and not any(s != r for s, _l, _c in self.inn.get(r, []))]

    def unreciprocated(self, note: str):
        return [d for d in self.neighbours(note, "out") if note not in self.neighbours(d, "out")]


def main(argv=None) -> int:
    V.force_utf8_stdio()
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if a else 2
    as_json = "--json" in a
    a = [x for x in a if x != "--json"]

    def opt(name, default=None):
        if name in a:
            i = a.index(name)
            v = a[i + 1] if i + 1 < len(a) else None
            del a[i:i + 2]
            return v
        return default
    try:
        depth = int(opt("--depth", "1"))
    except ValueError:
        print("ERROR: --depth needs a number", file=sys.stderr)
        return 2
    scope = opt("--scope", "")
    cmd, rest = a[0], a[1:]
    if cmd not in ("in", "out", "orphans", "unreciprocated"):
        print(f"ERROR: unknown command {cmd!r}", file=sys.stderr)
        return 2
    g = Graph()
    if cmd == "orphans":
        o = g.orphans(scope)
        print(json.dumps({"orphans": o, "total_notes": len(g.files)}, ensure_ascii=False) if as_json else "\n".join(o + [f"# {len(o)} orphans of {len(g.files)} notes"]))
        return 0
    if not rest:
        print(f"ERROR: {cmd} needs a note", file=sys.stderr)
        return 2
    note = g.find_note(" ".join(rest))
    if not note:
        print(f"ERROR: no note named {' '.join(rest)!r}", file=sys.stderr)
        return 2
    if cmd == "unreciprocated":
        r = g.unreciprocated(note)
        print(json.dumps({"note": note, "unreciprocated": r}, ensure_ascii=False) if as_json else "\n".join(r))
        return 0
    if cmd == "in":
        if depth <= 1:
            rows = [(1, s, l, c) for s, l, c in sorted(g.inn.get(note, []))]
            firsts, counts = {}, defaultdict(int)
            for d, s, l, c in rows:
                counts[s] += 1
                firsts.setdefault(s, (l, c))
            res = [{"path": s, "line": firsts[s][0], "links": counts[s], "context": firsts[s][1]} for s in sorted(firsts)]
            print(json.dumps({"note": note, "in": res}, ensure_ascii=False) if as_json else "\n".join(f"{r['path']}\t{r['line']}\t{r['context']}" + (f"  (+{r['links'] - 1} more)" if r["links"] > 1 else "") for r in res))
            return 0
        walk = g.walk(note, "in", depth)
    else:
        if depth <= 1:
            res = [{"path": d, "line": l} for d, _t, l in g.out.get(note, []) if d]
            seen, uniq = set(), []
            for r in res:
                if r["path"] not in seen:
                    seen.add(r["path"])
                    uniq.append(r)
            unresolved = sorted({t for d, t, _l in g.out.get(note, []) if d is None})
            print(json.dumps({"note": note, "out": uniq, "unresolved": unresolved}, ensure_ascii=False) if as_json
                  else "\n".join([f"{r['path']}\t{r['line']}" for r in uniq] + [f"? {t}" for t in unresolved]))
            return 0
        walk = g.walk(note, "out", depth)
    print(json.dumps({"note": note, cmd: [{"distance": d, "path": p} for d, p in walk]}, ensure_ascii=False) if as_json else "\n".join(f"{d}\t{p}" for d, p in walk))
    return 0


if __name__ == "__main__":
    sys.exit(main())
