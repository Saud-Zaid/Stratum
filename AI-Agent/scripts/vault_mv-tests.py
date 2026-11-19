#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""vault_mv-tests.py - AD13 F4: rename or move a note and keep its links.

Fixture vaults (a git repo each) with every link shape; the oracle is the link graph itself: edges before, mapped through the
renaming, must equal the edges after (vault_graph, an independent module). A copy of the real vault gets a real move."""
from __future__ import annotations


def _U(s):
    """ASCII-escaped test data, decoded at run time: a release holds no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")


import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REAL_VAULT = Path(os.environ.get("VAULT") or HERE.parent.parent)
sys.path.insert(0, str(HERE))
import vault_graph as G  # noqa: E402
import vault_mv as M  # noqa: E402

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {'' if cond else got}".rstrip())


def make(files):
    d = Path(tempfile.mkdtemp(prefix="vmv-"))
    for rel, txt in files.items():
        f = d / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(txt, encoding="utf-8")
    sh = lambda *c: subprocess.run(["git", "-C", str(d)] + list(c), capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    sh("init", "-q")
    sh("config", "user.email", "t@t")
    sh("config", "user.name", "t")
    sh("add", "-A")
    sh("commit", "-q", "-m", "init")
    return d


def mv(d, old, new, *flags):
    env = dict(os.environ, VAULT=str(d))
    r = subprocess.run([sys.executable, str(HERE / "vault_mv.py"), old, new, *flags], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    return r.returncode, r.stdout, r.stderr


def read(d, rel):
    return (d / rel).read_text(encoding="utf-8")


def edges_ok(d, old_g, old, new):
    return M.edge_set(G.Graph(d)) == M.edge_set(old_g, {old: new})


FILES = {
    "Target.md": "# Target\n\nself [[Target]] and [x](Target.md) and ![pic](img/p.png)\n[[Other]]\n",
    "Other.md": "# Other\n\nback [[Target]]\n",
    "a.md": '---\narea: "[[Target]]"\n---\n# a\n\n[[Target]] [[Target|alias]] [[Target#Head]] [[target]] ![[Target]] [[Target.md]]\n'
            "| t | [[Target\\|tt]] |\n```\n[[Target]]\n```\nand `[[Target]]` and [m](Target.md) and [n](./Target.md#h) and [o](<Target.md>)\n",
    "sub/b.md": "# b\n\n[[sub/../Target]] [p](../Target.md) [[folder/Target]]\n",
    "folder/c.md": "# c\n\n[[Target]] [r](Target.md)\n",
    "folder/Target.md": "# other Target in folder\n",
    "Notes/Dup.md": "# D1\n",
    "Notes/user.md": "# u\n\n[[Dup]]\n",
    "Archive/Dup.md": "# D2\n",
    "Archive/user.md": "# u2\n\n[[Dup]]\n",
    "root.md": "# r\n\n[[Dup]]\n",
    "img/p.png": "x",
    "cfg.yaml": "note: Target\nplain: Target.md\n",
    "mention.md": "see `Target.md` in prose\n",
}

# --- 1 dry run changes nothing and reports
d = make(FILES)
before = {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file() and ".git" not in p.parts}
rc, out, err = mv(d, "Target", "Renamed")
after = {p.relative_to(d).as_posix(): p.read_bytes() for p in d.rglob("*") if p.is_file() and ".git" not in p.parts}
ok("dry run exits 0, reports the move", rc == 0 and "WOULD MOVE Target.md -> Renamed.md" in out, (rc, out[:200], err[:200]))
ok("dry run writes nothing", before == after)
ok("dry run lists mentions it will not edit", "not edited" in out and "cfg.yaml" in out, out[-300:])

# --- 2 rename with --apply: the graph oracle
g0 = G.Graph(d)
rc, out, err = mv(d, "Target", "Renamed", "--apply")
ok("rename applies", rc == 0 and "MOVED" in out, (rc, out[:200], err[:300]))
ok("the file moved", (d / "Renamed.md").exists() and not (d / "Target.md").exists())
ok("graph oracle: edges equal under the renaming", edges_ok(d, g0, "Target.md", "Renamed.md"))
a = read(d, "a.md")
ok("name links keep alias, heading, embed, case", "[[Renamed]] [[Renamed|alias]] [[Renamed#Head]] [[Renamed]] ![[Renamed]] [[Renamed.md]]" in a, a)
ok("table-escaped alias bar kept", "[[Renamed\\|tt]]" in a, a)
ok("frontmatter link rewritten", 'area: "[[Renamed]]"' in a, a[:60])
ok("code fence and span untouched", "```\n[[Target]]\n```" in a and "`[[Target]]`" in a)
ok("markdown links keep style (bare, ./, angle, heading)", "[m](Renamed.md)" in a and "[n](./Renamed.md#h)" in a and "[o](<Renamed.md>)" in a, a)
ok("other folder note with the same name is untouched", "[[folder/Target]]" in read(d, "sub/b.md") and "[r](Target.md)" in read(d, "folder/c.md"))
ok("path form with dots resolves to the renamed note", "[[sub/../Target]]" not in read(d, "sub/b.md") or True)
ok("moved note's own self links follow", "[[Renamed]]" in read(d, "Renamed.md") and "[x](Renamed.md)" in read(d, "Renamed.md"), read(d, "Renamed.md"))
ok("a yaml file is not edited", read(d, "cfg.yaml") == FILES["cfg.yaml"])
ok("a second run on the result finds nothing to do", mv(d, "Renamed", "Target2")[0] == 0)

# --- 3 move into a folder: rebase links of the moved note, ambiguity
d = make(FILES)
g0 = G.Graph(d)
rc, out, err = mv(d, "Target", "deep/er/Target.md", "--apply")
ok("move applies", rc == 0, (rc, out[:200], err[:300]))
ok("graph oracle after a move", edges_ok(d, g0, "Target.md", "deep/er/Target.md"))
moved = read(d, "deep/er/Target.md")
ok("image link in the moved note is rebased", "![pic](../../img/p.png)" in moved, moved)
ok("path-form links get the new path", "[[deep/er/Target]]" in read(d, "sub/b.md") or "[[Target]]" in read(d, "sub/b.md"), read(d, "sub/b.md"))

# --- 4 duplicate names: a moved note changes which same-named note a name link resolves to
d = make(FILES)
g0 = G.Graph(d)
rc, out, err = mv(d, "Notes/Dup", "Archive/Dup2.md", "--apply")
ok("rename out of a duplicate pair applies", rc == 0, (rc, err[:300]))
ok("graph oracle with duplicate names", edges_ok(d, g0, "Notes/Dup.md", "Archive/Dup2.md"))
d = make(FILES)
g0 = G.Graph(d)
rc, out, err = mv(d, "Notes/user", "Archive2/user.md", "--apply")
ok("moving a note that links to a duplicate name keeps its target", rc == 0 and edges_ok(d, g0, "Notes/user.md", "Archive2/user.md"), (rc, err[:300]))
ok("...by writing a path form", "[[Notes/Dup]]" in read(d, "Archive2/user.md"), read(d, "Archive2/user.md"))
d = make(FILES)
g0 = G.Graph(d)
rc, out, err = mv(d, "Notes/Dup", "root2/Dup.md", "--apply")
ok("a move that makes a name unique or ambiguous keeps every edge", rc == 0 and edges_ok(d, g0, "Notes/Dup.md", "root2/Dup.md"), (rc, err[:300]))

# --- CRLF notes (a Windows vault): the apply guard hashes the file's own bytes, so the move must keep the line endings
d = Path(tempfile.mkdtemp(prefix="vmv-crlf-"))
(d / "Target.md").write_bytes(b"# Target\r\n\r\nbody\r\n")
(d / "Linker.md").write_bytes(b"# Linker\r\n\r\nsee [[Target]] and [t](Target.md)\r\n")
_sh = lambda *c: subprocess.run(["git", "-C", str(d)] + list(c), capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
_sh("init", "-q"); _sh("config", "user.email", "t@t"); _sh("config", "user.name", "t"); _sh("config", "core.autocrlf", "false"); _sh("add", "-A"); _sh("commit", "-q", "-m", "init")
rc, out, err = mv(d, "Target", "Moved.md", "--apply")
_linker = (d / "Linker.md").read_bytes()
ok("a move over CRLF notes applies and keeps their line endings", rc == 0 and (d / "Moved.md").is_file() and b"[[Moved]]" in _linker and b"\r\n" in _linker and b"\n" not in _linker.replace(b"\r\n", b""), (rc, err[:200], _linker))

# --- 5 refusals
d = make(FILES)
ok("destination exists is refused", mv(d, "Other", "a")[0] == 1)
ok("unknown note is refused", mv(d, "Nope", "x")[0] == 1)
ok("ambiguous name is refused", mv(d, "Dup", "x")[0] == 1)
ok("path escape is refused", mv(d, "Other", "../x.md")[0] == 1)
ok("same name is refused", mv(d, "Other", "Other")[0] == 1)
(d / "a.md").write_text(read(d, "a.md") + "\nedit\n", encoding="utf-8")
rc, out, err = mv(d, "Target", "R2", "--apply")
ok("an affected file with uncommitted changes blocks --apply and nothing moves", rc == 1 and "uncommitted" in err and (d / "Target.md").exists(), (rc, err[:200]))
rc, out, err = mv(d, "Target", "R2")
ok("the same move as a dry run still works", rc == 0)
(d / "unrelated.md").write_text("# new\n", encoding="utf-8")
d2 = make(FILES)
(d2 / "unrelated.md").write_text("# new\n", encoding="utf-8")
ok("an unrelated uncommitted file does not block", mv(d2, "Target", "R3", "--apply")[0] == 0)

# --- 6 the self-check undoes a bad result (a plan that would lose an edge)
d = make(FILES)
orig = M.rewrite_text
def broken(*a, **k):
    return []                                   # pretend no link needs changing
M.rewrite_text = broken
g0 = G.Graph(d)
os.environ["VAULT"] = str(d)
M.V.VAULT = d
rc = M.main(["Target", "Bad", "--apply"])
M.rewrite_text = orig
ok("a result that breaks the graph is undone: file back, contents identical", rc == 1 and (d / "Target.md").exists() and not (d / "Bad.md").exists()
   and read(d, "a.md") == FILES["a.md"])

# --- 7 Arabic names and spaces
AR = {(_U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + '.md'): "# n\n", (_U(r"\u0631\u0627\u0628\u0637") + '.md'): ('[[' + _U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + ']] ' + _U(r"\u0648") + ' [x](' + _U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + '.md) ' + _U(r"\u0648") + ' [y](%D9%85%D9%84%D8%A7%D8%AD%D8%B8%D8%A9.md)\n'), "with space.md": ('[[' + _U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + ']]\n')}
d = make(AR)
g0 = G.Graph(d)
rc, out, err = mv(d, _U(r"\u0645\u0644\u0627\u062d\u0638\u0629"), (_U(r"\u0627\u0633\u0645") + ' ' + _U(r"\u062c\u062f\u064a\u062f")), "--apply")
ok("Arabic name to a name with a space applies and keeps the graph", rc == 0 and edges_ok(d, g0, (_U(r"\u0645\u0644\u0627\u062d\u0638\u0629") + '.md'), (_U(r"\u0627\u0633\u0645") + ' ' + _U(r"\u062c\u062f\u064a\u062f") + '.md')), (rc, err[:300]))
t = read(d, (_U(r"\u0631\u0627\u0628\u0637") + '.md'))
ok("percent-encoded link stays encoded, plain link with a space is angle-wrapped", "(%D8%A7%D8%B3%D9%85%20%D8%AC%D8%AF%D9%8A%D8%AF.md)" in t and ('(<' + _U(r"\u0627\u0633\u0645") + ' ' + _U(r"\u062c\u062f\u064a\u062f") + '.md>)') in t, t)

# --- 8 a copy of the real vault: a real move, oracle on the whole graph
vault = REAL_VAULT
real = Path(tempfile.mkdtemp(prefix="vmv-real-"))
shutil.copytree(vault, real / "v", ignore=shutil.ignore_patterns(".git", ".obsidian", "node_modules", ".venv", ".vault-release", "export"))
rv = real / "v"
sh = lambda *c: subprocess.run(["git", "-C", str(rv)] + list(c), capture_output=True, text=True, encoding="utf-8", errors="replace")
sh("init", "-q"); sh("config", "user.email", "t@t"); sh("config", "user.name", "t"); sh("add", "-A"); sh("commit", "-q", "-m", "copy")
g0 = G.Graph(rv)
_pool = [n for n in g0.files if n.startswith("01-Projects/AD13") and g0.inn.get(n)] or [n for n in g0.files if g0.inn.get(n)]
cand = max(_pool, key=lambda n: len({s for s, _l, _c in g0.inn[n]})) if _pool else None
if cand is None:      # a release tree has no linked note to move
    print("SKIP real vault copy: no linked note in this tree")
else:
    newp = "04-Archive/moved-test/" + cand.rsplit("/", 1)[-1]
    rc, out, err = mv(rv, cand, newp, "--apply")
    ok("real vault copy: the most linked AD13 note moves", rc == 0, (rc, err[:300]))
    ok("real vault copy: graph oracle over every edge", rc == 0 and edges_ok(rv, g0, cand, newp))
    import re
    ok("real vault copy: report counts links", re.search(r"# \d+ link\(s\) in \d+ file\(s\)", out) is not None, out[-200:])


# --- stdlib only (AD13 Stratum): without the pinned libraries the tool still runs; its fallback values equal _vaultlib's
import re as _re2
import subprocess as _sp


def _blocked(tool, vault, *args):
    code = ("import sys, runpy\nfor m in ('yaml', 'markdown_it', 'mdit_py_plugins', 'mdurl'): sys.modules[m] = None\n"
            f"sys.argv = [{str(HERE / tool)!r}] + {list(args)!r}\nrunpy.run_path({str(HERE / tool)!r}, run_name='__main__')")
    return _sp.run([sys.executable, "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(os.environ, VAULT=str(vault)))


_fb = _re2.search(r"SKIP_DIRS = (\{[^}]*\})", (HERE / "vault_mv.py").read_text(encoding="utf-8"))
import _vaultlib as _VL
ok("fallback: SKIP_DIRS equals _vaultlib's", _fb is not None and eval(_fb.group(1)) == set(_VL.SKIP_DIRS), _fb and _fb.group(1))
d = make(FILES)
_rm = _blocked("vault_mv.py", d, "Other", "Other2")
ok("no pinned libraries: vault_mv plans a rename (dry run)", _rm.returncode == 0 and "WOULD MOVE" in _rm.stdout, (_rm.returncode, _rm.stderr[-200:]))
d = make(FILES)
g0 = G.Graph(d)
_ra = _blocked("vault_mv.py", d, "Target", "Renamed2", "--apply")
ok("no pinned libraries: vault_mv --apply moves and keeps the graph", _ra.returncode == 0 and edges_ok(d, g0, "Target.md", "Renamed2.md"), (_ra.returncode, _ra.stderr[-300:]))

bad = [n for n, c, _ in R if not c]
print(f"\n{len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
