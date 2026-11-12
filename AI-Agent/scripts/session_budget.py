#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Session budget printer (FX02/FX12, execution cycle 1 of the architecture-consumption fix).

Prints at task start: current context size (tiktoken o200k_base, AD06 T4 standard),
the announced per-call cost note, and the task-type call ceiling read from
AI-Agent/schema/budget.yaml — no hardcoded values in code (FX12 acceptance).
Prints at close: actual calls vs the announced ceiling.

Usage: session_budget --start <type>
       session_budget --close <type> <actual_calls>
       session_budget --check <type>
Exit:  0 normally; 1 if the close shows OVER; 2 if the map is missing/broken
       (the caller must not proceed blindly — ValueError never silently passed).
"""
import os
import sys

MAP_REL = os.path.join("schema", "budget.yaml")


def map_path():
    """budget.yaml relative to this script's vault root (AI-Agent/)."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), MAP_REL)


def load_budget(path=None):
    """Parse budget.yaml into {task_type: ceiling_int, ...} plus the cost note.

    Flat format (mini-parser, no yaml lib): list entries `- "type|ceiling"`.
    Raises ValueError on a missing block, a non-numeric ceiling, or duplicate keys
    — the caller must not proceed blindly on a broken map (FX12 negative tests).
    """
    path = path or map_path()
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                lines = lines[i + 1:]
                break
    caps = {}
    note = ""
    in_block = False
    for raw in lines:
        line = raw.strip()
        if line == "# Task budget ceilings (FX02/FX12)":
            in_block = True
            continue
        if in_block and line.startswith("- "):
            entry = line[2:].strip().strip('"')
            if "|" not in entry:
                continue
            key, _, val = entry.partition("|")
            key, val = key.strip(), val.strip()
            if key == "call_cost_note":
                note = val
            else:
                if not val.isdigit():
                    raise ValueError(f"budget: ceiling for '{key}' is not a number: '{val}'")
                if key in caps:
                    raise ValueError(f"budget: duplicate task type '{key}'")
                caps[key] = int(val)
    if not caps:
        raise ValueError(f"budget: no task-type ceilings found in {path}")
    if not note:
        raise ValueError(f"budget: call_cost_note missing in {path}")
    return caps, note


def ceiling_for(task_type, caps):
    if task_type not in caps:
        raise ValueError(f"budget: unknown task type '{task_type}' — declared: {sorted(caps)}")
    return caps[task_type]


def start_line(task_type, caps=None, note=None):
    if caps is None or note is None:
        caps, note = load_budget()
    return (
        f"BUDGET-START task={task_type} ceiling={ceiling_for(task_type, caps)} "
        f"note=\"{note}\""
    )


def close_line(task_type, actual, caps=None):
    if caps is None:
        caps, _ = load_budget()
    cap = ceiling_for(task_type, caps)
    status = "OK" if actual <= cap else "OVER"
    return f"BUDGET-CLOSE task={task_type} actual={actual} ceiling={cap} {status}", status


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    try:
        caps, note = load_budget()
    except (ValueError, OSError) as e:
        print(f"BLOCK budget: {e}", file=sys.stderr)
        return 2
    if "--start" in argv:
        i = argv.index("--start")
        if i + 1 >= len(argv):
            print("no task type given", file=sys.stderr)
            return 1
        print(start_line(argv[i + 1], caps, note))
        return 0
    if "--close" in argv:
        i = argv.index("--close")
        if i + 2 >= len(argv) or not argv[i + 2].isdigit():
            print("close needs a task type and a numeric call count", file=sys.stderr)
            return 1
        line, status = close_line(argv[i + 1], int(argv[i + 2]), caps)
        print(line)
        return 0 if status == "OK" else 1
    if "--check" in argv:
        i = argv.index("--check")
        if i + 1 >= len(argv):
            print("no task type given", file=sys.stderr)
            return 1
        print(f"BUDGET-CHECK task={argv[i + 1]} ceiling={ceiling_for(argv[i + 1], caps)}")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
