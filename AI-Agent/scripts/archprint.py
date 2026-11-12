# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Normalize and fingerprint architecture elements (ADR-016, D03). Read-only: prints, never writes.

An element is a heading whose title starts with an element ID (D03, M12, SH02, RL05, ...).
Its body runs to the next heading of the same or higher level. Status lines are outside the hash (E4).

Usage:
  archprint <path>                      TSV: id, level, fingerprint, title
  archprint <path> --json               JSON snapshot {id: {fp, title}} for the agent to save
  archprint <path> --against <json>     compare with a saved snapshot: changed / added / removed
"""
import hashlib
import json
import re
import sys
import unicodedata

from _vaultlib import VAULT, force_utf8_stdio, locale_value, read, sections, standard_parser

ID_RE = re.compile(r"^(SH|RL|AP|KR|LS|[GQSMDETKFRPZN])(\d{1,3})(?=$|[\s—:·\-])")
STATUS_RE = re.compile(r"^\s*[-*]?\s*(\*\*)?(" + (re.escape(locale_value("STATUS_WORD")) + "|" if locale_value("STATUS_WORD") else "") + r"status)(\*\*)?\s*[:：]", re.IGNORECASE)
TATWEEL = locale_value("TATWEEL", "\u0000")   # the Arabic elongation mark; a NUL placeholder where there is none, so replacing it is a no-op


def normalize(text: str) -> str:
    """The vault's normalization rule before any fingerprint: NFC, LF, no trailing spaces,
    no tatweel, blank-line runs collapsed, outer blank lines dropped. Letters never change."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(TATWEEL, "")
    lines = [ln.rstrip() for ln in text.split("\n")]
    out, blank = [], False
    for ln in lines:
        if ln == "":
            if not blank:
                out.append("")
            blank = True
        else:
            out.append(ln)
            blank = False
    return "\n".join(out).strip("\n")


def element_id(title: str):
    m = ID_RE.match(title.strip())
    return (m.group(1) + m.group(2)) if m else None


def elements(text: str) -> dict:
    """{id: {"level", "title", "body"}} for every ID heading. Body excludes the heading line
    and status lines. Duplicate IDs keep the first and are reported under key '__dup__'."""
    lines = text.splitlines()
    secs = sections(text)
    found, dups = {}, []
    for i, (level, title, start, count) in enumerate(secs):
        eid = element_id(title)
        if not eid:
            continue
        end = start + count - 1
        for level2, _t, start2, _c in secs[i + 1:]:
            if level2 <= level:
                end = start2 - 1
                break
        else:
            end = len(lines)
        body = [ln for ln in lines[start:end] if not STATUS_RE.match(ln)]
        if eid in found:
            dups.append(eid)
            continue
        found[eid] = {"level": level, "title": title.strip(), "body": "\n".join(body)}
    if dups:
        found["__dup__"] = dups
    return found


def fingerprint(body: str) -> str:
    return hashlib.sha256(normalize(body).encode("utf-8")).hexdigest()[:16]


def snapshot(text: str) -> dict:
    els = elements(text)
    els.pop("__dup__", None)
    return {k: {"fp": fingerprint(v["body"]), "title": v["title"]} for k, v in els.items()}


def compare(old: dict, new: dict) -> dict:
    return {
        "changed": sorted(k for k in new if k in old and new[k]["fp"] != old[k]["fp"]),
        "added": sorted(k for k in new if k not in old),
        "removed": sorted(k for k in old if k not in new),
    }


def main(argv):
    force_utf8_stdio()
    ap = standard_parser(__doc__, "archprint")
    ap.add_argument("path", help="architecture note, relative to the vault")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--json", action="store_true", help="JSON snapshot instead of TSV")
    mode.add_argument("--against", metavar="SNAPSHOT", help="compare with a saved snapshot")
    args = ap.parse_args(argv)
    argv = [args.path] + (["--json"] if args.json else []) + (["--against", args.against] if args.against else [])
    path = VAULT / argv[0]
    if not path.is_file():
        sys.exit(f"not found: {argv[0]}")
    text = read(path)
    els = elements(text)
    dups = els.pop("__dup__", [])
    snap = {k: {"fp": fingerprint(v["body"]), "title": v["title"]} for k, v in els.items()}
    if "--json" in argv:
        print(json.dumps(snap, ensure_ascii=False, indent=1, sort_keys=True))
    elif "--against" in argv:
        ref = VAULT / argv[argv.index("--against") + 1]
        diff = compare(json.loads(read(ref)), snap)
        for kind in ("changed", "added", "removed"):
            print(f"{kind}\t{len(diff[kind])}\t{' '.join(diff[kind])}")
    else:
        for k, v in els.items():
            print(f"{k}\tH{v['level']}\t{snap[k]['fp']}\t{v['title'][:80]}")
    if dups:
        print(f"WARN duplicate element IDs: {' '.join(dups)}")


if __name__ == "__main__":
    main(sys.argv[1:])
