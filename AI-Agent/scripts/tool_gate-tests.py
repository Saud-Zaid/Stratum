#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""tool_gate-tests.py — Comprehensive Unit & Integration Tests for tool_gate.py.

AD13 M06 Verification:
- Tests 200-line read cap enforcement and surgical rejection.
- Tests actionable outline suggestions and section.py command formatting.
- Tests system override bypass mechanism.
- Tests path traversal and boundary security checks.
- Tests tool admission controller with argument validation.
- Tests JSON output structure and exit code contracts.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
VAULT_DIR = SCRIPTS_DIR.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import tool_gate

R = []


def ok(name: str, condition: bool, details: str = "") -> None:
    R.append((name, condition, details))
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name} {details}".strip())


def test_small_file_admitted():
    with tempfile.NamedTemporaryFile("w", suffix=".md", dir=VAULT_DIR, delete=False) as tf:
        tf.write("\n".join(f"Line {i}" for i in range(1, 100)))
        tf_path = Path(tf.name)
    try:
        res = tool_gate.check_read_admission(str(tf_path.relative_to(VAULT_DIR)))
        ok("T01-small-file-admitted", res["admitted"] is True and res["verdict"] == "ADMIT",
           f"lines={res['lines']}, admitted={res['admitted']}")
    finally:
        tf_path.unlink()


def test_large_file_rejected_with_surgical_guidance():
    with tempfile.NamedTemporaryFile("w", suffix=".md", dir=VAULT_DIR, delete=False) as tf:
        tf.write("# Heading One\n\n")
        tf.write("\n".join(f"Paragraph line {i}" for i in range(1, 150)) + "\n\n")
        tf.write("## Heading Two\n\n")
        tf.write("\n".join(f"More lines {i}" for i in range(1, 150)) + "\n")
        tf_path = Path(tf.name)
    try:
        rel_str = str(tf_path.relative_to(VAULT_DIR))
        res = tool_gate.check_read_admission(rel_str)
        is_rejected = res["admitted"] is False and res["verdict"] == "REJECT"
        has_sections = len(res["sections"]) >= 2
        has_commands = any("section.py" in cmd for cmd in res["suggested_actions"])
        ok("T02-large-file-rejected", is_rejected, f"lines={res['lines']} (cap={res['cap']})")
        ok("T03-actionable-sections-provided", has_sections and has_commands,
           f"sections={len(res['sections'])}, suggested_actions={len(res['suggested_actions'])}")
    finally:
        tf_path.unlink()


def test_system_override_admitted():
    with tempfile.NamedTemporaryFile("w", suffix=".md", dir=VAULT_DIR, delete=False) as tf:
        tf.write("\n".join(f"Line {i}" for i in range(1, 250)))
        tf_path = Path(tf.name)
    try:
        rel_str = str(tf_path.relative_to(VAULT_DIR))
        res = tool_gate.check_read_admission(rel_str, system_override=True)
        ok("T04-system-override-admitted", res["admitted"] is True and res["verdict"] == "ADMIT",
           f"override={res['system_override']}, lines={res['lines']}")
    finally:
        tf_path.unlink()


def test_path_traversal_prevention():
    res = tool_gate.check_read_admission("../../etc/passwd")
    ok("T05-path-traversal-blocked", res["admitted"] is False and "Security" in res["reason"],
       f"verdict={res['verdict']}")


def test_tool_admission_controller():
    # 1. Valid local script
    res_valid = tool_gate.check_tool_admission("outline", ["some_note.md"])
    ok("T06-tool-admit-valid", res_valid["admitted"] is True and res_valid["verdict"] == "ADMIT",
       f"tool={res_valid['tool']}")

    # 2. Argument traversal attack
    res_traversal = tool_gate.check_tool_admission("section", ["../../etc/shadow", "H1"])
    ok("T07-tool-arg-traversal-blocked", res_traversal["admitted"] is False and res_traversal["verdict"] == "REJECT",
       f"reason={res_traversal['reason']}")


def test_vault_stats():
    stats = tool_gate.get_vault_read_stats()
    ok("T08-vault-stats-calculated", stats["total_markdown_files"] > 50 and "safe_percentage" in stats,
       f"total={stats['total_markdown_files']}, safe={stats['safe_percentage']}%")


def test_cli_subprocess_contract():
    python_bin = sys.executable   # the interpreter running the tests: no wrapper dependency
    script = SCRIPTS_DIR / "tool_gate.py"

    # 1. CLI JSON output
    res_json = subprocess.run([str(python_bin), str(script), "check-read", "AI-Agent/schema/budget.yaml", "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        data = json.loads(res_json.stdout)
        json_valid = data["admitted"] is True and "lines" in data
    except Exception:
        json_valid = False
    ok("T09-cli-json-contract", json_valid and res_json.returncode == 0, "CLI emits valid JSON schema")

    # 2. CLI exit code 1 on rejection
    large_note = "AI-Agent/scripts/audit.py"
    res_rej = subprocess.run([str(python_bin), str(script), "check-read", large_note], capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok("T10-cli-exit-code-on-rejection", res_rej.returncode == 1 and "[REJECT]" in res_rej.stdout,
       f"returncode={res_rej.returncode}")


def _tmp_note(text: str, suffix: str = ".md") -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=suffix, dir=VAULT_DIR, delete=False, encoding="utf-8") as tf:
        tf.write(text)
    return Path(tf.name)


def test_byte_ceiling():
    """T-02d (U-29): a file within 200 lines but over the byte ceiling is rejected; ceiling 0 leaves behavior as before."""
    orig = tool_gate.read_cap_bytes
    wide = _tmp_note("\n".join("x" * 400 for _ in range(100)))              # 100 lines, ~40 KB
    try:
        tool_gate.read_cap_bytes = lambda: 0
        r0 = tool_gate.check_read_admission(str(wide.relative_to(VAULT_DIR)))
        ok("T08-byte-ceiling-off-admits", r0["admitted"] is True, str(r0["bytes"]))
        tool_gate.read_cap_bytes = lambda: 16384
        r1 = tool_gate.check_read_admission(str(wide.relative_to(VAULT_DIR)))
        ok("T09-over-bytes-rejected", r1["admitted"] is False and r1["lines"] <= 200 and "byte cap" in r1["reason"], r1["reason"])
        ok("T10-cap-bytes-reported", r1["cap_bytes"] == 16384)
        ro = tool_gate.check_read_admission(str(wide.relative_to(VAULT_DIR)), system_override=True)
        ok("T11-override-still-admits", ro["admitted"] is True)
        small = _tmp_note("\n".join("y" * 50 for _ in range(100)))
        try:
            rs = tool_gate.check_read_admission(str(small.relative_to(VAULT_DIR)))
            ok("T12-under-both-caps-admitted", rs["admitted"] is True)
        finally:
            small.unlink()
        many = _tmp_note("\n".join("z" for _ in range(300)))
        try:
            rm = tool_gate.check_read_admission(str(many.relative_to(VAULT_DIR)))
            ok("T13-over-lines-still-rejected", rm["admitted"] is False and "300 lines" in rm["reason"], rm["reason"])
        finally:
            many.unlink()
    finally:
        tool_gate.read_cap_bytes = orig
        wide.unlink()


def test_structured_outline():
    orig = tool_gate.read_cap_bytes
    j = _tmp_note(json.dumps({f"key{i}": "v" * 3000 for i in range(8)}, indent=0), ".json")
    y = _tmp_note("\n".join(f"top{i}:\n  - " + "w" * 3000 for i in range(8)), ".yaml")
    try:
        tool_gate.read_cap_bytes = lambda: 16384
        for f, name in ((j, "json"), (y, "yaml")):
            r = tool_gate.check_read_admission(str(f.relative_to(VAULT_DIR)))
            titles = [x["title"] for x in r["sections"]]
            ok(f"T14-{name}-outline-lists-top-keys", r["admitted"] is False and titles[:2] in (["key0", "key1"], ["top0", "top1"]), str(titles[:3]))
        bad = _tmp_note("{not json", ".json")
        try:
            ok("T15-bad-json-no-crash", tool_gate._structured_sections(".json", "{not json") == [])
        finally:
            bad.unlink()
    finally:
        tool_gate.read_cap_bytes = orig
        j.unlink()
        y.unlink()


def test_profile_drives_ceiling():
    from _vaultlib import load_profile
    want = load_profile(VAULT_DIR)["limits"]["read_cap_bytes"]   # 0 in the mother vault, the release patch sets 16384
    ok("T16-profile-drives-the-ceiling", tool_gate.read_cap_bytes() == want, f"{tool_gate.read_cap_bytes()} vs profile {want}")


def main():
    test_byte_ceiling()
    test_structured_outline()
    test_profile_drives_ceiling()
    test_small_file_admitted()
    test_large_file_rejected_with_surgical_guidance()
    test_system_override_admitted()
    test_path_traversal_prevention()
    test_tool_admission_controller()
    test_vault_stats()
    test_cli_subprocess_contract()

    passed = sum(1 for _, c, _ in R if c)
    total = len(R)
    print(f"\nTOOL-GATE-TESTS: {passed}/{total} passed")
    if passed != total:
        sys.exit(1)


if __name__ == "__main__":
    main()
