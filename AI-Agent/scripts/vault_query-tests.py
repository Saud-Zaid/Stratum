#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""vault_query-tests.py - AD13 F1: Dataview-style queries without Obsidian.

Fixture vault for semantics; the live vault for two independent oracles (a raw-text scan of `area:` lines, and the
share of the vault's own dataview blocks that run). Mutation notes are in the AD13 F1 note."""
from __future__ import annotations


def _U(s):
    """ASCII-escaped test data, decoded at run time: a release holds no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")


import datetime as dt
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import vault_query as Q  # noqa: E402
import _vaultlib as V  # noqa: E402

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))
    print(f"[{'PASS' if cond else 'FAIL'}] {name} {'' if cond else got}".rstrip())


TODAY = dt.date(2026, 11, 15)
FILES = {
    "01-Projects/a.md": '---\nstatus: active\narea: "[[Area1]]"\ncreated: 2026-11-10\ntags:\n  - x\n  - exampleclub-event\ncontexts:\n  - exampleclub-tech-a\n  - other\n---\nbody\n',
    "01-Projects/b.md": '---\nstatus: done\narea: "[[Area1|alias]]"\ncreated: 2026-10-01\n---\n',
    "03-Resources/e.md": '---\nstatus: draft\narea: "[[02-Areas/Area1]]"\ncreated: 2026-11-10\n---\n',
    "01-Projects/sub/c.md": '---\nstatus: active\narea: "[[Area2]]"\ncreated: 2026-11-14\n---\n',
    "04-Archive/d.md": '---\nstatus: active\ntags:\n  - x\n---\n',
    "02-Areas/Area1.md": '---\nstatus: active\n---\n',
    "02-Areas/p1.md": '---\ncontexts:\n  - ai-community\n---\n',
    "02-Areas/p2.md": '---\ncontexts:\n  - exampleclub-tech-x\nconsent_on: 2026-01-01\n---\n',
    "02-Areas/p3.md": '---\ncontexts:\n  - other\n---\n',
    "02-Areas/p4.md": '---\ncontexts:\n  - exampleclub-tech-y\n---\n',
    ('02-Areas/' + _U(r"\u0639\u0631\u0628\u064a") + '-' + _U(r"\u0628") + '.md'): '---\nstatus: active\n---\n',
    ('02-Areas/' + _U(r"\u0639\u0631\u0628\u064a") + '-' + _U(r"\u0623") + '.md'): '---\nstatus: active\n---\n',
    "02-Areas/Tasks.md": '---\nowner: me\ntags:\n  - weekly\n---\n- [x] done one #report #impact-high \u2705 2026-11-12\n- [ ] open one #automation \U0001f4c5 2026-12-01\n- [-] cancelled one\n- [X] parent done\n  - [x] child done\n- [x] parent with open child\n  - [ ] open child\n```\n- [x] inside code fence\n```\n  * [x] star bullet #automation\nplain line [x] not a task\n',
    "02-Areas/Dash.md": '---\nstatus: active\n---\n```dataview\nLIST FROM "01-Projects" WHERE status = "active"\n```\n',
}
tmp = Path(tempfile.mkdtemp())
for rel, txt in FILES.items():
    f = tmp / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(txt, encoding="utf-8")
before = sorted((str(p.relative_to(tmp)), p.stat().st_mtime_ns) for p in tmp.rglob("*") if p.is_file())


def names(q, this=None):
    r = Q.run(q, tmp, this=this, today=TODAY)
    return [Q.fmt(row[0]).strip("[]") for row in r["rows"]]


try:
    ok("T01-list-folder", names('LIST FROM "01-Projects"') == ["a", "b", "c"], names('LIST FROM "01-Projects"'))
    ok("T02-where-equals-and-not-equals",
       names('LIST FROM "01-Projects" WHERE status = "active"') == ["a", "c"]
       and names('LIST FROM "01-Projects" WHERE status != "active"') == ["b"])
    ok("T03-missing-field-is-null", names('LIST FROM "02-Areas" WHERE status = "done"') == []
       and names('LIST FROM "01-Projects" WHERE nofield = null') == ["a", "b", "c"])
    ok("T04-link-equality-ignores-alias-and-uses-this",
       names('LIST FROM "01-Projects" WHERE area = link(this.file.link)', this="02-Areas/Area1.md") == ["a", "b"]
       and names('LIST FROM "03-Resources" WHERE area = link(this.file.link)', this="02-Areas/Area1.md") == ["e"])
    ok("T05-date-minus-duration",
       names('LIST FROM "01-Projects" WHERE created >= date(today) - dur(7 days)') == ["a", "c"]
       and names('LIST FROM "01-Projects" WHERE created >= date(today) - dur(60 days)') == ["a", "b", "c"]
       and names('LIST FROM "01-Projects" WHERE created >= date(today) - dur(30 days)') == ["a", "c"]
       and names('LIST FROM "01-Projects" WHERE created < date("2026-11-01")') == ["b"]
       and names('LIST FROM "01-Projects" WHERE created <= date("2026-11-10")') == ["a", "b"])
    ok("T06-sort-desc-asc-and-multi-key",
       names('LIST FROM "01-Projects" SORT created DESC') == ["c", "a", "b"]
       and names('LIST FROM "01-Projects" SORT created ASC') == ["b", "a", "c"]
       and names('LIST FROM "01-Projects" SORT status ASC, created DESC') == ["c", "a", "b"])
    ok("T07-limit", names('LIST FROM "01-Projects" SORT created DESC LIMIT 2') == ["c", "a"])
    ok("T08-or-and-minus-and-tag-sources",
       names('LIST FROM "01-Projects/sub" OR "04-Archive"') == ["c", "d"]
       and names('LIST FROM #x') == ["a", "d"]
       and names('LIST FROM "01-Projects" AND #x') == ["a"]
       and names('LIST FROM "01-Projects" AND -#x') == ["b", "c"]
       and names('LIST FROM "01-Projects/a.md"') == ["a"])
    ok("T09-contains-startswith-lower",
       names('LIST FROM "01-Projects" WHERE contains(tags, "exampleclub-event")') == ["a"]
       and names('LIST FROM "01-Projects" WHERE contains(file.name, "a")') == ["a"]
       and names('LIST FROM "01-Projects" WHERE startswith(lower(status), "do")') == ["b"])
    q = 'LIST FROM "02-Areas" WHERE any(map(contexts, (c) => startswith(c, "exampleclub-tech") OR c = "ai-community")) AND !consent_on'
    ok("T10-lambda-any-map-and-negation", names(q) == ["p1", "p4"], names(q))
    r = Q.run(('TABLE status AS "' + _U(r"\u0627\u0644\u062d\u0627\u0644\u0629") + '", created FROM "01-Projects" WHERE status = "active" SORT created ASC'), tmp, today=TODAY)
    ok("T11-table-columns-alias-and-render",
       r["columns"] == ["File", _U(r"\u0627\u0644\u062d\u0627\u0644\u0629"), "created"] and Q.render(r).split("\n")[1] == "[[a]]\tactive\t2026-11-10", Q.render(r))
    r = Q.run('TABLE WITHOUT ID status FROM "04-Archive"', tmp, today=TODAY)
    ok("T12-table-without-id", r["columns"] == ["status"] and r["rows"] == [["active"]])
    r = Q.run('LIST status FROM "01-Projects/sub"', tmp, today=TODAY)
    ok("T13-list-with-expression", Q.render(r) == "- [[c]]: active", Q.render(r))
    r = Q.run('TABLE ctx FROM "01-Projects" FLATTEN contexts AS ctx', tmp, today=TODAY)
    ok("T14-flatten-expands-lists-and-drops-empty", [x[1] for x in r["rows"]] == ["exampleclub-tech-a", "other"], r["rows"])
    ok("T15-sort-by-file-name-arabic", names(('LIST FROM "02-Areas" WHERE startswith(file.name, "' + _U(r"\u0639\u0631\u0628\u064a") + '") SORT file.name ASC')) == [(_U(r"\u0639\u0631\u0628\u064a") + '-' + _U(r"\u0623")), (_U(r"\u0639\u0631\u0628\u064a") + '-' + _U(r"\u0628"))])
    ok("T16-multiple-where-steps", names('LIST FROM "01-Projects" WHERE status = "active" WHERE created > date("2026-11-11")') == ["c"])
    bad = {}
    for label, qq in (("group", 'TABLE status FROM "01-Projects" GROUP BY status'),
                      ("lists", 'TABLE L.text FROM "01-Projects" FLATTEN file.lists AS L'), ("func", 'LIST FROM "01-Projects" WHERE magic(status)'),
                      ("linksrc", 'LIST FROM [[Area1]]')):
        try:
            Q.run(qq, tmp, today=TODAY)
            bad[label] = "ran"
        except Q.Unsupported:
            bad[label] = "unsupported"
        except Q.QueryError as exc:
            bad[label] = f"error {exc}"
    ok("T17-unsupported-features-say-so", set(bad.values()) == {"unsupported"}, bad)
    errs = []
    for qq in ("", "SELECT * FROM x", 'LIST FROM "a" WHERE (status = "x"', 'LIST FROM "a" WHERE status ~ 1'):
        try:
            Q.run(qq, tmp, today=TODAY)
            errs.append(("ran", qq))
        except Q.Unsupported:
            errs.append(("unsupported", qq))
        except Q.QueryError:
            pass
        except IndexError:
            errs.append(("crash", qq))
    ok("T18-malformed-queries-raise-query-error-not-crash", errs == [], errs)
    after = sorted((str(p.relative_to(tmp)), p.stat().st_mtime_ns) for p in tmp.rglob("*") if p.is_file())
    ok("T19-read-only", before == after)
    ok("T20-same-query-twice-same-result", names('LIST FROM "01-Projects" SORT created DESC') == names('LIST FROM "01-Projects" SORT created DESC'))

    def trows(q):
        return Q.run(q, tmp, today=TODAY)["rows"]
    done_texts = [r[3].split(" #")[0] for r in trows('TASK FROM "02-Areas/Tasks.md" WHERE completed')]
    ok("T26-task-completed-and-status-chars", done_texts == ["done one", "parent done", "child done", "parent with open child", "star bullet"], done_texts)
    ok("T27-task-fenced-code-and-prose-skipped",
       all("code fence" not in r[3] and "not a task" not in r[3] for r in trows('TASK FROM "02-Areas/Tasks.md"'))
       and len(trows('TASK FROM "02-Areas/Tasks.md"')) == 8, len(trows('TASK FROM "02-Areas/Tasks.md"')))
    ok("T28-task-tags-match-with-or-without-hash",
       [r[3][:8] for r in trows('TASK FROM "02-Areas/Tasks.md" WHERE contains(tags, "automation")')] == ["open one", "star bul"]
       and len(trows('TASK FROM "02-Areas/Tasks.md" WHERE contains(tags, "#automation")')) == 2
       and trows('TASK FROM "02-Areas/Tasks.md" WHERE contains(tags, "weekly")') == [])
    ok("T29-task-dates-and-fully-completed",
       [r[3][:8] for r in trows('TASK FROM "02-Areas/Tasks.md" WHERE completion = date("2026-11-12")')] == ["done one"]
       and [r[3][:8] for r in trows('TASK FROM "02-Areas/Tasks.md" WHERE due > date(today)')] == ["open one"]
       and [r[3] for r in trows('TASK FROM "02-Areas/Tasks.md" WHERE fullyCompleted')] == ["done one #report #impact-high \u2705 2026-11-12", "parent done", "child done", "star bullet #automation"],
       [r[3] for r in trows('TASK FROM "02-Areas/Tasks.md" WHERE fullyCompleted')])
    ok("T30-task-inherits-page-fields-and-render-groups-by-note",
       len(trows('TASK FROM "02-Areas" WHERE owner = "me" AND checked AND file.name = "Tasks"')) == 6
       and trows('TASK FROM "02-Areas/Tasks.md" WHERE status = "weekly"') == []
       and Q.render(Q.run('TASK FROM "02-Areas/Tasks.md" WHERE text = "parent done"', tmp, today=TODAY)) == "[[Tasks]]\n- [X] parent done")
    lines = [r[1] for r in trows('TASK FROM "02-Areas/Tasks.md" SORT line DESC LIMIT 2')]
    ok("T31-task-sort-and-limit", len(lines) == 2 and lines[0] > lines[1] and lines[0] == max(r[1] for r in trows('TASK FROM "02-Areas/Tasks.md"')), lines)

    env = {**os.environ, "VAULT": str(tmp)}
    p = subprocess.run([sys.executable, str(HERE / "vault_query.py"), 'LIST FROM "01-Projects" WHERE area = link(this.file.link)', "--this", "02-Areas/Area1.md"],
                       capture_output=True, text=True, env=env, encoding="utf-8")
    ok("T21-cli-this-end-to-end", p.returncode == 0 and p.stdout.strip().split("\n") == ["- [[a]]", "- [[b]]"], (p.returncode, p.stdout, p.stderr))
    p = subprocess.run([sys.executable, str(HERE / "vault_query.py"), "TABLE x FROM \"a\" GROUP BY x"], capture_output=True, text=True, env=env, encoding="utf-8")
    ok("T22-cli-unsupported-exit-2", p.returncode == 2 and "UNSUPPORTED" in p.stderr, (p.returncode, p.stderr))
    p = subprocess.run([sys.executable, str(HERE / "vault_query.py"), "--note", "02-Areas/Dash.md"], capture_output=True, text=True, env=env, encoding="utf-8")
    ok("T23-cli-note-runs-its-blocks", p.returncode == 0 and p.stdout.strip().split("\n") == ["- [[a]]", "- [[c]]"], (p.returncode, p.stdout, p.stderr))

    if (V.VAULT / "02-Areas" / "Current-Week.md").is_file():      # the live oracles read the mother vault; a release has none of these notes
        # live vault: independent oracle (raw-text scan of `area:` lines, markdown notes only) and block coverage
        area = ('02-Areas/' + _U(r"\u0625\u062f\u0627\u0631\u0629") + '-Second-Brain.md')
        got = sorted(Q.run('TABLE file.path FROM "01-Projects" WHERE area = link(this.file.link)', V.VAULT, this=area)["rows"], key=lambda r: r[1])
        got = [r[1] for r in got]
        stem = Path(area).stem
        import re
        raw = []
        for f in sorted((V.VAULT / "01-Projects").rglob("*.md")):
            head = f.read_text(encoding="utf-8", errors="replace").split("\n---", 1)[0]
            if re.search(rf'^area:\s*"?\[\[{re.escape(stem)}(\||\]\])', head, re.M):
                raw.append(f.relative_to(V.VAULT).as_posix())
        ok("T24-live-area-query-matches-raw-scan", got == sorted(raw) and len(got) > 0, (len(got), len(raw)))
        _wkdir = next((q.relative_to(V.VAULT).as_posix() for q in sorted((V.VAULT / "04-Archive").glob("*-" + _U(r"\u0623\u0633\u0627\u0628\u064a\u0639"))) if q.is_dir()), None)   # the real archive folder of the weekly notes; found by suffix so no owner name is written here
        if _wkdir is None:
            print("SKIP T32: no weekly archive folder in this vault")
        else:
            wk = [_wkdir, "02-Areas/Current-Week.md"]
            eng = len(Q.run(('TASK FROM "' + _wkdir + '" OR "02-Areas/Current-Week" WHERE completed'), V.VAULT)["rows"])
            raw_n = 0
            for f in sorted((V.VAULT / wk[0]).rglob("*.md")) + [V.VAULT / wk[1]]:
                fence = False
                for ln in f.read_text(encoding="utf-8", errors="replace").split("\n"):
                    if ln.lstrip().startswith("```"):
                        fence = not fence
                    elif not fence and re.match(r"^\s*[-*+]\s+\[[xX]\]\s+\S", ln):
                        raw_n += 1
            ok("T32-live-completed-tasks-match-raw-scan", eng == raw_n and eng > 0, (eng, raw_n))
        c = Q.coverage(V.VAULT)
        total = c["ok"] + len(c["unsupported"]) + len(c["error"])
        ok("T25-live-blocks-coverage-at-least-85-percent-no-crash", total > 0 and c["ok"] / total >= 0.85 and not c["error"], (c["ok"], total, c["error"][:2]))
    else:
        print("SKIP T24, T32, T25: the live-vault oracles need the mother vault notes")
finally:
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

P = sum(1 for _, c, _ in R if c)
print(f"VAULT_QUERY-TESTS {P}/{len(R)}")
for n, c, g in R:
    if not c:
        print(f"FAIL {n} :: {g}")
sys.exit(0 if P == len(R) else 1)
