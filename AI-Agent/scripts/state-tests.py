# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for state (2026-10-23, AD10 C15 stage 3): validates the state.py
helpers on controlled data -- date parsing (ISO + Arabic), latest() sorting,
deferral line regexes, section extraction, and club selftest integration.
Usage: state-tests"""

def _U(s):
    """ASCII-escaped test data: the shipped sources hold no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")

import sys
import datetime

import state as S

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


RELEASE = S.PROFILE.get("mode") == "release"   # a release has English headings and no architecture or club sections
HAS_AR = bool(S.locale_value("NORMALIZE", {}))


def aok(name, cond, got=""):
    """ok(), run only where the Arabic locale tables exist."""
    if HAS_AR:
        ok(name, cond, got)
    else:
        print(f"SKIP {name}: no Arabic locale in this tree")


# --- line_date ---
# T1: ISO date parses
ok("T1-iso", S.line_date("updated 2026-09-28 done") == datetime.date(2026, 9, 28), str(S.line_date("updated 2026-09-28 done")))

# T2: Arabic date (day month year) parses
aok("T2-arabic", S.line_date(_U(r"28 \u0633\u0628\u062a\u0645\u0628\u0631 2026")) == datetime.date(2026, 9, 28), str(S.line_date(_U(r"28 \u0633\u0628\u062a\u0645\u0628\u0631 2026"))))

# T3: Arabic-Indic digits are translated
aok("T3-arabic-digits", S.line_date(_U(r"\u0662\u0660\u0662\u0666-\u0660\u0669-\u0662\u0668")) == datetime.date(2026, 9, 28), str(S.line_date(_U(r"\u0662\u0660\u0662\u0666-\u0660\u0669-\u0662\u0668"))))

# T4: no date -> None
ok("T4-none", S.line_date("no date here") is None, str(S.line_date("no date here")))

# T5: unknown month name -> None
ok("T5-unknown-month", S.line_date("28 NotAMonth 2026") is None, str(S.line_date("28 NotAMonth 2026")))

# --- latest ---
# T6: newest progress lines sorted ascending by date (newest is last, n=2)
lines = ["- 2026-09-01 first", "- 2026-10-15 newest", "- 2026-09-20 middle"]
ok("T6-latest", S.latest(lines) == ["- 2026-09-20 middle", "- 2026-10-15 newest"], str(S.latest(lines)))

# T7: n=1 returns only the newest
ok("T7-latest-n1", S.latest(lines, n=1) == ["- 2026-10-15 newest"], str(S.latest(lines, 1)))

# T8: undated lines get the date of the nearest preceding ### heading (newest is last)
lines2 = ["### 2026-09-25 dated heading", "- undated line under it", "- 2026-10-01 explicitly dated"]
ok("T8-heading-date", S.latest(lines2)[-1] == "- 2026-10-01 explicitly dated" and S.latest(lines2)[0] == "- undated line under it", str(S.latest(lines2)))

# T9: input order does not matter (sorted internally)
lines3 = ["- 2026-10-15 newest", "- 2026-09-01 first", "- 2026-09-20 middle"]
ok("T9-order-independent", S.latest(lines3) == S.latest(lines), str(S.latest(lines3)))

# --- deferral line regexes ---
# T10: DEF_LINE captures the id from a deferral line
m = S.DEF_LINE.match("- [ ] Review architecture plan [id:: D-101]")
ok("T10-defline", m is not None and m.group(1) == "D-101", str(m.groups()) if m else "no match")

# T11: DEF_LINE does not match a checked-off line
m = S.DEF_LINE.match("- [x] Review architecture plan [id:: D-101]")
ok("T11-defline-checked", m is None, str(m))

# T12: TAG_COUNT captures tag name and threshold
m = S.TAG_COUNT.search('[state:: "opens count >= 2"]')
ok("T12-tagcount", m is not None and m.group(1) == "opens" and m.group(2) == "2", str(m.groups()) if m else "no match")

# --- section_lines ---
TEXT = _U(r"## \u0627\u0644\u062e\u0637\u0648\u0627\u062a \u0627\u0644\u0642\u0627\u062f\u0645\u0629\n- [ ] task A\n- [ ] task B\n\n## \u0633\u062c\u0644 \u0627\u0644\u062a\u0642\u062f\u0645\n- 2026-10-01 did X\n")
# T13: extracts lines under a matching heading
got = S.section_lines(TEXT, (_U(r"\u0627\u0644\u062e\u0637\u0648\u0627\u062a \u0627\u0644\u0642\u0627\u062f\u0645\u0629"),))
ok("T13-section-lines", len(got) == 2 and all(l.strip().startswith("- [ ]") for l in got), str(got))

# T14: no match -> empty
ok("T14-no-section", S.section_lines(TEXT, ("nonexistent",)) == [], str(S.section_lines(TEXT, ("nonexistent",))))

# --- club_selftest integration ---
# T15: club_selftest runs and reports all PASS (0 failures)
_CS = S.club_module()
if _CS is None:
    print("SKIP T15-club-selftest: the club section is not part of this tree")
else:
    result = _CS.club_selftest()
    ok("T15-club-selftest", result == 0, f"exit={result}")


# --- delta-only tests (AD13 M01) ---
import time
t0 = time.time()
delta_out = S.delta_state()
elapsed = time.time() - t0

# T16: delta_state returns non-empty string
ok("T16-delta-output", isinstance(delta_out, str) and len(delta_out) > 0, delta_out[:50])

# T17: contains required stateless sections
has_sections = all(k in delta_out for k in ("dirty:", "commits:", "active:", "integrity:"))
ok("T17-delta-sections", has_sections, delta_out)

# T18: integrity is masked to single line format
integ_lines = [l for l in delta_out.splitlines() if l.startswith("integrity:")]
ok("T18-integrity-masked", len(integ_lines) == 1 and "run archops check for details" in integ_lines[0], str(integ_lines))

# T19: output size is strictly < 50 tokens (using len//4 and word count)
tok_est = max(1, len(delta_out) // 4)
ok("T19-token-count", tok_est < 50, f"tokens={tok_est}, chars={len(delta_out)}")

# T20: --delta-only stays quick. The ceiling is generous on purpose: it guards against a scan of the whole vault (seconds), not
# against a cold disk or a long Git history, which made a 0.15s limit fail on a fresh clone.
ok("T20-exec-time", elapsed < 1.5, f"{elapsed:.4f}s")

# T21: main(["--delta-only"]) exits cleanly with 0
ret = S.main(["--delta-only"])
ok("T21-main-delta", ret == 0, f"exit={ret}")

# --- T-02c: upgrade alerts (read-only), profile-driven headings, check_on, hubs without arch_contract ---
import json
import shutil
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="state-t02c-"))
try:
    ok("T22-alerts-absent-file-is-silent", S.upgrade_alerts(_tmp) == [])
    (_tmp / ".vault-release").mkdir()
    _pr = _tmp / S.PENDING_REVIEW
    _pr.write_text(json.dumps({"pending": [{"id": "conflict-skew", "severity": "high", "summary": "base moved"},
                                           {"id": "cli-1", "summary": "flag renamed"}]}), encoding="utf-8")
    _rows = S.upgrade_alerts(_tmp)
    ok("T23-alerts-rows", _rows == ["HIGH\tconflict-skew\tbase moved", "WARN\tcli-1\tflag renamed"], _rows)
    _before = _pr.read_bytes()
    S.upgrade_alerts(_tmp)
    ok("T24-alerts-read-only", _pr.read_bytes() == _before)
    _pr.write_text("{not json", encoding="utf-8")
    ok("T25-alerts-malformed-no-crash", S.upgrade_alerts(_tmp)[0].startswith("WARN\tpending-review unreadable"), S.upgrade_alerts(_tmp))
    _pr.write_text('["a"]', encoding="utf-8")
    ok("T26-alerts-wrong-shape-no-crash", S.upgrade_alerts(_tmp)[0].startswith("WARN\t"), S.upgrade_alerts(_tmp))
finally:
    shutil.rmtree(_tmp, ignore_errors=True)

if RELEASE:
    ok("T27-default-headings-unchanged", S.NEXT == ("Next Steps",) and S.LOG == ("Progress Log", "Changelog"), (S.NEXT, S.LOG))
else:
    ok("T27-default-headings-unchanged", S.NEXT == (_U(r"\u0627\u0644\u062e\u0637\u0648\u0627\u062a \u0627\u0644\u0642\u0627\u062f\u0645\u0629"),) and S.LOG == (_U(r"\u0633\u062c\u0644 \u0627\u0644\u062a\u0642\u062f\u0645"), _U(r"\u0633\u062c\u0644 \u0627\u0644\u062a\u063a\u064a\u064a\u0631\u0627\u062a")), (S.NEXT, S.LOG))
ok("T28-check_on-default-true", (not S.check_on("arch") and not S.check_on("club")) if RELEASE else (S.check_on("arch") and S.check_on("club")))
_saved = S.PROFILE
try:
    S.PROFILE = {**_saved, "checks": {"disabled": ["arch"]}}
    ok("T29-check_on-disabled", not S.check_on("arch") and S.check_on("club"))
    # hubs() with arch disabled and no system_homes must not import arch_contract
    import sys as _s
    _s.modules.pop("arch_contract", None)
    S.hubs()
    ok("T30-hubs-arch-off-no-import", "arch_contract" not in _s.modules)
    import contextlib
    import io
    S.PROFILE = {**_saved, "checks": {"disabled": ["arch", "club"]}}
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        S.run_default(1)
    _o = _buf.getvalue()
    ok("T32-run-default-skips-disabled-sections", "## architecture" not in _o and "## club" not in _o and "## active work" in _o)
    S.PROFILE = {**_saved}
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        S.run_default(1)
    ok("T33-run-default-keeps-sections-when-enabled", RELEASE or ("## architecture" in _buf.getvalue() and "## club" in _buf.getvalue()))
    S.PROFILE = {**_saved, "paths": {**_saved["paths"], "system_homes": ["02-Areas"]}}
    _s.modules.pop("arch_contract", None)
    ok("T31-hubs-profile-homes-no-import", bool(S.hubs()) and "arch_contract" not in _s.modules)
finally:
    S.PROFILE = _saved

# T34-T38 (T-02d, U-49): .venv lock stamp
import hashlib as _hl
_v = Path(tempfile.mkdtemp(prefix="state-venv-"))
try:
    ok("T34-venv-alert-silent-without-venv", S.venv_lock_alert(_v) == [])
    (_v / "uv.lock").write_text("lock-v1", encoding="utf-8")
    ok("T35-venv-alert-silent-without-stamp", S.venv_lock_alert(_v) == [])
    (_v / ".venv").mkdir()
    (_v / S.VENV_STAMP).write_text(_hl.sha256(b"lock-v1").hexdigest() + "\n", encoding="utf-8")
    ok("T36-venv-alert-silent-when-current", S.venv_lock_alert(_v) == [])
    (_v / "uv.lock").write_text("lock-v2", encoding="utf-8")
    _a = S.venv_lock_alert(_v)
    ok("T37-venv-alert-warns-when-stale", len(_a) == 1 and _a[0].startswith("WARN\tvenv-stale"), _a)
    (_v / S.VENV_STAMP).write_text(_hl.sha256(b"lock-v2").hexdigest(), encoding="utf-8")
    ok("T38-venv-alert-clears-after-refresh", S.venv_lock_alert(_v) == [])
finally:
    shutil.rmtree(_v, ignore_errors=True)

# T-05: the net-preflight line goes to $STRATUM_NET_LOG when it is set, and the default log is left alone
import os as _os
import tempfile as _tf
_nl = Path(_tf.mkdtemp()) / "net.log"
_os.environ["STRATUM_NET_LOG"] = str(_nl)
try:
    S._probe = lambda host, port, af: False   # no network is touched
    S._net_preflight()
    ok("T-05-net-log-override-is-written", _nl.is_file() and _nl.read_text(encoding="utf-8").count("\n") == 1, _nl.exists())
finally:
    _os.environ.pop("STRATUM_NET_LOG", None)

# STRATUM_SKIP_NET=1: no probe is made, the line stays visible as `skipped`, and IPv6 is not probed once IPv4 answers
_nl2 = Path(_tf.mkdtemp()) / "net2.log"
_os.environ["STRATUM_NET_LOG"] = str(_nl2)
_calls = []
try:
    _os.environ["STRATUM_SKIP_NET"] = "1"
    S._probe = lambda host, port, af: _calls.append(af) or True
    ok("T-06-skip-net-makes-no-probe-and-reports-skipped", S._net_preflight() == "skipped" and not _calls, _calls)
    ok("T-06b-skip-net-still-writes-the-log-line", "skipped" in _nl2.read_text(encoding="utf-8"))
    _os.environ.pop("STRATUM_SKIP_NET")
    _calls.clear()
    import socket as _sk
    ok("T-06c-ipv4-up-skips-the-ipv6-probe", S._net_preflight() == "up" and set(_calls) == {_sk.AF_INET}, _calls)
finally:
    _os.environ.pop("STRATUM_NET_LOG", None)
    _os.environ.pop("STRATUM_SKIP_NET", None)

# Step 5: digits of any script normalise to ASCII with no locale data, and dates written with them parse
ok("T-07-normalize-digits-handles-arabic-indic-extended-and-devanagari", S.normalize_digits(_U(r"\u0662\u0660\u0662\u0666-\u06f1\u06f1-\u0967\u096f ok 7")) == "2026-11-19 ok 7", S.normalize_digits(_U(r"\u0662\u0660\u0662\u0666-\u06f1\u06f1-\u0967\u096f ok 7")))
ok("T-07b-line-date-reads-an-arabic-indic-iso-date", S.line_date(_U(r"- \u0662\u0660\u0662\u0666-\u0661\u0661-\u0661\u0669 done")) == datetime.date(2026, 11, 19), S.line_date(_U(r"- \u0662\u0660\u0662\u0666-\u0661\u0661-\u0661\u0669 done")))

# AD13 B2: stale active work streams print one line; fresh ones keep full detail
_today = datetime.date(2026, 11, 15)
_nxt = ["first step", "second step", "third step", "fourth step"]
_fresh_log = ["- 2026-11-10 - did a thing", "- 2026-11-14 - did another"]
_stale_log = ["- 2026-09-01 - old", "- 2026-09-02 - older"]
_r = S.active_rows("p.md", _nxt, _fresh_log, _today)
ok("T60-fresh-full-detail", len(_r) == 1 + 3 + 2 and _r[0] == "- p.md\topen 4", _r)
_r = S.active_rows("p.md", _nxt, _stale_log, _today)
ok("T61-stale-one-line-plus-first-next", len(_r) == 2 and "stale" in _r[0] and "last 2026-09-02" in _r[0] and "first step" in _r[1], _r)
_r = S.active_rows("p.md", [], [], _today)
ok("T62-no-log-no-next-is-one-line", len(_r) == 1 and "last none" in _r[0] and "open 0" in _r[0], _r)
_r = S.active_rows("p.md", _nxt, _stale_log, _today, full=True)
ok("T63-full-flag-restores-detail", len(_r) == 1 + 3 + 2, _r)
_edge = (_today - datetime.timedelta(days=S.STALE_DAYS)).isoformat()
ok("T64-boundary-day-is-fresh", len(S.active_rows("p.md", _nxt, ["- %s - x" % _edge], _today)) == 1 + 3 + 1)
_over = (_today - datetime.timedelta(days=S.STALE_DAYS + 1)).isoformat()
ok("T65-day-after-boundary-is-stale", len(S.active_rows("p.md", _nxt, ["- %s - x" % _over], _today)) == 2)
import subprocess as _sp
_d = _sp.run([sys.executable, S.__file__], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
_f = _sp.run([sys.executable, S.__file__, "--full"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
_nt = lambda o: "\n".join(l for l in o.splitlines() if not l.startswith("PREFLIGHT"))      # the preflight line carries a timing whose digits differ between two runs
ok("T66-cli-full-not-smaller-than-default", len(_nt(_f)) >= len(_nt(_d)) and "## active work" in _d and "## active work" in _f, (len(_nt(_d)), len(_nt(_f))))
# 2026-11-19 (Stratum): in a fresh release the notes are empty; --full must still be a superset of the default for every stream shape
for _nm, _n, _l in (("empty", [], []), ("next only", ["a step"], []), ("stale log", ["a step"], _stale_log), ("fresh log", ["a step"], _fresh_log)):
    _dflt = "\n".join(S.active_rows("p.md", _n, _l, _today))
    _full = "\n".join(S.active_rows("p.md", _n, _l, _today, full=True))
    ok(f"T66b-full-row-not-shorter-than-default ({_nm})", len(_full) >= len(_dflt), (len(_dflt), len(_full)))



# --- Fable review: a malformed date in one note must not crash the session-start script ---
def _noexc(fn):
    try:
        return fn()
    except Exception as exc:   # noqa: BLE001
        return exc


def _state_cli(notes, *args):
    """Run the real entry point on a temporary vault; returns (exit code, stdout + stderr)."""
    root = Path(tempfile.mkdtemp(prefix="state-cli-"))
    try:
        for name, body in notes.items():
            f = root / name
            f.parent.mkdir(parents=True, exist_ok=True)
            if body is None:
                f.symlink_to(root / "gone-target.md")
            else:
                f.write_text(body, encoding="utf-8")
        env = dict(_os.environ, VAULT=str(root), STRATUM_NET_LOG=str(root / "net.log"))
        r = _sp.run([sys.executable, S.__file__, *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
        return r.returncode, r.stdout + r.stderr
    finally:
        shutil.rmtree(root, ignore_errors=True)


ok("T70-line-date-impossible-iso-is-none", _noexc(lambda: S.line_date("- 2026-02-30 typo")) is None, repr(_noexc(lambda: S.line_date("- 2026-02-30 typo"))))
ok("T71-line-date-skips-a-digit-run-and-finds-the-real-date", _noexc(lambda: S.line_date("ticket 1234-56-78 closed 2026-10-01")) == datetime.date(2026, 10, 1),
   repr(_noexc(lambda: S.line_date("ticket 1234-56-78 closed 2026-10-01"))))
aok("T72-line-date-impossible-arabic-day-is-none", _noexc(lambda: S.line_date(_U(r"31 \u0633\u0628\u062a\u0645\u0628\u0631 2026"))) is None,
    repr(_noexc(lambda: S.line_date(_U(r"31 \u0633\u0628\u062a\u0645\u0628\u0631 2026")))))
_ll = ["- 2026-13-01 typo", "- 2026-10-01 real"]
ok("T73-latest-survives-an-impossible-date", _noexc(lambda: S.latest(_ll)) == _ll, repr(_noexc(lambda: S.latest(_ll))))
_rc, _out = _state_cli({"n.md": "# n\n\n- [ ] later [id:: D-01] \U0001F4C5 2026-02-30\n- [ ] soon [id:: D-02] \U0001F4C5 2020-01-01\n"})
ok("T74-cli-deferral-with-impossible-date-does-not-crash", _rc == 0 and "Traceback" not in _out and "DEF\tD-02\tn.md\tdated 2020-01-01" in _out, _out[-400:])

_rc, _out = _state_cli({"n.md": "---\ndue: 2020-01-01 10:00:00\n---\n# n\n", "d.md": "---\ndue: 2020-01-02\n---\n# d\n"})
ok("T75-cli-due-with-a-time-does-not-crash-and-is-listed", _rc == 0 and "Traceback" not in _out and "due\t2020-01-01\tn.md" in _out and "due\t2020-01-02\td.md" in _out, _out[-400:])

_rc, _out = _state_cli({"d.md": "---\ndue: 2020-01-02\n---\n# d\n", "dangling.md": None})   # None: a .md symlink whose target is gone
ok("T76-cli-dangling-md-symlink-does-not-crash", _rc == 0 and "Traceback" not in _out and "due\t2020-01-02\td.md" in _out and "## deferrals" in _out, _out[-400:])

# the gate's audit is bounded by a timeout (20s when the network is down); running out of time must be reported, not raised
_real_run, _saved = S.subprocess.run, S.PROFILE


def _slow_audit(cmd, *a, **kw):
    if any(str(x).endswith("audit.py") for x in cmd):
        raise _sp.TimeoutExpired(cmd, kw.get("timeout", 0))
    return _real_run(cmd, *a, **kw)


try:
    S.subprocess.run = _slow_audit
    S.PROFILE = {**_saved, "checks": {"disabled": ["arch", "club"]}}
    _buf = io.StringIO()
    with contextlib.redirect_stdout(_buf):
        _exc = _noexc(lambda: S.run_default(1))
    _o = _buf.getvalue()
    ok("T77-audit-timeout-is-reported-and-the-rest-still-prints", _exc is None and "GATE UNKNOWN" in _o and "## active work" in _o and "## due" in _o, (repr(_exc), _o[-300:]))
finally:
    S.subprocess.run, S.PROFILE = _real_run, _saved

F, P = sum(1 for _, c, _ in R if not c), sum(1 for _, c, _ in R if c)
print(f"STATE-TESTS {P}/{len(R)}")
for name, c, got in R:
    if not c:
        print(f"FAIL {name} :: {got}")
sys.exit(1 if F else 0)
