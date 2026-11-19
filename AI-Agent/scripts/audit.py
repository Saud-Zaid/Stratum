# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Vault structure audit (T04/T05): R1 dup headings, R3 depth, R4 leaf size, R5 heading chars, R6 internal numeric refs, R7 H1, R8 nested headings, R12 heading links, R13 link corruption, FM yaml/team, D3 fixed-schema, D14 waivers, RG trap registry, ADR fitness (incl. ADR-011 retired system path), DEF deferrals (package Y), CLUB ExampleClub club rules (club_rules.py), ARCH architecture card rules (arch_rules.py). Usage: audit [--check headings,size,refs,links,frontmatter,schema,waivers,registry,config,def,club,arch,g06,t1,inj] [--baseline PATH] [--ratchet] [--path P] [--new-since REV] [--min info|warn|error] [--limit N] [--leaf-max BYTES]"""


from __future__ import annotations

import argparse
import collections
import os
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from _vaultlib import ALLOWED_THIRD_PARTY, SCHEMA_UNITS, script_import_roots, unapproved_imports, alternation, class_of, locale_value, resolve_classes, scan_secrets, scan_pii, force_utf8_stdio, sqlite_ro_uri, PROFILE_REL, ensure_o200k_cache, file_sha1, audit_cache_fingerprint_check, code_fingerprint, preload_inline, doc_to_meta, doc_from_meta, invalid_utf8, broken_md_symlinks, UNTOUCHABLE_CHECKS, VAULT, SKIP_DIRS, _PROFILE_DEFAULTS, load_profile, inline_texts, iter_md, leaf_sections, normalize_ar, parse, read, rel

_PROFILE_CACHE: dict = {}


def optional_module(name: str):
    """A mother-vault module (the club and architecture rules) or None when this tree does not ship it."""
    import importlib
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name == name:
            return None
        raise


def _profile_cached() -> dict:
    """The release profile for the current VAULT (read once per vault path; a broken one yields the defaults)."""
    key = str(VAULT)
    if key not in _PROFILE_CACHE:
        try:
            _PROFILE_CACHE[key] = load_profile(VAULT)
        except ValueError:
            _PROFILE_CACHE[key] = _PROFILE_DEFAULTS
    return _PROFILE_CACHE[key]


NON_NOTE_SUFFIXES = (".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".env", ".sh", ".txt", ".js", ".ts", ".html", ".cmd", ".ps1", ".csv")


def _non_note_texts():
    """(relative path, text) of the text files that are not notes: git's tracked and not-ignored files when the vault is a
    repository (an ignored local token file is never scanned or committed), else a walk without the system folders.
    Over 1 MB, AI-Agent/state (run data), .obsidian (third-party plugin code) and the shapes file are left out."""
    import subprocess
    names = []
    if (VAULT / ".git").exists():
        try:
            for extra in ((), ("--others", "--exclude-standard")):
                names += subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-z", *extra], cwd=VAULT, capture_output=True, timeout=60).stdout.decode("utf-8", "replace").split("\0")
        except (OSError, subprocess.SubprocessError):
            names = []
    if not names:
        for dp, dn, fn in os.walk(VAULT):
            dn[:] = [d for d in dn if d not in SKIP_DIRS and d != "__pycache__"]
            names += [rel(Path(dp) / f) for f in fn]
    for nme in sorted(set(names)):
        if (not nme or not nme.lower().endswith(NON_NOTE_SUFFIXES) or nme.startswith(("AI-Agent/state/", ".obsidian/"))
                or nme == "AI-Agent/schema/secret-shapes.json"):          # run data, third-party plugin code, and the shapes file itself
            continue
        try:
            p = VAULT / nme
            if p.stat().st_size > 1_000_000:
                continue
            data = p.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue
        yield nme, data.decode("utf-8", "replace")


def is_vault_owner(text: str) -> bool:
    """True when `text` names the vault owner (profile owner.name or any alias, Arabic-normalized)."""
    prof = _profile_cached()["owner"]
    norm, low = normalize_ar(text), text.lower()
    return any(n and (normalize_ar(n) in norm or n.lower() in low) for n in [prof["name"], *prof["aliases"]])


def caps_doc() -> str:
    """The tools-and-capabilities document trap registry tools are checked against (profile paths.capabilities_doc)."""
    return _profile_cached()["paths"]["capabilities_doc"] or CAPS


def people_dir() -> str:
    """Folder (vault-relative, no trailing slash) that holds the person notes (profile paths.people_dir)."""
    return (_profile_cached()["paths"]["people_dir"] or locale_value("PEOPLE_DIR", "02-Areas/People")).rstrip("/")


SEV = {"info": 0, "warn": 1, "error": 2}
CHECKS = ["headings", "size", "refs", "links", "frontmatter", "schema", "waivers", "registry", "adr", "due", "config", "def", "club", "arch", "g06", "t1", "inj", "contract", "s13", "s16", "s17", "g13", "sigkey", "katex", "livedoc", "args_contract", "consumer_drift", "secrets", "commitref", "gatehash"]
# gate integrity anchor (2026-10-23, AD10 C14, owner approval): the CHECKS list
# is pinned in AI-Agent/gate_baseline.json. The pre-commit hook runs this audit;
# if someone silently strips checks from CHECKS above, the anchor mismatch
# below fails the commit -- the guard cannot be blinded by editing itself
# alone. Adding/removing a check requires updating gate_baseline.json in the
# same commit (visible in git diff). Threat model = drift, not full adversary:
# a deliberate multi-file tamper stays visible in git history (declared limit).
import json as _json
try:
    with open(VAULT / "AI-Agent" / "gate_baseline.json", encoding="utf-8") as _gb:
        _pinned = set(_json.load(_gb).get("pinned_checks", []))
    if _pinned != set(CHECKS):
        print(f"GATE BLOCKED blocking=1")
        print(f"BLOCK\terror\tGATE-CHECKS-tampered\tAI-Agent/scripts/audit.py:1\tgate-anchor\tCHECKS diverges from gate_baseline.json: missing={sorted(_pinned - set(CHECKS))} added={sorted(set(CHECKS) - _pinned)}")
        sys.exit(1)
except FileNotFoundError:
    print("GATE BLOCKED blocking=1")
    print("BLOCK\terror\tGATE-anchor-missing\tAI-Agent/gate_baseline.json:1\tgate-anchor\tgate integrity anchor file missing -- trust root unguarded")
    sys.exit(1)
SKIP_PREFIXES = ("AI-Agent/fixtures/", "AI-Agent/release-overlay/", "export/")          # tool-behaviour test data (T05 R11); the card template's export (T-21)
ADR_FILE = "03-Resources/Architecture-Decision-Records.md"
GUIDE = "03-Resources/Second-Brain-User-Guide.md"
SCHEMA_FILE = "AI-Agent/schema/frontmatter.yaml"                                  # ADR-012
TOC_OPTIONS = ["style: nestedList", "minLevel: 2", "maxLevel: 2", "exclude:"]   # ADR-008 R19
HACK_PREFIXES = ("gen-", "crit-", "dev-", "pitch-")                              # ADR-003
# ADR-006 as amended (2026-10-19, AD06 C6 F3): schema/ units are vault-local too — read-only
# consumers in scripts/ may import them; ledger writes stay behind the mediator (S13 guard).
ADR_ARTIFACTS = {                                                                # ADR-002
    **({locale_value("RELATIONSHIPS_NOTE"): "the relationships Area note"} if locale_value("RELATIONSHIPS_NOTE") else {}),
    "Templates/Person.md": "the Person template",
}
CAPS = "03-Resources/Agent-Capabilities.md"
FORBIDDEN = ["::", "^", "|", "[[", "]]"]
_DG = "0-9" + locale_value("DIGIT_RANGE", "")                                       # ASCII digits, plus the Eastern Arabic-Indic ones where the locale has them
NUMREF = re.compile(alternation(locale_value("NUMREF_WORDS", [])) + r"\s*\(?\s*[" + _DG + r"]+(?:\s*[-–]\s*[" + _DG + r"]+)?")
RANGE = re.compile(r"[" + _DG + r"]\s*[-–]\s*[" + _DG + r"]")
R19_SKIP = ("Templates/", "card-template/", "AI-Agent/fixtures/", "AI-Agent/handoff/research/")   # placeholders, samples, raw research (AD13 E1)
R20_SKIP = R19_SKIP + ("04-Archive/", "AI-Agent/scratch/", "AI-Agent/state/", "AI-Agent/skills/")
R20_GENERATED = ("AI-Agent/state/", "AI-Agent/scratch/", "AI-Agent/gate/", "AI-Agent/logs/", "AI-Agent/data/")   # derived or ignored: absent in a fresh checkout
R20_PLANNED = re.compile(r"\b(planned|proposed|future|new|renamed|old name|retired|deleted|removed)\b" + "".join("|" + w for w in locale_value("R20_PLANNED_WORDS", ())), re.I)
R20_TOP = None
# AD13 E1 prior-art retrofit (MkDocs validation classes `not_found`, `absolute_links`, `unrecognized_links`): inline Markdown links
_ABS_DEST = re.compile(r"\]\(\s*(<[^>\n]*>?|[^)\n]*)")
_ABS_START = re.compile(r"(?i)^(file:|/(?:home|Users|mnt|tmp|var|opt)/|[A-Za-z]:[\\/])")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


_REL_LINK = re.compile(r"\]\(\s*(<[^>\n]+>|[^)\s]+)(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
BACKTICK = re.compile(r"`([^`\n]+)`")
WIKILINK = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]*)?\]\]")
NUMPREFIX = re.compile(r"^\s*[" + _DG + r"]+\s*[).\-]\s*")
DUE = re.compile(r"^\s*[-*+]\s*\[ \].*\U0001F4C5\s*(\d{4}-\d{2}-\d{2})")   # Tasks-plugin due date on an open item
DEF_ID = re.compile(r"\[id::\s*(D-\d+)\]")                                         # package Y: deferral item id
DEF_SNOOZE = re.compile(r"\[snoozed::\s*(\d+)\]")
DEF_WORD = re.compile(r"(?<!\w)" + alternation(locale_value("DEF_WORDS", [])) + r"(?!\w)|\blater\b", re.I)   # standalone words only (not the Arabic noun for "the deferrals"); after TASHKEEL strip
DEF_BLOCK_START = re.compile(r"^\s*(?:[-*+]\s|\d+[.)]\s|[|>#])")                  # each list item / row / quote / heading is its own unit
DEF_SPEC_TAGS = {"task-spec", "system-design"}                                   # DEF-untracked scope (spec Open 3)
TASHKEEL = re.compile(r"[\U0000064B-\U00000652\U00000670]")                       # 8-digit escapes: the write path decodes \u
LETTER = re.compile(r"[A-Za-z\U00000621-\U0000063A\U00000641-\U0000064A]")
_OLP = locale_value("ONE_LETTER_PREFIXES", "")
ONE_LETTER_PREFIX = re.compile(r"(?:^|[^A-Za-z\U00000621-\U0000063A\U00000641-\U0000064A])[" + re.escape(_OLP) + r"]$") if _OLP else re.compile(r"(?!)")   # a one-letter Arabic prefix before a link is legitimate
SYSTEM_DIR = SCHEMA_FILE.split("/", 1)[0]                                         # ADR-011: the system folder, spelled once
_OLD_PATH = None


def yaml_dup_keys(text: str) -> list[tuple]:
    """[(line, key, first line)] for every key repeated inside one YAML mapping (AD02 D10, K16)."""
    import yaml
    out = []

    def walk(node):
        if isinstance(node, yaml.MappingNode):
            seen = {}
            for k, v in node.value:
                if isinstance(k, yaml.ScalarNode):
                    if k.value in seen:
                        out.append((k.start_mark.line + 1, k.value, seen[k.value]))
                    else:
                        seen[k.value] = k.start_mark.line + 1
                walk(v)
        elif isinstance(node, yaml.SequenceNode):
            for x in node.value:
                walk(x)

    walk(yaml.compose(text))
    return out


def trap_registry() -> str:
    """ADR-007 registry prefix, read from the schema's trap class (single source). Raises if unreadable."""
    import yaml
    s = yaml.safe_load((VAULT / SCHEMA_FILE).read_text(encoding="utf-8"))
    p = s["classes"]["trap"]["when"]["path_prefix"]
    if not (isinstance(p, list) and len(p) == 1 and isinstance(p[0], str) and p[0].endswith("/")):
        raise ValueError(f"classes.trap.when.path_prefix must be one folder ending in '/', got {p!r}")
    return p[0]


def old_path_re():
    """ADR-011: the retired `Claude/` folder followed by a name that exists in the system folder today."""
    global _OLD_PATH
    if _OLD_PATH is None:
        root = VAULT / SYSTEM_DIR
        names = sorted((p.name for p in root.iterdir()), key=len, reverse=True) if root.is_dir() else []
        alt = "|".join(map(re.escape, names)) or "(?!)"
        _OLD_PATH = re.compile(r"(?<![\w./-])Claude/(?:" + alt + r")(?![\w-])")
    return _OLD_PATH


def git(*args):
    # core.quotepath=off: git otherwise prints a non-ASCII path as "\331\205..." and no changed Arabic-named note matches (--new-since)
    r = subprocess.run(["git", "-C", str(VAULT), "-c", "core.quotepath=off", *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout if r.returncode == 0 else None


class Ctx:
    def __init__(self, texts, docs):
        self.docs = docs
        self.stems = collections.defaultdict(list)
        for r in texts:
            self.stems[r.rsplit("/", 1)[-1][:-3].casefold()].append(r)
        self.stem_norms = {normalize_ar(s) for s in self.stems}
        self._assets = None

    def resolve(self, note: str, source: str):
        if not note.strip():
            return [source]
        return self.stems.get(note.strip().rsplit("/", 1)[-1].casefold(), [])

    def exists(self, target: str) -> bool:
        """Does a wikilink target (no fragment, no alias) name a note or a non-markdown file of the vault?
        Obsidian matches by file name, case-insensitively; a path form matches by its last component (AD13 E1)."""
        t = target.strip().rstrip("\\").strip()
        if not t:
            return True
        last = t.rsplit("/", 1)[-1].casefold()
        if last in self.stems or (last.endswith(".md") and last[:-3] in self.stems):
            return True
        if self._assets is None:   # every file name of the vault, README.md included (the audit's own text map leaves READMEs out)
            self._assets = set()
            for dirpath, dirnames, filenames in os.walk(VAULT):
                dirnames[:] = [x for x in dirnames if x not in SKIP_DIRS]
                for f in filenames:
                    self._assets.add(f.casefold())
                    if f.endswith(".md"):
                        self._assets.add(f[:-3].casefold())
        return last in self._assets


def findings_for(path_rel: str, text: str, checks: set, leaf_max: int, ctx: Ctx | None = None, d=None) -> list[tuple]:
    d = d if d is not None else parse(text)
    fixed = "table" in d.fm
    out = []

    def add(sev, rule, line, key, detail=""):
        out.append((sev, rule, path_rel, line, key, detail))

    if "frontmatter" in checks:
        if d.fm_error:
            add("error", "FM-yaml", 1, "yaml", d.fm_error)
        else:
            team_val = d.fm.get("team")
            if team_val is not None:
                if not isinstance(team_val, list):
                    add("error", "FM-team-format", 1, "team", "team must be a list of members")
                else:
                    for member in team_val:
                        if isinstance(member, list):
                            add("error", "FM-team-link", 1, str(member), "unquoted wikilink in YAML parsed as nested list: wrap in quotes e.g. \"[[...]]\"")
                            continue
                        m_str = str(member).strip()
                        if path_rel.startswith("Templates/") and "<%" in m_str:
                            continue
                        if is_vault_owner(m_str):
                            continue
                        m = WIKILINK.match(m_str)
                        if not m:
                            add("error", "FM-team-link", 1, m_str, f"external teammate must be a wikilink [[...]] to {people_dir()}/ (vault owner exempted)")
                            continue
                        if ctx is not None:
                            target = m.group(1).strip()
                            resolved = ctx.resolve(target, path_rel)
                            if not resolved:
                                add("error", "FM-team-missing", 1, target, f"teammate note not found: {target}")
                            elif not any(p.startswith(people_dir() + "/") for p in resolved):
                                add("error", "FM-team-location", 1, target, f"teammate note must reside in {people_dir()}/: {resolved[0]}")
    if "headings" in checks:
        groups = collections.defaultdict(list)
        siblings_only = path_rel in _profile_cached()["markdown"]["md024_siblings_only_files"]   # MD024 siblings_only: a repeat under another parent is fine (a changelog's "### Added")
        stack: list = []
        for h in d.headings:
            while stack and stack[-1].level >= h.level:
                stack.pop()
            parent = id(stack[-1]) if stack else 0
            stack.append(h)
            groups[(normalize_ar(h.title.strip()), parent, h.level) if siblings_only else normalize_ar(h.title.strip())].append(h)
            for ch in FORBIDDEN:
                if ch in h.plain:
                    add("warn", "R5-char", h.line, h.title, ch)
            if "#" in h.plain:
                add("warn", "R5-hash", h.line, h.title, "# outside code")
            if h.level >= 4 and not fixed:
                add("info", "R3-depth", h.line, h.title, f"H{h.level}")
        for hs in groups.values():
            if len(hs) > 1:
                add("error", "R1-dup", hs[1].line, hs[0].title, "lines " + ",".join(str(x.line) for x in hs))
        h1 = sum(1 for h in d.headings if h.level == 1)
        if h1 > 1:
            add("warn", "R7-h1", 1, "h1", f"{h1} H1 headings")
        if d.nested_headings:
            add("info", "R8-nested", d.nested_headings[0].line, "nested", f"{len(d.nested_headings)} headings inside quotes/lists (not targetable)")
    if "size" in checks:
        for s in leaf_sections(text, d):
            if s["bytes"] > leaf_max:
                if s["atomic_share"] >= 0.6:
                    add("info", "R4-atomic", s["line"], s["title"], f"{s['bytes']}B, table/code {s['atomic_share']:.0%}")
                else:
                    add("warn", "R4-leaf", s["line"], s["title"], f"{s['bytes']}B {s['lines']}L")
    prose = list(inline_texts(text))
    if "refs" in checks and not fixed:
        stems = ctx.stem_norms if ctx is not None else set()
        for line, p in prose:
            p_norm = None
            for m in NUMREF.finditer(p):
                if "[[" in p:
                    internal = True
                else:
                    if p_norm is None:
                        p_norm = normalize_ar(p)
                    internal = any(n and n in p_norm for n in stems if len(n) > 4)
                key = normalize_ar(p[max(0, m.start() - 25):m.end() + 10])
                if RANGE.search(m.group(0)):
                    # R9 removed heading numbering, so a bare numeric range no longer resolves to anything
                    add("warn", "R6-range", line, key, m.group(0) + " (R15: use a computed reference, e.g. every H2 in this file)")
                elif locale_value("LESSON_WORD") and locale_value("LESSON_WORD") in m.group(0):
                    add("info", "R6-lesson", line, key, m.group(0) + " (append-only id, linkable after T13)")
                else:
                    add("warn" if internal else "info", "R6-numref" if internal else "R6-external", line, key, m.group(0))
    if "links" in checks:
        raw = text.splitlines()
        for n in sorted(d.table_lines):
            if n <= len(raw) and re.search(r"\[\[[^\]]*(?<!\\)\|[^\]]*\]\]", raw[n - 1]):
                add("warn", "R14-table-alias", n, normalize_ar(raw[n - 1][:60]), "aliased link inside a table: escape | as \\| or the cell splits")
        for line, p in prose:
            # table cells are split on | before inline parsing, so bracket balance is checked on the raw line (R14)
            for k, ln in enumerate([] if line in d.table_lines else p.split("\n")):
                here = line + k
                if ln.count("[[") != ln.count("]]"):
                    add("error", "R13-unbalanced", here, normalize_ar(ln[:60]), f"{ln.count('[[')} [[ vs {ln.count(']]')} ]]")
                for m in re.finditer(r"\[\[", ln):
                    before = ln[:m.start()]
                    if before and LETTER.match(before[-1]) and not ONE_LETTER_PREFIX.search(before):
                        add("error", "R13-glued", here, normalize_ar(ln[max(0, m.start() - 15):m.start() + 25]), "letter before [[")
                for m in re.finditer(r"\]\]", ln):
                    if LETTER.match(ln[m.end():m.end() + 1]):
                        add("error", "R13-glued", here, normalize_ar(ln[max(0, m.start() - 25):m.end() + 10]), "letter after ]]")
            for m in WIKILINK.finditer(p):
                target = m.group(1)
                if ctx is not None and not path_rel.startswith(R19_SKIP) and "<%" not in target and "{{" not in target:
                    note_only = target.partition("#")[0]
                    if (note_only.strip() and re.search(r"\w", note_only) and not is_vault_owner(note_only.strip())
                            and not ctx.exists(note_only)):
                        add("info" if path_rel.startswith("04-Archive/") else "warn", "R19-missing-note",
                            line + p[:m.start()].count("\n"), target, "no file with this name in the vault (an alias does not resolve a link)")
                if "#" not in target or "#^" in target:
                    continue
                note, _, frag = target.partition("#")
                line_here = line + p[:m.start()].count("\n")
                if "#" in frag:
                    add("error", "R12-nested", line_here, target, "nested-path heading link is not rewritten by rename_heading (TR-0017)")
                if ctx is not None:
                    paths = ctx.resolve(note, path_rel)
                    if len(paths) != 1 or paths[0] not in ctx.docs:
                        continue    # note-level resolution is reliable in find_broken_links (TR-0018)
                    heads = {h.title.strip() for h in ctx.docs[paths[0]].headings}
                    if frag.split("#")[-1].strip() not in heads:
                        add("error", "R12-missing", line_here, target, "heading not found in target note")
        if ctx is not None and not path_rel.startswith(R19_SKIP):
            sev = "info" if path_rel.startswith("04-Archive/") else "warn"
            bad_dest = {}            # kind -> [first line, first destination, count]: one finding per kind and note, with its count
            import urllib.parse as _up
            for n, ln in enumerate(raw, 1):                # raw lines and code_lines, like R20: the same answer with or without the parse cache
                if n in d.code_lines or "](" not in ln:
                    continue
                ln = re.sub(r"`[^`\n]*`", "", ln)
                for m in _ABS_DEST.finditer(ln):
                    dest = m.group(1).strip()
                    inner = dest[1:].rstrip(">") if dest.startswith("<") else dest
                    if not _ABS_START.match(inner):
                        continue
                    if dest.startswith("<"):
                        kind = "absolute"
                    else:
                        kind = "malformed" if re.search(r"\s", dest) or dest.count("(") != dest.count(")") else "absolute"
                    if kind in bad_dest:
                        bad_dest[kind][2] += 1
                    else:
                        bad_dest[kind] = [n, inner[:70], 1]
                for m in _REL_LINK.finditer(ln):
                    href = m.group(1).strip()
                    href = href[1:-1].strip() if href.startswith("<") and href.endswith(">") else href
                    if not href or href.startswith("#") or _SCHEME.match(href) or href.startswith("//") or _ABS_START.match(href) or "<%" in href or "{{" in href:
                        continue
                    tpath = _up.unquote(href.split("#")[0].split("?")[0]).strip()
                    if not tpath or re.search(r"[<>*{}$|]|\.\.\.", tpath):
                        continue
                    stem_only = "." not in Path(tpath).name
                    if (VAULT / path_rel).parent.joinpath(tpath).exists() or (VAULT / tpath).exists() or (stem_only and ctx.exists(tpath)):
                        continue
                    add(sev, "R21-missing-link", n, href[:70], "inline link target does not exist (relative to this note)")
            for kind, (here, first, count) in bad_dest.items():
                more = f" ({count} such links in this note)" if count > 1 else ""
                if kind == "malformed":
                    add(sev, "R21-malformed-link", here, first, "link destination holds a space or a parenthesis: Markdown does not read it as a link; encode it (%20 %28 %29), use a relative path or a [[wikilink]]" + more)
                else:
                    add(sev, "R21-absolute-link", here, first, "absolute machine path in a link: it breaks when the vault moves, is copied or is read on another machine; use a relative path or a [[wikilink]]" + more)
        if not path_rel.startswith(R20_SKIP):
            global R20_TOP
            if R20_TOP is None:
                R20_TOP = tuple(sorted(x.name + "/" for x in VAULT.iterdir() if x.is_dir() and not x.name.startswith(".") and x.name != "__pycache__"))
            for n, ln in enumerate(raw, 1):
                if n in d.code_lines or "`" not in ln or R20_PLANNED.search(ln):
                    continue
                for m in BACKTICK.finditer(ln):
                    t = re.sub(r":\d+(?:-\d+)?$", "", m.group(1).strip()).rstrip(".,;:)")
                    if (not t.startswith(R20_TOP) or t.startswith(R20_GENERATED) or "\u2026" in t
                            or re.search(r"[<>*?{}\[\]|$]|\.\.\.", t)):
                        continue
                    if not (VAULT / t.rstrip("/")).exists() and not (" " in t and (VAULT / t.split(" ")[0].rstrip("/")).exists()):
                        add("info", "R20-missing-path", n, t, "path in backticks does not exist (mark planned or renamed paths with a word such as planned or renamed)")
        # ADR-008 R18: a run of >=5 consecutive list items that are all heading links = a hand-written TOC
        own = {normalize_ar(h.title.strip()) for h in d.headings}
        raw = text.splitlines()
        run_start, run_len = 0, 0
        for n, ln in enumerate(raw, 1):
            m = re.match(r"\s*(?:[-*+]|\d+[.)])\s+\[\[#?([^\]|]+?)(?:\|[^\]]*)?\]\]\s*$", ln)
            hit = n not in d.code_lines and m and normalize_ar(m.group(1).partition("#")[2] or m.group(1)) in own
            if hit:
                run_start = run_start or n
                run_len += 1
            else:
                if run_len >= 5:
                    add("warn", "R18-manual-toc", run_start, normalize_ar(raw[run_start - 1][:50]),
                        f"{run_len} consecutive heading links mirroring this file's own headings: generate it (ADR-008)")
                run_start, run_len = 0, 0
        if run_len >= 5:
            add("warn", "R18-manual-toc", run_start, normalize_ar(raw[run_start - 1][:50]),
                f"{run_len} consecutive heading links mirroring this file's own headings: generate it (ADR-008)")
    # ADR-011: the retired system path, checked on raw lines (code included: commands get copied from code blocks)
    if "adr" in checks and not path_rel.startswith("04-Archive/"):
        for n, ln in enumerate(text.splitlines(), 1):
            for m in old_path_re().finditer(ln):
                add("warn", "ADR-011-oldpath", n, m.group(0), f"retired system folder: use {SYSTEM_DIR}/ (ADR-011)")
    # Package Y (deferrals), all warn-only
    if "def" in checks:
        out.extend(deferral_findings(path_rel, text, d.fm if isinstance(d.fm, dict) else {}))
    # ExampleClub club rules (club plan phase E), all warn-only: AI-Agent/scripts/club_rules.py
    if "club" in checks and ctx is not None:
        club_rules = optional_module("club_rules")
        if club_rules:
            out.extend(club_rules.findings(path_rel, text, d, ctx))
    # Architecture card rules (ADR-016), all warn-only: AI-Agent/scripts/arch_rules.py
    if "arch" in checks and ctx is not None:
        arch_rules = optional_module("arch_rules")
        if arch_rules:
            out.extend(arch_rules.findings(path_rel, text, d, ctx))
    # G13-paths (CF4-W6, AD06 B6a): a file must not keep privacy logic locally or classify send channels locally;
    # the channels are classified once, in the send-point ADR and the single mediator (d3).
    if "g13" in checks:
        out.extend(g13_findings(path_rel, text, d, ctx))
    return out


def g13_findings(path_rel: str, text: str, d, ctx) -> list[tuple]:
    """g13-paths checker, pattern T6/T11: privacy logic kept locally is forbidden (error), classifying channels outside
    the mediator is forbidden, and excluded paths are written once in the mediator, not in every tool.
    Findings are the six-element tuples (sev, rule, path_rel, line, key, detail) of the internal add()."""
    allowed, forbidden, mediator = locale_value("G13_ALLOWED", ""), locale_value("G13_FORBIDDEN", []), locale_value("G13_MEDIATOR", "")
    out: list[tuple] = []
    for n, ln in enumerate(text.splitlines(), 1):
        low = ln.lower()
        if "curl" in low and ("allowed" in low or "permitted" in low or (allowed and allowed in ln)):
            out.append(("error", "G13-free-curl", path_rel, n, ln.strip()[:120],
                        "free curl is allowed in text -- restrict the network and close the residuals in the mediator"))
        if re.search(r"browserruncodeunsafe", low) and not re.search("forbidden|blocked" + "".join("|" + re.escape(w) for w in forbidden), low):
            out.append(("error", "G13-unsafe-browser", path_rel, n, ln.strip()[:120],
                        "browserRunCodeUnsafe without an explicit restriction -- RCE-level, a network blocker is required"))
        if "classify" in low and "channel" in low and "mediator" not in low and not (mediator and mediator in ln):
            out.append(("error", "G13-local-classify", path_rel, n, ln.strip()[:120],
                        "channels classified locally outside the mediator -- the pre-check must go through mediator.py"))
    return out


def deferral_findings(path_rel: str, text: str, fm: dict) -> list[tuple]:
    """DEF-archived · DEF-untracked · DEF-incomplete · DEF-snooze. Fenced code is skipped."""
    out, lines, fence = [], text.splitlines(), False
    tags = fm.get("tags")
    tags = {str(t) for t in tags} if isinstance(tags, list) else ({str(tags)} if tags else set())
    spec_file = bool(tags & DEF_SPEC_TAGS) and not path_rel.startswith("04-Archive/")
    para = {"start": 0, "word": False, "id": False}

    def add(rule, line, key, detail):
        out.append(("warn", rule, path_rel, line, key, detail))

    def close_para():
        if spec_file and para["word"] and not para["id"]:
            add("DEF-untracked", para["start"], normalize_ar(lines[para["start"] - 1].strip()[:50]),
                "deferral word with no [id:: D-NN] item in the same paragraph (package Y)")
        para.update(start=0, word=False, id=False)

    for n, ln in enumerate(lines, 1):
        if ln.lstrip().startswith(("```", "~~~")):
            close_para()
            fence = not fence
            continue
        if fence:
            continue
        if not ln.strip():
            close_para()
            continue
        if DEF_BLOCK_START.match(ln):
            close_para()
        ident = DEF_ID.search(ln)
        if path_rel.startswith("04-Archive/") and DUE.match(ln):
            add("DEF-archived", n, normalize_ar(ln.strip()[:60]),
                "open dated task in an archived file: move it to its Area first (package Y 2.1)")
        if ident:
            missing = [k for k in ("state::", "kill::") if k not in ln]
            if missing:
                add("DEF-incomplete", n, ident.group(1), "missing " + ", ".join(missing))
            s = DEF_SNOOZE.search(ln)
            if s and int(s.group(1)) >= 2:
                add("DEF-snooze", n, ident.group(1),
                    f"snoozed {s.group(1)}x: no third snooze, execute or kill (package Y 2.4)")
        para["start"] = para["start"] or n
        para["word"] = para["word"] or bool(DEF_WORD.search(TASHKEEL.sub("", ln)))
        para["id"] = para["id"] or bool(ident)
    close_para()
    return out


def fingerprint(f) -> tuple:
    return (f[1], f[2], f[4])


def apply_waivers(path_rel: str, fm: dict, found: list, checks: set) -> list:
    waive = fm.get("audit_waive")
    if waive is None:
        return found
    if not isinstance(waive, dict):
        return found + [("error", "D14-waiver-format", path_rel, 1, "audit_waive", "must be a mapping rule: reason")]
    kept, used = [], set()
    for f in found:
        hit = next((k for k in waive if f[1].startswith(str(k))), None)
        if hit is None:
            kept.append(f)
        else:
            used.add(hit)
    if "waivers" in checks:
        for k, reason in waive.items():
            if not reason:
                kept.append(("warn", "D14-no-reason", path_rel, 1, str(k), "waiver without a reason"))
            if k not in used and not str(k).startswith("FM-"):  # FM-* waivers are resolved in the schema block
                kept.append(("warn", "D14-unused", path_rel, 1, str(k), "waiver no longer suppresses anything"))
    return kept


def registry_findings(texts, docs, scope, registry) -> list[tuple]:
    out = []
    caps = texts.get(caps_doc(), "")
    known = set(re.findall(r"`([a-z][a-z0-9]*(?:_[a-z0-9_]+)*)(?:\([^`]*\))?`", caps)) | {"*"}  # 2026-10-17: allow no-underscore names (goose built-ins like `delegate`), TR-0030
    entries = {r: docs[r].fm for r in texts if r.startswith(registry)}
    ids = {fm.get("id") for fm in entries.values()}
    for r, fm in entries.items():
        if r not in scope:
            continue
        stem = r.rsplit("/", 1)[-1][:-3]

        def add(rule, detail, sev="error"):
            out.append((sev, rule, r, 1, stem, detail))

        if docs[r].fm_error:
            add("RG-yaml", docs[r].fm_error)
        if fm.get("id") != stem:
            add("RG-id", f"id {fm.get('id')!r} must equal filename")
        kind = fm.get("kind", "tool")
        if kind not in ("tool", "design", "process", "build"):
            add("RG-kind", f"kind {kind!r} must be tool, design, process or build", "warn")  # warn: owner, 2026-10-02; build: T-20b, W13
        tools = fm.get("tools")
        if kind != "tool" and not tools:
            pass  # design and process errors need no tools (ADR-016, T-04)
        elif not isinstance(tools, list) or not tools:
            add("RG-tools", "tools must be a non-empty list")
        else:
            unknown = [t for t in tools if t not in known]
            if unknown:
                add("RG-tools-unknown", "not in capabilities doc: " + ", ".join(map(str, unknown)))
        if not isinstance(fm.get("rule"), str) or not fm.get("rule").strip():
            add("RG-rule", "rule must be a non-empty string")
        status = fm.get("status")
        if status not in ("active", "superseded"):
            add("RG-status", f"status {status!r}")
        if status == "superseded" and fm.get("superseded_by") not in ids:
            add("RG-superseded", f"superseded_by {fm.get('superseded_by')!r} is not an existing id")
        if any(h.level == 1 for h in docs[r].headings):
            add("RG-h1", "registry entries keep the title in front matter, no H1")
    return out


def adr_findings(texts, docs, scope, registry, db_conn=None) -> list[tuple]:
    """Fitness functions for the accepted decisions (MADR confirmation). Severity split:
    error/warn = the vault contradicts a live decision; info = decision accepted but not implemented yet."""
    import os
    import sys

    out = []

    def add(sev, rule, path, line, key, detail):
        out.append((sev, rule, path, line, key, detail))

    # ADR-008 - generated index
    if GUIDE in scope:
        toc = re.search(r"```table-of-contents\n(.*?)```", texts.get(GUIDE, ""), re.S)
        if not toc:
            add("error", "ADR-008-toc-missing", GUIDE, 1, "table-of-contents", "generated index block is gone")
        else:
            missing = [o for o in TOC_OPTIONS if o not in toc.group(1)]
            if missing:
                add("warn", "ADR-008-toc-options", GUIDE, texts[GUIDE][:toc.start()].count("\n") + 1,
                    "table-of-contents", "pinned options missing: " + ", ".join(missing))

    # ADR-001 - one folder per contest, folder note with the same name, depth 1
    projects = VAULT / "01-Projects"
    if projects.is_dir() and not scope_is_narrow(scope):
        for sub in sorted(p for p in projects.iterdir() if p.is_dir() and not p.name.startswith(".")):
            r = f"01-Projects/{sub.name}"
            if not (sub / f"{sub.name}.md").is_file():
                add("error", "ADR-001-folder-note", r, 1, sub.name, "folder note with the same name is missing")
            deeper = [d.name for d in sub.iterdir() if d.is_dir() and not d.name.startswith(".")]
            if deeper:
                add("warn", "ADR-001-depth", r, 1, sub.name, "nesting deeper than one level: " + ", ".join(deeper))
            notes = [p for p in sub.glob("*.md")]
            if len(notes) > 1 and not any("```dataview" in texts.get(f"{r}/{p.name}", read(p)) for p in notes):
                add("info", "ADR-004-forcing-function", r, 1, sub.name,
                    "no dataview block pulling previous lessons yet (ADR-004 item 3, not implemented)")

    # ADR-002 - relationships Area artifacts
    for path, what in ADR_ARTIFACTS.items():
        if not (VAULT / path).is_file():
            add("warn", "ADR-002-artifact", path, 1, path.rsplit("/", 1)[-1], f"{what} is missing")
    if not (VAULT / people_dir()).is_dir():
        add("warn", "ADR-002-artifact", people_dir(), 1, people_dir().rsplit("/", 1)[-1], "the people folder is missing")

    # ADR-003 - contest tool templates carry a stage prefix
    tools = VAULT / "Templates/Contest-Tools"
    if tools.is_dir():
        for f in sorted(tools.glob("*.md")):
            if not f.name.startswith(HACK_PREFIXES):
                add("warn", "ADR-003-prefix", f"Templates/Contest-Tools/{f.name}", 1, f.stem,
                    "missing a stage prefix: " + ", ".join(HACK_PREFIXES))

    # ADR-006 (amended by ADR-009) - scripts may import stdlib, _vaultlib and the pinned read-only libraries only
    scripts = VAULT / "AI-Agent/scripts"
    if scripts.is_dir():
        import ast
        local = {p.stem for p in scripts.glob("*.py")}    # sibling scripts are local modules, like _vaultlib
        py_cached = {}
        py_updates = []
        if db_conn is not None:
            try:
                db_conn.execute(
                    "CREATE TABLE IF NOT EXISTS adr_py_cache "
                    "(path TEXT PRIMARY KEY, sha1 TEXT NOT NULL, mods_json TEXT NOT NULL)"
                )
                py_cached = {row[0]: (row[1], row[2]) for row in db_conn.execute(
                    "SELECT path, sha1, mods_json FROM adr_py_cache"
                ).fetchall()}
            except Exception:
                py_cached = {}
        for f in sorted(scripts.glob("*.py")):
            raw_bytes = f.read_bytes()
            sha1 = (hashlib.sha1(raw_bytes).hexdigest() + "+dyn") if db_conn is not None else ""     # +dyn: module sets that include string-literal dynamic imports (AD13 E7)
            f_rel = f"AI-Agent/scripts/{f.name}"
            mods = None
            if db_conn is not None and f_rel in py_cached and py_cached[f_rel][0] == sha1:
                try:
                    mods = set(json.loads(py_cached[f_rel][1]))
                except Exception:
                    mods = None
            if mods is None:
                src = raw_bytes.decode("utf-8")
                mods = script_import_roots(src, dynamic=True)   # real import statements; a docstring line starting with "from" is prose (2026-10-02)
                if db_conn is not None:
                    py_updates.append((f_rel, sha1, json.dumps(sorted(mods))))
            bad = unapproved_imports(mods, local, _profile_cached()["scripts"]["optional_modules"], script=f.stem)
            if bad:
                add("error", "ADR-006-imports", f_rel, 1, f.stem,
                    "imports outside stdlib and the pinned libraries: " + ", ".join(bad))
        if py_updates and db_conn is not None:
            try:
                db_conn.executemany(
                    "INSERT OR REPLACE INTO adr_py_cache (path, sha1, mods_json) VALUES (?, ?, ?)",
                    py_updates,
                )
                db_conn.commit()
            except Exception:
                pass
        stray = sorted(p.name for p in scripts.iterdir() if p.is_file() and p.suffix != ".py")
        if stray:
            add("warn", "ADR-006-stray", "AI-Agent/scripts", 1, "scripts", "non-python files present: " + ", ".join(stray))

    # ADR-007 - registry parity: one file per trap, all readable by the B0 query (path from the schema)
    reg = VAULT / registry if registry else None
    if reg and reg.is_dir():
        files = sorted(reg.glob("TR-*.md"))
        parsed = [r for r in texts if r.startswith(registry)]
        if len(files) != len(parsed):
            add("error", "ADR-007-parity", registry, 1, "traps",
                f"{len(files)} files on disk vs {len(parsed)} parsed entries")

    # MADR coverage: every decision names at least one fitness function
    if ADR_FILE in scope:
        lines = texts.get(ADR_FILE, "").splitlines()
        entries = [h for h in docs[ADR_FILE].headings if h.level == 3 and h.plain.strip().startswith("ADR-")]
        for i, h in enumerate(entries):
            end = entries[i + 1].line if i + 1 < len(entries) else len(lines) + 1
            body = "\n".join(lines[h.line - 1:end - 1])
            if (not locale_value("CONFIRMATION_MARKER") or locale_value("CONFIRMATION_MARKER") not in body) and "**Confirmation" not in body:   # the English release writes **Confirmation:**
                add("warn", "ADR-no-confirmation", ADR_FILE, h.line, h.plain.split("\U00002014")[0].strip(),
                    "no confirmation section: every live decision needs at least one fitness function (MADR)")
    return out


def s13_scan_file(f) -> str | None:
    """S13-bypass detector (extracted for testability, C4 D4).
    Returns the bypass path relative to VAULT if the file writes the ledger DB
    directly with no mediator import, else None. The scan scope is expanded in
    C4 D4 from scripts/+schema/ to the entire AI-Agent/ tree."""
    # Exempt: mediator.py (the sanctioned sole writer), decision_ledger.py (the
    # sanctioned ledger API), audit.py (this checker: read-only mode=ro consumer
    # whose source contains the writer markers as string literals), and any
    # probe/test script (*-tests.py).
    if f.name.endswith("-tests.py") or f.name in ("mediator.py", "decision_ledger.py", "audit.py"):
        return None
    try:
        txt = f.read_text(encoding="utf-8")
    except Exception:
        return None
    # The exemption requires an actual import of mediator - the sanctioned
    # write path (critique 2026-10-19: the literal-word heuristic was demoted).
    has_import = ("import mediator" in txt or "from mediator" in txt)
    # 2026-11-19 (AD13 Stratum): "decision_ledger" as a bare word is not a reference to the ledger (SCHEMA_UNITS in _vaultlib names it as data and
    # the file also commits to its own cache DB, which made the test g06 red); a reference is the DB path, an import of the module or a dynamic import by name.
    refs_ledger = bool(re.search(r"decision-ledger\.sqlite3|^\s*(?:import|from)\s+decision_ledger\b|(?:import_module|__import__)\(\s*[\"']decision_ledger", txt, re.M))
    if refs_ledger and not has_import:
        is_writer = any(w in txt for w in (
            "INSERT INTO", "executemany", "conn.commit()", ".commit()",
            "append_decision(", "append_injection_log("))
        if is_writer:
            return f.relative_to(VAULT)
    return None


def scope_is_narrow(scope) -> bool:
    """Filesystem-level checks run only on a full sweep, not on a --path or --new-since subset."""
    return len(scope) < 20


def katex_findings(texts, docs, scope) -> list[tuple]:
    r"""TR-0022 (2026-10-21, AD08-C2-02): unescaped dollar signs in markdown prose.
    Ignores code fences, inline code, math spans, and escaped dollars.
    Flags a bare dollar sign (or double) in prose as error - KaTeX renders it as math."""
    out = []
    for r in texts:
        text = read(VAULT / r)
        # strip code fences
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        text = re.sub(r"~~~.*?~~~", "", text, flags=re.S)
        # strip escaped dollars
        text = text.replace("\\$", "")
        # strip inline code (double-backtick spans first: `` `^...$` `` holds a single backtick inside; plan kh-3-R)
        text = re.sub(r"``[^\n]*?``", "", text)
        text = re.sub(r"`[^`\n]*`", "", text)
        # find math spans first, mask them
        masked = list(text)
        for m in re.finditer(r"\$\$.*?\$\$|\$[^$\n]*\$", text, flags=re.S):
            for i in range(m.start(), m.end()):
                masked[i] = " "
        text = "".join(masked)
        for ln, line in enumerate(text.split("\n"), 1):
            for m in re.finditer(r"\$+", line):
                out.append(("warn", "KATX-dollar", r, ln, "katex",
                            f"TR-0022: unescaped dollar sign in prose (column {m.start() + 1}) - KaTeX renders it as math"))
    return out


def promote_staged_katex(results: list, staged: set) -> list:
    """Owner directive 2026-11-17 (plan kh-3-R): KATX-dollar blocks the commit, but only in files the commit itself
    stages; the rest of the vault keeps it as a warning. Promoted findings name the fix command."""
    out = []
    for f in results:
        if f[1] == "KATX-dollar" and f[0] == "warn" and f[2] in staged:
            f = ("error",) + tuple(f[1:5]) + (f[5] + " - staged file: run AI-Agent/vault-python AI-Agent/scripts/katex_escape.py --fix " + f[2],)
        out.append(f)
    return out


def commitref_findings(ops: str, git) -> list[tuple]:
    """OP-0062 (2026-10-30): structural commit references in the operations
    ledger — closes the 7baad39 phantom-commit class (a ledger entry citing a
    commit that never existed, cross-session contamination).

    Only the explicit `commit=<hex>` field is verified; free prose ("in
    1cd449c", the Arabic word for "in") is untouched, so the before=/after= 12-hex FILE fingerprints can
    never fire it (the critique's false-positive-explosion fix: the ledger
    holds hundreds of 12-hex fingerprints that are NOT commits). The value
    MUST be a hex hash of 7-40 chars — a non-hex placeholder (PENDING or
    similar) is simply not a valid field and fails the last-op rule instead
    (this is the fix for the scanner eating the op's own documentation of the
    check: prose containing the literal "commit=PENDING" can never match a
    hex field). A hash that does not resolve to a commit object = error
    commitref-phantom (blocks the commit — owner approved error severity for
    this check specifically, overriding the §3.3 warn-only default). The LAST
    op block, when closed, must carry the field = warn commitref-missing;
    older entries are grandfathered — no history retrofit. `git` is the audit
    helper which returns its stdout UNSTRIPPED (and None on failure) — compare
    against the stripped value (the friendly-fire class the OP-0059 lesson
    named: the first version of this check rejected 86e19df, a real commit,
    because 'commit\\n' != 'commit').

    OP-0063 hardening (2026-10-31, adversarial round): git itself accepts
    UPPERCASE hex refs (cat-file -t 86E19DF resolves), so the old [0-9a-f]
    regex was an escape hatch — the field class is now case-insensitive
    ([0-9a-fA-F]). The old \b word boundary also failed when the hash was
    followed by a non-hex word char (commit=86e19df followed by an Arabic letter — Arabic letters are
    word chars, so \b never landed and the phantom sailed through); the
    pattern is now an OPEN-ENDED hex run ([0-9a-fA-F]{7,}) truncated to the
    first 40 chars: a 41+-hex paste verifies its 40-hex prefix (fail-closed —
    the old {7,40}+\b let a 41-hex run backtrack out of every position and
    escape entirely), a non-hex suffix no longer hides the phantom, and a
    7-40-hex run is verified exactly as written. Duplicate citations are
    cached (one git call per distinct ref) and the warn line number now
    reports the actual last-op line instead of a hardcoded 1."""
    findings = []
    verified = {}   # OP-0063 cache: ref -> bool (same ref cited twice = one git call)
    FIELD = re.compile(r"commit=([0-9a-fA-F]{7,})")
    for m in FIELD.finditer(ops):
        ln = ops.count("\n", 0, m.start()) + 1
        ref = m.group(1)[:40]
        if ref not in verified:
            verified[ref] = (git("cat-file", "-t", ref) or "").strip() == "commit"
        if not verified[ref]:
            findings.append(("error", "commitref-phantom", "AI-Agent/operations.md", ln, "commit=" + ref,
                             "commit=" + ref + " does not exist in git - a phantom commit reference (the 7baad39 class)"))
    op_lines = [(i, ln) for i, ln in enumerate(ops.splitlines(), 1) if ln.strip().startswith("- **op:**")]
    if op_lines and "· applied ·" in op_lines[-1][1] and not FIELD.search(op_lines[-1][1]):
        findings.append(("warn", "commitref-missing", "AI-Agent/operations.md", op_lines[-1][0], "last op",
                         "closing applied entry without a commit= field (the last op only; older entries grandfathered)"))
    return findings


GATEHASH_FIELD = re.compile(r"state_hash=([0-9a-fA-F]{12,})")
GATEHASH_JSON = re.compile(r'"state_hash"\s*:\s*"([0-9a-fA-F]{12,})"')
GATEHASH_REL = "AI-Agent/state/decision-ledger.sqlite3"
GATE_SIG = ('"gate":', '"cycle":')


def git_bytes(*args):
    """git() with raw stdout bytes — the state_hash registry is a binary sqlite
    blob; the text=True git() helper would mangle it (the OP-0059 shape rule:
    probes must mirror THIS helper's two-arg call shape exactly)."""
    r = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(VAULT), *args], capture_output=True)
    return r.stdout if r.returncode == 0 else None


def gatehash_findings(texts: dict, ledger_path, ledger_rel: str, git_bytes) -> list[tuple]:
    """OP-0064 (2026-10-31): state_hash registration check — closes the
    e069ffdd class (a hash cited in a note whose evidence was never persisted
    in the registry, so the citation is unverifiable forever) and the
    entry-44-class inverse (a gate verdict recorded without its fingerprint).
    Enforces R-2026-10-31 (Gate Registration) structurally at commit time.

    Side 1 — notes (citation integrity): any literal `state_hash=<hex>` field
    in a tracked note must appear in a decision-ledger body = warn
    gatehash-unregistered. Only the explicit field is verified; prose ("returns
    state_hash", in Arabic) and other fingerprints (before=/after=/fp=, which never carry
    the state_hash= prefix) are untouched — the commitref false-positive
    explosion fix, same shape. The hex run is OPEN-ENDED {12,} truncated to the
    first 16 chars (the OP-0063 lesson: an exact-{16} pattern lets a longer
    paste backtrack out of every position and escape; a 12-15 hex paste is a
    corrupted field that can never match a registry hash and fails closed
    instead of escaping). Case-insensitive hex with lowercase normalization —
    the ledger stores sha256 hex lowercase; an uppercase paste verifies its
    normalized value (the git-hex uppercase lesson).

    Side 2 — ledger (fingerprint presence): NEW rows only (id > the max id
    committed in HEAD) whose body carries the gate-output signature (BOTH
    `"gate":` and `"cycle":` keys — the jev_gate return shape) must carry a
    state_hash field in EITHER form (= or JSON) = warn gatehash-ledger-gate.
    Fork rows (jev_choice/check/score) return NO state_hash by design (entry 44
    is a correct fork record), so only the gate signature triggers the rule;
    prose that merely DISCUSSES the gate tool (entry 41) carries neither JSON
    key and never fires. Rows already committed in HEAD are history — never
    re-flagged (the ledger is append-only: a gap can never be repaired, so
    re-flagging would be permanent noise; the warn is a commit-time signal the
    agent can still act on, since rows not yet in HEAD are being written now).
    The HEAD blob is read as raw bytes via git_bytes (the text=True git helper
    would corrupt the binary sqlite) and parsed through a temp file.

    Side 3 — fail-closed: the working ledger missing or unreadable = ONE error
    gatehash-no-ledger and an immediate return (the registry is broken, so
    both sides are unverifiable); a HEAD blob that fails plumbing or parses
    wrong = error too, but the note-side scan still runs (the registry works —
    only the new-row comparison is lost). Same philosophy as commitref's
    git-failure fail-closed case.
    SCANNER SELF-TRAP: this docstring documents both field forms WITHOUT ever
    writing state_hash=<12+hex> literally — a literal example here would fire
    unregistered on its own scan (the OP-0062 prose=PENDING lesson at the
    docstring level)."""
    import os
    import sqlite3
    import tempfile

    def _hashes(body):
        body = body or ""
        out = set()
        for m in GATEHASH_FIELD.finditer(body):
            out.add(m.group(1)[:16].lower())
        for m in GATEHASH_JSON.finditer(body):
            out.add(m.group(1)[:16].lower())
        return out

    findings = []
    try:
        conn = sqlite3.connect(str(ledger_path))
        rows = conn.execute("SELECT id, body FROM decisions").fetchall()
        conn.close()
    except Exception:
        findings.append(("error", "gatehash-no-ledger", ledger_rel, 1, "working ledger",
                         "the decision ledger is missing or unreadable - the state_hash registry cannot be verified (fail-closed)"))
        return findings

    ledger_hashes = set()
    gate_rows = []
    for rid, body in rows:
        ledger_hashes |= _hashes(body)
        b = body or ""
        if all(k in b for k in GATE_SIG):
            gate_rows.append((rid, b))

    for r, t in texts.items():
        for i, ln in enumerate(t.splitlines(), 1):
            for m in GATEHASH_FIELD.finditer(ln):
                h = m.group(1)[:16].lower()
                if h not in ledger_hashes:
                    findings.append(("warn", "gatehash-unregistered", r, i, "state_hash=" + h,
                                     "cited in a note but not registered in any decision-ledger body (R-2026-10-31)"))

    if git("rev-parse", "--verify", "-q", "HEAD") is None:
        return findings  # genesis repo (no HEAD yet): there is no committed ledger to compare new rows against
    blob = git_bytes("show", "HEAD:" + ledger_rel)
    if blob is None:
        findings.append(("error", "gatehash-no-ledger", ledger_rel, 1, "HEAD:" + ledger_rel,
                         "committed ledger blob unreadable (plumbing failure or ledger not tracked) - the new-row rule cannot be verified (fail-closed)"))
    else:
        committed_max = None
        tmp = None
        try:
            fd, tmp = tempfile.mkstemp(suffix=".sqlite3")
            os.write(fd, blob)
            os.close(fd)
            conn = sqlite3.connect(tmp)
            committed_max = conn.execute("SELECT MAX(id) FROM decisions").fetchone()[0] or 0
            conn.close()
        except Exception:
            committed_max = None
        finally:
            if tmp:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        if committed_max is None:
            findings.append(("error", "gatehash-no-ledger", ledger_rel, 1, "HEAD blob",
                             "committed ledger blob unparsable as sqlite - the new-row rule cannot be verified (fail-closed)"))
        else:
            for rid, body in gate_rows:
                if rid <= committed_max:
                    continue
                if _hashes(body):
                    continue
                findings.append(("warn", "gatehash-ledger-gate", ledger_rel, rid, "entry " + str(rid),
                                 "new gate verdict entry (gate+cycle signature) carries no state_hash - the gate fingerprint was not recorded (R-2026-10-31)"))
    return findings


def rule_matches_checks(rule: str, checks: set) -> bool:
    if len(checks) >= len(CHECKS):
        return True
    if rule.startswith("FM-"):
        return "frontmatter" in checks
    if rule.startswith(("R1-", "R3-", "R5-", "R7-", "R8-")):
        return "headings" in checks
    if rule.startswith("R4-"):
        return "size" in checks
    if rule.startswith("R6-"):
        return "refs" in checks
    if rule.startswith(("R13-", "R14-", "R18-", "R12-")):
        return "links" in checks
    if rule.startswith("ADR-011-"):
        return "adr" in checks
    if rule.startswith("DEF-"):
        return "def" in checks
    if rule.startswith("G13-"):
        return "g13" in checks
    if rule.startswith("D14-"):
        return "waivers" in checks or "def" in checks
    if rule.startswith("ARCH-"):
        return "arch" in checks
    if rule.startswith("CLUB-"):
        return "club" in checks
    return True


def main():
    force_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", default=",".join(CHECKS))
    ap.add_argument("--path", default="")
    ap.add_argument("--new-since", default="")
    ap.add_argument("--min", default="warn", choices=list(SEV))
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--leaf-max", type=int, default=4000)
    ap.add_argument("--baseline", default="", help="Path to baseline json to suppress legacy findings (Ratchet pattern)")
    ap.add_argument("--ratchet", action="store_true", help="Enable ratchet mode using default AI-Agent/audit_baseline.json")
    ap.add_argument("--no-cache", action="store_true", help="Bypass CAS cache and recompute all findings from scratch")
    ap.add_argument("--rebuild-cache", action="store_true", help="Force rebuild full CAS cache in vault-index.sqlite3")
    a = ap.parse_args()
    checks = set(a.check.split(","))
    try:
        profile = load_profile(VAULT)
    except ValueError:
        profile = _PROFILE_DEFAULTS  # broken profile: schema check reports it; run with defaults
    # T-02b: the profile may switch checks off, never the integrity ones (U-33).
    checks -= set(profile["checks"]["disabled"]) - UNTOUCHABLE_CHECKS
    release_mode = profile["mode"] == "release"

    texts = {rel(p): read(p) for p in iter_md() if not rel(p).startswith(SKIP_PREFIXES)}

    use_cas = not a.no_cache
    db_conn = None
    cached_rows = {}
    cache_note = "" if use_cas else "off (--no-cache)"
    invalidated: list[str] = []
    _code_fp = ""
    if use_cas:
        try:
            from _vaultlib import get_vault_index_db
            db_conn = get_vault_index_db()
            # The store holds only pure parse products. They depend on the text, the profile, the frontmatter schema
            # and the code that produced them (M04 F2); findings are never cached, so a cached run equals a no-cache run.
            _code_fp = code_fingerprint(Path(__file__))
            invalidated = audit_cache_fingerprint_check(
                db_conn,
                profile_sha1=file_sha1(VAULT / PROFILE_REL),
                schema_sha1=file_sha1(VAULT / SCHEMA_FILE),
                code_sha1=_code_fp)
            cached_rows = {row[0]: (row[1], row[2]) for row in db_conn.execute("SELECT path, blob_sha1, doc_meta_json FROM audit_cas_cache")}
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:160]
            print(f"WARN audit cache disabled, running uncached: {reason}", file=sys.stderr)
            cache_note = f"disabled reason={reason}"
            db_conn, use_cas, cached_rows = None, False, {}

    docs = {}
    cached_wikilinks = {}
    new_cache_rows = []
    hits = misses_new = misses_changed = 0

    from _vaultlib import Heading, Doc

    for r, t in texts.items():
        blob_sha = None
        if use_cas:   # the key is the hash of the exact text the audit processes (M04 F1), never a git-index proxy
            b = t.encode("utf-8")
            blob_sha = hashlib.sha1(b"blob " + str(len(b)).encode("ascii") + b"\0" + b).hexdigest()

        hit = False
        if use_cas and not a.rebuild_cache and r in cached_rows and cached_rows[r][0] == blob_sha:
            try:
                meta = json.loads(cached_rows[r][1])
                docs[r] = doc_from_meta(meta)
                cached_wikilinks[r] = meta["wikilinks"]
                preload_inline(t, meta["inline"])
                hit = True
                hits += 1
            except Exception:
                hit = False

        if not hit:
            if use_cas:
                if r in cached_rows and not a.rebuild_cache:
                    misses_changed += 1
                else:
                    misses_new += 1
            d = parse(t)
            docs[r] = d
            w_links = []
            for line, p in inline_texts(t):
                for m in WIKILINK.finditer(p):
                    w_links.append(m.group(1).partition("#")[0])
            if d.fm_raw:
                for m in WIKILINK.finditer(d.fm_raw):
                    w_links.append(m.group(1).partition("#")[0])
            cached_wikilinks[r] = w_links
            if use_cas:
                meta = {
                    **doc_to_meta(d),
                    "wikilinks": w_links,
                    "inline": list(inline_texts(t)),
                }
                new_cache_rows.append((r, blob_sha, 0, "[]", json.dumps(meta, ensure_ascii=False, default=str), time.time()))

    if db_conn:
        try:
            with db_conn:   # one transaction for the writes and the removal of rows for notes that no longer exist
                db_conn.executemany(
                    "INSERT OR REPLACE INTO audit_cas_cache (path, blob_sha1, leaf_max, findings_json, doc_meta_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    new_cache_rows)
                gone = [(row_path,) for row_path in cached_rows if row_path not in texts]
                db_conn.executemany("DELETE FROM audit_cas_cache WHERE path = ?", gone)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:160]
            print(f"WARN audit cache write failed, results are unaffected: {reason}", file=sys.stderr)
            cache_note = f"write-failed reason={reason}"
    if use_cas and not cache_note:
        cache_note = (f"parse_hits={hits} parse_misses={misses_new + misses_changed} (new={misses_new} changed={misses_changed}) "
                      f"written={len(new_cache_rows)} invalidated={','.join(invalidated) or 'none'}")

    ctx = Ctx(texts, docs)

    # D10 read-priority proxy: guidance files (last_reviewed) + inbound links + recent change
    inbound = collections.Counter()
    for r in texts:
        links = cached_wikilinks.get(r)
        if links is None:
            blob = docs[r].fm_raw + "\n" + "\n".join(s for _, s in inline_texts(texts[r]))
            links = [m.group(1).partition("#")[0] for m in WIKILINK.finditer(blob)]
        for target_note in links:
            target = ctx.resolve(target_note, r)
            if len(target) == 1 and target[0] != r:
                inbound[target[0]] += 1
    recent = set((git("log", "--since=7.days", "--name-only", "--format=") or "").split("\n"))
    score = {r: (5 if "last_reviewed" in docs[r].fm else 0) + inbound[r] + (1 if r in recent else 0) for r in texts}
    priority = {r for r, s in sorted(score.items(), key=lambda x: -x[1])[:8] if s > 0}

    scope = {r for r in texts if r.startswith(a.path)}
    mode, new_only, old_fps = "full", set(), {}
    if a.new_since:
        if git("rev-parse", "--verify", "-q", a.new_since + "^{commit}") is None:
            mode = f"full (base {a.new_since} not found)"
        else:
            mode = f"new-since {a.new_since[:10]}"
            changed = {}
            for line in (git("diff", "--name-status", "-M", a.new_since, "--", "*.md") or "").splitlines():
                parts = line.split("\t")
                if parts[0].startswith("R"):
                    changed[parts[2]] = parts[1]
                elif parts[0] != "D":
                    changed[parts[1]] = parts[1] if parts[0] != "A" else None
            for p in (git("ls-files", "--others", "--exclude-standard", "--", "*.md") or "").splitlines():
                changed[p] = None
            new_only = {r for r in changed if r in texts}
            for new, old in changed.items():
                if old and new in texts:
                    old_text = git("show", f"{a.new_since}:{old}")
                    if old_text is not None:
                        old_fps[new] = {(f[1], new, f[4]) for f in findings_for(new, old_text, checks, a.leaf_max, ctx)}
            scope &= new_only | priority

    results = []
    for r in sorted(scope):
        d = docs[r]
        found = findings_for(r, texts[r], checks, a.leaf_max, ctx, d=d)

        found = apply_waivers(r, d.fm, found, checks)
        if mode.startswith("new-since") and r in new_only and r not in priority:
            found = [f for f in found if fingerprint(f) not in old_fps.get(r, set())]
        results.extend(found)

    if "schema" in checks:
        fixed = [r for r in texts if "table" in docs[r].fm]
        if len(fixed) >= 3:
            # schema key = the title without numbering and without the bilingual suffix ("3) <Arabic title> — Column Reference")
            sets = {r: {normalize_ar(re.split(r"\s+[—–]\s+", NUMPREFIX.sub("", h.plain))[0]).strip() for h in docs[r].headings if h.level == 2} for r in fixed}
            freq = collections.Counter(x for s in sets.values() for x in s)
            majority = {x for x, c in freq.items() if c >= 0.6 * len(fixed)}
            for r in fixed:
                if r in scope:
                    for miss in sorted(majority - sets[r]):
                        results.append(("warn", "D3-schema", r, 1, miss, "missing standard section"))
    # ADR-012 (a): frontmatter schema, read from AI-Agent/schema/frontmatter.yaml, never hard-coded.
    if "schema" in checks or "due" in checks:
        import yaml
        try:
            schema = yaml.safe_load((VAULT / SCHEMA_FILE).read_text(encoding="utf-8"))
        except Exception as e:
            schema = None
            results.append(("error", "FM-schema-file", SCHEMA_FILE, 1, "yaml", str(e)[:120]))
    if "schema" in checks:
        # T-02a: release_profile.yaml structure (an integrity check: never disabled by the profile itself).
        try:
            if (VAULT / PROFILE_REL).is_file():
                load_profile(VAULT)
        except Exception as e:
            results.append(("error", "PROFILE-invalid", "AI-Agent/config/release_profile.yaml", 1, "profile", str(e)[:160]))
    if "schema" in checks and schema:
        # AD02 D10 (K16): a key written twice in one mapping is kept once by the loader, silently (`scope` was).
        for line, key, first in yaml_dup_keys((VAULT / SCHEMA_FILE).read_text(encoding="utf-8")):
            results.append(("error", "FM-schema-dupkey", SCHEMA_FILE, line, key,
                            f"`{key}` repeats the key on line {first}; the loader keeps only the last one"))
        sev_of = {k: v.get("severity", "warn") for k, v in schema.get("checks", {}).items()}
        if schema.get("strict"):
            sev_of["FM-unknown"] = "error"
        report_only = schema.get("enforcement", "report") != "enforce"

        def fm_sev(rule):
            s = sev_of.get(rule, "warn")
            return "warn" if report_only and s == "error" else s

        classes, keys = schema.get("classes", {}), schema.get("keys", {})
        classes, _cls_problems = resolve_classes(classes)
        for rule, cname, msg in _cls_problems:
            results.append(("error", rule, SCHEMA_FILE, 1, f"classes.{cname}", msg))
        # FM-schema-drift (2026-10-02): archive.optional is a hand copy of para.optional unless the class says
        # `extends: para` (U-27, resolved above). A para key missing from archive only fails later, when a note
        # carrying it is archived. Warn-only by owner decision (2026-10-02): new checks never block (spec §3.3).
        _para_opt = set(classes.get("para", {}).get("optional", []) or [])
        _arch_opt = set(classes.get("archive", {}).get("optional", []) or [])
        _drift = sorted(_para_opt - _arch_opt) if "archive" in classes else []
        if _drift:
            results.append(("warn", "FM-schema-drift", SCHEMA_FILE, 1, "classes.archive.optional",
                            "para optional keys missing from archive: " + ", ".join(_drift)))

        def fm_class(path, fm):
            return class_of(path, fm, classes, schema.get("unclassed_ok", []))

        for r in sorted(scope):
            if docs[r].fm_error:
                continue
            fm = docs[r].fm or {}
            name = fm_class(r, fm)
            if name is None:
                if not any(r.startswith(p) for p in schema.get("unclassed_ok", [])):
                    results.append((fm_sev("FM-unclassed"), "FM-unclassed", r, 1, "class", "matches no class and is not in unclassed_ok"))
                continue
            c = classes[name]
            n0 = len(results)  # this file's FM-* findings start here (audit_waive routing, 2026-09-28)
            allowed = set(c.get("required", [])) | set(c.get("optional", []))
            for k in c.get("required", []):
                if k not in fm:
                    results.append((fm_sev("FM-required"), "FM-required", r, 1, k, f"class {name}"))
            for k in fm:
                if k not in keys:
                    results.append((fm_sev("FM-unknown"), "FM-unknown", r, 1, k, "key not registered"))
                elif k not in allowed:
                    results.append((fm_sev("FM-unknown"), "FM-unknown", r, 1, k, f"not allowed for class {name}"))
            if "status" in fm and "status_enum" in c and fm["status"] not in c["status_enum"]:
                results.append((fm_sev("FM-status-enum"), "FM-status-enum", r, 1, str(fm["status"]), f"class {name}"))
            _cv = fm.get("created")   # only a str was refused: an empty value, a number or a timestamp passed as "a date"
            if "created" in fm and (not isinstance(_cv, datetime.date) or isinstance(_cv, datetime.datetime)) and not r.startswith("Templates/"):
                # Templates/ carries a live Templater placeholder in `created`
                # (e.g. `<% tp.date.now(...) %>`), which is necessarily a str
                # until QuickAdd instantiates a note from it. Flagging it here
                # is a false positive, not a real ADR-010 violation.
                results.append((fm_sev("FM-created-type"), "FM-created-type", r, 1, "created", f"{'empty' if _cv is None else type(_cv).__name__}, not date (ADR-010)"))
            # FM-nonlatin-digit: FM-created-type covers `created`; the other date keys are checked here. A date typed with
            # Arabic-Indic or other non-Latin digits is a string that Dataview, Tasks and every date comparison skip.
            for _dk in ("due", "last_reviewed", "last_updated", "date", "fresh_until", "last_checked"):
                _dv = fm.get(_dk)
                if isinstance(_dv, str) and any(not _c.isascii() and _c.isdecimal() for _c in _dv):
                    results.append((fm_sev("FM-nonlatin-digit"), "FM-nonlatin-digit", r, 1, _dk, "date written with non-Latin digits; use ASCII YYYY-MM-DD"))
            area = fm.get("area")
            if isinstance(area, str):
                m = re.match(r"^\[\[([^\]|#]+)", area.strip())
                if m and not ctx.resolve(m.group(1), r):
                    results.append((fm_sev("FM-area-target"), "FM-area-target", r, 1, area, "area resolves to no note"))
            # audit_waive for FM-* rules (2026-09-28): this block appends to `results` directly, so the
            # per-file apply_waivers() in the main loop never saw these findings and the waiver was inert.
            waive = fm.get("audit_waive")
            if isinstance(waive, dict):
                fmw = {k: v for k, v in waive.items() if str(k).startswith("FM-")}
                mine = results[n0:]
                results[n0:] = [f for f in mine if not any(f[1].startswith(str(k)) for k in fmw)]
                if "waivers" in checks:
                    for k in fmw:
                        if not any(f[1].startswith(str(k)) for f in mine):
                            results.append(("warn", "D14-unused", r, 1, str(k), "waiver no longer suppresses anything"))
        # FM-tag-variant (2026-09-28): a tag spelled two ways splits every search and every contains-filter.
        # Compares tags to each other (case, `_` vs `-`, trailing plural s): no hand-written vocabulary.
        variants = {}
        for p, d in docs.items():
            tg = (d.fm or {}).get("tags")
            for t in (tg if isinstance(tg, list) else []):
                key = re.sub(r"(?<=[a-z])s$", "", str(t).lower().replace("_", "-"))
                variants.setdefault(key, {}).setdefault(str(t), set()).add(p)
        for spellings in variants.values():
            if len(spellings) > 1:
                canon = max(spellings, key=lambda s: (len(spellings[s]), -len(s)))   # most files, then the shorter
                for s, files in spellings.items():
                    if s != canon:
                        for p in sorted(files & set(scope)):
                            results.append((fm_sev("FM-tag-variant"), "FM-tag-variant", p, 1, s, f"variant of `{canon}` ({len(spellings[canon])} files)"))
    if "due" in checks and schema:
        today = datetime.date.today()           # review 25 Sep: frontmatter `due` was never read
        for r in sorted(scope):
            fm = docs[r].fm or {}
            due = fm.get("due")
            if isinstance(due, datetime.datetime):
                due = due.date()   # a `due: 2020-01-01 10:00:00` is a datetime; subtracting a date from it raised TypeError
            if isinstance(due, datetime.date) and fm.get("status") in ("active", "on-hold"):
                days = (due - today).days
                if days <= 0:
                    results.append(("warn", "DUE-now", r, 1, "due (frontmatter)",
                                    f"due {due}" + (f" ({-days}d overdue)" if days < 0 else " (today)")))
                elif days <= 3:
                    results.append(("info", "DUE-soon", r, 1, "due (frontmatter)", f"due {due} (in {days}d)"))
    if "due" in checks:
        today = datetime.date.today()
        for r in sorted(scope):
            for n, ln in enumerate(texts[r].splitlines(), 1):
                m = DUE.match(ln)
                if not m:
                    continue
                try:
                    due = datetime.date.fromisoformat(m.group(1))
                except ValueError:   # `2026-02-30` matches the pattern but is no date: one typo must not crash the gate
                    results.append(("warn", "DUE-invalid", r, n, normalize_ar(ln.strip()[:60]), f"due {m.group(1)} is not a calendar date"))
                    continue
                days = (due - today).days
                if days <= 0:
                    results.append(("warn", "DUE-now", r, n, normalize_ar(ln.strip()[:60]),
                                    f"due {m.group(1)}" + (f" ({-days}d overdue)" if days < 0 else " (today)")))
                elif days <= 3:
                    results.append(("info", "DUE-soon", r, n, normalize_ar(ln.strip()[:60]), f"due in {days}d"))
    registry = None
    if "registry" in checks or "adr" in checks:
        try:
            registry = trap_registry()
        except Exception as e:
            results.append(("error", "RG-schema-path", SCHEMA_FILE, 1, "classes.trap.when.path_prefix", str(e)[:120]))
    if "registry" in checks and registry:
        results.extend(registry_findings(texts, docs, scope, registry))
    if "adr" in checks:
        results.extend(adr_findings(texts, docs, scope, registry, db_conn=db_conn if use_cas else None))


    if "frontmatter" in checks:   # file-level integrity of the notes themselves (red team R1: both used to crash the audit)
        for r in sorted(scope):
            if invalid_utf8(VAULT / r):
                results.append(("warn", "FM-file-invalid-utf8", r, 1, "encoding", "the file is not valid UTF-8; the audit read it with replacement characters"))
        for r in broken_md_symlinks():
            results.append(("warn", "FM-file-broken-symlink", r, 1, "symlink", "a .md symlink whose target does not exist (skipped by the audit)"))

    if "katex" in checks:
        results.extend(katex_findings(texts, docs, scope))

    if "config" in checks:
        omni_data = VAULT / ".obsidian/plugins/omnisearch/data.json"
        if omni_data.is_file():
            try:
                with open(omni_data, "r", encoding="utf-8") as cf:
                    cdata = json.load(cf)
                    if not cdata.get("ignoreArabicDiacritics", False):
                        results.append(("warn", "config-diacritics", ".obsidian/plugins/omnisearch/data.json", 1, "ignoreArabicDiacritics", "Arabic diacritics matching disabled in Omnisearch"))
                    if "00-Inbox" not in cdata.get("downrankedFoldersFilters", []):
                        results.append(("warn", "config-inbox-downrank", ".obsidian/plugins/omnisearch/data.json", 1, "downrankedFoldersFilters", "00-Inbox not downranked in Omnisearch"))
            except Exception:
                pass

    if "t1" in checks:
        # T1 (2026-10-18, AD06 B2, conditions 4-5 / CF1-W4-W5): Arabic normalization gate.
        # Runs the frozen T1 fixture in-process: FTS5 unicode61 over normalized docs,
        # 5 queries across the 5 historical forms. Recall below 5/5 = blocking error
        # (recall regression fails the commit). Silent on pass.
        try:
            import importlib.util as _ilu
            _fxp = VAULT / "AI-Agent" / "tests" / "fixtures" / "t1_fixture.py"
            if not _fxp.is_file():
                results.append(("error", "T1-fixture-missing", str(_fxp.relative_to(VAULT)), 1, "fixture",
                                "frozen T1 fixture missing - recall has no acceptance threshold (condition 5)"))
            else:
                _spec = _ilu.spec_from_file_location("t1_fixture_audit", _fxp)
                _mod = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                _res = _mod.run_recall()
                if _res["recall"] < _res["min_recall"]:
                    results.append(("error", "T1-recall-regression", str(_fxp.relative_to(VAULT)), 1, "recall",
                                    f"{_res['recall']}/{len(_mod.QUERIES)} below {_res['min_recall']} - recall regression blocks commit (condition 5)"))
        except Exception as _e:  # noqa: BLE001
            results.append(("error", "T1-fixture-broken", "AI-Agent/tests/fixtures/t1_fixture.py", 1, "run",
                            f"fixture failed to run: {_e.__class__.__name__}: {_e}"))

    if "inj" in checks:
        # INJ (2026-10-18, AD06 B3, conditions 7/11 CF2-W1/W5): injection enforcement gate.
        # Runs the frozen injection fixture: enforce_injection must return no violation for a
        # legit under-cap payload and an error for a payload exceeding the 1300-token cap
        # (loaded total, tokens not bytes). Silent on pass.
        try:
            import importlib.util as _ilu
            _fxp = VAULT / "AI-Agent" / "tests" / "fixtures" / "injection_fixture.py"
            if not _fxp.is_file():
                results.append(("error", "INJ-fixture-missing", str(_fxp.relative_to(VAULT)), 1, "fixture",
                                "frozen injection fixture missing - the 1300 cap has no acceptance threshold (condition 7)"))
            else:
                _spec = _ilu.spec_from_file_location("injection_fixture_audit", _fxp)
                _mod = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                _res = _mod.run_injection()
                if not _res["pass"]:
                    results.append(("error", "INJ-enforcement-fail", str(_fxp.relative_to(VAULT)), 1, "enforcement",
                                    f"cap enforcement broken: under_cap_violations={_res['under_cap_violations']} "
                                    f"over_cap_violations={_res['over_cap_violations']} (condition 7)"))
        except Exception as _e:  # noqa: BLE001
            results.append(("error", "INJ-fixture-broken", "AI-Agent/tests/fixtures/injection_fixture.py", 1, "run",
                            f"fixture failed to run: {_e.__class__.__name__}: {_e}"))

    if "contract" in checks:
        # CONTRACT (2026-10-19, AD06 C3-b, P2 mitigation C1-04; escalated to blocker
        # 2026-10-19, AD06 C3 D1, delegated decision #20): frozen contracts B/D run
        # their behavioral conformance gate live in pre-commit (contract-tests.py run
        # in-process), plus a warn on review_by expiry so a contract with no consumer
        # cannot go stale silently. Gate-integrity findings (gate missing, conformance
        # failure, parse failure, gate broken) are now errors per the hierarchy of
        # delegated decision #19: gate self-integrity = error, measured-value
        # enforcement = warn until explicit. review_by findings stay warn (review
        # scheduling is a value concern, not an integrity breach).
        try:
            import importlib.util as _ilc
            _ctp = VAULT / "AI-Agent" / "schema" / "contract-tests.py"
            if not _ctp.is_file():
                results.append(("error", "contract-gate-missing", str(_ctp.relative_to(VAULT)), 1, "contract",
                                "behavioral contract gate missing - contracts B/D have no live conformance check (D1 escalation: gate integrity = error)"))
            else:
                _spec = _ilc.spec_from_file_location("contract_tests_audit", _ctp)
                _mod = _ilc.module_from_spec(_spec)
                _spec.loader.exec_module(_mod)
                for _tname, _t in sorted(vars(_mod).items()):
                    if _tname.startswith("test_") and callable(_t):
                        try:
                            _t()
                        except AssertionError as _exc:
                            results.append(("error", "contract-conformance", _tname, 1, "contract",
                                            f"{_tname} failed: {_exc} (D1 escalation: conformance failure = gate integrity)"))
            for _cf in sorted((VAULT / "AI-Agent" / "contracts").glob("*.json")):
                try:
                    import json as _cjson
                    import datetime as _cdt
                    _cdata = _cjson.loads(_cf.read_text(encoding="utf-8"))
                    _rb = _cdata.get("review_by")
                    if not _rb:
                        results.append(("warn", "contract-review-missing", _cf.relative_to(VAULT), 1, "contract",
                                        f"contract {_cf.name} has no review_by date - P2 mitigation requires one"))
                        continue
                    if _cdt.date.today() > _cdt.date.fromisoformat(str(_rb)):
                        results.append(("warn", "contract-review-expired", _cf.relative_to(VAULT), 1, "contract",
                                        f"contract {_cf.name} review_by {_rb} expired - stale-contract risk P2"))
                except Exception as _e:  # noqa: BLE001
                    results.append(("error", "contract-parse", _cf.relative_to(VAULT), 1, "contract",
                                    f"cannot parse contract {_cf.name}: {_e} (D1 escalation: unparseable contract cannot be verified)"))
        except Exception as _e:  # noqa: BLE001
            results.append(("error", "contract-gate-broken", "AI-Agent/schema/contract-tests.py", 1, "contract",
                            f"contract gate failed to run: {_e.__class__.__name__}: {_e} (D1 escalation: gate self-integrity)"))

    if "s13" in checks:
        # S13 (2026-10-19, AD06 C4): ledger-bypass coverage test - every production tool
        # path must go through the single mediator. Evidence source: the send_log table
        # (mediator.py is its only writer) plus a static scan of production scripts for
        # direct sqlite writes to the ledger DB (the bypass pattern S13 targets).
        # Timed: if the check itself exceeds the declared s13_max_seconds the check fails
        # (K2 lesson: a slow gate gets bypassed and becomes a silent boast).
        import time as _time
        _t0 = _time.perf_counter()
        try:
            import sqlite3 as _sq3
            _dbp = VAULT / "AI-Agent" / "state" / "decision-ledger.sqlite3"
            if not _dbp.is_file():
                results.append(("error", "S13-ledger-missing", str(_dbp.relative_to(VAULT)), 1, "s13",
                                "decision-ledger DB missing - the mediator has no evidence table"))
            else:
                _conn = _sq3.connect(sqlite_ro_uri(_dbp), uri=True)
                try:
                    _n = _conn.execute("SELECT COUNT(*) FROM send_log").fetchone()[0]
                    if _n == 0:
                        results.append(("info" if release_mode else "warn", "S13-no-evidence", str(_dbp.relative_to(VAULT)), 1, "s13",
                                        "send_log is empty - the mediator envelope has no recorded evidence yet"))
                finally:
                    _conn.close()
            _bypass = []
            # C4 D4: scope expanded from scripts/+schema/ to the entire AI-Agent/
            # tree, excluding designated non-production directories (state, tests,
            # scratch, fixtures, proposals, __pycache__). The per-file logic lives
            # in s13_scan_file (extracted for testability).
            _excluded_dirs = {"tests", "state", "scratch", "fixtures", "proposals", "release-overlay", "__pycache__"}
            _all_py = []
            for _f in sorted((VAULT / "AI-Agent").rglob("*.py")):
                if any(part in _excluded_dirs for part in _f.relative_to(VAULT / "AI-Agent").parts[:-1]):
                    continue
                _all_py.append(_f)
            for _f in _all_py:
                _res = s13_scan_file(_f)
                if _res:
                    _bypass.append(_res)
            for _b in _bypass:
                results.append(("warn", "S13-bypass", _b, 1, "s13",
                                "writes the ledger DB directly with no mediator import - ledger bypass (F7); warn per standing rule (new checks never block), escalation to blocking deferred to cycle-3 review with the contract check"))
        except Exception as _e:  # noqa: BLE001
            results.append(("error", "S13-broken", "AI-Agent/scripts/audit.py", 1, "s13",
                            f"s13 check failed: {_e.__class__.__name__}: {_e}"))
        _elapsed = _time.perf_counter() - _t0
        try:
            import json as _sj
            _g6 = _sj.loads((VAULT / "AI-Agent" / "g06_baseline.json").read_text(encoding="utf-8"))
            _cap = _g6.get("metrics", {}).get("s13_max_seconds")
        except Exception:
            _cap = None
        if isinstance(_cap, (int, float)) and _elapsed > _cap:
            results.append(("error", "S13-time-budget", "AI-Agent/scripts/audit.py", 1, "s13",
                            f"s13 check took {_elapsed:.2f}s, above the declared {_cap}s budget (K2: a slow gate is itself a bypass)"))

    if "s16" in checks:
        # S16 (2026-10-19, AD06 C4): total session budget enforcement - the ceiling is
        # declared in the signed g06_baseline (session_ceiling_tokens=1300, live payload
        # only: injection+session+results; static childhood excluded per S14). Measured
        # source: AI-Agent/state/injection-log.jsonl, the session injection ledger.
        # Warn-only per owner standing decision; escalation to blocking after approval.
        try:
            import json as _j16
            _g6s = _j16.loads((VAULT / "AI-Agent" / "g06_baseline.json").read_text(encoding="utf-8"))
            _ceil = _g6s.get("metrics", {}).get("session_ceiling_tokens")
            _ilp = VAULT / "AI-Agent" / "state" / "injection-log.jsonl"
            if not isinstance(_ceil, (int, float)):
                results.append(("error", "S16-ceiling-undeclared", "AI-Agent/g06_baseline.json", 1, "s16",
                                "session_ceiling_tokens not declared in baseline - no total session budget exists"))
            elif not _ilp.is_file():
                results.append(("warn", "S16-no-measurement", str(_ilp.relative_to(VAULT)), 1, "s16",
                                "no injection log - the ceiling is declared but no session payload is measured against it"))
            else:
                _sess = {}
                for _ln in _ilp.read_text(encoding="utf-8").splitlines():
                    if not _ln.strip():
                        continue
                    _e = _j16.loads(_ln)
                    if _e.get("kind") == "static_childhood":
                        continue
                    _sess[_e.get("session", "?")] = _sess.get(_e.get("session", "?"), 0) + (_e.get("tokens") or 0)
                for _sn, _tot in sorted(_sess.items()):
                    if _tot > _ceil:
                        results.append(("warn", "S16-ceiling-breached", str(_ilp.relative_to(VAULT)), 1, "s16",
                                        f"session {_sn} loaded {_tot} tokens, above the {_ceil} ceiling (S16 total session budget)"))
                # S16-token-provenance (2026-10-19, AD06 C3 D3): the ceiling is only as
                # honest as the writer of its tokens value. append_injection_log now
                # accepts a declared measurement method; one aggregated warn covers the
                # historical rows written before the field existed (declared-only era).
                _no_method = sum(1 for _ln in _ilp.read_text(encoding="utf-8").splitlines()
                                 if _ln.strip() and not _j16.loads(_ln).get("method"))
                if _no_method:
                    results.append(("warn", "S16-token-provenance", str(_ilp.relative_to(VAULT)), 1, "s16",
                                    f"{_no_method} injection rows declare no measurement method (D3 provenance) - new rows should pass method='tiktoken-first-party' or 'declared'"))
        except Exception as _e:  # noqa: BLE001
            results.append(("error", "S16-broken", "AI-Agent/g06_baseline.json", 1, "s16",
                            f"s16 check failed: {_e.__class__.__name__}: {_e}"))

    if "s17" in checks:
        # S17 (2026-10-19, AD06 C4): hit-rate measurement must be scheduled, not manual.
        # The baseline declares hit_rate_pct with a value (45, self-referential warning);
        # S17 closes by requiring a scheduling contract: schedule_established timestamp in
        # the baseline + a declared cadence. last_measured is only set by a real hit-rate
        # measurement - never as a scheduling device (critique 2026-10-19: the C4 fix
        # wrote a treatment date into last_measured and silenced the honest warn).
        # Stale beyond the cadence = warn.
        try:
            import json as _j17
            import datetime as _dt
            _g6h = _j17.loads((VAULT / "AI-Agent" / "g06_baseline.json").read_text(encoding="utf-8"))
            _m17 = _g6h.get("metrics", {})
            if "hit_rate_pct" not in _m17:
                results.append(("error", "S17-no-metric", "AI-Agent/g06_baseline.json", 1, "s17",
                                "hit_rate_pct not declared - the >=80% target has no owner"))
            else:
                _lm = _g6h.get("last_measured")
                _cad = _m17.get("hit_rate_cadence_days") or _g6h.get("hit_rate_cadence_days")
                if _cad is None:
                    results.append(("warn", "S17-unscheduled", "AI-Agent/g06_baseline.json", 1, "s17",
                                    "hit_rate_cadence_days not declared - the measurement is manual, not scheduled (S17)"))
                if _lm is None:
                    results.append(("warn", "S17-never-measured", "AI-Agent/g06_baseline.json", 1, "s17",
                                    "last_measured is null - hit_rate_pct is a declaration, not a measurement (S17)"))
                elif isinstance(_cad, (int, float)):
                    _age = (_dt.date.today() - _dt.date.fromisoformat(str(_lm)[:10])).days
                    if _age > _cad:
                        results.append(("warn", "S17-stale", "AI-Agent/g06_baseline.json", 1, "s17",
                                        f"hit-rate last measured {_age}d ago, beyond the {_cad}d cadence - re-measure"))
        except Exception as _e:  # noqa: BLE001
            results.append(("error", "S17-broken", "AI-Agent/g06_baseline.json", 1, "s17",
                            f"s17 check failed: {_e.__class__.__name__}: {_e}"))

    if "g06" in checks:
        # G06/F06 (2026-10-18, AD06 T11): baseline metrics file must exist and stay fresh.
        # (1) G06-baseline / G06-metric-missing: AI-Agent/g06_baseline.json must exist and declare
        #     the required metric keys (F06: baseline before any architectural change).
        # (2) G06-tokens-loaded: re-measure token counts of the auto-loaded system files with
        #     tiktoken o200k_base (first-party method of AD06 T4); warn on >5% drift.
        # (3) G06-hit-rate / G06-layer-depth: threshold guards for A05-G02 (hit rate >= 80%)
        #     and the permanent-layer 1300-token cap (candidates C/E), when declared.
        bp = VAULT / "AI-Agent" / "g06_baseline.json"
        if not bp.is_file():
            results.append(("error", "G06-baseline", "AI-Agent/g06_baseline.json", 1, "baseline",
                            "F06: no G06 baseline file - metrics must exist before any architectural change"))
        else:
            try:
                import json as _json
                g = _json.loads(bp.read_text(encoding="utf-8"))
                if not isinstance(g.get("metrics"), dict):
                    results.append(("error", "G06-baseline", "AI-Agent/g06_baseline.json", 1, "metrics",
                                    "baseline must declare a 'metrics' object"))
                    g = {"metrics": {}}
                m = g["metrics"]
                for key, lim in (("hit_rate_pct", 80), ("usage_rate_pct", 80), ("token_ratio_out_in", None)):
                    if key not in m:
                        results.append(("error", "G06-metric-missing", "AI-Agent/g06_baseline.json", 1, key,
                                        "required metric not declared in baseline (A05-G02/G04/G10)"))
                    elif m[key] is None:
                        results.append(("info", "G06-not-measured", "AI-Agent/g06_baseline.json", 1, key,
                                        "declared but not yet measured"))
                    elif isinstance(m[key], (int, float)) and lim is not None and m[key] < lim:
                        results.append(("warn", "G06-hit-rate", "AI-Agent/g06_baseline.json", 1, key,
                                        f"{m[key]} below the {lim}% acceptance threshold (A05-G02)"))
                def _tok(path):
                    try:
                        if not ensure_o200k_cache():
                            return None
                        import tiktoken
                        enc = tiktoken.get_encoding("o200k_base")
                        return len(enc.encode((VAULT / path).read_text(encoding="utf-8")))
                    except Exception:
                        return None
                for name, src in (("operations_md_tokens", "AI-Agent/operations.md"),
                                  ("rules_md_tokens", "AI-Agent/rules.md"),
                                  ("handoff_md_tokens", "AI-Agent/handoff.md")):
                    val = m.get(name)
                    ops_ceiling = profile["limits"]["operations_md_max_tokens"] if name == "operations_md_tokens" else 0
                    if ops_ceiling:
                        # T-02d: operations.md is append-only, so a release bounds it by a ceiling instead of a drift baseline
                        got = _tok(src)
                        if got is None:
                            results.append(("info", "G06-tokens-unmeasured", "AI-Agent/g06_baseline.json", 1, name,
                                            "tiktoken unavailable - re-measure when the pylib is present"))
                        elif got > ops_ceiling:
                            results.append(("warn", "G06-ops-ceiling", src, 1, name,
                                            f"{got} tokens exceeds the {ops_ceiling} ceiling (limits.operations_md_max_tokens) - archive old operations"))
                        continue
                    if not isinstance(val, (int, float)):
                        results.append(("error", "G06-tokens-loaded", "AI-Agent/g06_baseline.json", 1, name,
                                        f"no declared token count for {src}"))
                        continue
                    got = _tok(src)
                    if got is None:
                        results.append(("info", "G06-tokens-unmeasured", "AI-Agent/g06_baseline.json", 1, name,
                                        "tiktoken unavailable - re-measure when the pylib is present"))
                        continue
                    drift = abs(got - val) / max(val, 1)
                    if drift > 0.05:
                        results.append(("warn", "G06-tokens-loaded", "AI-Agent/g06_baseline.json", 1, name,
                                        f"drift {got} vs baseline {val} ({drift:.0%} > 5%) - refresh the baseline"))
                pl = m.get("permanent_layer")
                if isinstance(pl, dict) and pl.get("file"):
                    f, cap = pl["file"], pl.get("cap_tokens")
                    if (VAULT / f).is_file() and isinstance(cap, int):
                        got = _tok(f)
                        if got is not None and got > cap:
                            results.append(("error", "G06-layer-depth", f, 1, "permanent layer",
                                            f"{got} tokens exceeds the {cap} cap"))
                    elif not (VAULT / f).is_file():
                        results.append(("info", "G06-layer-depth", f, 1, "permanent layer",
                                        "declared but not built yet"))
                # (5) G06-injection-log (AD06 B3, conditions 7/11 CF2-W1/W5): session injection
                # log reaches the g06 check in pre-commit; static_childhood leads it.
                ilp = VAULT / "AI-Agent" / "state" / "injection-log.jsonl"
                if not ilp.is_file():
                    results.append(("error", "G06-injection-log-missing", str(ilp.relative_to(VAULT)), 1, "injection log",
                                    "session injection log missing - g06 has no consumption-point feed (condition 7)"))
                else:
                    try:
                        _lines = [_json.loads(l) for l in ilp.read_text(encoding="utf-8").splitlines() if l.strip()]
                        if not _lines or _lines[0].get("kind") != "static_childhood":
                            results.append(("error", "G06-opening-entry", str(ilp.relative_to(VAULT)), 1, "injection log",
                                            "first entry is not static_childhood - the opening billed item must lead the log (condition 11)"))
                        _sct = m.get("static_childhood_tokens")
                        if isinstance(_sct, int) and _lines and _lines[0].get("tokens") != _sct:
                            results.append(("error", "G06-childhood-mismatch", str(ilp.relative_to(VAULT)), 1, "injection log",
                                            f"opening entry {_lines[0].get('tokens')} tokens differs from baseline static_childhood_tokens {_sct} (condition 11)"))
                    except Exception as _e2:  # noqa: BLE001
                        results.append(("error", "G06-injection-log-broken", str(ilp.relative_to(VAULT)), 1, "injection log",
                                        f"cannot parse JSONL: {_e2}"))
            except Exception as e:
                results.append(("error", "G06-baseline", "AI-Agent/g06_baseline.json", 1, "parse", str(e)[:120]))

    if "sigkey" in checks:
        # sigkey (2026-10-19, AD06-C5-E2-v2, owner approval): vault signature keys
        # integrity -- the verification trust root itself must be guarded.
        # (1) key file & keyring configured in release_profile.yaml exist; (2) the
        # vault binary keyring contains the pinned public-key fingerprint; a tampered
        # or replaced vault-keys.gpg fails the ratchet on the next commit.
        _sig_cfg = _profile_cached().get("sigkey") or {}
        _key_file = (_sig_cfg.get("key_file") or "").strip()
        _pinned_fpr = (_sig_cfg.get("fingerprint") or "").strip().upper()
        _keys_dir = VAULT / "AI-Agent" / "keys"
        _ring = _keys_dir / "vault-keys.gpg"
        if not _key_file or not _pinned_fpr:
            results.append(("error", "SIGKEY-missing", "AI-Agent/config/release_profile.yaml", 1, "sigkey",
                            "sigkey.key_file or sigkey.fingerprint not configured in release_profile.yaml"))
        elif not (_keys_dir / _key_file).is_file() or not _ring.is_file():
            results.append(("error", "SIGKEY-missing", "AI-Agent/keys/", 1, "sigkey",
                            "signature verification keys missing -- baseline trust root unguarded"))
        else:
            try:
                import subprocess as _sp
                _lp = _sp.run(["gpg", "--no-default-keyring", "--keyring", str(_ring),
                               "--list-keys", "--with-fingerprint", "--with-colons"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10, cwd=str(VAULT))
                _fps = re.findall(r"^fpr:::::::::([0-9A-F]{40}):", _lp.stdout, re.M)
                if _pinned_fpr not in _fps:
                    results.append(("error", "SIGKEY-tampered", "AI-Agent/keys/vault-keys.gpg", 1, "sigkey",
                                    f"pinned fingerprint {_pinned_fpr[:16]} not found in vault keyring -- keyring tampered or key replaced"))
            except Exception as e:  # noqa: BLE001
                results.append(("error", "SIGKEY-broken", "AI-Agent/keys/", 1, "sigkey",
                                f"sigkey check failed: {e.__class__.__name__}: {e}"))

    if "secrets" in checks:
        # secrets (2026-10-24, AD11 C1-04 D4, owner approval): no secrets in
        # instruction/handoff/map files. Entry-path files (handoffs, AGENTS.md,
        # instruction files) are read by every agent at session start (AD11 entry
        # sequence); a leaked token there propagates to every consumer. Pattern
        # scan on instruction-path files + handoffs -- not the whole vault
        # (research data may legitimately discuss token formats).
        _secret_scope = [r for r in sorted(scope)
                         if r == "AGENTS.md"
                         or r == "AI-Agent/handoff.md"
                         or r.startswith("AI-Agent/handoff/")
                         or r.startswith("AI-Agent/skills/")
                         or (r.startswith("01-Projects/") and "/handoff" in r.lower())
                         or (r.endswith(".md") and "/handoff" in r.lower())]
        # AD13 perf (2026-11-19): the warm audit spent 4.5 s of 7.5 s here. scan_secrets is a pure function of one text (and of the code and
        # the shapes file), so its findings are cached by the text's sha1: the exception to "findings are never cached" is stated
        # here and held by audit_equiv (a cached run must equal a no-cache run). The key carries the code and shapes fingerprint.
        _sc, _sc_rows, _sc_new, _sc_hit = (db_conn if use_cas else None), {}, [], [0]
        if _sc is not None:
            try:
                _shp = VAULT / "AI-Agent" / "schema" / "secret-shapes.json"
                _sc_code = _code_fp + "|" + (file_sha1(_shp) if _shp.is_file() else "none")
                _sc.execute("CREATE TABLE IF NOT EXISTS secrets_scan_cache (key TEXT PRIMARY KEY, code_sha1 TEXT NOT NULL, findings_json TEXT NOT NULL)")
                _sc.execute("DELETE FROM secrets_scan_cache WHERE code_sha1 != ?", (_sc_code,))
                _sc_rows = dict(_sc.execute("SELECT key, findings_json FROM secrets_scan_cache").fetchall())
            except Exception:
                _sc = None

        def _scan_secrets_cached(_t, entropy, hidden, placeholders_ok):
            if _sc is None:
                return scan_secrets(_t, entropy=entropy, hidden=hidden, placeholders_ok=placeholders_ok)
            _k = hashlib.sha1(_t.encode("utf-8", "surrogatepass")).hexdigest() + f"|{int(entropy)}{int(hidden)}{int(placeholders_ok)}"
            _hit = _sc_rows.get(_k)
            if _hit is not None:
                _sc_hit[0] += 1
                return [tuple(x) for x in json.loads(_hit)]
            _r = scan_secrets(_t, entropy=entropy, hidden=hidden, placeholders_ok=placeholders_ok)
            _sc_new.append((_k, _sc_code, json.dumps(_r)))
            return _r
        _release_mode = _profile_cached()["mode"] == "release"
        # a release ships every note, so every note in scope is scanned there; the mother vault keeps the narrow scope for
        # credential shapes and entropy (research notes may discuss token formats), but hidden text is never legitimate anywhere
        for r in sorted(scope):
            try:
                _stext = (VAULT / r).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            _full = _release_mode or r in _secret_scope
            if r.startswith(people_dir() + "/"):      # AD13 D7: personal-data shapes in the people folder warn, never block
                for _pk, _pl, _pd in scan_pii(_stext):
                    results.append(("warn", f"PII-{_pk}", r, _pl, "secrets", f"{_pd} in a people note (check consent and need)"))
            for _kind, _sln, _detail in _scan_secrets_cached(_stext, _full, True, not _full):
                if _kind.startswith("pattern:"):
                    results.append(("error", f"SECRET-leak-{_kind.split(':')[1]}", r, _sln, "secrets",
                                    f"{_detail} matched in a shipped or instruction-path file -- no secrets in handoffs (D4)" if _full
                                    else f"{_detail} matched in a note (AD13 D7: credential shapes are errors in every note; a placeholder is skipped; "
                                    "a public documentation sample: add the word example or change a few characters)"))
                elif _kind == "entropy":
                    results.append(("error", "SECRET-entropy", r, _sln, "secrets", _detail))
                elif _kind == "bidi":
                    results.append(("error", "BIDI-control", r, _sln, "secrets", _detail))
                else:
                    results.append(("error", "BOM-midfile", r, _sln, "secrets", _detail))
        # AD13 D7: tracked or about-to-be-tracked text files that are not notes (scripts, config, data); credential shapes only
        for _nr, _ntext in _non_note_texts():
            for _kind, _sln, _detail in _scan_secrets_cached(_ntext, False, False, True):
                results.append(("error", f"SECRET-leak-{_kind.split(':')[1]}", _nr, _sln, "secrets",
                                f"{_detail} matched in a non-note file (AD13 D7)"))
        if _sc is not None and _sc_new:
            try:
                with _sc:
                    _sc.executemany("INSERT OR REPLACE INTO secrets_scan_cache (key, code_sha1, findings_json) VALUES (?, ?, ?)", _sc_new)
            except Exception:
                pass
        if _sc is not None:
            print(f"CACHE-SECRETS hits={_sc_hit[0]} misses={len(_sc_new)}")

    if "args_contract" in checks:
        # args-contract (2026-10-23, AD10 C12/R3, owner approval): every skill must
        # carry an MCP-style args contract (input/output/consumer) in its
        # frontmatter, derived from its own SKILL.md text (no invented contracts).
        # Structural validation only -- semantic faithfulness (does args.input
        # truly match the SKILL.md body?) stays a human-review step (declared
        # limitation, AD10 C12 report).
        for r in sorted(scope):
            if not (r.startswith("AI-Agent/skills/") and r.endswith("SKILL.md")):
                continue
            if docs[r].fm_error:
                continue                                  # already a FM-yaml error
            fm = docs[r].fm or {}
            args = fm.get("args")
            if not isinstance(args, dict):
                results.append(("error", "ARGS-missing", r, 1, "args",
                                "skill has no args contract (MCP-style metadata required)"))
                continue
            for _ak in ("input", "output", "consumer"):
                _av = args.get(_ak)
                if _av is None or (isinstance(_av, str) and not _av.strip()):
                    results.append(("error", "ARGS-empty", r, 1, f"args.{_ak}",
                                    f"args.{_ak} is required and must be non-empty"))

    if "consumer_drift" in checks:
        # consumer-drift (2026-10-23, AD10 C19 stage C, ida methodology): the
        # consumer-map.yaml is the single source of truth for live registry
        # counters (skills, tools). Any addition/removal of a skill dir or a
        # script without updating the map is silent drift -- the exact failure
        # class that bit C17 (disk-probe broke skill_args-tests T3) and C18
        # (radar_reconcile missing from tool-matrix). Runs once, not per-file.
        try:
            import yaml as _yaml
            _map_p = VAULT / "AI-Agent" / "schema" / "consumer-map.yaml"
            _mtxt = _map_p.read_text(encoding="utf-8")
            if _mtxt.lstrip().startswith("---"):
                _mtxt = _mtxt.split("---", 2)[2]
            _map = _yaml.safe_load(_mtxt).get("counters", {})
            _real_skills = len([d for d in (VAULT / "AI-Agent" / "skills").iterdir() if d.is_dir()])
            _real_tools = len([p for p in (VAULT / "AI-Agent" / "scripts").glob("*.py")
                               if not p.name.endswith("-tests.py")])
            _prof = _profile_cached()
            _need = ("skills", "tools") + (("progress",) if _prof["mode"] == "vault" else ())   # a release has no progress note
            _real = {"skills": _real_skills, "tools": _real_tools}
            if "progress" in _need or "progress" in _map:
                _pn = VAULT / (_prof["paths"]["progress_note"] or locale_value("PROGRESS_NOTE", "progress-note.md"))
                _real["progress"] = len([l for l in _pn.read_text(encoding="utf-8").splitlines() if l.startswith("- 2026-")])
            for _ck in _need:
                _mp = _map.get(_ck)
                _rv = _real[_ck]
                if _mp is None:
                    results.append(("error", "CDRIFT-map-missing", _map_p, 1, "consumer_drift",
                                    f"counter '{_ck}' absent from consumer-map.yaml"))
                elif _mp != _rv:
                    results.append(("error", "CDRIFT-drift", _map_p, 1, "consumer_drift",
                                    f"counter '{_ck}' map={_mp} reality={_rv} -- update the map in the same commit"))
        except Exception as e:  # noqa: BLE001
            results.append(("error", "CDRIFT-broken", "AI-Agent/schema/consumer-map.yaml", 1, "consumer_drift",
                            f"map read failed: {e.__class__.__name__}: {e}"))

    if "livedoc" in checks:
        # livedoc (2026-10-23, AD10 C10/R1, owner approval): the live architecture
        # document must not drift from the authoritative tool-matrix baseline.
        # Delegates to derive_live_arch.check() -- light structural figure match
        # (scripts count + 37/12/2-style verdicts), volatile measurements excluded.
        try:
            import derive_live_arch as _dla
            if _dla.check() != 0:
                results.append(("error", "LIVEDOC-drift", _dla.rel(_dla.LIVE_DOC), 1, "livedoc",
                                "live doc figures diverge from the measured baseline"))
        except Exception as e:  # noqa: BLE001
            results.append(("error", "LIVEDOC-broken", "AI-Agent/scripts/derive_live_arch.py", 1, "livedoc",
                            f"livedoc check failed: {e.__class__.__name__}: {e}"))

    baseline_set = set()
    baseline_path = a.baseline or ("AI-Agent/audit_baseline.json" if a.ratchet else "")
    if baseline_path and (VAULT / baseline_path).is_file():
        try:
            with open(VAULT / baseline_path, "r", encoding="utf-8") as bf:
                bdata = json.load(bf)
                for item in bdata.get("findings", []):
                    loc = item.get("location", "").split(":")[0]
                    baseline_set.add((item.get("severity"), item.get("rule"), loc))
        except Exception:
            pass

    if baseline_set:
        filtered = []
        for f in results:
            sev, rule, path = f[0], f[1], f[2]
            if sev == "error" or (sev, rule, path) not in baseline_set:
                filtered.append(f)
        results = filtered

    if "commitref" in checks:
        ops_file = VAULT / "AI-Agent" / "operations.md"
        if ops_file.is_file():   # a release ships no operations log: nothing to cross-check
            results.extend(commitref_findings(ops_file.read_text(encoding="utf-8"), git))

    if "gatehash" in checks:
        results.extend(gatehash_findings(texts, VAULT / "AI-Agent" / "state" / "decision-ledger.sqlite3",
                                         GATEHASH_REL, git_bytes))

    # Commit gate: only errors block. Warnings (DUE-* included) are file-quality
    # signals for the weekly review, not backup-freezing events — an overdue
    # calendar line or a long section should never stop a commit (observed twice,
    # 20 and 25 Sep 2026).
    if a.ratchet and "katex" in checks:
        staged = set((git("diff", "--cached", "--name-only") or "").splitlines())
        results = promote_staged_katex(results, staged)
    blocking = [f for f in results if f[0] == "error"]
    if a.ratchet:
        try:      # AD13 G1: one line per run of the commit gate (mother vault only: a release does not ship gate_log)
            import gate_log as _GL
            _GL.record("audit", [(f[1], f"{f[2]}:{f[3]}", f[5]) for f in blocking])
        except ImportError:
            pass
        print(f"GATE {'BLOCKED' if blocking else 'CLEAR'} blocking={len(blocking)}")
        for f in blocking:
            print(f"BLOCK\t{f[0]}\t{f[1]}\t{f[2]}:{f[3]}\t{f[5]}")

    head = (git("rev-parse", "HEAD") or "").strip()
    by_rule = collections.Counter(f[1] for f in results)
    by_sev = collections.Counter(f[0] for f in results)
    print(f"AUDIT head={head[:10]} mode={mode} files={len(scope)}/{len(texts)} checks={','.join(sorted(checks))} leaf_max={a.leaf_max}")
    print("CACHE " + cache_note)
    print("SUMMARY " + " ".join(f"{s}={by_sev[s]}" for s in ("error", "warn", "info")) + " | " + " ".join(f"{k}={v}" for k, v in sorted(by_rule.items())))
    print(f"SNAPSHOT {head} " + " ".join(f"{k}={v}" for k, v in sorted(by_rule.items())))
    print("PRIORITY " + " | ".join(f"{score[r]} {r}" for r in sorted(priority, key=lambda x: -score[x])))
    shown = sorted((f for f in results if SEV[f[0]] >= SEV[a.min]), key=lambda f: (-SEV[f[0]], f[1], f[2], f[3]))
    for f in shown[:a.limit]:
        print(f"{f[0]}\t{f[1]}\t{f[2]}:{f[3]}\t{str(f[4])[:60]}\t{f[5]}")
    if len(shown) > a.limit:
        print(f"[{len(shown) - a.limit} more findings at --min {a.min}: narrow with --path, --check or raise --min]")

    gate = collections.Counter(f[0] for f in results)
    if gate["error"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
