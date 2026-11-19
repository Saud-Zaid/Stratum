#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""vault_graph-tests.py - AD13 F2: the note link graph without Obsidian.

Fixture vault for semantics (links of every kind with known answers); two oracles on the real vault: a second, independent
implementation of backlinks (a line-by-line fence state machine and plain regexes, sharing no code with vault_graph) over a
sample of real notes, and the tool run through its real entry point."""
from __future__ import annotations


def _U(s):
    """ASCII-escaped test data, decoded at run time: a release holds no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")


import json
import os
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vault_graph as G  # noqa: E402

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {'' if cond else got}".rstrip())


FILES = {
    "A.md": '---\narea: "[[F]]"\ntags: [x]\n---\n# A\n\nplain [[B]] and [[B|alias]] and [[B#Heading]] and [[b]] again\n'
            "path form [[folder/C]] and embed ![[D]]\n"
            "| table | [[E\\|e]] |\n"
            "```\n[[Zfence]]\n```\n"
            "and `[[Zspan]]` and a [t](./G.md) and [u](folder/C.md) and [v](H) and [w](https://example.com/x.md)\n"
            "![img](pic.png) [[pic.png]] [[#Heading]] [[A]] [[Missing]] [[ghost.png]]\n",
    "B.md": "# B\n\nback to [[A]]\n",
    "D.md": "# D\n",
    "E.md": "# E\n",
    "F.md": "# F\n",
    "G.md": "# G\n",
    "H.md": "# H\n",
    "folder/C.md": "# C\n\nup to [[A]] and [t](../B.md)\n",
    "dup.md": "# dup root\n",
    "sub/dup.md": "# dup sub\n",
    "sub/n.md": "# n\n\n[[dup]]\n",
    "m.md": "# m\n\n[[dup]]\n",
    ('arabic/' + _U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + '.md'): ('# n\n\n[[' + _U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + '-' + _U(r"\u0623\u062e\u0631\u0649") + ']]\n'),
    ('arabic/' + _U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + '-' + _U(r"\u0623\u062e\u0631\u0649") + '.md'): "# other\n",
    "orphan.md": "# alone\n",
    "pic.png": "x",
}
tmp = Path(tempfile.mkdtemp(prefix="vgraph-"))
for rel, txt in FILES.items():
    f = tmp / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(txt, encoding="utf-8")
before = sorted((str(p.relative_to(tmp)), p.stat().st_mtime_ns) for p in tmp.rglob("*") if p.is_file())
g = G.Graph(tmp)
ins = lambda n: sorted({s for s, _l, _c in g.inn.get(n, [])})
outs = lambda n: sorted({d for d, _t, _l in g.out.get(n, []) if d})

ok("T01-wikilink-forms-all-reach-b-as-one-edge-per-line", ins("B.md") == ["A.md", "folder/C.md"] and [l for s, l, c in g.inn["B.md"] if s == "A.md"] == [7], g.inn.get("B.md"))
ok("T02-case-insensitive-and-alias-and-heading", sum(1 for s, _l, c in g.inn["B.md"] if s == "A.md") == 1, g.inn.get("B.md"))
ok("T03-outlinks-of-a", outs("A.md") == ["B.md", "D.md", "E.md", "F.md", "G.md", "H.md", "folder/C.md"], outs("A.md"))
ok("T04-path-form-and-inline-links", "A.md" in ins("folder/C.md") and "A.md" in ins("G.md") and "A.md" in ins("H.md"))
ok("T05-frontmatter-link-counts", "A.md" in ins("F.md") and any(l <= 4 for s, l, c in g.inn["F.md"] if s == "A.md"), g.inn.get("F.md"))
ok("T06-escaped-alias-bar-in-a-table-cell", "A.md" in ins("E.md"), g.inn.get("E.md"))
ok("T07-code-fences-and-spans-ignored", all(d != "Zfence.md" and d != "Zspan.md" for d in outs("A.md")) and not any("Zfence" in str(t) or "Zspan" in str(t) for _d, t, _l in g.out["A.md"]))
unres = sorted(t for d, t, _l in g.out["A.md"] if d is None)
ok("T08-unresolved-listed-existing-assets-and-self-links-are-not", unres == ["Missing", "ghost.png"], unres)
ok("T09-no-self-edge-and-heading-only-link", "A.md" not in outs("A.md"))
ok("T10-line-numbers-are-file-lines", {l for s, l, c in g.inn["D.md"] if s == "A.md"} == {8}, g.inn.get("D.md"))
ok("T11-duplicate-names-resolve-like-obsidian", ins("sub/dup.md") == ["sub/n.md"] and ins("dup.md") == ["m.md"], (ins("dup.md"), ins("sub/dup.md")))
ok("T12-arabic-names", ins(('arabic/' + _U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + '-' + _U(r"\u0623\u062e\u0631\u0649") + '.md')) == [('arabic/' + _U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + '.md')])
ok("T13-orphans", sorted(g.orphans()) == sorted(["m.md", "orphan.md", "sub/n.md", ("arabic/" + _U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + ".md")]), g.orphans())
ok("T14-orphan-scope", g.orphans("sub/") == [] or all(o.startswith("sub/") for o in g.orphans("sub/")))
ok("T15-unreciprocated", g.unreciprocated("A.md") == ["D.md", "E.md", "F.md", "G.md", "H.md"], g.unreciprocated("A.md"))
ok("T16-depth-two-walk-nearest-first", g.walk("A.md", "in", 2)[0] == (1, "B.md") and all(d in (1, 2) for d, _p in g.walk("A.md", "in", 2)) and all(p != "A.md" for _d, p in g.walk("A.md", "out", 3)), g.walk("A.md", "in", 2))
ok("T17-depth-reaches-through-a-chain", (2, "A.md") not in g.walk("A.md", "out", 2) and any(p == "D.md" and d == 1 for d, p in g.walk("A.md", "out", 2)))
ok("T18-find-note-by-name-path-and-case", g.find_note("a") == "A.md" and g.find_note("folder/C") == "folder/C.md" and g.find_note("folder/C.md") == "folder/C.md" and g.find_note("nope") is None)

env = {**os.environ, "VAULT": str(tmp)}
run = lambda *a: subprocess.run([sys.executable, str(HERE / "vault_graph.py"), *a], capture_output=True, text=True, env=env, encoding="utf-8")
p = run("in", "B", "--json")
j = json.loads(p.stdout) if p.returncode == 0 else {}
ok("T19-cli-in-json", p.returncode == 0 and j["note"] == "B.md" and [r["path"] for r in j["in"]] == ["A.md", "folder/C.md"] and j["in"][0]["links"] >= 1, p.stdout[:200])
p = run("out", "A")
ok("T20-cli-out-text-lists-unresolved-with-a-question-mark", p.returncode == 0 and "? Missing" in p.stdout and "B.md\t" in p.stdout, p.stdout[:200])
p = run("orphans")
ok("T21-cli-orphans-summary-line", p.returncode == 0 and p.stdout.strip().endswith("notes") and "orphan.md" in p.stdout, p.stdout[-120:])
p = run("in", "nosuchnote")
ok("T22-cli-unknown-note-exit-2", p.returncode == 2 and "no note named" in p.stderr)
p = run("frobnicate")
ok("T23-cli-unknown-command-exit-2", p.returncode == 2)
p = run("in", "B", "--depth", "x")
ok("T24-cli-bad-depth-exit-2", p.returncode == 2)
after = sorted((str(q.relative_to(tmp)), q.stat().st_mtime_ns) for q in tmp.rglob("*") if q.is_file())
ok("T25-read-only", before == after)

# real vault, independent oracle for backlinks
real = G.Graph()
root = str(real.vault)


def indep_sources(stem_cf, target):
    pw = re.compile(r"\[\[\s*(?:[^\]|#\n]*/)?" + re.escape(stem_cf) + r"(?:\.md)?\s*(?:#[^\]|\n]*)?(?:\\?\|[^\]\n]*)?\]\]", re.I)
    pm = re.compile(r"\]\(\s*<?[^)\s>]*?" + re.escape(stem_cf) + r"(?:\.md)?(?:#[^)\s>]*)?>?\s*\)", re.I)
    found = set()
    for rel in real.files:
        if rel == target:
            continue
        fence = False
        try:
            lines = open(os.path.join(root, rel), encoding="utf-8", errors="replace").readlines()
        except FileNotFoundError:   # a parallel test removed its own probe note from the tree between the listing and this read
            continue
        for ln in lines:
            s = ln.lstrip()
            if s.startswith("```") or s.startswith("~~~"):
                fence = not fence
                continue
            if fence:
                continue
            ln2 = re.sub(r"`[^`]*`", "", ln)
            if pw.search(ln2) or pm.search(ln2):
                found.add(rel)
                break
    return found


cands = sorted(r for r in real.files if len(real.stems[r.rsplit("/", 1)[-1][:-3].casefold()]) == 1 and not r.startswith(("card-template/", "AI-Agent/release-overlay/")))
random.Random(11).shuffle(cands)
sample = [c for c in cands if real.inn.get(c)][:9] + [c for c in cands if not real.inn.get(c)][:3]
bad = []
for note in sample:
    tool = {s for s, _l, _c in real.inn.get(note, []) if s != note}
    ind = indep_sources(note.rsplit("/", 1)[-1][:-3].casefold(), note)
    if tool != ind:
        bad.append((note[-40:], sorted(tool - ind)[:2], sorted(ind - tool)[:2]))
ok("T26-live-backlinks-equal-an-independent-implementation-on-a-sample", len(sample) == 12 and not bad, bad)
t0 = __import__("time").time()
G.Graph()
ok("T27-live-graph-builds-in-a-few-seconds", __import__("time").time() - t0 < 10, __import__("time").time() - t0)


# --- stdlib only (AD13 Stratum): without the pinned libraries the tool still runs; its fallback values equal _vaultlib's
import re as _re2
import subprocess as _sp


def _blocked(tool, vault, *args):
    code = ("import sys, runpy\nfor m in ('yaml', 'markdown_it', 'mdit_py_plugins', 'mdurl'): sys.modules[m] = None\n"
            f"sys.argv = [{str(HERE / tool)!r}] + {list(args)!r}\nrunpy.run_path({str(HERE / tool)!r}, run_name='__main__')")
    return _sp.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, VAULT=str(vault)))


_fb = _re2.search(r"SKIP_DIRS = (\{[^}]*\})", (HERE / "vault_graph.py").read_text(encoding="utf-8"))
import _vaultlib as _VL
ok("fallback: SKIP_DIRS equals _vaultlib's", _fb is not None and eval(_fb.group(1)) == set(_VL.SKIP_DIRS), _fb and _fb.group(1))
_rg = _blocked("vault_graph.py", tmp, "in", "B")
ok("no pinned libraries: vault_graph answers a backlink query", _rg.returncode == 0 and "A.md" in _rg.stdout, (_rg.returncode, _rg.stderr[-200:]))
_ro = _blocked("vault_graph.py", tmp, "orphans")
ok("no pinned libraries: vault_graph lists orphans", _ro.returncode == 0 and "orphan.md" in _ro.stdout, (_ro.returncode, _ro.stderr[-200:]))

P = sum(1 for _, c, _ in R if c)
print(f"VAULT_GRAPH-TESTS {P}/{len(R)}")
for n, c, gt in R:
    if not c:
        print(f"FAIL {n} :: {gt}")
import shutil
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(0 if P == len(R) else 1)
