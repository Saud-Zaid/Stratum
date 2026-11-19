#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""harness.py — probe of the six capabilities (FX03/T-07).

Reads the capabilities contract from AI-Agent/capabilities.yaml, probes each capability with
its own protocol, then prints the operating tier: full, reduced or minimal. Not one tool name
appears in this file — tool names have a single source, adapters.md (the declared separation)."""
import os
import re
import subprocess
import sys

VAULT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def contract_path():
    return os.path.join(VAULT, "AI-Agent", "capabilities.yaml")


def parse_contract(path):
    """Mini-parser for the contract: '- "C1|description"' lines. Raises ValueError on breakage."""
    if not os.path.isfile(path):
        raise ValueError("contract missing: %s" % path)
    caps = {}
    with open(path, encoding="utf-8") as f:
        text = f.read()
    in_contract = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("# Capabilities contract"):
            in_contract = True
            continue
        if not in_contract or not s.startswith('- "'):
            continue
        body = s[3:]
        if not body.endswith('"') or "|" not in body:
            raise ValueError("malformed contract line: %s" % line)
        body = body[:-1]
        cid, desc = body.split("|", 1)
        cid = cid.strip()
        if cid in caps:
            raise ValueError("duplicate capability: %s" % cid)
        if not re.fullmatch(r"C[1-6]", cid):
            raise ValueError("bad capability id: %s" % cid)
        caps[cid] = desc.strip()
    if set(caps) != {"C1", "C2", "C3", "C4", "C5", "C6"}:
        raise ValueError("contract incomplete: %s" % sorted(caps))
    return caps


def probe(cid):
    """Run the decisive cheap probe for one capability. Returns (ok: bool, evidence: str)."""
    if cid == "C1":  # partial reading of large notes
        p = os.path.join(VAULT, "AI-Agent", "scripts", "section.py")
        return os.path.isfile(p), "section.py present"
    if cid == "C2":  # batch script execution with readable output
        try:
            r = subprocess.run(
                [sys.executable, os.path.join(VAULT, "AI-Agent", "scripts", "session_budget.py"), "--start", "small"],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            )
            return r.returncode == 0 and "BUDGET-START" in r.stdout, "BUDGET-START rc=%d" % r.returncode
        except Exception as e:
            return False, "exception: %s" % e
    if cid == "C3":  # delegation to a sub-agent
        rd = os.path.join(VAULT, ".agents", "recipes")
        ok = os.path.isdir(rd) and any(n.endswith(".yaml") for n in os.listdir(rd))
        return ok, "recipes dir with %s" % ("yaml files" if ok else "no yaml")
    if cid == "C4":  # shared importable python library
        return os.path.isdir(os.path.join(VAULT, "AI-Agent", "pylib")), "pylib dir"
    if cid == "C5":  # session log written to disk
        p = os.path.join(VAULT, "AI-Agent", "sessions.md")
        return os.path.isfile(p), "sessions.md present"
    if cid == "C6":  # conditional write (only if unchanged since read)
        p = os.path.join(VAULT, "AI-Agent", "scripts", "apply.py")
        return os.path.isfile(p), "apply.py present"
    return False, "unknown capability: %s" % cid


def derive_layer(results):
    """Layer from probe results: full / reduced / minimal. `results` is a list of booleans."""
    passed = sum(1 for ok in results if ok)
    if passed == 6:
        return "full"
    if passed >= 4:
        return "reduced"
    if passed >= 2:
        return "minimal"
    return "minimal"


def run_layer_check(path=None):
    """Full check: parse contract, probe all six, print layer. Returns (layer, results)."""
    caps = parse_contract(path or contract_path())
    results = []
    for cid in ("C1", "C2", "C3", "C4", "C5", "C6"):
        ok, ev = probe(cid)
        results.append((cid, ok, ev))
    layer = derive_layer([r[1] for r in results])
    print("CAP-LAYER %s (%d/6)" % (layer, sum(1 for r in results if r[1])))
    for cid, ok, ev in results:
        print("  %s %s %s" % (cid, "PASS" if ok else "MISS", ev))
    return layer, results


def main(argv):
    for_json = "--json" in argv
    try:
        layer, results = run_layer_check()
    except ValueError as e:
        print("CONTRACT-BROKEN %s" % e)
        return 2
    if for_json:
        import json
        print(json.dumps({"layer": layer, "results": [{"id": c, "ok": o, "evidence": e} for c, o, e in results]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
