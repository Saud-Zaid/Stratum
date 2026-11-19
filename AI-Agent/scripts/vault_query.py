#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""vault_query.py - Dataview-style LIST and TABLE queries over note frontmatter, without Obsidian (AD13 F1).

usage:
  vault_query.py "<query>" [--this NOTE] [--json]     run one query; `this` is a note path relative to the vault
  vault_query.py --note NOTE [--block N] [--json]      run the dataview blocks of a note (this = that note)
  vault_query.py --coverage                            run every dataview block in the vault, report what is supported

Supported: LIST [expr] and TABLE [WITHOUT ID] cols [AS alias]; FROM "folder", #tag, - and ( ) with AND/OR;
WHERE; SORT [ASC|DESC]; LIMIT; FLATTEN expr AS name; comparisons, arithmetic, date(today) - dur(7 days),
link(), contains/startswith/endswith/lower/upper/length/default/choice/any/all/map/filter with (x) => lambdas.
TASK FROM ... WHERE ... SORT lists the checkbox lines (`- [x] text`) of the matched notes, grouped by note; a task has
text, status, checked, completed, fullyCompleted, line, tags (its own inline #tags; "automation" matches #automation) and
the emoji dates due, completion, created, start, scheduled; page fields are inherited. Fenced code is skipped.
Not supported (exit 2 with a clear message): GROUP BY, file.lists/tasks/outlinks, inline #tags on LIST/TABLE rows (frontmatter tags only).
Read-only; month and year durations are 30 and 365 days.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _vaultlib as V  # noqa: E402

CLAUSES = {"TABLE", "LIST", "TASK", "FROM", "WHERE", "SORT", "LIMIT", "FLATTEN", "GROUP"}
FUNCS = {"date", "link", "contains", "icontains", "startswith", "endswith", "lower", "upper", "length", "default",
         "choice", "any", "all", "map", "filter"}
UNSUPPORTED_FILE_FIELDS = {"lists", "tasks", "outlinks", "inlinks", "etags", "frontmatter"}
_TOK = re.compile(r'''\s*(?:
    (?P<str>"(?:[^"\\]|\\.)*")|
    (?P<link>\[\[[^\]]*\]\])|
    (?P<num>\d+(?:\.\d+)?)|
    (?P<tag>\#[\w/\-]+)|
    (?P<op>=>|!=|>=|<=|[=<>+\-*/!(),])|
    (?P<id>[^\W\d]\w*(?:\.[^\W\d]\w*)*)
)''', re.X)


class QueryError(Exception):
    pass


class Unsupported(QueryError):
    pass


class Tag(str):
    """An inline tag as Dataview stores it (`#automation`); equal to its name with or without the hash."""
    def __eq__(self, other):
        return isinstance(other, str) and str.lstrip(self, "#") == other.lstrip("#")

    def __hash__(self):
        return hash(str.lstrip(self, "#"))


class Link:
    def __init__(self, target: str, text: str | None = None):
        self.target, self.text = target, text

    def key(self) -> str:
        t = self.target.split("#")[0].split("/")[-1]
        return t[:-3] if t.endswith(".md") else t

    def __repr__(self):
        return f"[[{self.target}]]"


def tokenize(src: str) -> list:
    out, pos = [], 0
    while pos < len(src):
        if not src[pos:].strip():
            break
        m = _TOK.match(src, pos)
        if not m or m.end() == pos:
            raise QueryError(f"cannot read the query near: {src[pos:pos + 20]!r}")
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


# --- parser: expressions become nested tuples ---------------------------------------------------------------------
class Parser:
    def __init__(self, toks: list):
        self.t, self.i = toks, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def is_kw(self, word, k=0):
        kind, text = self.peek(k)
        return kind == "id" and text.lower() == word

    def is_op(self, op, k=0):
        return self.peek(k) == ("op", op)

    def expr(self):
        left = self.and_()
        while self.is_kw("or"):
            self.take()
            left = ("or", left, self.and_())
        return left

    def and_(self):
        left = self.cmp()
        while self.is_kw("and"):
            self.take()
            left = ("and", left, self.cmp())
        return left

    def cmp(self):
        left = self.add()
        kind, text = self.peek()
        if kind == "op" and text in ("=", "!=", "<", ">", "<=", ">="):
            self.take()
            left = ("cmp", text, left, self.add())
        return left

    def add(self):
        left = self.mul()
        while self.peek()[0] == "op" and self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            left = ("arith", op, left, self.mul())
        return left

    def mul(self):
        left = self.unary()
        while self.peek()[0] == "op" and self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            left = ("arith", op, left, self.unary())
        return left

    def unary(self):
        if self.is_op("!"):
            self.take()
            return ("not", self.unary())
        if self.is_op("-"):
            self.take()
            return ("neg", self.unary())
        return self.primary()

    def primary(self):
        kind, text = self.take()
        if kind == "str":
            return ("const", json.loads(text))
        if kind == "num":
            return ("const", float(text) if "." in text else int(text))
        if kind == "link":
            inner = text[2:-2]
            return ("const", Link(inner.split("|")[0], inner.split("|")[1] if "|" in inner else None))
        if kind == "tag":
            return ("tag", text[1:])
        if kind == "op" and text == "(":
            if self.peek()[0] == "id" and self.is_op(")", 1) and self.is_op("=>", 2):
                name = self.take()[1]
                self.take()
                self.take()
                return ("lambda", name, self.expr_until_close())
            node = self.expr()
            self.expect(")")
            return node
        if kind == "id":
            low = text.lower()
            if low in ("true", "false"):
                return ("const", low == "true")
            if low == "null":
                return ("const", None)
            if low == "dur" and self.is_op("("):
                self.take()
                parts = []
                while not self.is_op(")"):
                    if self.peek()[0] is None:
                        raise QueryError("dur( is not closed")
                    parts.append(self.take()[1])
                self.take()
                return ("const", parse_dur(" ".join(parts)))
            if self.is_op("("):
                self.take()
                args = []
                while not self.is_op(")"):
                    args.append(self.expr())
                    if self.is_op(","):
                        self.take()
                    elif not self.is_op(")"):
                        raise QueryError(f"bad arguments for {text}(")
                self.take()
                if low not in FUNCS:
                    raise Unsupported(f"function {text}() is not supported")
                return ("call", low, args)
            bits = text.split(".")
            if (bits[0] == "file" and len(bits) > 1 and bits[1] in UNSUPPORTED_FILE_FIELDS) or bits[0] == "rows":
                raise Unsupported(f"{text} is not supported")
            return ("field", text)
        raise QueryError(f"unexpected {text!r}")

    def expr_until_close(self):
        node = self.expr()
        return node

    def expect(self, op):
        if not self.is_op(op):
            raise QueryError(f"expected {op!r}")
        self.take()


def parse_dur(text: str) -> dt.timedelta:
    total = dt.timedelta()
    for n, unit in re.findall(r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)", text):
        u = unit.lower().rstrip("s")
        mult = {"second": 1 / 86400, "sec": 1 / 86400, "minute": 1 / 1440, "min": 1 / 1440, "hour": 1 / 24, "h": 1 / 24,
                "day": 1, "d": 1, "week": 7, "w": 7, "month": 30, "mo": 30, "year": 365, "yr": 365, "y": 365}.get(u)
        if mult is None:
            raise QueryError(f"unknown duration unit {unit!r}")
        total += dt.timedelta(days=float(n) * mult)
    return total


def split_clauses(toks: list) -> list:
    """[(KEYWORD, tokens)] with keywords recognised only outside parentheses."""
    out, depth, cur = [], 0, None
    i = 0
    while i < len(toks):
        kind, text = toks[i]
        if kind == "op" and text == "(":
            depth += 1
        elif kind == "op" and text == ")":
            depth -= 1
        up = text.upper() if kind == "id" else ""
        if depth == 0 and up in CLAUSES and not (up == "GROUP" and not (i + 1 < len(toks) and toks[i + 1][1].upper() == "BY")):
            if up == "GROUP":
                i += 1
            if up == "TABLE" and i + 2 < len(toks) and toks[i + 1][1].upper() == "WITHOUT" and toks[i + 2][1].upper() == "ID":
                cur = ["TABLE_NOID", []]
                i += 2
            else:
                cur = [up, []]
            out.append(cur)
        elif cur is None:
            raise QueryError("a query starts with TABLE, LIST or TASK")
        else:
            cur[1].append(toks[i])
        i += 1
    return [(k, t) for k, t in out]


# --- values ---------------------------------------------------------------------------------------------------------
def wrap(v):
    if isinstance(v, str):
        m = re.fullmatch(r"\[\[([^\]]*)\]\]", v.strip())
        if m:
            inner = m.group(1)
            return Link(inner.split("|")[0], inner.split("|")[1] if "|" in inner else None)
        return v
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, list):
        return [wrap(x) for x in v]
    if isinstance(v, dict):
        return {k: wrap(x) for k, x in v.items()}
    return v


def truthy(v) -> bool:
    return bool(v) if not isinstance(v, Link) else True


def eq(a, b) -> bool:
    if isinstance(a, Link) and isinstance(b, Link):
        return a.key() == b.key()
    if isinstance(a, Link) or isinstance(b, Link):
        return False
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(eq(x, y) for x, y in zip(a, b))
    return a == b


def _order(v):
    if v is None:
        return (0, 0)
    if isinstance(v, bool):
        return (1, v)
    if isinstance(v, (int, float)):
        return (2, v)
    if isinstance(v, (dt.date, dt.datetime)):
        return (3, v.isoformat())
    if isinstance(v, str):
        return (4, v.casefold())
    if isinstance(v, Link):
        return (4, v.key().casefold())
    if isinstance(v, list):
        return (5, tuple(_order(x) for x in v))
    return (6, str(v))


def compare(op, a, b) -> bool:
    if op == "=":
        return eq(a, b)
    if op == "!=":
        return not eq(a, b)
    if a is None or b is None:
        return False
    oa, ob = _order(a), _order(b)
    if oa[0] != ob[0]:
        return False
    return {"<": oa < ob, ">": oa > ob, "<=": oa <= ob, ">=": oa >= ob}[op]


def arith(op, a, b):
    try:
        if isinstance(a, (dt.date, dt.datetime)) and isinstance(b, dt.timedelta):
            r = a - b if op == "-" else a + b if op == "+" else None
            return r.date() if isinstance(r, dt.datetime) and not isinstance(a, dt.datetime) else r
        if isinstance(a, dt.timedelta) and isinstance(b, (dt.date, dt.datetime)) and op == "+":
            return b + a
        if isinstance(a, (dt.date, dt.datetime)) and isinstance(b, (dt.date, dt.datetime)) and op == "-":
            return a - b
        if op == "+":
            return a + b
        if op == "-":
            return a - b
        if op == "*":
            return a * b
        if op == "/":
            return a / b
    except (TypeError, ZeroDivisionError):
        return None
    return None


def resolve(path: str, env: dict):
    parts = path.split(".")
    if parts[0] not in env:
        return None
    if parts[0] == "file" and len(parts) > 1 and parts[1] in UNSUPPORTED_FILE_FIELDS:
        raise Unsupported(f"file.{parts[1]} is not supported")
    v = env[parts[0]]
    for p in parts[1:]:
        if isinstance(v, dict):
            v = v.get(p)
        elif isinstance(v, list):
            v = [x.get(p) if isinstance(x, dict) else None for x in v]
        else:
            return None
    return v


def _text(v) -> str:
    return v.key() if isinstance(v, Link) else "" if v is None else str(v)


def call(name, args, nodes, env):
    if name == "date":
        n = nodes[0]
        if n[0] == "field" and n[1] in ("today", "now", "tomorrow", "yesterday"):
            base = env["_today"]
            return base + {"tomorrow": dt.timedelta(days=1), "yesterday": -dt.timedelta(days=1)}.get(n[1], dt.timedelta())
        try:
            return dt.date.fromisoformat(str(args[0])[:10])
        except ValueError:
            return None
    if name == "link":
        a = args[0]
        return a if isinstance(a, Link) else Link(str(a))
    if name in ("contains", "icontains"):
        a, b = args
        if isinstance(a, list):
            return any(eq(x, b) or (name == "icontains" and _text(x).casefold() == _text(b).casefold()) for x in a)
        if isinstance(a, str):
            return (_text(b).casefold() in a.casefold()) if name == "icontains" else _text(b) in a
        return False
    if name == "startswith":
        return _text(args[0]).startswith(_text(args[1]))
    if name == "endswith":
        return _text(args[0]).endswith(_text(args[1]))
    if name == "lower":
        return _text(args[0]).lower()
    if name == "upper":
        return _text(args[0]).upper()
    if name == "length":
        return len(args[0]) if isinstance(args[0], (list, str, dict)) else 0
    if name == "default":
        return args[0] if args[0] is not None else args[1]
    if name == "choice":
        return args[1] if truthy(args[0]) else args[2]
    if name in ("any", "all", "map", "filter"):
        lst = args[0]
        items = lst if isinstance(lst, list) else ([] if lst is None else [lst])
        if len(nodes) == 1 and name in ("any", "all"):
            res = items                      # any(list): is some element true
        else:
            if len(nodes) < 2 or nodes[1][0] != "lambda":
                raise QueryError(f"{name}() needs a (x) => ... function")
            fn_node = nodes[1]
            res = [evaluate(fn_node[2], {**env, fn_node[1]: x}) for x in items]
        if name == "any":
            return any(truthy(r) for r in res)
        if name == "all":
            return all(truthy(r) for r in res)
        if name == "map":
            return res
        return [x for x, r in zip(items, res) if truthy(r)]
    raise Unsupported(f"function {name}() is not supported")


def evaluate(n, env):
    t = n[0]
    if t == "const":
        return n[1]
    if t == "field":
        return resolve(n[1], env)
    if t == "tag":
        raise QueryError("a #tag is only valid in FROM")
    if t == "not":
        return not truthy(evaluate(n[1], env))
    if t == "neg":
        v = evaluate(n[1], env)
        return -v if isinstance(v, (int, float)) else None
    if t == "or":
        return truthy(evaluate(n[1], env)) or truthy(evaluate(n[2], env))
    if t == "and":
        return truthy(evaluate(n[1], env)) and truthy(evaluate(n[2], env))
    if t == "cmp":
        return compare(n[1], evaluate(n[2], env), evaluate(n[3], env))
    if t == "arith":
        return arith(n[1], evaluate(n[2], env), evaluate(n[3], env))
    if t == "call":
        if n[1] in ("any", "all", "map", "filter"):
            return call(n[1], [evaluate(n[2][0], env)], n[2], env)
        return call(n[1], [evaluate(a, env) for a in n[2]], n[2], env)
    if t == "lambda":
        raise QueryError("a function is only valid inside any(), all(), map() or filter()")
    raise QueryError(f"cannot evaluate {t}")


def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, Link):
        return f"[[{v.target}]]"
    if isinstance(v, list):
        return ", ".join(fmt(x) for x in v)
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


# --- pages ----------------------------------------------------------------------------------------------------------
def load_page(vault: Path, rel: str) -> dict:
    p = vault / rel
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        fm = V.frontmatter(text) or {}
        st = p.stat()
    except OSError:
        return {}
    fm = {k: wrap(v) for k, v in fm.items()} if isinstance(fm, dict) else {}
    tags = fm.get("tags")
    tags = [str(t) for t in tags] if isinstance(tags, list) else [str(tags)] if isinstance(tags, str) else []
    fm["tags"] = tags
    stem = Path(rel).stem
    fm["_text"] = text
    fm["file"] = {"name": stem, "path": rel, "folder": "" if "/" not in rel else Path(rel).parent.as_posix(),
                  "link": Link(stem), "ext": "md", "tags": ["#" + t for t in tags],
                  "mtime": dt.datetime.fromtimestamp(st.st_mtime), "ctime": dt.datetime.fromtimestamp(st.st_ctime),
                  "size": st.st_size}
    return fm


TASK_RE = re.compile(r"^(\s*)[-*+]\s+\[(.)\]\s+(.*)$")
TASK_DATES = {"✅": "completion", "📅": "due", "➕": "created", "🛫": "start", "⏳": "scheduled"}


def tasks_of(text: str) -> list:
    """Checkbox list items outside fenced code, with Dataview's task fields; children are found by indentation."""
    tasks, stack, fence = [], [], False
    for n, line in enumerate(text.split("\n"), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        m = None if fence else TASK_RE.match(line)
        if not m:
            continue
        indent, ch, body = len(m.group(1).replace("\t", "    ")), m.group(2), m.group(3).strip()
        task = {"line": n, "status": ch, "checked": ch != " ", "completed": ch in "xX", "text": body, "children": [],
                "tags": [Tag("#" + x) for x in re.findall(r"(?:^|\s)#([\w/\-]+)", body)]}
        for emoji, name in TASK_DATES.items():
            d = re.search(re.escape(emoji) + r"\s*(\d{4}-\d{2}-\d{2})", body)
            if d:
                try:
                    task[name] = dt.date.fromisoformat(d.group(1))
                except ValueError:
                    pass
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if stack:
            stack[-1][1]["children"].append(task)
        stack.append((indent, task))
        tasks.append(task)

    def done(t):
        return t["completed"] and all(done(c) for c in t["children"])
    for t in tasks:
        t["fullyCompleted"] = done(t)
    return tasks


def source_matches(node, page) -> bool:
    t = node[0]
    path = page["file"]["path"]
    if t == "const" and isinstance(node[1], str):
        f = node[1].strip("/")
        return path == f or path == f + ".md" or path.startswith(f + "/")
    if t == "tag":
        return any(x == node[1] or x.startswith(node[1] + "/") for x in page["tags"])
    if t == "neg":
        return not source_matches(node[1], page)
    if t == "or":
        return source_matches(node[1], page) or source_matches(node[2], page)
    if t == "and":
        return source_matches(node[1], page) and source_matches(node[2], page)
    if t == "const":
        raise Unsupported("a link source ([[...]]) is not supported in FROM")
    raise Unsupported("this FROM source is not supported")


def source_folders(node):
    """Folders to walk when the source is a union of folders; None means walk everything."""
    t = node[0]
    if t == "const" and isinstance(node[1], str):
        return [node[1].strip("/")]
    if t == "or":
        a, b = source_folders(node[1]), source_folders(node[2])
        return None if a is None or b is None else a + b
    if t == "and":
        return source_folders(node[1]) or source_folders(node[2])
    return None


def walk_md(vault: Path, folders):
    seen = set()
    for f in folders if folders is not None else [""]:
        base = vault / f
        if base.is_dir():
            cands = []
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if d not in V.SKIP_DIRS)
                cands += [Path(dirpath) / n for n in sorted(filenames) if n.endswith(".md")]
        else:
            one = base if f.endswith(".md") else vault / (f + ".md")
            cands = [one] if one.is_file() else []
        for c in cands:
            rel = c.relative_to(vault).as_posix()
            if rel not in seen:
                seen.add(rel)
                yield rel


# --- running a query ------------------------------------------------------------------------------------------------
def run(query: str, vault: Path | None = None, this: str | None = None, today: dt.date | None = None) -> dict:
    vault = Path(vault) if vault else V.VAULT
    today = today or dt.date.today()
    clauses = split_clauses(tokenize(query))
    if not clauses:
        raise QueryError("empty query")
    kinds = [k for k, _ in clauses]
    if "GROUP" in kinds:
        raise Unsupported("GROUP BY is not supported")
    if kinds[0] not in ("TABLE", "TABLE_NOID", "LIST", "TASK"):
        raise QueryError("a query starts with TABLE, LIST or TASK")
    head_kind, head_toks = clauses[0]
    source = None
    for k, toks in clauses[1:]:
        if k == "FROM":
            p = Parser(toks)
            source = p.expr()
            if p.peek()[0] is not None:
                raise QueryError("unexpected text in FROM")
    this_page = load_page(vault, this) if this else None
    base_env = {"_today": today}
    if this_page:
        base_env["this"] = this_page
    rows = []
    for rel in walk_md(vault, source_folders(source) if source else None):
        page = load_page(vault, rel)
        if not page or (source is not None and not source_matches(source, page)):
            continue
        if head_kind == "TASK":
            for task in tasks_of(page["_text"]):
                rows.append({**base_env, **page, **{k: v for k, v in task.items() if k != "children"}})
        else:
            rows.append({**base_env, **page})
    for k, toks in clauses[1:]:
        p = Parser(toks)
        if k == "WHERE":
            node = p.expr()
            rows = [r for r in rows if truthy(evaluate(node, r))]
        elif k == "SORT":
            keys = []
            while p.peek()[0] is not None:
                node = p.expr()
                desc = False
                if p.is_kw("desc") or p.is_kw("descending"):
                    p.take()
                    desc = True
                elif p.is_kw("asc") or p.is_kw("ascending"):
                    p.take()
                keys.append((node, desc))
                if p.is_op(","):
                    p.take()
            for node, desc in reversed(keys):
                rows.sort(key=lambda r, n=node: _order(evaluate(n, r)), reverse=desc)
        elif k == "LIMIT":
            n = evaluate(p.expr(), {})
            rows = rows[: int(n)]
        elif k == "FLATTEN":
            node = p.expr()
            if not p.is_kw("as"):
                raise QueryError("FLATTEN needs AS name")
            p.take()
            name = p.take()[1].strip('"')
            out = []
            for r in rows:
                v = evaluate(node, r)
                for item in (v if isinstance(v, list) else [v] if v is not None else []):
                    out.append({**r, name: item})
            rows = out
    if head_kind == "TASK":
        return {"kind": "task", "columns": ["File", "line", "status", "text"],
                "rows": [[r["file"]["link"], r["line"], r["status"], r["text"]] for r in rows]}
    if head_kind == "LIST":
        node = Parser(head_toks).expr() if head_toks else None
        out = [[r["file"]["link"]] + ([evaluate(node, r)] if node else []) for r in rows]
        return {"kind": "list", "columns": ["File"] + (["value"] if node else []), "rows": out}
    cols, p = [], Parser(head_toks)
    while p.peek()[0] is not None:
        start = p.i
        node = p.expr()
        label = " ".join(t for _, t in head_toks[start:p.i])
        if p.is_kw("as"):
            p.take()
            label = p.take()[1].strip('"')
        cols.append((label, node))
        if p.is_op(","):
            p.take()
    columns = ([] if head_kind == "TABLE_NOID" else ["File"]) + [c[0] for c in cols]
    out = [([] if head_kind == "TABLE_NOID" else [r["file"]["link"]]) + [evaluate(n, r) for _, n in cols] for r in rows]
    return {"kind": "table", "columns": columns, "rows": out}


def render(result: dict) -> str:
    if result["kind"] == "task":
        out, last = [], None
        for link, _line, status, text in result["rows"]:
            if link.key() != last:
                out.append(fmt(link))
                last = link.key()
            out.append(f"- [{status}] {text}")
        return "\n".join(out)
    if result["kind"] == "list":
        return "\n".join("- " + fmt(r[0]) + (f": {fmt(r[1])}" if len(r) > 1 else "") for r in result["rows"])
    lines = ["\t".join(result["columns"])] + ["\t".join(fmt(c) for c in r) for r in result["rows"]]
    return "\n".join(lines)


def blocks_of(text: str) -> list:
    return [m.group(1).strip() for m in re.finditer(r"```dataview\n(.*?)```", text, re.S)]


def coverage(vault: Path | None = None) -> dict:
    vault = Path(vault) if vault else V.VAULT
    out = {"ok": 0, "unsupported": [], "error": []}
    for p in V.iter_md():
        text = V.read(p)
        for i, q in enumerate(blocks_of(text)):
            rel = V.rel(p)
            try:
                run(q, vault, this=rel)
                out["ok"] += 1
            except Unsupported as exc:
                out["unsupported"].append((rel, i, str(exc)))
            except QueryError as exc:
                out["error"].append((rel, i, str(exc)))
    return out


def main(argv=None) -> int:
    V.force_utf8_stdio()
    a = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in a
    a = [x for x in a if x != "--json"]

    def opt(name):
        if name in a:
            i = a.index(name)
            v = a[i + 1] if i + 1 < len(a) else None
            del a[i:i + 2]
            return v
        return None
    try:
        if "--coverage" in a:
            c = coverage()
            total = c["ok"] + len(c["unsupported"]) + len(c["error"])
            print(f"VQ-COVERAGE ok {c['ok']} of {total}, unsupported {len(c['unsupported'])}, errors {len(c['error'])}")
            for kind in ("unsupported", "error"):
                for rel, i, why in c[kind]:
                    print(f"{kind}\t{rel}#{i}\t{why}")
            return 0 if not c["error"] else 1
        this, note, block = opt("--this"), opt("--note"), opt("--block")
        if note:
            qs = blocks_of(V.read(V.VAULT / note))
            if not qs:
                print("no dataview block in that note", file=sys.stderr)
                return 2
            if block is not None:
                qs = [qs[int(block)]]
            for q in qs:
                print(render(run(q, this=note)) if not as_json else json.dumps(run(q, this=note), default=fmt, ensure_ascii=False))
            return 0
        if not a or a[0] in ("-h", "--help"):
            print(__doc__)
            return 0 if a else 2
        res = run(a[0], this=this)
        print(json.dumps(res, default=fmt, ensure_ascii=False) if as_json else render(res))
        return 0
    except Unsupported as exc:
        print(f"UNSUPPORTED: {exc}", file=sys.stderr)
        return 2
    except QueryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
