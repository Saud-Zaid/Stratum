# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Shared helpers for vault-sandbox scripts: structural Markdown parsing (markdown-it-py: CommonMark + tables + front matter). Import: from _vaultlib import *"""

from __future__ import annotations

import bisect
import copy
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Iterator, NamedTuple

import yaml
from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

VAULT = Path(os.environ.get("VAULT") or Path(__file__).resolve().parents[2])   # the checkout this script lives in, unless VAULT says otherwise
SKIP_DIRS = {".git", ".obsidian", ".trash", "node_modules", ".venv", ".vault-release"}

# ADR-006 import policy, one copy for audit.py and impact.py (AD13 E7: the two copies had drifted, `mediator` was allowed by one only)
ALLOWED_THIRD_PARTY = {"_vaultlib", "markdown_it", "mdit_py_plugins", "yaml", "tiktoken", "mcp"}    # ADR-006 as amended by ADR-009 (tiktoken) and ADR-020 (mcp<2)
# ADR-021: libraries allowed for ONE named script only (stem -> set). Every other script still gets the global list above.
SCRIPT_THIRD_PARTY: dict[str, set[str]] = {}   # per-script third-party libraries: none in this release
SCHEMA_UNITS = {"decision_ledger", "mediator"}    # schema/ units are vault-local; read-only consumers may import them (ADR-006 as amended 2026-10-19)


DYNAMIC_IMPORT_CALLS = ("import_module", "__import__", "optional_module")


def script_import_roots(src: str, fallback: bool = True, dynamic: bool = False):
    """Top-level module names a script imports, from real import statements (a docstring line starting with "from" is prose).
    A syntax error returns a line-regex guess when `fallback`, else None so the caller can report the parse failure itself.
    `dynamic`: also the names given as a string literal to importlib.import_module, __import__ or optional_module (deptry's
    DEP001 does not see these either; a computed name cannot be seen by anything)."""
    import ast as _ast
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        if not fallback:
            return None
        return {m.split(".")[0] for m in re.findall(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", src, re.M)}
    mods = set()
    for n in _ast.walk(tree):
        if isinstance(n, _ast.Import):
            mods.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, _ast.ImportFrom) and n.module and not n.level:
            mods.add(n.module.split(".")[0])
        elif dynamic and isinstance(n, _ast.Call) and n.args and isinstance(n.args[0], _ast.Constant) and isinstance(n.args[0].value, str):
            fn = n.func
            if (fn.attr if isinstance(fn, _ast.Attribute) else (fn.id if isinstance(fn, _ast.Name) else "")) in DYNAMIC_IMPORT_CALLS and n.args[0].value:
                mods.add(n.args[0].value.split(".")[0])
    return mods


def unapproved_imports(mods, local_stems, optional=(), script=None) -> list:
    """Modules outside stdlib, the pinned libraries, sibling scripts, schema units, the profile's optional modules
    and the per-script libraries of SCRIPT_THIRD_PARTY for `script` (a stem; ADR-021)."""
    stdlib = set(getattr(sys, "stdlib_module_names", set()))
    own = SCRIPT_THIRD_PARTY.get(script, set())
    return sorted(m for m in mods if m not in stdlib and m not in ALLOWED_THIRD_PARTY and m not in local_stems
                  and m not in SCHEMA_UNITS and m not in optional and m not in own)

try:
    import _locale_ar as _LOC          # the mother vault's Arabic tables; a release ships none of them
except ImportError:
    _LOC = None


def locale_value(name: str, default=None):
    """One table of the Arabic locale, or `default` when this tree has no Arabic locale."""
    return getattr(_LOC, name, default) if _LOC is not None else default


def alternation(words) -> str:
    """A regex alternation of literal words; one that never matches when there are none (an Arabic-only rule is then inert)."""
    words = [w for w in words if w]
    return "(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + ")" if words else "(?!)"


_TASHKEEL = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED\u0640]")
_MAP = str.maketrans(locale_value("NORMALIZE", {}))
_INVISIBLE = re.compile("[\u200b-\u200d\u2060\ufeff]")           # ZWSP, ZWNJ, ZWJ, word joiner, BOM
_PERSIAN = str.maketrans(locale_value("PERSIAN_FOLD", {}))     # Persian kaf, yeh -> Arabic kaf, yeh (AD13 B3); the table is in _locale_ar
_MD = MarkdownIt("commonmark").enable("table").use(front_matter_plugin)
_OBS_COMMENT = re.compile(r"%%.*?%%", re.S)


class Heading(NamedTuple):
    line: int       # 1-based, file-absolute
    level: int
    title: str      # raw inline source of the heading text
    plain: str      # heading text outside code spans (what tag/char rules must inspect)
    has_code: bool
    nested: bool    # inside a blockquote/callout or a list item (Obsidian's heading cache ignores these)
    setext: bool    # underline-style heading (=== / ---)


class Doc(NamedTuple):
    total_lines: int
    has_fm: bool
    fm_raw: str
    fm: dict
    fm_error: str
    body_start: int           # 1-based first body line
    tokens: list
    headings: list            # top-level headings only: matches Obsidian's metadata cache (verified 11 Sep 2026)
    nested_headings: list     # headings inside blockquotes/callouts/lists: not targetable by Obsidian tools
    code_lines: frozenset     # 1-based lines inside fenced/indented code
    table_lines: frozenset    # 1-based lines inside tables


def normalize_ar(text: str) -> str:
    """Normalize Arabic spelling variants + casefold, for matching only (never for writing back)."""
    if os.environ.get("STRATUM_NORMALIZE_EXTRA") == "0":   # kill switch for the AD13 B3 additions
        return _TASHKEEL.sub("", text).translate(_MAP).casefold()
    text = _INVISIBLE.sub("", unicodedata.normalize("NFKC", text))   # NFKC folds presentation forms and the lam-alef ligature
    return _TASHKEEL.sub("", text).translate(_PERSIAN).translate(_MAP).casefold()


def is_readme(path) -> bool:
    return Path(path).name.lower() == "readme.md"


def iter_md(prefix: str = "", include_readme: bool = False) -> Iterator[Path]:
    """Yield markdown files under /vault/<prefix>, skipping system folders and (by default) README.md files."""
    for dirpath, dirnames, filenames in os.walk(VAULT / prefix):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if f.endswith(".md") and (include_readme or not is_readme(f)) and (Path(dirpath) / f).is_file():   # a dangling symlink is not a note
                yield Path(dirpath) / f


def rel(path) -> str:
    return Path(path).relative_to(VAULT).as_posix()   # the vault speaks forward slashes on every platform


def read(path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def _code_table_lines(tokens) -> tuple[set, set]:
    code, table = set(), set()
    for t in tokens:
        if not t.map:
            continue
        if t.type in ("fence", "code_block"):
            code.update(range(t.map[0] + 1, t.map[1] + 1))
        elif t.type == "table_open":
            table.update(range(t.map[0] + 1, t.map[1] + 1))
    return code, table


def _mask_obsidian_comments(text: str, protected: set) -> str:
    """Blank %%comments%% that start outside code, preserving line and column positions."""
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    parts, last = [], 0
    for m in _OBS_COMMENT.finditer(text):
        if bisect.bisect_right(starts, m.start()) in protected:
            continue
        parts.append(text[last:m.start()])
        parts.append(re.sub(r"[^\n]", " ", m.group(0)))
        last = m.end()
    parts.append(text[last:])
    return "".join(parts)


_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)   # libyaml when the install has it (about 8x faster on the audit's hot path), the pure-Python loader otherwise


def _yaml_load(text: str):
    """yaml.safe_load with the fastest safe loader available; same results and the same yaml.YAMLError family."""
    return yaml.load(text, Loader=_YAML_LOADER)


def load_frontmatter(fm_raw: str) -> tuple[dict, str]:
    """(mapping, error) of a front matter block. The single place that turns the raw block into values, shared by
    parse() and by the audit cache, so a cached document equals a freshly parsed one by construction."""
    fm, fm_error = {}, ""
    try:
        loaded = _yaml_load(fm_raw) if fm_raw.strip() else {}
        if isinstance(loaded, dict):
            fm = loaded
        elif loaded is not None:
            fm_error = "front matter is not a mapping"
    except yaml.YAMLError as e:
        fm_error = str(e).splitlines()[0]
    except ValueError as e:   # PyYAML builds dates itself: `due: 2026-11-31` raises ValueError, not YAMLError
        fm_error = f"invalid date or time value: {e}"
    return fm, fm_error


def doc_to_meta(d: "Doc") -> dict:
    """The JSON-safe parse products of a note. The front matter VALUES are not stored: YAML values (dates, datetimes,
    sets, non-string keys) do not survive JSON, so the raw block is stored and re-read with load_frontmatter."""
    return {
        "total_lines": d.total_lines,
        "body_start": d.body_start,
        "has_fm": d.has_fm,
        "fm_raw": d.fm_raw,
        "headings": [(h.line, h.level, h.title, h.plain, h.has_code, h.nested, h.setext) for h in d.headings],
        "nested_headings": [(h.line, h.level, h.title, h.plain, h.has_code, h.nested, h.setext) for h in d.nested_headings],
        "table_lines": sorted(d.table_lines),
        "code_lines": sorted(d.code_lines),
    }


def doc_from_meta(meta: dict) -> "Doc":
    """Rebuild a Doc from doc_to_meta output (after a JSON round trip). Tokens are not kept."""
    fm, fm_error = load_frontmatter(meta["fm_raw"]) if meta["has_fm"] else ({}, "")
    return Doc(meta["total_lines"], bool(meta["has_fm"]), meta["fm_raw"], fm, fm_error, meta["body_start"], [],
               [Heading(*h) for h in meta["headings"]], [Heading(*h) for h in meta["nested_headings"]],
               frozenset(meta["code_lines"]), frozenset(meta["table_lines"]))


def invalid_utf8(path) -> bool:
    """True when the file's bytes are not valid UTF-8 (read() replaces them silently, so the audit reports it)."""
    try:
        Path(path).read_bytes().decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def broken_md_symlinks(prefix: str = "") -> list[str]:
    """Relative paths of `*.md` symlinks whose target does not exist (iter_md skips them; the audit reports them)."""
    out = []
    for dirpath, dirnames, filenames in os.walk(VAULT / prefix):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            p = Path(dirpath) / f
            if f.endswith(".md") and p.is_symlink() and not p.exists():
                out.append(p.relative_to(VAULT).as_posix())
    return sorted(out)


@lru_cache(maxsize=512)
def parse(text: str) -> Doc:
    tokens = _MD.parse(text)
    if "%%" in text:
        code, _ = _code_table_lines(tokens)
        masked = _mask_obsidian_comments(text, code)
        if masked != text:
            tokens = _MD.parse(masked)
    code, table = _code_table_lines(tokens)
    has_fm, fm_raw, fm, fm_error, body_start = False, "", {}, "", 1
    heads, nested = [], []
    for i, t in enumerate(tokens):
        if t.type == "front_matter":
            has_fm, fm_raw, body_start = True, t.content, t.map[1] + 1
            fm, fm_error = load_frontmatter(fm_raw)
        elif t.type == "heading_open":
            inline = tokens[i + 1]
            kids = inline.children or []
            plain = "".join(c.content for c in kids if c.type == "text")
            h = Heading(t.map[0] + 1, int(t.tag[1]), inline.content, plain,
                        any(c.type == "code_inline" for c in kids), t.level > 0,
                        t.markup in ("=", "-"))
            (nested if h.nested else heads).append(h)
    return Doc(text.count("\n") + 1, has_fm, fm_raw, fm, fm_error, body_start, tokens, heads, nested,
               frozenset(code), frozenset(table))


def split_frontmatter(text: str) -> tuple[str, str, int]:
    """Return (frontmatter_raw, body, body_start_line_1based)."""
    d = parse(text)
    if not d.has_fm:
        return "", text, 1
    return d.fm_raw, "".join(text.splitlines(keepends=True)[d.body_start - 1:]), d.body_start


def frontmatter(text: str) -> dict:
    return parse(text).fm


def frontmatter_keys(fm_raw: str) -> list[str]:
    try:
        loaded = _yaml_load(fm_raw) if fm_raw.strip() else {}
        return list(loaded.keys()) if isinstance(loaded, dict) else []
    except (yaml.YAMLError, ValueError):   # ValueError: an impossible date value
        return [m.group(1) for m in re.finditer(r"^([^\s:#][^:]*):", fm_raw, re.M)]


def headings(text: str) -> list[tuple[int, int, str]]:
    """Return [(line_1based, level, title)]; ignores code, HTML comments and Obsidian %% comments."""
    return [(h.line, h.level, h.title) for h in parse(text).headings]


def sections(text: str) -> list[tuple[int, str, int, int]]:
    """Return [(level, title, start_line, line_count)]; a section ends at the next heading of same or higher level."""
    hs = parse(text).headings
    total = text.count("\n") + 1
    out = []
    for idx, h in enumerate(hs):
        end = total + 1
        for n in hs[idx + 1:]:
            if n.level <= h.level:
                end = n.line
                break
        out.append((h.level, h.title, h.line, end - h.line))
    return out


def leaf_sections(text: str, d=None) -> list[dict]:
    """Own content of each heading (until the next heading of ANY level): bytes, lines and table/code share.
    `d` is the already parsed document of the same text (the audit passes it, so the note is parsed once)."""
    d = d if d is not None else parse(text)
    lines = text.splitlines(keepends=True)
    total = len(lines)
    out = []
    for idx, h in enumerate(d.headings):
        end = d.headings[idx + 1].line if idx + 1 < len(d.headings) else total + 1
        body = [n for n in range(h.line + 1, end) if n - 1 < total and lines[n - 1].strip()]
        atomic = sum(1 for n in body if n in d.code_lines or n in d.table_lines)
        out.append({"level": h.level, "title": h.title, "line": h.line, "lines": end - h.line,
                    "bytes": len("".join(lines[h.line - 1:end - 1]).encode()),
                    "atomic_share": atomic / len(body) if body else 0.0})
    return out


_INLINE_MEMO: dict[str, list[tuple[int, str]]] = {}   # text -> its inline prose; a pure function of the text, so safe to reuse


def preload_inline(text: str, items) -> None:
    """Seed the memo from the persisted parse products (audit cache) so a warm run never tokenizes the note again."""
    _INLINE_MEMO[text] = [(int(line), s) for line, s in items]


def inline_texts(text: str) -> Iterator[tuple[int, str]]:
    """Yield (line_1based, prose) for every inline block, with code spans removed and line breaks kept as \\n.
    Memoized per text: the same note is asked for several times in one run."""
    items = _INLINE_MEMO.get(text)
    if items is None:
        items = []
        for t in parse(text).tokens:
            if t.type == "inline" and t.map:
                s = "".join(c.content if c.type == "text" else "\n" for c in (t.children or [])
                            if c.type in ("text", "softbreak", "hardbreak"))
                if s.strip():
                    items.append((t.map[0] + 1, s))
        _INLINE_MEMO[text] = items
    yield from items


CLUB_AREA: str | None = locale_value("CLUB_AREA")   # None in a release: no club area
_PAUSE_KEY = re.compile(r"^\s*" + alternation([locale_value("PAUSE_WORD")]) + r"::(.*)$")
_PAUSE_VAL = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})\s*→\s*(\d{4}-\d{2}-\d{2})\s*$")


class Pause(NamedTuple):
    start: date
    end: date

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def pause_window(text: str | None = None, warnings: list | None = None) -> Pause | None:
    """The single reader of the club's seasonal pause line (D11, D15 item 5).

    Reads the pause line (`- <pause word>:: YYYY-MM-DD → YYYY-MM-DD`, the word comes from the Arabic locale) from the club area (or `text`), ignoring code and %% comments.
    Returns Pause(start, end), both inclusive, or None when there is no line. A malformed line, start after end,
    or more than one line returns None with a warning (appended to `warnings`, else printed to stderr).
    No other script may parse this line.
    """
    if text is None:
        path = VAULT / CLUB_AREA if CLUB_AREA else None
        if path is None or not path.is_file():
            return None
        text = read(path)
    found, bad = [], []
    for line, block in inline_texts(text):
        for off, part in enumerate(block.split("\n")):
            m = _PAUSE_KEY.match(part)
            if not m:
                continue
            v = _PAUSE_VAL.match(m.group(1))
            try:
                p = Pause(date.fromisoformat(v.group(1)), date.fromisoformat(v.group(2))) if v else None
            except ValueError:
                p = None
            if p is None or p.start > p.end:
                bad.append(f"line {line + off}: {part.strip()}")
            else:
                found.append(p)
    msgs = [f"pause line malformed, ignored ({b})" for b in bad]
    if len(found) > 1:
        msgs.append(f"{len(found)} pause lines, expected one; none applied")
    for msg in msgs:
        (warnings.append(msg) if warnings is not None else print(f"WARN {msg}", file=sys.stderr))
    return found[0] if len(found) == 1 and not bad else None


# VAULT_INDEX_DB redirects the derived store (tests, a read-only checkout); the default sits under the vault's state folder.
INDEX_DB_PATH = Path(os.environ["VAULT_INDEX_DB"]) if os.environ.get("VAULT_INDEX_DB") else VAULT / "AI-Agent" / "state" / "vault-index.sqlite3"
# Bump when the tables below change shape. The store is derived data, so a mismatch rebuilds it (AD13 M04, derived-cache standard).
INDEX_SCHEMA_VERSION = 2


def _open_index(p: Path) -> Any:
    import sqlite3
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def get_vault_index_db(db_path: Path | None = None) -> Any:
    """Open the derived vault-index store (SQLite, WAL). The store is disposable: an unreadable file or a
    schema version other than INDEX_SCHEMA_VERSION is deleted and rebuilt, with a warning on stderr, never read.
    A store that cannot be opened at all raises, so the caller can say so loudly and run without it."""
    import sqlite3
    p = Path(db_path) if db_path else INDEX_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    why = ""
    conn = None
    try:
        conn = _open_index(p)
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        has_tables = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'").fetchone()[0] > 0
        if version == INDEX_SCHEMA_VERSION or (version == 0 and not has_tables):
            _init_index_schema(conn)
            return conn
        why = f"schema version {version}, expected {INDEX_SCHEMA_VERSION}"
        conn.close()
    except sqlite3.DatabaseError as exc:
        why = f"{type(exc).__name__}: {exc}"
        if conn is not None:   # Windows cannot delete a file that a connection still holds open
            try:
                conn.close()
            except sqlite3.Error:
                pass
    print(f"WARN vault-index: store at {p} rebuilt ({why})", file=sys.stderr)
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(p) + suffix).unlink()
        except FileNotFoundError:
            pass
    conn = _open_index(p)
    _init_index_schema(conn)
    return conn


def _init_index_schema(conn: Any) -> None:
    """Initialize core tables for vault index and incremental CAS audit cache."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS vault_files (
            path TEXT PRIMARY KEY,
            stem TEXT NOT NULL,
            stem_norm TEXT NOT NULL,
            blob_sha1 TEXT,
            mtime REAL,
            size_bytes INTEGER,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_files_stem_norm ON vault_files(stem_norm);

        CREATE TABLE IF NOT EXISTS audit_cas_cache (
            path TEXT PRIMARY KEY,
            blob_sha1 TEXT NOT NULL,
            leaf_max INTEGER NOT NULL,
            findings_json TEXT NOT NULL,
            doc_meta_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_audit_blob ON audit_cas_cache(blob_sha1);

        CREATE TABLE IF NOT EXISTS cache_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION}")
    conn.commit()


def audit_cache_fingerprint_check(conn: Any, **fingerprints: str) -> list[str]:
    """Drop every cached audit row when any stored fingerprint differs from the current one, store the current ones,
    and return the names of the fingerprints that differed (empty list = cache kept). The first run (nothing stored)
    counts as stale: a cache of unknown provenance is not trusted. The ADR import cache is dropped with it."""
    stored = dict(conn.execute("SELECT key, value FROM cache_meta").fetchall())
    changed = [k for k, v in fingerprints.items() if stored.get(k) != v]
    if changed:
        conn.execute("DELETE FROM audit_cas_cache")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'adr_py_cache'").fetchone():
            conn.execute("DELETE FROM adr_py_cache")
        conn.executemany("INSERT OR REPLACE INTO cache_meta (key, value) VALUES (?, ?)", list(fingerprints.items()))
        conn.commit()
    return changed


def invalidate_audit_cache_if_stale(conn: Any, **fingerprints: str) -> bool:
    """True when the cache was invalidated (see audit_cache_fingerprint_check)."""
    return bool(audit_cache_fingerprint_check(conn, **fingerprints))


def code_fingerprint(entry: Path, extra: tuple = ()) -> str:
    """sha1 over the producing code: the entry script, every local script it imports (transitively, found with ast),
    plus the extra modules named by the caller and the literals of optional_module / import_module / __import__ calls, the interpreter minor version
    and the versions of the parsing libraries. Any edit changes it, so a cached result never outlives the code that made it."""
    import ast
    import hashlib
    from importlib import metadata
    entry = Path(entry).resolve()
    local = {q.stem: q for q in entry.parent.glob("*.py")}
    seen: dict[str, bytes] = {}
    stack = [entry.stem, *extra]
    while stack:
        name = stack.pop()
        if name in seen or name not in local:
            continue
        data = local[name].read_bytes()
        seen[name] = data
        try:
            tree = ast.parse(data)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                stack.extend(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                stack.append(node.module.split(".")[0])
            elif isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                fn = node.func   # modules imported by name at run time: optional_module("x"), importlib.import_module("x"), __import__("x")
                called = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
                if called in ("optional_module", "import_module", "__import__"):
                    stack.append(node.args[0].value.split(".")[0])
    h = hashlib.sha1()
    for name in sorted(seen):
        h.update(name.encode("utf-8") + b"\0" + seen[name] + b"\0")
    libs = []
    for dist in ("markdown-it-py", "mdit-py-plugins", "PyYAML"):
        try:
            libs.append(f"{dist}={metadata.version(dist)}")
        except Exception:
            libs.append(f"{dist}=?")
    h.update(("py%d.%d;" % sys.version_info[:2] + ";".join(libs)).encode("utf-8"))
    return h.hexdigest()


def scrub_git_env() -> list[str]:
    """Remove every GIT_* variable from this process's environment and return their names.
    A git hook runs with GIT_DIR, GIT_INDEX_FILE and friends set; a test that creates a temporary repository must not
    inherit them, or `git init` writes into the real repository's config (this corrupted core.bare and core.worktree of
    the main repository during AD13, 2026-11-13). Every test that spawns git repositories calls this first."""
    removed = [k for k in os.environ if k.startswith("GIT_")]
    for k in removed:
        del os.environ[k]
    return removed


def file_sha1(path: Path) -> str:
    """sha1 of a file's bytes, '' when it does not exist (a missing profile is a valid, distinct state)."""
    import hashlib
    return hashlib.sha1(path.read_bytes()).hexdigest() if path.is_file() else ""



# ---- release profile (T-02a) -------------------------------------------------
PROFILE_REL = "AI-Agent/config/release_profile.yaml"
PATCH_REL = "AI-Agent/config/release-patches/release_profile.patch.yaml"
# Integrity checks no profile may switch off (U-33).
UNTOUCHABLE_CHECKS = frozenset({"secrets", "gatehash", "schema", "s13", "contract"})
_PROFILE_MODES = ("vault", "release")
_PROFILE_LANGS = ("ar", "en")
_PROFILE_DEFAULTS = {
    "mode": "vault",
    "language": "ar",
    "owner": {"name": "", "aliases": []},
    "headings": {"next_steps": [], "progress_log": []},
    "checks": {"disabled": []},
    "paths": {"live_doc": "", "system_homes": [], "collector_exclude_prefixes": [], "people_dir": "", "capabilities_doc": "", "progress_note": ""},
    "markdown": {"md024_siblings_only_files": []},
    "limits": {"read_cap_bytes": 0, "operations_md_max_tokens": 0},
    "scripts": {"optional_modules": []},   # sibling modules a release does not ship; ADR-006 does not count them as foreign imports
    "sigkey": {"key_file": "", "fingerprint": ""},
}


def _merge_patch(base, patch):
    """RFC 7396 merge patch: dicts merge recursively, null deletes a key, anything else replaces."""
    if not isinstance(patch, dict):
        return patch
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = _merge_patch(out.get(k), v)
    return out


class PatchError(ValueError):
    """A release patch that does not apply cleanly. Patches fail closed: a path that is gone or a `test` that
    differs means the mother file drifted from what the patch was written against."""


def _pointer(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise PatchError(f"pointer must start with '/': {path!r}")
    return [p.replace("~1", "/").replace("~0", "~") for p in path[1:].split("/")]


def _walk(doc, parts: list[str], path: str):
    """The container that holds the last pointer step, and that step (an int for lists, '-' kept as is)."""
    cur = doc
    for step in parts[:-1]:
        cur = _child(cur, step, path)
    return cur, parts[-1]


def _child(cur, step: str, path: str):
    if isinstance(cur, dict):
        if step not in cur:
            raise PatchError(f"path not found: {path} (missing {step!r})")
        return cur[step]
    if isinstance(cur, list):
        try:
            return cur[int(step)]
        except (ValueError, IndexError):
            raise PatchError(f"path not found: {path} (bad index {step!r})") from None
    raise PatchError(f"path not found: {path} (cannot descend into a scalar at {step!r})")


def _index(lst: list, step: str, path: str, allow_end: bool = False) -> int:
    if step == "-" and allow_end:
        return len(lst)
    try:
        i = int(step)
    except ValueError:
        raise PatchError(f"bad list index {step!r} in {path}") from None
    if i < 0 or i > len(lst) or (i == len(lst) and not allow_end):
        raise PatchError(f"list index out of range in {path}")
    return i


def _matches(item, match) -> bool:
    if isinstance(match, dict) and isinstance(item, dict):
        return all(k in item and item[k] == v for k, v in match.items())
    return item == match


def apply_ops(doc, ops: list):
    """RFC 6902 subset (add, remove, replace, test) plus two array operations that keep a patch order-proof:
    `add_unique` (append unless an equal item is there) and `remove_match` (drop every item equal to `value`, or
    every dict that contains all pairs of `match`). A strict op that finds nothing raises PatchError; set
    `optional: true` on remove / remove_match to accept an absent target. Returns a new document."""
    doc = copy.deepcopy(doc)
    for n, op in enumerate(ops):
        if not isinstance(op, dict) or "op" not in op or "path" not in op:
            raise PatchError(f"op {n} needs 'op' and 'path'")
        kind, path = op["op"], op["path"]
        parts = _pointer(path)
        if kind in ("add_unique", "remove_match"):
            target = doc
            for step in parts:
                target = _child(target, step, path)
            if not isinstance(target, list):
                raise PatchError(f"{kind} needs a list at {path}")
            if kind == "add_unique":
                if "value" not in op:
                    raise PatchError(f"add_unique at {path} needs 'value'")
                if op["value"] not in target:
                    target.append(copy.deepcopy(op["value"]))
            else:
                if ("value" in op) == ("match" in op):
                    raise PatchError(f"remove_match at {path} needs exactly one of 'value' or 'match'")
                want = op["value"] if "value" in op else op["match"]
                keep = [it for it in target if not _matches(it, want)]
                if len(keep) == len(target) and not op.get("optional"):
                    raise PatchError(f"remove_match at {path} matched nothing")
                target[:] = keep
            continue
        if kind not in ("add", "remove", "replace", "test"):
            raise PatchError(f"unknown op {kind!r}")
        if not parts:
            if kind == "replace" or kind == "add":
                doc = copy.deepcopy(op["value"])
                continue
            raise PatchError(f"{kind} cannot target the document root")
        parent, last = _walk(doc, parts, path)
        if isinstance(parent, dict):
            if kind == "add":
                parent[last] = copy.deepcopy(op["value"])
            elif kind == "test":
                if last not in parent or parent[last] != op["value"]:
                    raise PatchError(f"test failed at {path}")
            else:
                if last not in parent:
                    if kind == "remove" and op.get("optional"):
                        continue
                    raise PatchError(f"path not found: {path}")
                if kind == "remove":
                    del parent[last]
                else:
                    parent[last] = copy.deepcopy(op["value"])
        elif isinstance(parent, list):
            if kind == "add":
                parent.insert(_index(parent, last, path, allow_end=True), copy.deepcopy(op["value"]))
            else:
                try:
                    i = _index(parent, last, path)
                except PatchError:
                    if kind == "remove" and op.get("optional"):
                        continue
                    raise
                if kind == "test":
                    if parent[i] != op["value"]:
                        raise PatchError(f"test failed at {path}")
                elif kind == "remove":
                    del parent[i]
                else:
                    parent[i] = copy.deepcopy(op["value"])
        else:
            raise PatchError(f"path not found: {path}")
    return doc


def apply_patch(doc, patch: dict):
    """One release patch document: `merge:` (RFC 7396) first, then `ops:` (apply_ops). Unknown keys are an error
    so a typo never turns into a silent no-op."""
    if not isinstance(patch, dict):
        raise PatchError("patch is not a mapping")
    extra = set(patch) - {"merge", "ops"}
    if extra:
        raise PatchError(f"unknown patch keys: {sorted(extra)}")
    out = doc
    if "merge" in patch:
        out = _merge_patch(out, patch["merge"])
    if "ops" in patch:
        if not isinstance(patch["ops"], list):
            raise PatchError("'ops' must be a list")
        out = apply_ops(out, patch["ops"])
    return copy.deepcopy(out)


def canonical_sha256(obj: dict) -> str:
    """sha256 of the canonical JSON without the `content_hash` field: the contract signature (hash_mode
    canonical_json_no_hash_field). Same bytes as schema/validate.py's sha256_canonical; a test keeps them equal."""
    import hashlib
    import json
    body = {k: v for k, v in obj.items() if k != "content_hash"}
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def release_contract(doc: dict, patch: dict) -> dict:
    """A contract patched for the release, then re-signed: the patch changes the content, so the stored hash is
    recomputed here and never carried over from the mother file."""
    out = apply_patch(doc, patch)
    out["content_hash"] = canonical_sha256(out)
    return out


def derive_obsidian(root, patch_dir) -> tuple[dict, list[str], list[str]]:
    """The release form of `.obsidian/` under the manifest `obsidian.manifest.yaml`. Returns
    ({relative path: text}, [dropped paths], [unclassified paths]); an unclassified file is an export-stopping finding.
    A patched file is read, patched (apply_patch) and written as JSON; a verbatim one is read as it is; plugin code is
    left to the plugin installer; a dropped one is never copied."""
    import fnmatch
    import json
    root, patch_dir = Path(root), Path(patch_dir)
    man = yaml.safe_load((patch_dir / "obsidian.manifest.yaml").read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    dropped: list[str] = []
    unclassified: list[str] = []
    base = root / ".obsidian"
    if not base.is_dir():
        return out, dropped, unclassified
    for f in sorted(p for p in base.rglob("*") if p.is_file()):
        rel = f.relative_to(root).as_posix()
        if rel in man["patched"]:
            patch = yaml.safe_load((patch_dir / man["patched"][rel]).read_text(encoding="utf-8"))
            doc = json.loads(f.read_text(encoding="utf-8"))
            out[rel] = json.dumps(apply_patch(doc, patch), indent=2, ensure_ascii=False) + "\n"
        elif rel in man["verbatim"]:
            out[rel] = f.read_text(encoding="utf-8")
        elif any(fnmatch.fnmatch(rel, g) for g in man["drop"]):
            dropped.append(rel)
        elif any(fnmatch.fnmatch(rel, g) for g in man["plugin_code"]):
            continue
        else:
            unclassified.append(rel)
    return out, dropped, unclassified


# --- secrets and hidden-text scanning (T-05) -----------------------------------------------------------------------
SECRET_PATTERNS = [
    ("sk-ant-[A-Za-z0-9_-]{20,}", "Anthropic key"),
    ("sk-proj-[A-Za-z0-9_-]{20,}", "OpenAI project key"),
    ("ghp_[A-Za-z0-9]{30,}", "GitHub token"),
    ("gho_[A-Za-z0-9]{30,}", "GitHub OAuth token"),
    ("github_pat_[A-Za-z0-9_]{40,}", "GitHub fine-grained token"),
    ("AKIA[A-Z0-9]{16}", "AWS access key"),
    ("glpat-[A-Za-z0-9_-]{20,}", "GitLab token"),
    ("xox[baprs]-[A-Za-z0-9-]{10,}", "Slack token"),
    ("-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", "private key block"),
    # AD13 D7 (HS-03): appended, so the numbers of the shapes above (the SECRET-leak-N rule ids) never move
    ("sk-[A-Za-z0-9]{32,}", "OpenAI key (legacy shape)"),
    ("sk-or-v1-[A-Za-z0-9]{30,}", "OpenRouter key"),
    ("AIza[0-9A-Za-z_-]{35}", "Google API key"),
    ("[sr]k_live_[0-9A-Za-z]{20,}", "Stripe live key"),
    (r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "JSON Web Token"),
    (r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s:/@]+:[^\s@/]{3,}@[^\s/]+", "database URL with a password"),
    (r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]{20,}", "Slack webhook"),
    ("hf_[A-Za-z0-9]{30,}", "Hugging Face token"),
    (r"SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}", "SendGrid key"),
    (r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b", "Telegram bot token"),
    ("gh[usr]_[A-Za-z0-9]{30,}", "GitHub app or refresh token"),
]
# public documentation samples that look like real credentials (the jwt.io example token's signature; the Firebase docs key)
PUBLIC_SAMPLES = ("SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "SyDaGmWKa4JsXZ-HjGw7ISLn_3namBGewQe")
_SHAPES_FILE = Path(__file__).resolve().parent.parent / "schema" / "secret-shapes.json"
_SHAPES_CACHE: list | None = None
ADAPTED_MAX_CHARS = 200_000     # the adapted shapes skip bigger texts (generated HTML, minified bundles: half the bytes, nearly all the time); the built-in shapes read everything


def adapted_shapes() -> list:
    """The provider shapes adapted from gitleaks (MIT; see the file's own `source`, `license`, `changes`): a list of dicts with
    the compiled `rx`, `id`, `name`, lowercase `kw` prefilter words and the `entropy` gate. A missing or broken file means no
    adapted shapes, never an error: the built-in list still runs."""
    global _SHAPES_CACHE
    if _SHAPES_CACHE is None:
        import json
        import warnings
        out = []
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)   # a Go pattern with `[[` draws a warning, not an error
                for r in json.loads(_SHAPES_FILE.read_text(encoding="utf-8")).get("rules", []):
                    try:
                        out.append({"id": r["id"], "name": r["name"], "rx": re.compile(r["regex"]), "kw": [k.lower() for k in r.get("keywords") or []],
                                    "entropy": r.get("entropy") or 0})
                    except (KeyError, re.error, TypeError):
                        continue
        except Exception:                                # a scanner that cannot load its extra shapes still runs its own
            out = []
        _SHAPES_CACHE = out
    return _SHAPES_CACHE


_DOC_URL_HOST = re.compile(r"(?i)(localhost|127\.0\.0\.1|0\.0\.0\.0|:(?:pass|password|secret|user|username|postgres|root)@)")
# CVE-2021-42574 (Trojan Source): bidirectional controls that make code read differently from what it does.
BIDI_CONTROLS = "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"
_BIDI_RE = re.compile("[" + BIDI_CONTROLS + "]")
_KEYED_VALUE = re.compile(r"""(?i)\b(api[_-]?key|secret|token|passw(?:or)?d|bearer|authorization|private[_-]?key)\b["']?\s*[:=]\s*["']?(?:(?:Bearer|Basic|Token)\s+)?([A-Za-z0-9+/_\-=.]{20,})""")
_PLACEHOLDER = re.compile(r"(?i)(x{4,}|\*{3,}|your|example|placeholder|changeme|redacted|dummy|sample|<|>|\$\{|\$\(|\{\{)")
ENTROPY_MIN = 3.5   # bits per character: a 20+ character value below this reads as words or a pattern, not a secret


def shannon_entropy(s: str) -> float:
    import math
    if not s:
        return 0.0
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in (s.count(ch) for ch in set(s)))


def scan_secrets(text: str, entropy: bool = True, hidden: bool = True, placeholders_ok: bool = False) -> list[tuple[str, int, str]]:
    """Findings of one text as (kind, line, detail). kind: `pattern:<n>` (a known credential shape), `entropy` (a high-entropy
    value assigned to a key named like a secret), `bidi` (a bidirectional control character), `bom` (a byte-order mark that is
    not the first character). Placeholders, environment references and low-entropy values are not findings.
    `placeholders_ok`: a credential-shaped match that reads as a placeholder (xxxx, your, example, <...>, a localhost or
    `:password@` database URL) is skipped too; the narrow scope keeps it off so an instruction file never hides one."""
    out: list[tuple[str, int, str]] = []
    line_of = lambda i: text.count("\n", 0, i) + 1
    for n, (pat, name) in enumerate(SECRET_PATTERNS):
        for m in re.finditer(pat, text):
            if placeholders_ok and (_PLACEHOLDER.search(m.group(0)) or any(s in m.group(0) for s in PUBLIC_SAMPLES)
                                    or (name.startswith("database URL") and _DOC_URL_HOST.search(m.group(0)))):
                continue
            out.append((f"pattern:{n}", line_of(m.start()), name))
    shapes = adapted_shapes() if len(text) <= ADAPTED_MAX_CHARS else []
    if shapes:
        low = text.lower()
        seen_lines = {ln for _k, ln, _d in out}          # a token the built-in list already names is not named twice
        for sh in shapes:
            if sh["kw"] and not any(k in low for k in sh["kw"]):
                continue
            for m in sh["rx"].finditer(text):
                ln = line_of(m.start())
                secret = m.group(1) if m.groups() and m.group(1) else m.group(0)
                if ln in seen_lines or (sh["entropy"] and shannon_entropy(secret) < sh["entropy"]):
                    continue
                if placeholders_ok and (_PLACEHOLDER.search(m.group(0)) or any(s in m.group(0) for s in PUBLIC_SAMPLES)):
                    continue
                out.append((f"pattern:gl-{sh['id']}", ln, f"{sh['name']} (gitleaks rule {sh['id']})"))
    if entropy:
        for m in _KEYED_VALUE.finditer(text):
            v = m.group(2)
            if not _PLACEHOLDER.search(v) and not _PLACEHOLDER.search(m.group(0)) and shannon_entropy(v) >= ENTROPY_MIN and not v.replace(".", "").isalpha():
                out.append(("entropy", line_of(m.start(2)), f"high-entropy value for {m.group(1).lower()} ({len(v)} chars, {shannon_entropy(v):.1f} bits/char)"))
    if hidden:
        for m in _BIDI_RE.finditer(text):
            out.append(("bidi", line_of(m.start()), f"bidirectional control U+{ord(m.group()):04X} (Trojan Source, CVE-2021-42574)"))
        i = text.find("\ufeff", 1)
        if i != -1:
            out.append(("bom", line_of(i), "byte-order mark inside the text"))
    return out


# People data (AD13 D7, HS-03): local shapes, warn only, for the people folder (audit.people_dir(); the folder name and the Arabic
# identity words come from _locale_ar, a release has English words only)
_ID_CONTEXT = re.compile("(?i)(" + "|".join([*(re.escape(w) for w in locale_value("ID_CONTEXT_WORDS", ())), "national id", "iqama", "id number"]) + ")")
_PII = [
    ("iban", re.compile(r"\bSA\d{2}(?:[ ]?[0-9A-Z]{4}){5}\b"), "Saudi IBAN"),
    ("mobile", re.compile(r"(?<![\d+])(?:\+?966|00966|0)5\d{8}(?!\d)"), "Saudi mobile number"),
]


def scan_pii(text: str) -> list[tuple[str, int, str]]:
    """Personal-data shapes of one text as (kind, line, detail): a Saudi IBAN, a Saudi mobile number, and a ten-digit number
    starting with 1 or 2 on a line that names an identity (hawiyya, civil registry, iqama, national id). Warn-only material."""
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        for kind, rx, name in _PII:
            if rx.search(line):
                out.append((kind, n, name))
        if _ID_CONTEXT.search(line) and re.search(r"(?<!\d)[12]\d{9}(?!\d)", line):
            out.append(("national-id", n, "ten-digit identity number"))
    return out


_ARABIC_RE = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufefe]")   # raw: the pattern is spelled out in ASCII, so this file holds no Arabic character


def arabic_in_python(source: str) -> list[tuple[int, str, str]]:
    """Arabic in Python source as (line, kind, text), found three ways so that nothing is hidden: in the tokens (comments, names,
    docstrings as written), in the decoded string values (a \\uXXXX escape that spells an Arabic letter is still Arabic), and in
    identifiers. U-40: the release's scripts must have none."""
    import ast
    import io
    import tokenize
    hits: list[tuple[int, str, str]] = []
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if _ARABIC_RE.search(tok.string):
            hits.append((tok.start[0], "token", tok.string[:60]))
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _ARABIC_RE.search(node.value):
            hits.append((getattr(node, "lineno", 0), "ast-string", node.value[:60]))
        elif isinstance(node, ast.Name) and _ARABIC_RE.search(node.id):
            hits.append((node.lineno, "ast-name", node.id))
    return hits


TEXT_SUFFIXES = {".md", ".py", ".json", ".yaml", ".yml", ".base", ".canvas", ".js", ".css", ".html", ".sh", ".ps1", ".cmd", ".toml", ".txt", ".cff", ".mdc", ".lock"}


def _is_secret_rules_file(f: Path, root: Path, skip_files: set[str]) -> bool:
    """True for the gitleaks detection rules catalog itself (exempted across tree/sub-tree scans), never user notes."""
    if f.relative_to(root).as_posix() in skip_files:
        return True
    if f.name == "secret-shapes.json" and f.parent.name == "schema":
        if f.parent.parent.name == "AI-Agent":
            return True
        try:
            if f.resolve() == _SHAPES_FILE.resolve():
                return True
        except OSError:
            pass
    return False


def scan_tree(root, skip_dirs=(".git", ".venv", "node_modules", "__pycache__"),
              skip_files=("AI-Agent/schema/secret-shapes.json",)) -> list[tuple[str, str, int, str]]:
    """[(relative path, kind, line, detail)] over every text file under `root`, for the release exporter and its --check."""
    root = Path(root)
    skip_set = set(skip_files or ())
    found = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or any(part in skip_dirs for part in f.relative_to(root).parts) or (f.suffix.lower() not in TEXT_SUFFIXES and f.name not in ("VERSION", "LICENSE")):
            continue
        if _is_secret_rules_file(f, root, skip_set):
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found += [(f.relative_to(root).as_posix(), k, ln, d) for k, ln, d in scan_secrets(text)]
    return found


def dump_yaml_block(data) -> str:
    """YAML for a generated file: block lists, original key order, real UTF-8 (P6)."""
    return yaml.safe_dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True, width=1000)


def resolve_classes(classes: dict) -> tuple[dict, list[tuple[str, str, str]]]:
    """Resolve `extends` in the frontmatter schema's classes (U-27). A child inherits its parent's `required` and
    `optional` keys as OPTIONAL keys (minus what it requires itself), so a key the parent requires, such as `area`,
    stays allowed in the child. `required`, `when` and `status_enum` are never inherited. Returns
    (resolved classes, [(rule, class, message)]): FM-schema-extends for an unknown parent, FM-schema-cycle for a loop;
    a broken class resolves as if it had no `extends`, so one bad entry never hides the others."""
    resolved: dict = {}
    problems: list[tuple[str, str, str]] = []

    def resolve(name: str, stack: tuple) -> dict:
        if name in resolved:
            return resolved[name]
        c = copy.deepcopy(classes[name])
        parent = c.pop("extends", None)
        if parent is not None:
            if parent not in classes:
                problems.append(("FM-schema-extends", name, f"unknown parent class {parent!r}"))
            elif parent == name or parent in stack:
                problems.append(("FM-schema-cycle", name, "extends loop: " + " -> ".join((*stack, name, parent))))
            else:
                p = resolve(parent, (*stack, name))
                own = set(c.get("required") or [])
                inherited = [k for k in [*(p.get("required") or []), *(p.get("optional") or [])] if k not in own]
                c["optional"] = list(dict.fromkeys([*(c.get("optional") or []), *inherited]))
        resolved[name] = c
        return c

    for n in classes:
        resolve(n, ())
    return resolved, problems


def class_of(path: str, fm: dict, classes: dict, unclassed_ok) -> str | None:
    """The schema class of one note. Order: frontmatter selectors (fm_in / fm_eq), then the longest `path_suffix`
    (Excalidraw files), then `unclassed_ok` (a note listed there has no class), then the longest `path_prefix`."""
    for name, c in classes.items():
        w = c.get("when", {})
        if "fm_in" in w and all(fm.get(k) in v for k, v in w["fm_in"].items()):
            return name
        if "fm_eq" in w and all(fm.get(k) == v for k, v in w["fm_eq"].items()):
            return name
    best, blen = None, -1
    for name, c in classes.items():
        for sfx in c.get("when", {}).get("path_suffix", []):
            if path.endswith(sfx) and len(sfx) > blen:
                best, blen = name, len(sfx)
    if best is not None:
        return best
    if any(path.startswith(p) for p in (unclassed_ok or [])):
        return None
    for name, c in classes.items():
        for p in c.get("when", {}).get("path_prefix", []):
            if path.startswith(p) and len(p) > blen:
                best, blen = name, len(p)
    return best


def validate_profile(profile) -> list[str]:
    """Return structural problems of a profile dict (empty list = valid)."""
    if not isinstance(profile, dict):
        return ["profile is not a mapping"]
    errs = []
    for key in profile:
        if key not in _PROFILE_DEFAULTS:
            errs.append(f"unknown key: {key}")
    if profile.get("mode") not in _PROFILE_MODES:
        errs.append(f"mode must be one of {_PROFILE_MODES}")
    if profile.get("language") not in _PROFILE_LANGS:
        errs.append(f"language must be one of {_PROFILE_LANGS}")
    for section, fields in _PROFILE_DEFAULTS.items():
        if not isinstance(fields, dict):
            continue
        got = profile.get(section)
        if not isinstance(got, dict):
            errs.append(f"{section} must be a mapping")
            continue
        for fk, dv in fields.items():
            if fk not in got:
                errs.append(f"{section}.{fk} missing")
            elif isinstance(dv, list) and not (isinstance(got[fk], list) and all(isinstance(x, str) for x in got[fk])):
                errs.append(f"{section}.{fk} must be a list of strings")
            elif isinstance(dv, str) and not isinstance(got[fk], str):
                errs.append(f"{section}.{fk} must be a string")
            elif isinstance(dv, int) and not (isinstance(got[fk], int) and not isinstance(got[fk], bool) and got[fk] >= 0):
                errs.append(f"{section}.{fk} must be a non-negative integer")
        for fk in got:
            if fk not in fields:
                errs.append(f"unknown key: {section}.{fk}")
    disabled = (profile.get("checks") or {}).get("disabled")
    if isinstance(disabled, list):
        bad = sorted(UNTOUCHABLE_CHECKS & set(disabled))
        if bad:
            errs.append(f"checks.disabled may not contain integrity checks: {bad}")
    return errs


def load_profile(vault: Path | None = None) -> dict:
    """Read AI-Agent/config/release_profile.yaml (+ the release patch when mode is release).
    A missing file yields the defaults (mode vault); a malformed one raises ValueError."""
    root = Path(vault) if vault is not None else VAULT
    path = root / PROFILE_REL
    if not path.is_file():
        return _merge_patch(_PROFILE_DEFAULTS, {})
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    profile = _merge_patch(_PROFILE_DEFAULTS, data)
    if profile.get("mode") == "release":
        patch = root / PATCH_REL
        if patch.is_file():
            profile = _merge_patch(profile, yaml.safe_load(patch.read_text(encoding="utf-8")) or {})
    errs = validate_profile(profile)
    if errs:
        raise ValueError("release_profile invalid: " + "; ".join(errs))
    return profile


# ---- tiktoken o200k cache (T-02d, U-45) -----------------------------------------
_O200K_URL = "https://openaipublic.blob.core.windows.net/encodings/o200k_base.tiktoken"
_O200K_SHA256 = "446a9538cb6c348e3516120d7c08b09f57c36495e2acfffe59a5bf8b0cfb1a2d"   # published hash of o200k_base.tiktoken


def default_tiktoken_cache_dir() -> Path:
    """TIKTOKEN_CACHE_DIR, else the per-user cache dir (same rule as AI-Agent/vault-python)."""
    if os.environ.get("TIKTOKEN_CACHE_DIR"):
        return Path(os.environ["TIKTOKEN_CACHE_DIR"])
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "tiktoken"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "tiktoken"


def _dedup_paths(candidates: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for p in candidates:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def goose_session_dirs(platform: str | None = None, env: dict | None = None, home: Path | None = None) -> list[Path]:
    """Candidate Goose sessions directories in precedence order across Linux, macOS, and Windows."""
    plat = platform if platform is not None else sys.platform
    env_map = env if env is not None else os.environ
    home_dir = Path(home) if home is not None else Path.home()
    cands: list[Path] = []
    if plat == "win32":
        appdata = Path(env_map["APPDATA"]) if env_map.get("APPDATA") else home_dir / "AppData" / "Roaming"
        localapp = Path(env_map["LOCALAPPDATA"]) if env_map.get("LOCALAPPDATA") else home_dir / "AppData" / "Local"
        cands.extend([
            appdata / "Block" / "goose" / "data" / "sessions",
            localapp / "goose" / "sessions",
            appdata / "goose" / "sessions",
            home_dir / ".local" / "share" / "goose" / "sessions",
        ])
    elif plat == "darwin":
        app_sup = home_dir / "Library" / "Application Support"
        cands.extend([app_sup / "Block" / "goose" / "sessions", app_sup / "goose" / "sessions"])
        if env_map.get("XDG_DATA_HOME"):
            cands.append(Path(env_map["XDG_DATA_HOME"]) / "goose" / "sessions")
        cands.append(home_dir / ".local" / "share" / "goose" / "sessions")
    else:
        if env_map.get("XDG_DATA_HOME"):
            cands.append(Path(env_map["XDG_DATA_HOME"]) / "goose" / "sessions")
        cands.append(home_dir / ".local" / "share" / "goose" / "sessions")
    return _dedup_paths(cands)


def goose_config_paths(platform: str | None = None, env: dict | None = None, home: Path | None = None) -> list[Path]:
    """Candidate Goose config.yaml paths in precedence order across Linux, macOS, and Windows."""
    plat = platform if platform is not None else sys.platform
    env_map = env if env is not None else os.environ
    home_dir = Path(home) if home is not None else Path.home()
    cands: list[Path] = []
    if plat == "win32":
        appdata = Path(env_map["APPDATA"]) if env_map.get("APPDATA") else home_dir / "AppData" / "Roaming"
        localapp = Path(env_map["LOCALAPPDATA"]) if env_map.get("LOCALAPPDATA") else home_dir / "AppData" / "Local"
        cands.extend([
            appdata / "Block" / "goose" / "config" / "config.yaml",
            localapp / "goose" / "config.yaml",
            home_dir / ".config" / "goose" / "config.yaml",
        ])
    elif plat == "darwin":
        cands.append(home_dir / "Library" / "Application Support" / "Block" / "goose" / "config" / "config.yaml")
        if env_map.get("XDG_CONFIG_HOME"):
            cands.append(Path(env_map["XDG_CONFIG_HOME"]) / "goose" / "config.yaml")
        cands.append(home_dir / ".config" / "goose" / "config.yaml")
    else:
        if env_map.get("XDG_CONFIG_HOME"):
            cands.append(Path(env_map["XDG_CONFIG_HOME"]) / "goose" / "config.yaml")
        cands.append(home_dir / ".config" / "goose" / "config.yaml")
    return _dedup_paths(cands)


def session_db_path() -> Path:
    """The agent harness's sessions.db: STRATUM_SESSION_DB, explicit XDG_DATA_HOME override, else first existing cross-platform Goose dir."""
    if os.environ.get("STRATUM_SESSION_DB"):
        return Path(os.environ["STRATUM_SESSION_DB"])
    if os.name != "nt" and os.environ.get("XDG_DATA_HOME"):
        return Path(os.environ["XDG_DATA_HOME"]) / "goose" / "sessions" / "sessions.db"
    dirs = goose_session_dirs()
    for d in dirs:
        cand = d / "sessions.db"
        if cand.is_file():
            return cand
    return dirs[0] / "sessions.db"


def ensure_o200k_cache(timeout: float = 15.0, retries: int = 3, sleeper=None) -> bool:
    """True when the o200k_base vocabulary is in the tiktoken cache with the published hash.
    Always exports TIKTOKEN_CACHE_DIR when unset so tiktoken shares the vault cache dir instead of /tmp."""
    import hashlib
    import tempfile
    import urllib.request

    cache = default_tiktoken_cache_dir()
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(cache))
    target = cache / hashlib.sha1(_O200K_URL.encode("utf-8")).hexdigest()   # tiktoken's own cache key
    tmp: str | None = None
    try:
        if target.is_file():
            return hashlib.sha256(target.read_bytes()).hexdigest() == _O200K_SHA256
        if os.environ.get("STRATUM_SKIP_NET") == "1":
            return False
        with urllib.request.urlopen(_O200K_URL, timeout=timeout) as resp:   # noqa: S310 (fixed https URL)
            data = resp.read()
        if hashlib.sha256(data).hexdigest() != _O200K_SHA256:
            return False
        cache.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(cache), prefix=".o200k-")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        wait_fn = sleeper or time.sleep
        for n in range(retries):
            try:
                os.replace(tmp, target)
                tmp = None
                return True
            except PermissionError:
                if n == retries - 1:
                    raise
                wait_fn(0.1 * (n + 1))
        return False
    except Exception:
        return False
    finally:
        if tmp and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def run_utf8(cmd, *, cwd=None, env=None, timeout=None, input=None, check: bool = False) -> subprocess.CompletedProcess:
    """Run a subprocess capturing UTF-8 text safely across Windows (cp1252/cp1256), macOS, and Linux."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        input=input,
        check=check,
    )


def run_git(repo, *args, env=None, timeout: float | None = 30, check: bool = False) -> subprocess.CompletedProcess:
    """Run git in `repo` with -c core.quotepath=off and UTF-8 stdio so non-ASCII filenames never turn into octal escapes."""
    return run_utf8(
        ["git", "-C", str(repo), "-c", "core.quotepath=off", *args],
        env=env,
        timeout=timeout,
        check=check,
    )


def sqlite_ro_uri(db_path: Path | str) -> str:
    """Build a cross-platform SQLite read-only file URI (safe with spaces and Windows drive letters)."""
    return f"{Path(db_path).resolve().as_uri()}?mode=ro"


# ---- shared CLI contract (T-02e, U-47) ---------------------------------------------
def force_utf8_stdio() -> None:
    """Make stdout/stderr UTF-8 with replacement, so a cp1252 console prints Arabic instead of raising (U-33)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def standard_parser(doc: str | None, prog: str | None = None):
    """The one parser every tool starts from: -h/--help exits 0 with the module docstring and no side effect,
    an unknown flag exits 2 with the message on stderr (argparse's own behavior, kept on purpose)."""
    import argparse
    text = (doc or "").strip()
    return argparse.ArgumentParser(prog=prog, description=text.splitlines()[0] if text else None,
                                   epilog=text or None, formatter_class=argparse.RawDescriptionHelpFormatter)


def _deprecated_action():
    import argparse

    class DeprecatedFlagAction(argparse.Action):
        """A renamed flag: still accepted, warns once on stderr, stores into the new flag's dest.
        Expand-Contract: ship `--new` and `DeprecatedFlagAction` for `--old`, drop `--old` in a later release."""

        def __init__(self, option_strings, dest, new_flag=None, new_dest=None, nargs=None, **kw):
            self.new_flag = new_flag
            super().__init__(option_strings, new_dest or dest, nargs=nargs if nargs is not None else 0, **kw)

        def __call__(self, parser, namespace, values, option_string=None):
            hint = f"; use {self.new_flag}" if self.new_flag else ""
            print(f"warning: {option_string} is deprecated{hint}", file=sys.stderr)
            setattr(namespace, self.dest, True if self.nargs == 0 else values)

    return DeprecatedFlagAction


DeprecatedFlagAction = _deprecated_action()


def cli_migration_error(old: str, new: str, since: str = "") -> None:
    """A removed flag or command: one line on stderr naming the replacement, exit 2 (the same code as an unknown flag)."""
    tail = f" (removed in {since})" if since else ""
    print(f"error: {old} no longer exists{tail}; use {new}", file=sys.stderr)
    raise SystemExit(2)
