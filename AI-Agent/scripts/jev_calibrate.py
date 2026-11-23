#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""jev_calibrate.py - measure a recurring Jev question on a labelled set of cases BEFORE relying on it.

Usage:
  AI-Agent/vault-python AI-Agent/scripts/jev_calibrate.py [QUESTION ...] [--registry PATH] [--run] [--json OUT]

Without --run it only checks the files and prints the plan (cases, the most calls it could make, the estimated cost);
nothing is sent. With --run it asks Jev for every case through jev_client.py (paid calls on your OpenRouter key; each
case's state leaves your machine) and prints, per question:
  OK            no false accept, false-reject rate within the limit, enough deceptive cases to certify a threshold
  PROVISIONAL   no false accept and the false-reject rate within the limit, but too few deceptive cases to certify
  FAIL          a false accept (a case labelled fail that passed), or too many false rejects
Exit 0 when no question FAILs, 1 when one does, 2 when the registry or a case file is invalid.

The registry (default AI-Agent/config/jev-questions.yaml) holds every recurring question's exact wording, so that any change
of wording, criteria, threshold or model is visible and is recalibrated before use. Each question names its case file:
  cases: [{id, label: pass|fail, deceptive: true|false, state: <the evidence Jev sees, text or mapping>}]
A deceptive case is a fail that looks like a pass (the error that costs most). The rules:
  1. one question = one thing, at most 40 words, one sentence
  2. each criterion is observable in the state; no opinion words, no hint of the wanted answer
  3. the state carries the evidence the question needs and nothing that steers it
  4. zero false accepts; false rejects at most max_false_reject
  5. a refusal or an error from Jev is never a pass
  6. a first answer in the borderline band is asked 3 times and the median is used
The certified threshold is the Neyman-Pearson umbrella threshold (Tong, Feng and Li 2018): the k*-th order statistic of the
deceptive cases' scores, accept only strictly above it, capped at the registry threshold. It needs at least
ceil(log(delta) / log(1 - alpha)) deceptive cases: 29 for alpha 0.10, 59 for alpha 0.05 (delta 0.05).
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_REGISTRY = ROOT / "AI-Agent" / "config" / "jev-questions.yaml"
COST_PER_CALL = 0.00003          # USD, the highest cost measured for one Jev call on jev-1.14 (2026-11-23)
DELTA = 0.05


class RegistryError(Exception):
    pass


def np_min_negatives(alpha: float, delta: float = DELTA) -> int:
    return math.ceil(math.log(delta) / math.log(1 - alpha))


def np_threshold(neg_scores: list, alpha: float, delta: float = DELTA):
    """k* = min{k : sum_{j=k}^{n} C(n,j)(1-alpha)^j alpha^(n-j) <= delta}; the threshold is the k*-th smallest score."""
    t = sorted(neg_scores)
    n = len(t)
    for k in range(1, n + 1):
        if sum(math.comb(n, j) * (1 - alpha) ** j * alpha ** (n - j) for j in range(k, n + 1)) <= delta:
            return t[k - 1]
    return None


def pinned_model() -> str:
    """The model the shipped server uses: JEV_MODEL, else the default written in jev_mcp.py."""
    if os.environ.get("JEV_MODEL"):
        return os.environ["JEV_MODEL"]
    m = re.search(r'MODEL = os\.getenv\("JEV_MODEL", "([^"]+)"\)', (HERE / "jev_mcp.py").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def load(registry_path: Path, names: list) -> tuple[dict, dict]:
    """The registry and {question: cases}, validated. Raises RegistryError with every problem found."""
    import yaml
    if not registry_path.is_file():
        raise RegistryError(f"registry missing: {registry_path}")
    reg = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    errs = []
    for k in ("model", "threshold", "borderline", "max_false_reject", "alpha", "questions"):
        if k not in reg:
            errs.append(f"registry: missing key {k!r}")
    if errs:
        raise RegistryError("; ".join(errs))
    if reg["model"] != pinned_model():
        errs.append(f"registry model {reg['model']!r} differs from the server's {pinned_model()!r}: recalibrate and update the registry")
    qs = reg["questions"] or {}
    unknown = [n for n in names if n not in qs]
    if unknown:
        errs.append(f"unknown question(s): {', '.join(unknown)}")
    cases_by_q = {}
    for name in names or list(qs):
        if name not in qs:
            continue
        q = qs[name]
        if q.get("tool") not in ("jev_check", "jev_choice"):
            errs.append(f"{name}: tool must be jev_check or jev_choice")
        crit = q.get("criteria") or {}
        if q.get("tool") == "jev_check" and set(crit) != {"true", "false"}:
            errs.append(f"{name}: a jev_check question needs criteria 'true' and 'false'")
        if q.get("tool") == "jev_choice" and q.get("want") not in crit:
            errs.append(f"{name}: 'want' must be one of the criteria")
        words = len(str(q.get("instructions", "")).split())
        if not words or words > 40:
            errs.append(f"{name}: instructions must be one sentence of at most 40 words ({words})")
        path = Path(str(q.get("golden", "")))
        path = path if path.is_absolute() else ROOT / path
        if not q.get("golden") or not path.is_file():
            errs.append(f"{name}: case file missing: {q.get('golden')}")
            continue
        cases = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("cases") or []
        ids = [c.get("id") for c in cases]
        if len(set(ids)) != len(ids):
            errs.append(f"{name}: duplicate case ids")
        for c in cases:
            if c.get("label") not in ("pass", "fail") or not c.get("state") or not c.get("id"):
                errs.append(f"{name}: case {c.get('id')!r} needs id, label pass|fail and a state")
            if c.get("deceptive") and c.get("label") != "fail":
                errs.append(f"{name}: case {c.get('id')!r} is deceptive, so its label must be fail")
        if not any(c.get("label") == "pass" for c in cases) or not any(c.get("label") == "fail" for c in cases):
            errs.append(f"{name}: the case file needs both pass and fail cases")
        cases_by_q[name] = cases
    if errs:
        raise RegistryError("; ".join(errs))
    return reg, cases_by_q


def ask_jev(tool: str, args: dict) -> dict:
    """One call through the shipped client. A failed call returns {'error': ...} (rule 5 turns it into a fail)."""
    r = subprocess.run([sys.executable, str(HERE / "jev_client.py"), tool, json.dumps(args, ensure_ascii=False)],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    try:
        return json.loads(r.stdout[r.stdout.index("{"):])
    except ValueError:
        return {"error": (r.stderr or r.stdout)[-300:]}


def score_case(q: dict, state, reg: dict, ask=None) -> dict:
    """{p, confidence, score, pass, samples} for one case; the median of 3 when the first answer is borderline."""
    ask = ask or ask_jev
    lo, hi = reg["borderline"]
    samples = []
    for k in range(3):
        if q["tool"] == "jev_check":
            v = ask("jev_check", {"state": state, "question": q["instructions"], "if_true": q["criteria"]["true"], "if_false": q["criteria"]["false"]})
        else:
            v = ask("jev_choice", {"state": state, "question": q["instructions"], "options": q["criteria"]})
        a = (v.get("answers") or {}).get("q") or {}
        if v.get("error") or a.get("type") == "refusal" or not a:
            samples.append((0.0, 0.0))
        elif q["tool"] == "jev_check":
            samples.append((float(a.get("noul", 0)), float(a.get("confidence", 1.0))))
        else:
            samples.append((float((a.get("probabilities") or {}).get(q["want"], 0)), float(a.get("confidence", 0))))
        if k == 0 and not (lo <= min(samples[0]) < hi):
            break
    ps, cs = sorted(s[0] for s in samples), sorted(s[1] for s in samples)
    p, c = ps[len(ps) // 2], cs[len(cs) // 2]
    return {"p": p, "confidence": c, "score": min(p, c), "pass": p >= reg["threshold"] and c >= reg["threshold"], "samples": len(samples)}


def calibrate(name: str, q: dict, cases: list, reg: dict, ask=None) -> dict:
    res = [(c, score_case(q, c["state"], reg, ask)) for c in cases]
    fa = [c["id"] for c, r in res if c["label"] == "fail" and r["pass"]]
    fr = [c["id"] for c, r in res if c["label"] == "pass" and not r["pass"]]
    npos = sum(1 for c in cases if c["label"] == "pass")
    deceptive = [r["score"] for c, r in res if c.get("deceptive")]
    need = np_min_negatives(reg["alpha"])
    fr_rate = round(len(fr) / max(npos, 1), 2)
    if fa or fr_rate > reg["max_false_reject"]:
        verdict = "FAIL"
    elif len(deceptive) < need:
        verdict = "PROVISIONAL"
    else:
        verdict = "OK"
    thr = np_threshold(deceptive, reg["alpha"]) if len(deceptive) >= need else None
    pos = [r["score"] for c, r in res if c["label"] == "pass"]
    neg = [r["score"] for c, r in res if c["label"] == "fail"]
    return {"question": name, "verdict": verdict, "positives": npos, "negatives": len(cases) - npos, "deceptive": len(deceptive),
            "deceptive_needed": need, "false_accepts": fa, "false_rejects": fr, "false_reject_rate": fr_rate,
            "certified_threshold": None if thr is None else min(thr, reg["threshold"]),
            "separation": {"positives_min": round(min(pos), 2) if pos else None, "negatives_max": round(max(neg), 2) if neg else None},
            "calls": sum(r["samples"] for _, r in res)}


def main(argv: list) -> int:
    if any(a in ("-h", "--help") for a in argv[1:]):
        print(__doc__)
        return 0
    args, registry, out_json, run = [], DEFAULT_REGISTRY, None, False
    it = iter(argv[1:])
    for a in it:
        if a == "--registry":
            registry = Path(next(it, ""))
        elif a == "--json":
            out_json = next(it, None)
        elif a == "--run":
            run = True
        else:
            args.append(a)
    try:
        reg, cases_by_q = load(registry, args)
    except RegistryError as e:
        print(f"ERROR jev-calibrate: {e}", file=sys.stderr)
        return 2
    total = sum(len(c) for c in cases_by_q.values())
    print(f"PLAN {len(cases_by_q)} question(s), {total} case(s), at most {3 * total} calls, "
          f"at most {3 * total * COST_PER_CALL:.4f} USD; model {reg['model']}, threshold {reg['threshold']}")
    if not run:
        print("Nothing sent. Rerun with --run to ask Jev (paid calls; each case's state goes to OpenRouter).")
        return 0
    report = [calibrate(n, reg["questions"][n], cases, reg) for n, cases in cases_by_q.items()]
    for r in report:
        print(f"{r['verdict']:<11} {r['question']}: false accepts {len(r['false_accepts'])}, false-reject rate {r['false_reject_rate']}, "
              f"deceptive {r['deceptive']}/{r['deceptive_needed']}, certified threshold {r['certified_threshold']}, separation {r['separation']}")
        for cid in r["false_accepts"]:
            print(f"     FALSE ACCEPT {cid}")
        for cid in r["false_rejects"]:
            print(f"     false reject {cid}")
    if out_json:
        Path(out_json).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if any(r["verdict"] == "FAIL" for r in report) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
