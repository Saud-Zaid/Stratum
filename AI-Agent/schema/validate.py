# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""schema/validate.py — contract checker (M4', AD06 B1, conditions 18-20 CF3).
Standalone CLI with its own rc per check (condition 20): not wired to the hook before batch B3.
Usage: AI-Agent/vault-python AI-Agent/schema/validate.py --target all|baseline|contracts|fmea|switch
rc: 0 ok, 1 warn, 2 error. Exit = the highest rc."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parents[2]
BASELINE = VAULT / "AI-Agent" / "g06_baseline.json"
CONTRACTS = VAULT / "AI-Agent" / "contracts"
FMEA = VAULT / "AI-Agent" / "handoff" / "fmea-arch-f2.md"
SWITCH = VAULT / "AI-Agent" / "state" / "kill-switch-state.json"
FMEA_IDS = ("FM-G06-1", "FM-G13-1")   # N1
EXPECTED_CONTRACTS = ("decision-log-v1.0.0.json", "skill-record-v1.0.0.json")
SWITCH_OK = {"RUN"}


def sha256_canonical(obj: dict) -> str:
    """sha256 of the canonical JSON without the content_hash field itself — one pattern for every source."""
    body = {k: v for k, v in obj.items() if k != "content_hash"}
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def check_baseline(path: Path = BASELINE) -> tuple[int, str]:
    if not path.exists():
        return 2, "baseline: baseline file missing (G06) — no numbers without a signature"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return 2, f"baseline: file unreadable ({exc})"
    if "version" not in data:
        return 2, "baseline: no version — a change without a version goes undetected (condition 18)"
    if "content_hash" not in data:
        return 2, "baseline: no content_hash — signature missing (condition 18)"
    want = sha256_canonical(data)
    if data["content_hash"] != want:
        return 2, f"baseline: hash mismatch — the signature does not match the content (condition 18)"
    return 0, f"baseline: signed and intact version={data['version']}"


def check_contracts(dirpath: Path = CONTRACTS) -> tuple[int, str]:
    if not dirpath.exists():
        return 0, "contracts: not built yet — gate N3 (after the first SQLite batch) stands as planned"
    rc, msgs = 0, []
    for name in EXPECTED_CONTRACTS:
        f = dirpath / name
        if not f.exists():
            rc = max(rc, 2)
            msgs.append(f"contracts: {name} missing although the directory exists")
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            rc = max(rc, 2)
            msgs.append(f"contracts: {name} unreadable")
            continue
        for key in ("id", "version", "content_hash"):
            if key not in data:
                rc = max(rc, 2)
                msgs.append(f"contracts: {name} lacks {key}")
        if "content_hash" in data and data["content_hash"] != sha256_canonical(data):
            rc = max(rc, 2)
            msgs.append(f"contracts: {name} hash mismatch")
    return rc, "; ".join(msgs) if msgs else f"contracts: both files present and signed ({len(EXPECTED_CONTRACTS)}/{len(EXPECTED_CONTRACTS)})"


def check_fmea(path: Path = FMEA) -> tuple[int, str]:
    if not path.exists():
        if release_mode():
            return 0, "fmea: a design record of the mother vault, not part of a release"
        return 2, "fmea: FMEA file missing — building the mediator is blocked (N1)"
    text = path.read_text(encoding="utf-8")
    missing = [mid for mid in FMEA_IDS if mid not in text]
    if missing:
        return 2, f"fmea: lacks failure modes {', '.join(missing)} — N1 not met"
    return 0, f"fmea: the reduced part with the mediator's two modes is present ({len(FMEA_IDS)}/{len(FMEA_IDS)})"


def check_switch(path: Path = SWITCH) -> tuple[int, str]:
    if not path.exists():
        return 0, "switch: state/ not built yet (batch B5) — its absence is declared, not a fault"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 2, "switch: state file unreadable"
    status = data.get("status")
    if status not in ("RUN", "HALT"):
        return 2, f"switch: unknown status ({status!r}) — outside {sorted(SWITCH_OK)} or HALT"
    if status == "HALT":
        return 2, "switch: HALT — every build is stopped by a declared order"
    return 0, "switch: RUN — building is allowed"


def release_mode() -> bool:
    """True when the profile says `mode: release` (a missing or unreadable profile means the mother vault)."""
    try:
        import yaml
        prof = yaml.safe_load((VAULT / "AI-Agent" / "config" / "release_profile.yaml").read_text(encoding="utf-8")) or {}
        return prof.get("mode") == "release"
    except Exception:   # noqa: BLE001
        return False


def t1_disabled() -> bool:
    """True when the release profile switches the T1 recall check off (its Arabic fixture is not part of a release)."""
    try:
        import yaml
        prof = yaml.safe_load((VAULT / "AI-Agent" / "config" / "release_profile.yaml").read_text(encoding="utf-8")) or {}
        patch = VAULT / "AI-Agent" / "config" / "release_profile.patch.yaml"
        disabled = list((prof.get("checks") or {}).get("disabled") or [])
        if prof.get("mode") == "release" and patch.is_file():
            disabled = list((((yaml.safe_load(patch.read_text(encoding="utf-8")) or {}).get("merge") or {}).get("checks") or {}).get("disabled") or disabled)
        return "t1" in disabled
    except Exception:   # noqa: BLE001 - an unreadable profile means the check stays on
        return False


def check_norm() -> tuple[int, str]:
    """norm check: the normalisation unit exists + the T1 fixture recalls 5/5 (conditions 4-5)."""
    if t1_disabled():
        return 0, "norm: the T1 recall check is disabled by the release profile"
    unit = VAULT / "AI-Agent" / "schema" / "norm_v1.py"
    fixture = VAULT / "AI-Agent" / "tests" / "fixtures" / "t1_fixture.py"
    if not unit.exists():
        return 2, "norm: norm_v1.py missing — the normalisation gate is not built (condition 4)"
    if not fixture.exists():
        return 2, "norm: T1 fixture missing — recall has no frozen threshold (condition 5)"
    sys.path.insert(0, str(unit.parent))
    sys.path.insert(0, str(fixture.parent))
    try:
        import norm_v1  # noqa: F401
        import t1_fixture as fx
    except ImportError as exc:
        return 2, f"norm: importing the normaliser/fixture failed ({exc})"
    try:
        res = fx.run_recall()
    except Exception as exc:
        return 2, f"norm: the fixture run crashed ({exc.__class__.__name__}: {exc})"
    if res["recall"] < res["min_recall"]:
        return 2, f"norm: recall regressed to {res['recall']}/{len(fx.QUERIES)} below the threshold {res['min_recall']} — commit blocked (condition 5)"
    return 0, f"norm: recall {res['recall']}/{len(fx.QUERIES)} on the five forms, fixture v{res['fixture_version']} hash={res['data_hash']}"


def check_ledger() -> tuple[int, str]:
    """ledger check: SQLite ledger + session injection log (conditions 7 and 11 CF2)."""
    ledger = VAULT / "AI-Agent" / "state" / "decision-ledger.sqlite3"
    log = VAULT / "AI-Agent" / "state" / "injection-log.jsonl"
    if not ledger.exists():
        return 2, "ledger: ledger database missing — no decision batch recorded (condition 11, N3)"
    if not log.exists():
        return 2, "ledger: session injection log missing — no link to g06 in pre-commit (condition 7)"
    sys.path.insert(0, str(VAULT / "AI-Agent" / "schema"))
    try:
        import decision_ledger as dl
        if not dl.self_check():
            return 2, "ledger: self_check failed — the static_childhood opening entry or the ledger signature is broken"
        es = dl.entries()
        sct = es[0]["tokens_billed"]
        b = json.loads(BASELINE.read_text(encoding="utf-8"))
        want = b.get("metrics", {}).get("static_childhood_tokens")
        if want is None:
            return 2, "ledger: static_childhood_tokens not declared in g06_baseline.json (condition 11)"
        if sct != want:
            return 2, f"ledger: ledger opening entry {sct} does not match baseline {want} (condition 11)"
        first = dl.read_injection_log()[0]
        if first.get("tokens") != want:
            return 2, f"ledger: injection-log opening entry {first.get('tokens')} does not match baseline {want} (condition 11)"
        cov = [l.get("coverage_pct") for l in dl.read_injection_log() if "coverage_pct" in l]
        if not cov:
            return 2, "ledger: coverage ratio not shown in the injection log (B3 acceptance)"
        n = dl.count_decisions()
    except Exception as exc:
        return 2, f"ledger: the ledger check crashed ({exc.__class__.__name__}: {exc})"
    return 0, (f"ledger: static_childhood opening entry={sct} tokens matches the baseline, {n} decisions recorded, "
               f"coverage {cov[0]}% in the injection log")



def _goose_config() -> Path:
    """Goose keeps its config in %APPDATA%\\Block\\goose\\config on Windows and ~/.config/goose elsewhere; the first existing one wins."""
    cands = []
    if os.environ.get("APPDATA"):
        cands.append(Path(os.environ["APPDATA"]) / "Block" / "goose" / "config" / "config.yaml")
    cands.append(Path.home() / ".config" / "goose" / "config.yaml")
    return next((c for c in cands if c.exists()), cands[-1])


GOOSE_CONFIG = _goose_config()


def check_iso() -> tuple[int, str]:
    """iso check: periodic isolation at the container boundary (STRIDE class E residue in AD06-C1-10).
    rc 0 fresh (<=7 days); rc 1 stale 7-14 days or report missing; rc 2 recorded escape, broken chain or stale >14."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from isolation import check_isolation
    return check_isolation()


def check_sidedoor(path: Path | None = None) -> tuple[int, str]:
    """sidedoor check: the github side door and its secrets in the external agent config (d2, condition B5).
    rc 2: a plain-text token or an enabled github extension; rc 1: config missing (cannot be checked)."""
    p = path or GOOSE_CONFIG
    if not p.exists():
        return 1, f"sidedoor: agent config not found at {p} — the check is not possible in this environment"
    text = p.read_text(encoding="utf-8", errors="replace")
    import re
    tokens = re.findall(r"(ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,})", text)
    if tokens:
        return 2, f"sidedoor: plain-text token visible in the agent config ({len(tokens)} matches) — d2 broken"
    m = re.search(r"github:\s*\n\s*enabled:\s*(\w+)", text)
    if m and m.group(1).lower() == "true":
        return 2, "sidedoor: github extension enabled without a mediator — d2 broken (disabling is declared in B5)"
    return 0, "sidedoor: github side door closed, no plain-text token — d2 met"

def check_pl() -> tuple[int, str]:
    """pl check: the permanent layer exists and is under the measured cap (condition 7)."""
    path = VAULT / "AI-Agent" / "permanent-layer.md"
    if not path.exists():
        return 2, "pl: permanent-layer.md missing — the permanent layer is not built (condition 7)"
    try:
        data = json.loads(BASELINE.read_text(encoding="utf-8"))
        cap = data.get("metrics", {}).get("permanent_layer", {}).get("cap_tokens")
    except (OSError, ValueError):
        return 2, "pl: baseline unreadable"
    if not isinstance(cap, int):
        return 2, "pl: cap not declared in the baseline (condition 7)"
    try:
        import tiktoken
        got = len(tiktoken.get_encoding("o200k_base").encode(path.read_text(encoding="utf-8")))
    except Exception:
        return 1, "pl: tiktoken unavailable — the count is not measured in this environment"
    if got > cap:
        return 2, f"pl: {got} tokens exceed the cap {cap} — commit blocked (condition 7)"
    return 0, f"pl: {got} tokens <= cap {cap} (tiktoken o200k_base, condition 7)"


CHECKS = {"baseline": check_baseline, "contracts": check_contracts, "fmea": check_fmea, "switch": check_switch, "norm": check_norm, "ledger": check_ledger, "pl": check_pl, "iso": check_iso, "sidedoor": check_sidedoor}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="all", choices=["all", *CHECKS.keys()])
    args = ap.parse_args()
    picked = CHECKS if args.target == "all" else {args.target: CHECKS[args.target]}
    worst = 0
    for name, fn in picked.items():
        rc, msg = fn()
        worst = max(worst, rc)
        print(f"rc={rc}  {name:<10} {msg}")
    print(f"validate: worst rc={worst}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
