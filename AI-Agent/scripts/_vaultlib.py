# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Shared helpers for vault-sandbox scripts: structural Markdown parsing (markdown-it-py: CommonMark + tables + front matter). Import: from _vaultlib import *"""

from __future__ import annotations

import bisect
import copy
import os
import re
import sys
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Iterator, NamedTuple

import yaml
from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

VAULT = Path(os.environ.get("VAULT", "/vault"))
SKIP_DIRS = {".git", ".obsidian", ".trash", "node_modules", ".venv", ".vault-release"}

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
    return _TASHKEEL.sub("", text).translate(_MAP).casefold()


def is_readme(path) -> bool:
    return Path(path).name.lower() == "readme.md"


def iter_md(prefix: str = "", include_readme: bool = False) -> Iterator[Path]:
    """Yield markdown files under /vault/<prefix>, skipping system folders and (by default) README.md files."""
    for dirpath, dirnames, filenames in os.walk(VAULT / prefix):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            if f.endswith(".md") and (include_readme or not is_readme(f)):
                yield Path(dirpath) / f


def rel(path) -> str:
    return str(Path(path).relative_to(VAULT))


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
            try:
                loaded = yaml.safe_load(fm_raw) if fm_raw.strip() else {}
                if isinstance(loaded, dict):
                    fm = loaded
                elif loaded is not None:
                    fm_error = "front matter is not a mapping"
            except yaml.YAMLError as e:
                fm_error = str(e).splitlines()[0]
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
        loaded = yaml.safe_load(fm_raw) if fm_raw.strip() else {}
        return list(loaded.keys()) if isinstance(loaded, dict) else []
    except yaml.YAMLError:
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


def leaf_sections(text: str) -> list[dict]:
    """Own content of each heading (until the next heading of ANY level): bytes, lines and table/code share."""
    d = parse(text)
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


def inline_texts(text: str) -> Iterator[tuple[int, str]]:
    """Yield (line_1based, prose) for every inline block, with code spans removed and line breaks kept as \\n."""
    for t in parse(text).tokens:
        if t.type == "inline" and t.map:
            s = "".join(c.content if c.type == "text" else "\n" for c in (t.children or [])
                        if c.type in ("text", "softbreak", "hardbreak"))
            if s.strip():
                yield t.map[0] + 1, s


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


INDEX_DB_PATH = VAULT / "AI-Agent" / "state" / "vault-index.sqlite3"


def get_vault_index_db(db_path: Path | None = None) -> Any:
    """Return an open SQLite connection to the unified vault-index database with WAL mode."""
    import sqlite3
    p = db_path or INDEX_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
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
    conn.commit()


def invalidate_audit_cache_if_stale(conn: Any, **fingerprints: str) -> bool:
    """Drop every audit_cas_cache row when any stored fingerprint (profile_sha1, schema_sha1, ...) differs
    from the current one, then store the current ones. True when the cache was invalidated.
    The first run (nothing stored) counts as stale: a cache of unknown provenance is not trusted."""
    stored = dict(conn.execute("SELECT key, value FROM cache_meta").fetchall())
    stale = any(stored.get(k) != v for k, v in fingerprints.items())
    if stale:
        conn.execute("DELETE FROM audit_cas_cache")
        conn.executemany("INSERT OR REPLACE INTO cache_meta (key, value) VALUES (?, ?)", list(fingerprints.items()))
        conn.commit()
    return stale


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
]
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


def scan_secrets(text: str, entropy: bool = True, hidden: bool = True) -> list[tuple[str, int, str]]:
    """Findings of one text as (kind, line, detail). kind: `pattern:<n>` (a known credential shape), `entropy` (a high-entropy
    value assigned to a key named like a secret), `bidi` (a bidirectional control character), `bom` (a byte-order mark that is
    not the first character). Placeholders, environment references and low-entropy values are not findings."""
    out: list[tuple[str, int, str]] = []
    line_of = lambda i: text.count("\n", 0, i) + 1
    for n, (pat, name) in enumerate(SECRET_PATTERNS):
        for m in re.finditer(pat, text):
            out.append((f"pattern:{n}", line_of(m.start()), name))
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


def scan_tree(root, skip_dirs=(".git", ".venv", "node_modules", "__pycache__")) -> list[tuple[str, str, int, str]]:
    """[(relative path, kind, line, detail)] over every text file under `root`, for the release exporter and its --check."""
    root = Path(root)
    found = []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or any(part in skip_dirs for part in f.relative_to(root).parts) or (f.suffix.lower() not in TEXT_SUFFIXES and f.name not in ("VERSION", "LICENSE")):
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


def session_db_path() -> Path:
    """The agent harness's sessions.db: STRATUM_SESSION_DB, else XDG_DATA_HOME / LOCALAPPDATA, else ~/.local/share.
    Callers open it read-only and treat a missing file as "no session data"."""
    if os.environ.get("STRATUM_SESSION_DB"):
        return Path(os.environ["STRATUM_SESSION_DB"])
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"])
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "goose" / "sessions" / "sessions.db"


def ensure_o200k_cache(timeout: float = 15.0) -> bool:
    """True when the o200k_base vocabulary is in the tiktoken cache with the published hash.
    A missing file is downloaded once (bounded by `timeout`, hash-checked, written atomically) unless
    STRATUM_SKIP_NET=1; any failure returns False so callers fall back to their no-tiktoken estimate
    instead of hanging or trusting an unverified file."""
    import hashlib
    cache = default_tiktoken_cache_dir()
    target = cache / hashlib.sha1(_O200K_URL.encode("utf-8")).hexdigest()   # tiktoken's own cache key
    try:
        if target.is_file():
            return hashlib.sha256(target.read_bytes()).hexdigest() == _O200K_SHA256
        if os.environ.get("STRATUM_SKIP_NET") == "1":
            return False
        import tempfile
        import urllib.request
        with urllib.request.urlopen(_O200K_URL, timeout=timeout) as resp:   # noqa: S310 (fixed https URL)
            data = resp.read()
        if hashlib.sha256(data).hexdigest() != _O200K_SHA256:
            return False
        cache.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(cache))
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
        return True
    except Exception:
        return False


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
