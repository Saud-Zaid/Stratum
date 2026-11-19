#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""vault_mv.py - rename or move a note and keep every link pointing at it (AD13 F4, register D44). Without Obsidian.

usage:
  vault_mv.py OLD NEW            dry run: print the move and the link edits it needs, change nothing
  vault_mv.py OLD NEW --apply    do it: refuse if an affected file has uncommitted changes, move the note, rewrite the links
                                 through apply.py (one atomic batch), check the link graph, and undo everything if it differs
  any form: --json for one JSON object
OLD is a path or a unique note name; NEW is a vault path ending .md, or a bare file name (a rename in the same folder).

Method: a link is rewritten only when its resolution would change after the move, judged on a virtual graph with the note
moved (vault_graph's Obsidian semantics: same folder first, else shortest path). The new form keeps the old style (name or
path, alias, #heading, embed, relative or root Markdown link, ./ and ../) when it still resolves to the right note, else a path
form is used. Links inside the moved note are rebased when its folder changes, including links to images and other files.
Not edited, only listed: plain-text and backtick mentions of the old path (and the old name in non-note files), because a
program cannot tell a mention from prose. The self-check after --apply compares the whole link graph before and after under
the renaming; any difference undoes the move. The rule in rules.md still holds: the vault owner confirms the latest commit and push first.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse
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
import vault_graph as G  # noqa: E402

APPLY = Path(__file__).resolve().parent / "apply.py"
# vault_graph.MDLINK skips images; a move must also rebase the links of images and files
MDLINK_ANY = re.compile(G.MDLINK.pattern.replace("(?<!!)", ""))


def mask(text: str) -> str:
    """The text with fenced code and code spans blanked to spaces, newlines kept: offsets stay valid."""
    def blank(m):
        return re.sub(r"[^\n]", " ", m.group(0))
    return G.CODESPAN.sub(blank, G.FENCE.sub(blank, text))


def virtual_after(g: G.Graph, old: str, new: str) -> G.Graph:
    """A graph that answers resolution questions as if OLD had been moved to NEW."""
    g2 = copy.copy(g)
    g2.fileset = (g.fileset - {old}) | {new}
    g2.stems = {k: [c for c in v if c != old] for k, v in g.stems.items()}
    g2.stems.setdefault(new.rsplit("/", 1)[-1][:-3].casefold(), []).append(new)
    g2.stems = {k: v for k, v in g2.stems.items() if v}
    return g2


def relpath(target: str, base: str) -> str:
    return os.path.relpath(target, base or ".").replace(os.sep, "/")


def wiki_forms(inner_target: str, dst: str, had_path: bool, had_md: bool):
    stem = dst.rsplit("/", 1)[-1][:-3]
    name = stem + (".md" if had_md else "")
    path = dst if had_md else dst[:-3]
    return [path, name] if had_path else [name, path]


def split_alias(inner: str):
    """(target part, separator + alias part), the separator being | or the table-escaped \\|."""
    m = re.search(r"\\?\|", inner)
    return (inner[:m.start()], inner[m.start():]) if m else (inner, "")


def rewrite_text(g: G.Graph, g2: G.Graph, old: str, new: str, src_old: str, src_new: str, text: str):
    """[(start, end, replacement)] for the links of one file that must change, plus a count of links kept."""
    masked = mask(text)
    edits = []
    moved_here = src_old == old
    base_old = src_old.rsplit("/", 1)[0] if "/" in src_old else ""
    base_new = src_new.rsplit("/", 1)[0] if "/" in src_new else ""
    for m in G.WIKI.finditer(masked):
        inner = text[m.start(2):m.end(2)]
        tpart, rest = split_alias(inner)
        tgt = tpart.strip().rstrip("\\").strip()
        base, hsh = (tgt.split("#", 1) + [""])[:2] if "#" in tgt else (tgt, None)
        if not base:
            continue
        d_old = g.resolve_wiki(tgt, src_old)
        if not d_old:
            continue
        want = new if d_old == old else d_old
        if g2.resolve_wiki(tgt, src_new) == want:
            continue
        had_path = "/" in base.strip()
        had_md = base.strip().lower().endswith(".md")
        for cand in wiki_forms(tgt, want, had_path, had_md):
            if g2.resolve_wiki(cand + ("#" + hsh if hsh is not None else ""), src_new) == want:
                lead = tpart[:len(tpart) - len(tpart.lstrip())]
                trail = tpart[len(tpart.rstrip()):]
                edits.append((m.start(2), m.end(2), lead + cand + ("#" + hsh if hsh is not None else "") + trail + rest))
                break
        else:
            raise RuntimeError(f"{src_old}: no form of [[{tgt}]] resolves to {want}")
    for m in MDLINK_ANY.finditer(masked):
        href_raw = text[m.start(1):m.end(1)]
        angle = href_raw.startswith("<") and href_raw.endswith(">")
        href = href_raw[1:-1].strip() if angle else href_raw
        if not href or href.startswith("#") or G.SCHEME.match(href) or href.startswith("//"):
            continue
        frag = ""
        cut = re.search(r"[#?]", href)
        pathpart = urllib.parse.unquote(href[:cut.start()] if cut else href)
        if cut:
            frag = href[cut.start():]
        d_old = g.resolve_md(href_raw, src_old)
        rel_old = os.path.normpath(os.path.join(base_old, pathpart)).replace(os.sep, "/")
        if d_old:
            want = new if d_old == old else d_old
            if g2.resolve_md(href_raw, src_new) == want:
                continue
            kind = "note"
        elif moved_here and base_old != base_new and (g.vault / rel_old).is_file() and not G.SCHEME.match(pathpart):
            want, kind = rel_old, "file"                   # a link from the moved note to an image or another file
            if g2.resolve_md(href_raw, src_new) is not False and (g.vault / os.path.normpath(os.path.join(base_new, pathpart))).is_file():
                continue
        else:
            continue
        had_dot = pathpart.startswith("./") or pathpart.startswith("../")
        had_root = not had_dot and (g.vault / pathpart.lstrip("/")).exists() and not (g.vault / rel_old).exists()
        had_md = pathpart.lower().endswith(".md")
        bare = "." not in Path(pathpart).name
        cands = []
        rel = relpath(want, base_new)
        if had_root:
            cands.append(("/" if pathpart.startswith("/") else "") + want)
        if bare and kind == "note":
            cands.append(want[:-3].rsplit("/", 1)[-1])
        cands.append(("./" + rel) if had_dot and not rel.startswith("..") else rel)
        cands += [rel, want]
        done = False
        for c in cands:
            c2 = c if (had_md or kind == "file" or not c.endswith(".md")) else c[:-3]
            if kind == "note" and not bare and not had_md:
                c2 = c
            enc = urllib.parse.quote(c2, safe="/.-_~") if "%" in href else c2
            out = ("<" + enc + frag + ">") if (angle or (" " in enc)) else enc + frag
            ok_res = g2.resolve_md(out, src_new)
            if (kind == "note" and ok_res == want) or (kind == "file" and (g.vault / os.path.normpath(os.path.join(base_new, urllib.parse.unquote(enc)))).is_file()):
                edits.append((m.start(1), m.end(1), out))
                done = True
                break
        if not done:
            raise RuntimeError(f"{src_old}: no form of ({href}) resolves to {want}")
    return edits


def apply_edits(text: str, edits):
    for s, e, r in sorted(edits, reverse=True):
        text = text[:s] + r + text[e:]
    return text


def edge_set(g: G.Graph, rename=None):
    rename = rename or {}
    out = set()
    for src, lst in g.out.items():
        for dst, tgt, _line in lst:
            out.add((rename.get(src, src), rename.get(dst, dst) if dst else None, None if dst else tgt))
    return out


def git_dirty(vault: Path, paths):
    r = subprocess.run(["git", "-C", str(vault), "status", "--porcelain", "--"] + list(paths), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return ["(git status failed: " + r.stderr.strip()[:80] + ")"]
    return [ln[3:] for ln in r.stdout.splitlines() if ln.strip()]


def other_references(vault: Path, old: str, edited: set, limit: int = 8):
    """Files, other than the edited ones, that still hold the old path (any file) or the old name (non-note text files)."""
    stem = old.rsplit("/", 1)[-1][:-3]
    hits = []
    for dp, dn, fn in os.walk(vault):
        dn[:] = [d for d in dn if d not in V.SKIP_DIRS and d != "__pycache__"]
        for f in fn:
            p = Path(dp) / f
            rel = p.relative_to(vault).as_posix()
            if rel in edited or rel == old:
                continue
            try:
                if p.stat().st_size > 2_000_000:
                    continue
                t = p.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeDecodeError):
                continue
            n = t.count(old) + (0 if rel.endswith(".md") else t.count(stem))
            if n:
                hits.append((rel, n))
    return sorted(hits)[:limit], len(hits)


def run_apply(vault: Path, ops, dry=False):
    plan = json.dumps({"operations": ops})
    env = dict(os.environ, VAULT=str(vault))
    r = subprocess.run([sys.executable, str(APPLY), "--plan", "-"] + (["--dry-run"] if dry else []), input=plan, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"status": "invalid", "errors": [r.stderr.strip()[:200] or r.stdout.strip()[:200]]}


def plan_move(g: G.Graph, old: str, new: str):
    g2 = virtual_after(g, old, new)
    ops, counts = [], {}
    for src in g.files:
        src_new = new if src == old else src
        text = (g.vault / src).read_text(encoding="utf-8", errors="replace")
        if "[[" not in text and "](" not in text:
            continue
        ed = rewrite_text(g, g2, old, new, src, src_new, text)
        if ed:
            counts[src] = len(ed)
            ops.append({"path": src_new, "src": src, "text": text, "newContent": apply_edits(text, ed)})
    return ops, counts


def main(argv=None) -> int:
    V.force_utf8_stdio()
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if a else 2
    do_apply = "--apply" in a
    as_json = "--json" in a
    a = [x for x in a if x not in ("--apply", "--json")]
    if len(a) != 2:
        print("ERROR: give OLD and NEW", file=sys.stderr)
        return 2
    vault = V.VAULT
    g = G.Graph(vault)
    name = a[0].strip().strip('"')
    cands = [name] if name in g.fileset else ([name + ".md"] if name + ".md" in g.fileset else [])
    if not cands:
        base = (name[:-3] if name.lower().endswith(".md") else name)
        cands = [c for c in g.stems.get(base.rsplit("/", 1)[-1].casefold(), []) if "/" not in base or ("/" + c.casefold()).endswith("/" + base.casefold() + ".md")]
    if len(cands) != 1:
        print(f"ERROR: {name!r} names {len(cands)} notes" + (": " + ", ".join(sorted(cands)) if cands else ""), file=sys.stderr)
        return 1
    old = cands[0]
    new = a[1].strip().strip('"')
    if not new.lower().endswith(".md"):
        new += ".md"
    if "/" not in new:
        new = (old.rsplit("/", 1)[0] + "/" if "/" in old else "") + new
    if os.path.isabs(new) or ".." in new.split("/") or new.split("/")[0] in V.SKIP_DIRS:
        print("ERROR: NEW must be a path inside the vault", file=sys.stderr)
        return 1
    if new == old:
        print("ERROR: NEW equals OLD", file=sys.stderr)
        return 1
    if new in g.fileset or (vault / new).exists():
        print(f"ERROR: {new} already exists", file=sys.stderr)
        return 1
    try:
        ops, counts = plan_move(g, old, new)
    except RuntimeError as e:
        print("ERROR: " + str(e), file=sys.stderr)
        return 1
    edited = set(counts)
    refs, nrefs = other_references(vault, old, edited | {new})
    report = {"old": old, "new": new, "files_rewritten": len(counts), "links_rewritten": sum(counts.values()),
              "rewrites": {k: v for k, v in sorted(counts.items())}, "not_edited_references": {"files": nrefs, "first": refs}, "applied": False}
    if do_apply:
        touched = {old} | {o["src"] for o in ops}
        dirty = git_dirty(vault, touched)
        if dirty:
            print("ERROR: uncommitted changes in files this move touches (commit or stash first; rules.md: vault owner confirms commit and push): " + ", ".join(dirty[:5]), file=sys.stderr)
            return 1
        before = edge_set(g, {old: new})
        (vault / new).parent.mkdir(parents=True, exist_ok=True)
        os.rename(vault / old, vault / new)
        batch = [{"path": o["path"], "newContent": o["newContent"], "ifMatch": hashlib.sha256(o["text"].encode("utf-8")).hexdigest()} for o in ops]
        res = run_apply(vault, batch) if batch else {"status": "applied"}
        problem = None
        if res.get("status") != "applied":
            problem = "apply.py: " + res.get("status", "?") + " " + "; ".join(res.get("errors", []))[:200]
        else:
            after = edge_set(G.Graph(vault))
            if after != before:
                problem = f"link graph differs after the move: {len(before - after)} edges lost, {len(after - before)} gained"
        if problem:
            back = [{"path": o["path"], "newContent": o["text"]} for o in ops]
            if res.get("status") == "applied" and back:
                run_apply(vault, back)
            os.rename(vault / new, vault / old)
            print("ERROR: undone: " + problem, file=sys.stderr)
            return 1
        report["applied"] = True
    if as_json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"{'MOVED' if report['applied'] else 'WOULD MOVE'} {old} -> {new}")
        for k, v in report["rewrites"].items():
            print(f"  {v} link(s) in {k}")
        print(f"# {report['links_rewritten']} link(s) in {report['files_rewritten']} file(s)")
        if nrefs:
            print(f"# not edited: {nrefs} file(s) still mention the old path or name, first: " + ", ".join(f"{r} ({n})" for r, n in refs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
