#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""apply.py — multi-file write batches with conditional verification and a rollback plan (FX04/T-09).

Usage: vault-python AI-Agent/scripts/apply.py --plan <plan.json>

Plan format (JSON):
{
  "operations": [
    {
      "path": "01-Projects/my-note.md",
      "expectedContent": "optional exact text to verify before write",
      "newContent": "the full content to write"
    }
  ]
}

Behavior:
1. Pre-flight: all paths resolved (sandboxed to vault root), all expectedContent
   matched. Any failure aborts the whole batch with exit code 1 and NO writes.
2. Commit: writes newContent for every operation.
3. Soft rollback: if a write fails mid-batch (unexpected IO error), files already
   written in this run are restored to their pre-write content.

Output: a JSON line: {"status": "aborted"|"applied"|"rolled_back", "errors": [...]}
Exit codes: 0 = applied; 1 = aborted/rolled back; 2 = broken plan file.
"""
import argparse
import json
import os
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def resolve_sandboxed(path):
    """Resolve path against vault root; reject anything escaping the vault."""
    full = os.path.realpath(os.path.join(VAULT, path))
    vault_real = os.path.realpath(VAULT)
    if not full.startswith(vault_real + os.sep) and full != vault_real:
        raise ValueError("path escapes vault sandbox: %s" % path)
    return full


def load_plan(path):
    """Load and validate the plan file. Raises ValueError on structural breakage."""
    if not os.path.isfile(path):
        raise ValueError("plan file missing: %s" % path)
    try:
        with open(path, encoding="utf-8") as f:
            plan = json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError("plan is not valid JSON: %s" % e)
    ops = plan.get("operations")
    if not isinstance(ops, list) or not ops:
        raise ValueError("plan must have a non-empty 'operations' list")
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            raise ValueError("operation %d is not an object" % i)
        if "path" not in op or "newContent" not in op:
            raise ValueError("operation %d missing 'path' or 'newContent'" % i)
    return plan


def preflight(ops):
    """Check every path and expectedContent. Returns list of error strings (empty = clear)."""
    errors = []
    for i, op in enumerate(ops):
        try:
            full = resolve_sandboxed(op["path"])
        except ValueError as e:
            errors.append("op %d: %s" % (i, e))
            continue
        if not os.path.isfile(full):
            if "expectedContent" in op:
                errors.append("op %d: file missing but expectedContent given: %s" % (i, op["path"]))
            continue
        with open(full, encoding="utf-8") as f:
            current = f.read()
        exp = op.get("expectedContent")
        if exp is not None and current != exp:
            errors.append("op %d: expectedContent mismatch: %s" % (i, op["path"]))
    return errors


def commit(ops):
    """Write all operations. On failure, roll back what this run changed. Returns errors."""
    written = []  # (full_path, original_content_or_None)
    errors = []
    for i, op in enumerate(ops):
        try:
            full = resolve_sandboxed(op["path"])
            os.makedirs(os.path.dirname(full), exist_ok=True)
            original = None
            if os.path.isfile(full):
                with open(full, encoding="utf-8") as f:
                    original = f.read()
            with open(full, "w", encoding="utf-8") as f:
                f.write(op["newContent"])
            written.append((full, original))
        except OSError as e:
            errors.append("op %d write failed: %s" % (i, e))
            break
    if errors:
        # Soft rollback: restore every file this run touched.
        for full, original in written:
            try:
                if original is None:
                    os.remove(full)
                else:
                    with open(full, "w", encoding="utf-8") as f:
                        f.write(original)
            except OSError:
                errors.append("rollback failed for %s" % full)
        return errors, "rolled_back"
    return errors, "applied"


def main(argv):
    parser = argparse.ArgumentParser(description="Apply multi-file write plan with conditional checks")
    parser.add_argument("--plan", required=True, help="path to plan JSON")
    args = parser.parse_args(argv)

    try:
        plan = load_plan(args.plan)
    except ValueError as e:
        print(json.dumps({"status": "invalid", "errors": [str(e)]}, ensure_ascii=False))
        return 2

    ops = plan["operations"]
    errors = preflight(ops)
    if errors:
        print(json.dumps({"status": "aborted", "errors": errors}, ensure_ascii=False))
        return 1

    errors, status = commit(ops)
    print(json.dumps({"status": status, "errors": errors, "applied": len(ops) if status == "applied" else 0},
                     ensure_ascii=False))
    return 0 if status == "applied" else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
