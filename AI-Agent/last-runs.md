---
tags:
  - ai-agent
created: 2026-10-07
updated_by: AI-Agent
---

# Last runs (P5)

Every job that runs on the owner's machine appends one line here when it finishes, in the contract 1.2 shape (`AI-Agent/scripts/arch_contract.py`, LAST_RUN):

`- **last_run:** <job> · YYYY-MM-DD HH:MM · ok|fail · <note>`

`state.py` prints the newest line per job and warns when a job failed or its line is stale: `daily-prep` after 2 days, `restore-test` after 35 days, `opens` after 2 days, any other job after 8. Jobs: the daily preparation task (T-16), the restore test (T-16b; an ok line ends with `tip=`, the backup branch's last commit, so the next run can see a force-push, AD02 D11), and the hourly opens timer, which writes at most one line a day (AD02 D12). The restore test runs itself from a systemd user timer on the owner's machine (`archrestore.timer`, monthly, `Persistent=true` so a missed month runs at the next boot); a failure still writes a `fail` line, and `state.py` warns when the line is missing, failed, or older than 35 days. Append only; never edit a past line.

## Runs
- **last_run:** restore-test · 2026-10-07 13:16 · fail · failed: state, audit
- **last_run:** restore-test · 2026-10-07 13:29 · ok · clone, state, audit
- **last_run:** restore-test · 2026-10-07 13:44 · ok · clone, state, audit
- **last_run:** daily-prep · 2026-10-07 15:01 · ok · 0 due, 0 written
- **last_run:** daily-prep · 2026-10-08 10:19 · ok · 0 due, 0 written
- **last_run:** opens · 2026-10-08 12:29 · ok · seen 37, 0 new
- **last_run:** opens · 2026-10-09 09:37 · ok · seen 38, 0 new
- **last_run:** daily-prep · 2026-10-09 09:37 · ok · 0 due, 0 written
- **last_run:** opens · 2026-10-10 00:00 · ok · seen 38, 0 new
- **last_run:** daily-prep · 2026-10-10 10:42 · ok · 0 due, 0 written
- **last_run:** opens · 2026-10-11 08:06 · ok · seen 38, 0 new
- **last_run:** daily-prep · 2026-10-11 08:06 · ok · 0 due, 0 written
- **last_run:** opens · 2026-10-12 09:06 · ok · seen 38, 0 new
- **last_run:** daily-prep · 2026-10-12 09:06 · ok · 0 due, 0 written
- **last_run:** opens · 2026-10-13 09:20 · ok · seen 38, 0 new
- **last_run:** daily-prep · 2026-10-13 09:20 · ok · 0 due, 0 written
- **last_run:** opens · 2026-10-14 09:33 · ok · seen 37, 0 new
- **last_run:** daily-prep · 2026-10-14 09:33 · ok · 0 due, 0 written
- **last_run:** opens · 2026-10-15 09:02 · ok · seen 38, 0 new
- **last_run:** daily-prep · 2026-10-15 09:02 · ok · 1 due, 1 written
- **last_run:** opens · 2026-10-16 00:02 · ok · seen 37, 0 new
- **last_run:** daily-prep · 2026-10-16 15:14 · ok · 1 due, 0 written
- **last_run:** opens · 2026-10-19 22:00 · ok · seen 38, 0 new
- **last_run:** daily-prep · 2026-10-19 22:00 · ok · 1 due, 0 written
- **last_run:** launch-pilot · 2026-10-30 21:08 · ok-with-findings · 2 launches (20261030p1/p2 via probe-parallel) + 1 resume (p2) — deliverables complete on disk, claim lines exact, F2 clean (warn on a); p1's tool-env shows execute_javascript bridge broken; finding: "partially confirmed" evades the VERDICT-row counter (regex counts confirmed|uncertain|not-found only) — a partially-confirmed target reported as 2/2 complete escapes the status check
