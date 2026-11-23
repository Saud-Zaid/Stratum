#!/usr/bin/env python3
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Tests of jev_calibrate.py with a deterministic stand-in for Jev: no network, no key, no mcp.
Run: AI-Agent/vault-python AI-Agent/scripts/jev_calibrate-tests.py"""
import io
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import jev_calibrate as C  # noqa: E402
import yaml  # noqa: E402

results = []


def ok(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f" :: {detail}"))


REG = {"version": 1, "model": C.pinned_model(), "threshold": 0.95, "borderline": [0.90, 0.95], "max_false_reject": 0.15, "alpha": 0.10}
Q = {"tool": "jev_check", "instructions": "Is it true?", "criteria": {"true": "yes", "false": "no"}}


def fake(scores):
    """A stand-in for ask_jev: the state is a case id; scores maps it to a list of answers returned in order."""
    calls = {}

    def ask(tool, args):
        cid = args["state"]
        n = calls.get(cid, 0)
        calls[cid] = n + 1
        v = scores[cid][min(n, len(scores[cid]) - 1)]
        if v == "error":
            return {"error": "boom"}
        if v == "refusal":
            return {"answers": {"q": {"type": "refusal"}}}
        return {"answers": {"q": {"type": "noul", "noul": v}}}
    ask.calls = calls
    return ask


def cases(spec):
    return [{"id": i, "label": lab, "deceptive": dec, "state": i} for i, lab, dec in spec]


# the threshold and the minimum number of deceptive cases (Tong, Feng and Li 2018)
ok("K01-29-deceptive-cases-are-needed-for-alpha-0.10", C.np_min_negatives(0.10) == 29, C.np_min_negatives(0.10))
ok("K02-59-deceptive-cases-are-needed-for-alpha-0.05", C.np_min_negatives(0.05) == 59, C.np_min_negatives(0.05))
ok("K03-with-29-scores-the-threshold-is-the-largest", C.np_threshold([i / 100 for i in range(29)], 0.10) == 0.28)
ok("K04-below-the-minimum-there-is-no-threshold", C.np_threshold([0.1] * 28, 0.10) is None)

# verdicts
cs = cases([("p1", "pass", False), ("p2", "pass", False), ("f1", "fail", True)])
r = C.calibrate("q", Q, cs, REG, fake({"p1": [0.99], "p2": [0.98], "f1": [0.97]}))
ok("K05-a-deceptive-case-that-passes-is-a-false-accept-and-FAIL", r["verdict"] == "FAIL" and r["false_accepts"] == ["f1"], r)
r = C.calibrate("q", Q, cs, REG, fake({"p1": [0.99], "p2": [0.10], "f1": [0.05]}))
ok("K06-a-false-reject-rate-above-the-limit-is-FAIL", r["verdict"] == "FAIL" and r["false_rejects"] == ["p2"] and r["false_reject_rate"] == 0.5, r)
r = C.calibrate("q", Q, cs, REG, fake({"p1": [0.99], "p2": [0.98], "f1": [0.05]}))
ok("K07-clean-but-too-few-deceptive-cases-is-PROVISIONAL", r["verdict"] == "PROVISIONAL" and r["deceptive"] == 1 and r["certified_threshold"] is None, r)
big = cases([(f"p{i}", "pass", False) for i in range(10)] + [(f"d{i}", "fail", True) for i in range(29)])
sc = {**{f"p{i}": [0.99] for i in range(10)}, **{f"d{i}": [i / 100] for i in range(29)}}
r = C.calibrate("q", Q, big, REG, fake(sc))
ok("K08-clean-with-29-deceptive-cases-is-OK-with-a-certified-threshold", r["verdict"] == "OK" and r["certified_threshold"] == 0.28, r)

# sampling and failures of Jev
ask = fake({"b": [0.92, 0.97, 0.96]})
s = C.score_case(Q, "b", REG, ask)
ok("K09-a-borderline-first-answer-is-asked-3-times-and-the-median-used", s["samples"] == 3 and s["p"] == 0.96 and s["pass"], s)
ask = fake({"c": [0.99]})
s = C.score_case(Q, "c", REG, ask)
ok("K10-a-clear-first-answer-is-asked-once", s["samples"] == 1 and ask.calls["c"] == 1, s)
ok("K11-an-error-is-never-a-pass", not C.score_case(Q, "e", REG, fake({"e": ["error"]}))["pass"])
ok("K12-a-refusal-is-never-a-pass", not C.score_case(Q, "r", REG, fake({"r": ["refusal"]}))["pass"])

# the files
with tempfile.TemporaryDirectory() as d:
    d = Path(d)
    gold = d / "g.yaml"
    gold.write_text(yaml.safe_dump({"cases": cases([("p1", "pass", False), ("f1", "fail", True)])}), encoding="utf-8")

    def write(reg):
        p = d / "r.yaml"
        p.write_text(yaml.safe_dump(reg), encoding="utf-8")
        return p

    good = {**REG, "questions": {"q": {**Q, "golden": str(gold)}}}
    reg, by_q = C.load(write(good), [])
    ok("K13-a-valid-registry-loads", list(by_q) == ["q"] and len(by_q["q"]) == 2)

    def refused(reg, needle):
        try:
            C.load(write(reg), [])
        except C.RegistryError as e:
            return needle in str(e)
        return False
    ok("K14-a-model-other-than-the-server-pin-is-refused", refused({**good, "model": "typesafe/other"}, "differs from the server"))
    ok("K15-a-question-over-40-words-is-refused", refused({**good, "questions": {"q": {**Q, "golden": str(gold), "instructions": "word " * 41}}}, "at most 40 words"))
    ok("K16-a-missing-case-file-is-refused", refused({**good, "questions": {"q": {**Q, "golden": str(d / "none.yaml")}}}, "case file missing"))
    gold2 = d / "g2.yaml"
    gold2.write_text(yaml.safe_dump({"cases": [{"id": "x", "label": "pass", "deceptive": True, "state": "s"}, {"id": "y", "label": "fail", "state": "s"}]}), encoding="utf-8")
    ok("K17-a-deceptive-case-labelled-pass-is-refused", refused({**good, "questions": {"q": {**Q, "golden": str(gold2)}}}, "deceptive"))

    out = io.StringIO()
    with redirect_stdout(out):
        code = C.main(["jev_calibrate.py", "--registry", str(write(good))])
    ok("K18-without-run-it-prints-the-plan-and-sends-nothing", code == 0 and "PLAN 1 question(s), 2 case(s), at most 6 calls" in out.getvalue() and "Nothing sent" in out.getvalue(), out.getvalue())

    # the template the release ships: in a release tree it is at AI-Agent/config, in the source vault under the overlay
    for base in (C.ROOT, C.ROOT / "AI-Agent" / "release-overlay"):
        tpl = base / "AI-Agent" / "config" / "jev-questions.yaml"
        if tpl.is_file():
            t = yaml.safe_load(tpl.read_text(encoding="utf-8"))
            for q in t["questions"].values():
                q["golden"] = str(base / q["golden"])
            reg, by_q = C.load(write(t), [])
            ok("K19-the-shipped-template-and-its-example-cases-are-valid", by_q and all(len(v) >= 2 for v in by_q.values()), by_q)
            break
    else:
        ok("K19-the-shipped-template-and-its-example-cases-are-valid", False, "no template found")

print(f"JEV-CALIBRATE-TESTS {sum(results)}/{len(results)}")
sys.exit(0 if all(results) else 1)
