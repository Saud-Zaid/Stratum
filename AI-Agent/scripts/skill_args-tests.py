# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for skill_args (2026-10-23, AD10 C13 stage 1): verifies the
retrieval consumer of the MCP-style skill args contracts. Runs against the real
skills directory (read-only tool; no mutation possible). Usage: skill_args-tests"""
import json
import subprocess
import sys
from pathlib import Path

import skill_args as S

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


def run(*argv):
    p = subprocess.run([sys.executable, str(Path(S.__file__).resolve()), *argv],
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


# T1: single-skill retrieval returns valid JSON with the three contract keys
rc, out, err = run("vault-writer")
a = json.loads(out) if rc == 0 else {}
ok("T1-json", rc == 0 and set(a) == {"input", "output", "consumer"}, out[:80])
ok("T1-nonempty", all(isinstance(a.get(k), str) and a[k].strip() for k in a), str(a)[:80])

# T2: the retrieved contract matches the frontmatter on disk verbatim
fm_args = S.load_args("vault-writer")
ok("T2-faithful", fm_args == a, "tool output != frontmatter args")

# T3: --all covers every skill directory (count from consumer-map.yaml — C19 stage B:
# live counters read from the single source of truth, not a hardcoded number; adding a
# skill must touch the map = mechanical proof of consumer awareness)
def map_count(key):
    import yaml
    p = Path(S.__file__).parent.parent / "schema" / "consumer-map.yaml"
    if not p.exists():
        raise SystemExit(f"consumer-map.yaml missing: {p}")
    txt = p.read_text(encoding="utf-8")
    if txt.lstrip().startswith("---"):
        txt = txt.split("---", 2)[2]      # skip frontmatter (C19 lesson: yaml loader sees 2 docs otherwise)
    return yaml.safe_load(txt)["counters"][key]

EXPECTED_SKILLS = map_count("skills")
dirs = [d.name for d in S.SKILLS.iterdir() if d.is_dir()]
rc, out, err = run("--all")
rows = [l.split("\t") for l in out.strip().splitlines()]
ok("T3-count", rc == 0 and len(rows) == len(dirs) == EXPECTED_SKILLS, f"rows={len(rows)} dirs={len(dirs)} map={EXPECTED_SKILLS}")
ok("T3-cols", all(len(r) == 4 for r in rows), "each row: name/input/output/consumer")
# every row: the full contract present (input/output/consumer non-empty) --
# strip the column prefix ("input=..." etc.) before emptiness check.
# C13 lessons from two tamper rounds: (1) first draft guarded one column only;
# (2) second draft compared raw strings where a bare prefix always passed.
ok("T3-all-contracts", all(r[0] != "" and r[0] != "<no args>" for r in rows)
   and all(r[c].split("=", 1)[-1] != "" for r in rows for c in (1, 2, 3)),
   "every skill row: 3 non-empty contract values after prefix strip")

# T4: unknown skill -> exit 1 + error JSON, no traceback
rc, out, err = run("no-such-skill")
ok("T4-unknown", rc == 1 and json.loads(out).get("error") and "Traceback" not in err,
   f"rc={rc} out={out[:60]}")

# T5: no argv -> usage on stderr + exit 2
rc, out, err = run()
ok("T5-usage", rc == 2 and "usage" in err, f"rc={rc} err={err[:60]}")

# T6: load_args on a skill without args returns None (future-proofing)
ok("T6-noargs-none", S.load_args("__nonexistent__") is None, "None for missing skill")

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"SKILLARGS-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
