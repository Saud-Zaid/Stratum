#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""apply.py — multi-file write batches with conditional verification, block edits, receipts and rollback
(FX04/T-09, extended by AD13 D1).

Usage: vault-python AI-Agent/scripts/apply.py --plan <plan.json | -> [--dry-run]     (`-` reads the plan from stdin)

Plan format (JSON): {"operations": [op, ...]}. Every op has "path" and exactly one write form:
  {"path": p, "newContent": "<the full content>"}                          whole file (creates it if missing)
  {"path": p, "edits": [{"old": "...", "new": "..."}, ...]}                search and replace blocks
  {"path": p, "section": "<heading text>", "newBody": "..."}               replace the body of one unique heading
and optionally a guard: "expectedContent" (exact text) and "ifMatch" (sha256 of the file's UTF-8 bytes, the
`before_sha` of an earlier receipt). Line endings are kept exactly as they are on disk.

Edit rules: each `old` must occur exactly once in the text as it stands after the edits before it; none or several
aborts the whole batch. An edit whose `old` is gone but whose `new` is present exactly once is reported as already
applied (a retry after a crash is safe); that detection is skipped when `new` contains `old`, so use `ifMatch`
there. A section edit keeps the heading line and replaces everything up to the next heading of the file's outline.

Behavior:
1. Preflight: paths sandboxed to the vault, guards checked, every edit resolved in memory. Any failure aborts the
   whole batch with NO writes. Several ops on one path are folded in order and written once.
2. Commit: each changed file is written to a temporary file beside it, flushed and renamed over the original, so a
   crash never leaves half a file. A failure rolls back every file this run changed, in reverse order, byte-exact.
3. Receipts: per file, the sha256 before and after, bytes, lines changed, edits applied and already applied.
   `--dry-run` runs step 1 only and prints the receipts it would produce.

Output: a JSON line: {"status": "applied"|"dry_run"|"aborted"|"rolled_back"|"invalid", "errors": [...],
"applied": <ops>, "files_changed": <n>, "receipts": [...]}. Exit codes: 0 = applied or dry run;
1 = aborted or rolled back; 2 = broken plan file.
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import sys

VAULT = os.environ.get("VAULT") or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MAX_DIFF_LINES = 20000


def resolve_sandboxed(path):
    """Resolve path against vault root; reject anything escaping the vault."""
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    full = os.path.realpath(os.path.join(VAULT, path))
    vault_real = os.path.realpath(VAULT)
    if not full.startswith(vault_real + os.sep) and full != vault_real:
        raise ValueError("path escapes vault sandbox: %s" % path)
    return full


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_exact(full):
    """File text with line endings untouched (no newline translation)."""
    with open(full, encoding="utf-8", newline="") as f:
        return f.read()


def load_plan(path):
    """Load and validate the plan file. Raises ValueError on structural breakage."""
    if path != "-" and not os.path.isfile(path):
        raise ValueError("plan file missing: %s" % path)
    try:
        if path == "-":
            plan = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        else:
            with open(path, encoding="utf-8") as f:
                plan = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError("plan is not valid JSON: %s" % e)
    if not isinstance(plan, dict):
        raise ValueError("plan must be a JSON object")
    ops = plan.get("operations")
    if not isinstance(ops, list) or not ops:
        raise ValueError("plan must have a non-empty 'operations' list")
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise ValueError("operation %d is not an object" % i)
        if not isinstance(op.get("path"), str) or not op["path"]:
            raise ValueError("operation %d missing 'path'" % i)
        forms = [k for k in ("newContent", "edits", "section") if k in op]
        if len(forms) != 1:
            raise ValueError("operation %d needs exactly one of newContent, edits, section (got %s)" % (i, forms or "none"))
        if forms[0] == "newContent" and not isinstance(op["newContent"], str):
            raise ValueError("operation %d: newContent must be a string" % i)
        if forms[0] == "edits":
            ed = op["edits"]
            if not isinstance(ed, list) or not ed or not all(
                    isinstance(e, dict) and isinstance(e.get("old"), str) and isinstance(e.get("new"), str) and e["old"] for e in ed):
                raise ValueError("operation %d: edits must be a non-empty list of {old (non-empty), new} strings" % i)
        if forms[0] == "section" and (not isinstance(op["section"], str) or not op["section"].strip()
                                      or not isinstance(op.get("newBody"), str)):
            raise ValueError("operation %d: section needs a heading text and a string newBody" % i)
        if "expectedContent" in op and not isinstance(op["expectedContent"], str):
            raise ValueError("operation %d: expectedContent must be a string" % i)
        if "ifMatch" in op and not (isinstance(op["ifMatch"], str) and HEX64.match(op["ifMatch"])):
            raise ValueError("operation %d: ifMatch must be a 64-character lowercase sha256" % i)
    return plan


def _apply_section(cur, heading, body):
    """New text with the body of the unique heading replaced, or an error string."""
    from _vaultlib import sections
    want = heading.strip()
    hits = [s for s in sections(cur) if s[1].strip() == want]
    if len(hits) != 1:
        return None, ("heading %r not found" % heading) if not hits else ("heading %r is ambiguous (%d matches)" % (heading, len(hits)))
    _level, _title, line, count = hits[0]
    lines = cur.splitlines(keepends=True)
    eol = "\r\n" if "\r\n" in cur else "\n"
    new_body = body.replace("\r\n", "\n").replace("\n", eol)
    return "".join(lines[:line]) + new_body + "".join(lines[line + count - 1:]), None


HINT_MIN_SIMILARITY = 0.6     # below this, no "closest text" is offered (a wrong hint is worse than none)
HINT_EXCERPT = 300
HINT_MAX_CANDIDATES = 40


def _near_miss(cur, old):
    """A diagnosis for an `old` text that is not in `cur`, in the spirit of Aider's "Did you mean to match some of these actual
    lines": names how the text differs when it differs only in whitespace or line endings, else the closest block of lines
    (line numbers, similarity, a short excerpt). Returns "" when nothing is close enough. Never changes anything."""
    if "\r\n" in cur and "\r\n" not in old and old.replace("\n", "\r\n") in cur:
        return "; the file uses CRLF line endings and the old text uses LF"
    if "\r\n" in old and "\r\n" not in cur and old.replace("\r\n", "\n") in cur:
        return "; the old text uses CRLF line endings and the file uses LF"
    want = old.splitlines()
    have = cur.splitlines()
    if not want or not have or len(cur) > 2_000_000:
        return ""
    k = len(want)
    norm = lambda ls: [re.sub(r"\s+", " ", x).strip() for x in ls]
    nwant, nhave = norm(want), norm(have)
    for s in range(0, len(have) - k + 1):
        if nhave[s:s + k] == nwant:
            how = "leading or trailing whitespace" if [x.strip() for x in have[s:s + k]] == [x.strip() for x in want] else "internal whitespace"
            return "; the same text exists at lines %d-%d and differs only in %s" % (s + 1, s + k, how)
    first = next((x for x in nwant if x), "")
    ranked = sorted(((difflib.SequenceMatcher(None, x, first).quick_ratio(), i) for i, x in enumerate(nhave)), reverse=True) if first else []
    scored = sorted(((difflib.SequenceMatcher(None, nhave[i], first).ratio(), i) for q, i in ranked[:200] if q >= HINT_MIN_SIMILARITY), reverse=True)
    cands = [i for r, i in scored if r >= HINT_MIN_SIMILARITY][:HINT_MAX_CANDIDATES]    # the best lines, not the first ones: generated text has many alike
    best, at = 0.0, -1
    target = "\n".join(nwant)
    for s in cands:
        for start in {s, max(0, s - 1)}:
            ratio = difflib.SequenceMatcher(None, "\n".join(nhave[start:start + k]), target).ratio()
            if ratio > best:
                best, at = ratio, start
    if best < HINT_MIN_SIMILARITY or at < 0:
        return ""
    excerpt = "\n".join(have[at:at + k])
    if len(excerpt) > HINT_EXCERPT:
        excerpt = excerpt[:HINT_EXCERPT] + "..."
    return "; closest text is at lines %d-%d (similarity %.2f): %s" % (at + 1, at + min(k, len(have) - at), best, json.dumps(excerpt, ensure_ascii=False))


def _match_lines(cur, old, limit=5):
    """Line numbers where `old` starts, for an ambiguous match (the agent adds context to pick one)."""
    out, pos = [], cur.find(old)
    while pos != -1 and len(out) < limit:
        out.append(cur.count("\n", 0, pos) + 1)
        pos = cur.find(old, pos + 1)
    return out


def _apply_op(op, i, cur):
    """(new_text, receipt_counts, error) for one op against the current text of its file."""
    counts = {"applied": 0, "already": 0}
    if "newContent" in op:
        return op["newContent"], counts, None
    if "section" in op:
        if cur is None:
            return None, counts, "op %d: section edit but the file is missing: %s" % (i, op["path"])
        new, err = _apply_section(cur, op["section"], op["newBody"])
        if err:
            return None, counts, "op %d: %s" % (i, err)
        counts["applied"] = 1
        return new, counts, None
    if cur is None:
        return None, counts, "op %d: edits on a missing file: %s" % (i, op["path"])
    for j, e in enumerate(op["edits"]):
        old, new = e["old"], e["new"]
        n = cur.count(old)
        if n == 1:
            cur = cur.replace(old, new, 1)
            counts["applied"] += 1
        elif n == 0:
            if old not in new and new and cur.count(new) == 1:
                counts["already"] += 1
            else:
                return None, counts, "op %d edit %d: old text not found in %s%s" % (i, j, op["path"], _near_miss(cur, old))
        else:
            return None, counts, "op %d edit %d: old text is ambiguous (%d matches) in %s; it starts at lines %s, add surrounding text to pick one" % (
                i, j, n, op["path"], ", ".join(str(x) for x in _match_lines(cur, old)) + (", ..." if n > 5 else ""))
    return cur, counts, None


def _lines_changed(a, b):
    if a is None or max(a.count("\n"), b.count("\n")) > MAX_DIFF_LINES:
        return None
    return sum(1 for l in difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="", n=0)
               if l[:1] in "+-" and l[:3] not in ("+++", "---"))


def preflight(ops):
    """Fold every op in memory. Returns (errors, files, receipts); files maps full path -> (original, final)."""
    errors, files, order, counts_by = [], {}, [], {}
    for i, op in enumerate(ops):
        try:
            full = resolve_sandboxed(op["path"])
        except ValueError as e:
            errors.append("op %d: %s" % (i, e))
            continue
        if full not in files:
            try:
                orig = read_exact(full) if os.path.isfile(full) else None
            except (OSError, UnicodeDecodeError) as e:
                errors.append("op %d: cannot read %s: %s" % (i, op["path"], type(e).__name__))
                continue
            files[full] = [orig, orig, op["path"]]
            order.append(full)
            counts_by[full] = {"applied": 0, "already": 0}
        cur = files[full][1]
        if cur is None and ("expectedContent" in op or "ifMatch" in op):
            errors.append("op %d: file missing but a guard was given: %s" % (i, op["path"]))
            continue
        if "expectedContent" in op and cur != op["expectedContent"]:
            errors.append("op %d: expectedContent mismatch: %s" % (i, op["path"]))
            continue
        if "ifMatch" in op and sha(cur) != op["ifMatch"]:
            errors.append("op %d: ifMatch mismatch: %s (file sha256 is %s)" % (i, op["path"], sha(cur)))
            continue
        new, counts, err = _apply_op(op, i, cur)
        if err:
            errors.append(err)
            continue
        files[full][1] = new
        for k in counts:
            counts_by[full][k] += counts[k]
    receipts = []
    for full in order:
        orig, final, rel = files[full]
        receipts.append({"path": rel, "created": orig is None, "unchanged": orig == final,
                         "before_sha": sha(orig) if orig is not None else None, "after_sha": sha(final) if final is not None else None,
                         "bytes_before": len(orig.encode("utf-8")) if orig is not None else 0,
                         "bytes_after": len(final.encode("utf-8")) if final is not None else 0,
                         "lines_changed": _lines_changed(orig, final) if final is not None else None,
                         "edits_applied": counts_by[full]["applied"], "edits_already_applied": counts_by[full]["already"]})
    return errors, files, receipts


_tmp_counter = [0]


def _fsync_dir(d):
    """Make the rename itself durable (python-atomicwrites does the same): best effort, skipped where a directory cannot be opened."""
    if not hasattr(os, "O_DIRECTORY"):
        return
    try:
        fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_atomic(full, text):
    """Temporary file beside the target, flushed and fsynced, renamed over it; the temp file never survives."""
    d = os.path.dirname(full)
    os.makedirs(d, exist_ok=True)
    _tmp_counter[0] += 1
    tmp = os.path.join(d, ".apply-%d-%d.tmp" % (os.getpid(), _tmp_counter[0]))
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if os.path.isfile(full):
            try:
                os.chmod(tmp, os.stat(full).st_mode & 0o7777)
            except OSError:
                pass
        os.replace(tmp, full)
        _fsync_dir(d)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def commit(files):
    """Write every changed file. On failure restore what this run changed, in reverse order. Returns (errors, status)."""
    done = []   # (full, original) in write order
    errors = []
    for full, (orig, final, rel) in files.items():
        if orig == final:
            continue
        try:
            _write_atomic(full, final)
            done.append((full, orig))
        except OSError as e:
            errors.append("write failed for %s: %s" % (rel, e))
            break
    if errors:
        for full, orig in reversed(done):
            try:
                if orig is None:
                    os.remove(full)
                else:
                    _write_atomic(full, orig)
            except OSError:
                errors.append("rollback failed for %s" % full)
        return errors, "rolled_back"
    return errors, "applied"


def main(argv):
    parser = argparse.ArgumentParser(description="Apply multi-file write plan with conditional checks")
    parser.add_argument("--plan", required=True, help="path to plan JSON")
    parser.add_argument("--dry-run", action="store_true", help="resolve everything, write nothing, print the receipts")
    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
    except ValueError as e:
        print(json.dumps({"status": "invalid", "errors": [str(e)]}, ensure_ascii=False))
        return 2

    ops = plan["operations"]
    errors, files, receipts = preflight(ops)
    if errors:
        print(json.dumps({"status": "aborted", "errors": errors}, ensure_ascii=False))
        return 1
    changed = sum(1 for r in receipts if not r["unchanged"])
    if args.dry_run:
        print(json.dumps({"status": "dry_run", "errors": [], "applied": 0, "files_changed": changed, "receipts": receipts},
                         ensure_ascii=False))
        return 0
    errors, status = commit(files)
    print(json.dumps({"status": status, "errors": errors, "applied": len(ops) if status == "applied" else 0,
                      "files_changed": changed if status == "applied" else 0,
                      "receipts": receipts if status == "applied" else []}, ensure_ascii=False))
    return 0 if status == "applied" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
