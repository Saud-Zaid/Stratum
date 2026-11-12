#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""harness-tests.py — checks for harness.py (FX03/T-07).

Positive: contract parses, probes map C1-C6, layer derivation full/reduced/minimal.
Negative: missing contract, malformed line, duplicate id, bad id, incomplete set.
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness  # noqa: E402

SCRIPT = os.path.join(HERE, "harness.py")
VAULT = harness.VAULT

tmp = tempfile.mkdtemp(prefix="harness-tests-")
passed = failed = 0


def ok(name):
    global passed
    passed += 1
    print("PASS %s" % name)


def fail(name, detail):
    global failed
    failed += 1
    print("FAIL %s %s" % (name, detail))


def t1_parse_contract():
    try:
        caps = harness.parse_contract(harness.contract_path())
        if set(caps) == {"C1", "C2", "C3", "C4", "C5", "C6"} and all(isinstance(v, str) and v for v in caps.values()):
            ok("t1_parse_contract")
        else:
            fail("t1_parse_contract", "unexpected caps: %s" % sorted(caps))
    except ValueError as e:
        fail("t1_parse_contract", str(e))


def _write_contract(content):
    p = os.path.join(tmp, "caps-%d.yaml" % len(os.listdir(tmp)))
    with open(p, "w", encoding="utf-8") as f:
        f.write(content)
    return p


GOOD = """---
status: active
---

# Capabilities contract (capabilities contract)

- "C1|partial reading"
- "C2|batch execution"
- "C3|delegation"
- "C4|library"
- "C5|session log"
- "C6|conditional write"
"""


def t2_real_contract():
    try:
        harness.parse_contract(_write_contract(GOOD))
        ok("t2_good_contract")
    except ValueError as e:
        fail("t2_good_contract", str(e))


def t3_missing():
    try:
        harness.parse_contract(os.path.join(tmp, "no-such-file.yaml"))
        fail("t3_missing", "no ValueError")
    except ValueError:
        ok("t3_missing")


def t4_malformed():
    bad = GOOD.replace('- "C3|delegation"', "- C3 no-quotes-no-pipe")
    try:
        harness.parse_contract(_write_contract(bad))
        fail("t4_malformed", "no ValueError")
    except ValueError:
        ok("t4_malformed")


def t5_duplicate():
    bad = GOOD.replace('- "C4|library"', '- "C3|duplicate"')
    try:
        harness.parse_contract(_write_contract(bad))
        fail("t5_duplicate", "no ValueError")
    except ValueError:
        ok("t5_duplicate")


def t6_bad_id():
    bad = GOOD.replace('- "C4|library"', '- "C7|undefined"')
    try:
        harness.parse_contract(_write_contract(bad))
        fail("t6_bad_id", "no ValueError")
    except ValueError:
        ok("t6_bad_id")


def t7_incomplete():
    bad = GOOD.replace('- "C6|conditional write"\n', "")
    try:
        harness.parse_contract(_write_contract(bad))
        fail("t7_incomplete", "no ValueError")
    except ValueError:
        ok("t7_incomplete")


def t8_probe_map():
    for cid in ("C1", "C2", "C3", "C4", "C5", "C6"):
        res = harness.probe(cid)
        if not (isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], bool) and isinstance(res[1], str)):
            fail("t8_probe_map", "bad probe shape for %s" % cid)
            return
    ok("t8_probe_map")


def t9_layers():
    if harness.derive_layer([True] * 6) != "full":
        fail("t9_layers", "full expected")
        return
    if harness.derive_layer([True, True, False, True, True, False]) != "reduced":
        fail("t9_layers", "reduced expected")
        return
    if harness.derive_layer([True, False, False, False, False, False]) != "minimal":
        fail("t9_layers", "minimal expected")
        return
    ok("t9_layers")


def t10_cli():
    r = subprocess.run([sys.executable, SCRIPT], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or "CAP-LAYER" not in r.stdout:
        fail("t10_cli", "rc=%d out=%r" % (r.returncode, r.stdout[:200]))
        return
    if "CONTRACT-BROKEN" in r.stdout:
        fail("t10_cli", "contract broken on real vault")
        return
    ok("t10_cli")


def t11_cli_json():
    r = subprocess.run([sys.executable, SCRIPT, "--json"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        fail("t11_cli_json", "rc=%d" % r.returncode)
        return
    line = [l for l in r.stdout.splitlines() if l.startswith("{")]
    if not line:
        fail("t11_cli_json", "no json line")
        return
    data = json.loads(line[-1])
    if data.get("layer") not in ("full", "reduced", "minimal") or len(data.get("results", [])) != 6:
        fail("t11_cli_json", "bad json: %s" % line[-1][:200])
        return
    ok("t11_cli_json")


def t12_real_probes_match_files():
    real = {c: o for c, o, _ in harness.run_layer_check()[1]}
    expect = {
        "C1": os.path.isfile(os.path.join(VAULT, "AI-Agent", "scripts", "section.py")),
        "C2": True,
        "C3": os.path.isdir(os.path.join(VAULT, ".agents", "recipes")),
        "C4": os.path.isdir(os.path.join(VAULT, "AI-Agent", "pylib")),
        "C5": os.path.isfile(os.path.join(VAULT, "AI-Agent", "sessions.md")),
        "C6": os.path.isfile(os.path.join(VAULT, "AI-Agent", "scripts", "apply.py")),
    }
    if real != expect:
        fail("t12_real_probes_match_files", "mismatch %s vs %s" % (real, expect))
        return
    ok("t12_real_probes_match_files")


for fn in (t1_parse_contract, t2_real_contract, t3_missing, t4_malformed, t5_duplicate,
           t6_bad_id, t7_incomplete, t8_probe_map, t9_layers, t10_cli, t11_cli_json,
           t12_real_probes_match_files):
    fn()

print("SUITE %d/%d" % (passed, passed + failed))
sys.exit(1 if failed else 0)
