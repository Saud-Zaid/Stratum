# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""run_tests.py — run the test files listed in AI-Agent/config/test-classification.yaml.

Usage: python AI-Agent/scripts/run_tests.py [--set core|all] [--lane parallel|serial|all] [--jobs N] [--timeout S]
                                            [--only SUBSTRING] [--list]

The default set is `stratum_core`: the tests that ship with a release. A `parallel` lane runs concurrently, a `serial`
lane runs one file at a time afterwards (tests that touch shared state). A `probe_cli` entry is a probe tool, not a test:
it is listed and skipped. Each test runs in its own process with the interpreter that runs this script, from the vault
root, with the environment as it is (VAULT, TIKTOKEN_CACHE_DIR, ...). Exit code 0 only when every selected test passes; a test that exits 77 reports SKIP (its inputs are not in this tree).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import yaml  # noqa: E402

from _vaultlib import VAULT, force_utf8_stdio, standard_parser  # noqa: E402

CLASSIFICATION = "AI-Agent/config/test-classification.yaml"
SETS = {"core": ("stratum_core",), "all": ("stratum_core", "mother_vault_drop")}
RUNNABLE = {"direct", "pytest_or_direct"}


def load_plan(root: Path, which: str = "core", lane: str = "all", only: str = "") -> list[dict]:
    """Entries of the chosen set(s) in file order; each is {path, runner, lane, set}."""
    data = yaml.safe_load((root / CLASSIFICATION).read_text(encoding="utf-8"))
    plan = []
    for key in SETS[which]:
        for e in data.get(key) or []:
            if lane != "all" and e.get("lane", "serial") != lane:
                continue
            if only and only not in e["path"]:
                continue
            plan.append({"path": e["path"], "runner": e.get("runner", "direct"), "lane": e.get("lane", "serial"), "set": key})
    return plan


def _tail(out: str) -> str:
    """The last 15 lines, preceded by any earlier lines that name a failure (a long suite prints its FAIL line long before its summary)."""
    lines = out.splitlines()
    early = [ln for ln in lines[:-15] if "FAIL" in ln or "Error" in ln][:20]
    return "\n".join(early + lines[-15:])


def run_one(root: Path, entry: dict, timeout: float, python: str | None = None) -> dict:
    """PASS / FAIL / TIMEOUT / MISSING / SKIP for one entry. The mother-only set may be absent from a release tree."""
    path = root / entry["path"]
    res = {"path": entry["path"], "lane": entry["lane"], "seconds": 0.0, "tail": ""}
    env = dict(os.environ, VAULT=str(root))
    env.setdefault("STRATUM_NET_LOG", str(Path(tempfile.gettempdir()) / "stratum-tests-net-preflight.log"))   # a test run must not write into the tree under test
    if entry["runner"] not in RUNNABLE:
        return {**res, "status": "SKIP", "tail": f"runner {entry['runner']} is a probe, not a test"}
    if not path.is_file():
        return {**res, "status": "SKIP" if entry["set"] != "stratum_core" else "MISSING", "tail": "file not found"}
    t0 = time.perf_counter()
    try:
        p = subprocess.run([python or sys.executable, str(path)], cwd=root, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env)
        status, out = ("PASS" if p.returncode == 0 else "SKIP" if p.returncode == 77 else "FAIL"), (p.stdout + p.stderr)   # 77: the test says its inputs are not here
    except subprocess.TimeoutExpired as e:
        status, out = "TIMEOUT", ((e.stdout or b"").decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or ""))
    res.update(status=status, seconds=round(time.perf_counter() - t0, 1), tail=_tail(out))
    return res


def run_plan(root: Path, plan: list[dict], jobs: int = 4, timeout: float = 280.0, python: str | None = None) -> list[dict]:
    """The parallel lane concurrently, then the serial lane one by one; results come back in plan order."""
    results: dict[str, dict] = {}
    par = [e for e in plan if e["lane"] == "parallel"]
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for r in ex.map(lambda e: run_one(root, e, timeout, python), par):
            results[r["path"]] = r
    for e in plan:
        if e["lane"] != "parallel":
            results[e["path"]] = run_one(root, e, timeout, python)
    return [results[e["path"]] for e in plan]


def summarize(results: list[dict]) -> tuple[int, int, int]:
    """(passed, selected, skipped): SKIP is not selected, so a probe never counts for or against."""
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    return sum(1 for r in results if r["status"] == "PASS"), len(results) - skipped, skipped


def main(argv=None) -> int:
    force_utf8_stdio()
    ap = standard_parser(__doc__, "run_tests")
    ap.add_argument("--set", choices=sorted(SETS), default="core", dest="which")
    ap.add_argument("--lane", choices=["parallel", "serial", "all"], default="all")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=280.0)
    ap.add_argument("--only", default="")
    ap.add_argument("--list", action="store_true", help="print the plan and exit")
    args = ap.parse_args(argv)
    root = Path(os.environ.get("VAULT") or VAULT)
    plan = load_plan(root, args.which, args.lane, args.only)
    if args.list:
        for e in plan:
            print(f"{e['lane']:8} {e['runner']:17} {e['path']}")
        print(f"RUN-TESTS plan {len(plan)}")
        return 0
    results = run_plan(root, plan, args.jobs, args.timeout)
    for r in results:
        print(f"{r['status']:7} {r['path']} ({r['seconds']}s)")
    for r in results:
        if r["status"] in ("FAIL", "TIMEOUT", "MISSING"):
            print(f"--- {r['status']} {r['path']}\n{r['tail']}")
    passed, selected, skipped = summarize(results)
    print(f"RUN-TESTS {passed}/{selected} passed ({skipped} skipped)")
    return 0 if passed == selected else 1


if __name__ == "__main__":
    sys.exit(main())
