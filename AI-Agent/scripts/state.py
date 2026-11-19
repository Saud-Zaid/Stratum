# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Derived session state (T25 / 2026-09-28): what is true NOW, computed from the vault, never stored.
Run it first in every session instead of trusting any written "current state".
Usage: state [--days N]   (default 7)"""
import datetime
import json
import importlib.util
import os
import re
import socket
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

from _vaultlib import force_utf8_stdio, locale_value, standard_parser, VAULT, Pause, load_profile, frontmatter, iter_md, normalize_ar, parse, pause_window, read, rel as vrel, sections

DAYS = 7
TODAY = datetime.date.today()
try:
    PROFILE = load_profile()
except ValueError:      # a broken profile is reported by `audit --check schema`; state still prints with the defaults
    PROFILE = load_profile(VAULT / "__no_profile__")
NEXT = tuple(PROFILE["headings"]["next_steps"]) or tuple(locale_value("NEXT_HEADINGS", ("Next Steps",)))   # open next steps, as `- [ ]` lines
LOG = tuple(PROFILE["headings"]["progress_log"]) or tuple(locale_value("LOG_HEADINGS", ("Progress Log", "Changelog")))   # dated progress lines, any order: latest() sorts by date
PENDING_REVIEW = ".vault-release/pending-review.json"   # written by the upgrade tool; state only reads it (U-46)


def check_on(name: str) -> bool:
    """False when the release profile switched the check off (arch, club, ...)."""
    return name not in PROFILE["checks"]["disabled"]
OPEN = re.compile(r"^\s*- \[ \]\s*(.+)$")
DEF_LINE = re.compile(r"^\s*- \[ \].*\[id::\s*(D-\d+)\]")
TAG_COUNT = re.compile(r'\[state::\s*"([\w/-]+) count >= (\d+)"\]')
MONTHS = dict(locale_value("MONTHS", {}))          # Arabic month names; empty in a release
def normalize_digits(s: str) -> str:
    """Every non-ASCII decimal digit (Arabic-Indic, Extended Arabic-Indic, Devanagari, ...) becomes its ASCII digit, in any locale."""
    return "".join(str(unicodedata.decimal(c)) if (not c.isascii() and c.isdecimal()) else c for c in s)


def _probe(host: str, port: int, af: int) -> bool:
    """N6: probe-based liveness (raw TCP connect, no DNS, no route assumption)."""
    s = socket.socket(af)
    try:
        s.settimeout(2.0)
        s.connect((host, port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _net_preflight() -> str:
    """N1 mechanical net-preflight before the gate's audit.py call (ledger 304, A_adopt_mechanical).
    Probes are hard-bounded at 2s each; route presence alone is NOT IPv6 liveness (N6).
    Returns net state: up / v6-only / down. Logs one line to AI-Agent/state/net-preflight.log, or to $STRATUM_NET_LOG when set (N4)."""
    t0 = time.time()
    if os.environ.get("STRATUM_SKIP_NET") == "1":   # offline or CI: no probes at all; the state stays visible as `skipped`, never silent
        v4 = v6 = False
        state = "skipped"
    else:
        v4 = any(_probe(h, 443, socket.AF_INET) for h in ("1.1.1.1", "8.8.8.8"))
        v6 = v4 or any(_probe(h, 443, socket.AF_INET6) for h in ("2606:4700:4700::1111", "2001:4860:4860::8888"))   # IPv4 up: IPv6 is not needed
        state = "up" if v4 else ("v6-only" if v6 else "down")
    secs = round(time.time() - t0, 2)
    try:
        logp = Path(os.environ["STRATUM_NET_LOG"]) if os.environ.get("STRATUM_NET_LOG") else Path(__file__).resolve().parent.parent / "state" / "net-preflight.log"   # run_tests points it at a temp file
        with logp.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')}\tv4={v4}\tv6={v6}\t{state}\t{secs}s\n")
    except OSError:
        pass  # logging must never break the state script (a-4 blast-radius rule)
    print(f"PREFLIGHT\tv4={v4}\tv6={v6}\tstate={state}\t{secs}s")
    return state


def line_date(line: str):
    """ISO date (2026-09-28) or, where the Arabic locale is present, an Arabic-month date found in a line, else None."""
    s = normalize_digits(line)
    for m in re.finditer(r"(\d{4})-(\d{2})-(\d{2})", s):
        try:
            return datetime.date(*map(int, m.groups()))
        except ValueError:      # `2026-02-30` or a digit run such as 1234-56-78: not a date, and never a crash at session start
            continue
    m = re.search(r"(\d{1,2})\s+(\S+)\s+(\d{4})", s)
    if m and m.group(2) in MONTHS:
        try:
            return datetime.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
        except ValueError:
            return None
    return None


def latest(lines: list[str], n: int = 2) -> list[str]:
    """Newest progress lines by date, whatever the order in the note. A dated `### ` heading dates the lines under it."""
    current, dated = None, []
    for i, l in enumerate(lines):
        if l.lstrip().startswith("#"):
            current = line_date(l) or current
        elif l.lstrip().startswith("- "):
            dated.append((line_date(l) or current or datetime.date.min, i, l.strip()))
    return [l for _, _, l in sorted(dated)[-n:]]


STALE_DAYS = 21   # AD13 B2: a work stream with no log line for this long prints one line, not five (state.py is the mandatory session-start command)


def active_rows(name: str, nxt: list[str], log: list[str], today: datetime.date, full: bool = False) -> list[str]:
    """Rows for one active work stream. Fresh streams print up to 3 next steps and the 2 latest log lines; a stream whose
    newest log line is older than STALE_DAYS (or has none) prints its open count, first next step and last date only."""
    last = max((line_date(l) for l in log if line_date(l)), default=None)
    head = f"- {name}\topen {len(nxt)}"
    stale = not (last is not None and (today - last).days <= STALE_DAYS)
    if full or not stale:
        if full:      # --full is a superset of the default: the same last-date and stale marker (a fresh release has empty notes)
            head += f"\tlast {last or 'none'}" + (" (stale)" if stale else "")
        return [head] + [f"    next\t{t[:110]}" for t in nxt[:3]] + [f"    log\t{l[2:][:110]}" for l in log]
    hidden = len(nxt) > 1 or bool(log)      # the hint only when --full would show more
    row = head + f"\tlast {last or 'none'} (stale" + (", --full)" if hidden else ")")
    return [row] + ([f"    next\t{nxt[0][:110]}"] if nxt else [])


def git(*args) -> str:
    try:
        return subprocess.run(["git", "-C", str(VAULT), "-c", "core.quotepath=off", *args],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30).stdout
    except Exception:
        return ""


def section_lines(text: str, titles: tuple) -> list[str]:
    lines = text.splitlines()
    out = []
    for level, title, start, count in sections(text):
        if any(title.strip().startswith(t) for t in titles):
            out += lines[start: start - 1 + count]          # skip the heading line itself
    return [l for l in out if l.strip()]


def hubs() -> list[Path]:
    """Project notes, folder notes, and Area notes: the places where a work stream's state lives."""
    found = []
    for p in sorted((VAULT / "01-Projects").glob("*.md")):
        if p.name != "README.md":
            found.append(p)
    homes = list(PROFILE["paths"]["system_homes"])
    if not homes and check_on("arch"):
        try:
            import arch_contract as C   # production systems keep their folder note in their home (AD02 D06)
            homes = list(C.SYSTEM_HOMES)
        except ImportError:
            homes = []
    for top in dict.fromkeys([VAULT / "01-Projects"] + [VAULT / h for h in homes]):
        for d in sorted(x for x in top.iterdir() if x.is_dir()) if top.is_dir() else []:
            note = d / f"{d.name}.md"
            if note.is_file():
                found.append(note)
    for p in sorted((VAULT / "02-Areas").glob("*.md")):
        if (frontmatter(read(p)) or {}).get("type") == "area":
            found.append(p)
    return found


def rel(p: Path) -> str:
    return str(p.relative_to(VAULT))


def club_module():
    """The mother vault's club section (club_state.py), or None in a tree that does not ship it (a release)."""
    try:
        import club_state
    except ImportError:
        return None
    return club_state


def delta_state(vault: Path = VAULT) -> str:
    """Stateless delta-only dashboard (<50 tokens, <0.15s, AD13 M01):
    Uncommitted files from git status, commits in last 48h, active projects with open tasks,
    and masked integrity findings count.
    """
    now = datetime.datetime.now().astimezone()

    # 1. Uncommitted files (git status -s)
    raw_status = git("status", "--short", "--", ".", ":(exclude).obsidian").splitlines()
    dirty = [l[3:].strip() for l in raw_status if l.strip()]
    if not dirty:
        d_str = "0"
    elif len(dirty) == 1:
        d_name = Path(dirty[0].strip('"\x27')).name[:20]
        d_str = d_name
    else:
        d_name = Path(dirty[0].strip('"\x27')).name[:15]
        d_str = f"{len(dirty)} ({d_name}, ...)"

    # 2. Commits of last 48 hours (git log --since="48 hours")
    raw_log = [l.strip() for l in git("log", "--since=48 hours", "--oneline").splitlines() if l.strip()]
    if not raw_log:
        c_str = "none"
    elif len(raw_log) == 1:
        c_str = raw_log[0][:35]
    else:
        first = raw_log[0][:22]
        c_str = f"{first}... (+{len(raw_log)-1} in 48h)"

    # 3. Active projects with open tasks only (ignore idle ones)
    OPEN_RE = re.compile(r"^\s*- \[ \]")
    active_pairs = []
    for p in sorted((vault / "01-Projects").glob("*.md")):
        if p.name == "README.md":
            continue
        try:
            txt = p.read_text(encoding="utf-8")
        except Exception:
            continue
        if "status: active" not in txt:
            continue
        m = re.search(r"^##\s+(?:%s).*?\n(.*?)(?=\n##|\Z)" % "|".join(re.escape(t) for t in NEXT), txt, re.S | re.M)
        if m:
            count = sum(1 for l in m.group(1).splitlines() if OPEN_RE.match(l))
            if count > 0:
                stem = p.stem.replace("01-Projects/", "")
                active_pairs.append((stem, count))

    if not active_pairs:
        a_str = "none"
    else:
        items = [f"{name[:8]}({c})" for name, c in active_pairs[:3]]
        more = len(active_pairs) - 3
        a_str = ", ".join(items) + (f" (+{more})" if more > 0 else "")

    # 4. Integrity masking (delta integrity)
    dirty_md = [vault / d.strip('"\x27') for d in dirty if d.strip('"\x27').endswith(".md")]
    out_finds = []
    try:
        import archops
        import yaml
        for p in dirty_md:
            if not p.is_file():
                continue
            rel_p = p.relative_to(vault).as_posix()
            if rel_p.startswith(archops.SKIP_TOP):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if text.startswith("---\n"):
                end = text.find("\n---", 4)
                try:
                    if end < 0:
                        raise yaml.YAMLError("frontmatter never closes")
                    yaml.safe_load(text[4:end])
                except yaml.YAMLError as e:
                    out_finds.append(f"{rel_p}: fm error")
            for n, ln in archops.C.readable_lines(text):
                m = archops.SHAPE_LIKE.match(ln)
                if m and not getattr(archops.C, archops.PARSERS[m.group(1)])(ln):
                    out_finds.append(f"{rel_p}:{n}: shape error")

        ops, steps = archops.operations(vault)
        for oid, o in sorted(ops.items()):
            if o["status"] == "open" and (now - archops.when(o["at"])).total_seconds() / 3600 > archops.OPEN_OP_HOURS:
                out_finds.append(f"{oid}: open")
        newest = {}
        for (oid, n), s in steps.items():
            newest[s["path"]] = max(newest.get(s["path"], ""), oid)
        for (oid, n), s in sorted(steps.items()):
            if s["after"] in ("pending",) or newest.get(s["path"]) != oid or ops.get(oid, {}).get("status") != "applied":
                continue
            if s["path"] in archops.MACHINE_LOGS:
                continue
            if archops.fingerprint(vault / s["path"]) != s["after"]:
                out_finds.append(f"{oid}: changed")
        used = set()
        for kind in ("AD", "RL", "TR", "R", "P", "LS"):
            used |= archops.existing(vault, kind, None)
        for r in archops.reservations(vault):
            e = r["id"].split(":")[-1]
            if e not in used and (now - archops.when(r["at"])).days > archops.RESERVATION_DAYS and not archops.C.in_system_home(r["file"]):
                out_finds.append(f"{r['id']}: unused")
    except Exception:
        pass

    if not out_finds:
        i_str = "integrity: ok (run archops check for details)"
    else:
        i_str = f"integrity: {len(out_finds)} findings (run archops check for details)"

    return f"dirty: {d_str}\ncommits: {c_str}\nactive: {a_str}\n{i_str}"


def run_delta_only():
    print(delta_state())


def upgrade_alerts(vault: Path = VAULT) -> list[str]:
    """Read-only (U-46): rows for `.vault-release/pending-review.json`, nothing when the file is absent.
    Format: {"pending": [{"id": str, "severity": "HIGH"|"WARN", "summary": str}]}."""
    f = vault / PENDING_REVIEW
    if not f.is_file():
        return []
    try:
        items = json.loads(f.read_text(encoding="utf-8")).get("pending", [])
        rows = [f"{str(i.get('severity', 'WARN')).upper()}\t{i.get('id', '?')}\t{str(i.get('summary', ''))[:110]}" for i in items]
    except (ValueError, AttributeError, TypeError) as e:
        return [f"WARN\tpending-review unreadable\t{type(e).__name__}"]
    return rows


VENV_STAMP = ".venv/.stratum-lock-sha256"   # setup writes sha256(uv.lock) here (U-49)


def venv_lock_alert(vault: Path = VAULT) -> list[str]:
    """One WARN row when the vault's own .venv is older than uv.lock. Silent without a .venv, a uv.lock or a stamp
    (a VAULT_PYLIB or /opt/pylib setup has none); the check is a single hash of one file, no network."""
    stamp, lock = vault / VENV_STAMP, vault / "uv.lock"
    if not (stamp.is_file() and lock.is_file()):
        return []
    import hashlib
    try:
        want = hashlib.sha256(lock.read_bytes()).hexdigest()
        have = stamp.read_text(encoding="utf-8").strip()
    except OSError:
        return []
    return [] if want == have else ["WARN\tvenv-stale\t.venv is older than uv.lock: run setup to refresh it"]


def run_default(days: int = 7, full: bool = False):
    alerts = upgrade_alerts() + venv_lock_alert()
    if alerts:
        print("## upgrade alerts")
        for row in alerts:
            print(row)
        print()
    # 1. Git: what changed, and when
    print(f"## git (last {days} days)")
    head = git("log", "-1", "--format=%h %ci %s").strip()
    print(f"head\t{head or 'unavailable'}")
    changed = [l for l in git("log", f"--since={days}.days", "--name-only", "--format=").splitlines() if l.endswith(".md")]
    counts = {}
    for f in changed:
        counts[f] = counts.get(f, 0) + 1
    for f, n in sorted(counts.items(), key=lambda x: -x[1])[:15]:
        print(f"changed\t{n}\t{f}")
    dirty = [l[3:] for l in git("status", "--short", "--", ".", ":(exclude).obsidian").splitlines()]
    print(f"uncommitted\t{len(dirty)}\t{', '.join(dirty[:6])}")

    # 2. Gate: will the next commit pass?
    # N1 net-preflight (ledger 304, A_adopt_mechanical): probe-based liveness BEFORE audit.py,
    # because audit.py stalls on network-dependent checks; dead network => hang, not fail.
    net_state = _net_preflight()
    aud_timeout = 120 if net_state in ("up", "skipped") else 20  # N6: down/v6-only => bound the audit tightly
    print(f"PREFLIGHT\taud_timeout={aud_timeout}s")
    try:
        aud = subprocess.run([sys.executable, str(Path(__file__).with_name("audit.py")), "--ratchet"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(VAULT), timeout=aud_timeout)
        for l in (aud.stdout + aud.stderr).splitlines():
            if l.startswith(("GATE", "BLOCK")):
                print(l)
    except subprocess.TimeoutExpired:   # the bound exists so a dead network cannot hang the session start; hitting it must not kill it either
        print(f"GATE UNKNOWN\taudit did not finish in {aud_timeout}s: run `audit.py --ratchet` before committing")

    # 3. Active work streams: next steps + latest progress, from the notes themselves
    print("\n## active work (status: active)")
    for p in hubs():
        text = read(p)
        fm = frontmatter(text) or {}
        if fm.get("status") != "active":
            continue
        nxt = [OPEN.match(l).group(1) for l in section_lines(text, NEXT) if OPEN.match(l)]
        log = latest(section_lines(text, LOG))
        for row in active_rows(rel(p), nxt, log, datetime.date.today(), full):
            print(row)

    # 4. Due dates within a week
    print("\n## due (<= 7 days)")
    for p in sorted(VAULT.rglob("*.md")):
        if ".obsidian" in p.parts or "fixtures" in p.parts or vrel(p).startswith("export/") or not p.is_file():   # not a file: a dangling symlink (read() raised)
            continue
        due = (frontmatter(read(p)) or {}).get("due")
        if isinstance(due, datetime.datetime):
            due = due.date()   # `due: 2026-11-20 10:00:00` is a datetime; subtracting a date from it raised TypeError (audit.py had the same fix)
        if isinstance(due, datetime.date) and (due - TODAY).days <= 7:
            print(f"due\t{due}\t{rel(p)}")

    # 4b. Deferrals due for attention (package Y): dated within a week, snoozed twice, or a computable state met
    print("\n## deferrals (package Y)")
    notes = [p for p in VAULT.rglob("*.md") if ".obsidian" not in p.parts and "fixtures" not in p.parts and not vrel(p).startswith("export/") and p.is_file()]
    tag_n = {}
    for p in notes:
        tags = (frontmatter(read(p)) or {}).get("tags") or []
        for t in (tags if isinstance(tags, list) else [tags]):
            tag_n[str(t)] = tag_n.get(str(t), 0) + 1
    for p in sorted(notes):
        if rel(p).startswith("04-Archive/"):
            continue
        for ln in read(p).splitlines():
            m = DEF_LINE.match(ln)
            if not m:
                continue
            why = []
            d = re.search(r"\U0001F4C5\s*(\d{4}-\d{2}-\d{2})", ln)
            if d and line_date(d.group(1)) and (line_date(d.group(1)) - TODAY).days <= 7:   # line_date: None for an impossible date
                why.append(f"dated {d.group(1)}")
            s = re.search(r"\[snoozed::\s*(\d+)\]", ln)
            if s and int(s.group(1)) >= 2:
                why.append("needs decision (snoozed x2)")
            c = TAG_COUNT.search(ln)
            if c and tag_n.get(c.group(1), 0) >= int(c.group(2)):
                why.append(f"condition met ({c.group(1)} = {tag_n[c.group(1)]})")
            if why:
                print(f"DEF\t{m.group(1)}\t{rel(p)}\t{' · '.join(why)}")

    # 4c. Error registry (D02, D11): a fixed error whose regression check fails is a warning (regress.py)
    if importlib.util.find_spec("regress"):   # the registry belongs to the mother vault; a release has none
        print("\n## regressions (error registry)")
        try:
            import regress
            rows = regress.results()
            for r in regress.failing_fixed(rows):
                print(f"WARN\t{r[0]}\tfixed error regressed ({r[1]})\t{r[3]}\t{r[4]}")
            print(f"checked\t{len(rows)}\tfixed_failing {len(regress.failing_fixed(rows))}")
        except Exception as e:  # state must still print the rest
            print(f"unavailable\t{type(e).__name__}: {e}")

    # 4d. Architecture (D03, D10, D14, P5; spec §3.22, §3.23): catalog, anchors, due cycles, last runs
    if check_on("arch"):
        print("\n## architecture")
        try:
            import archcatalog
            import archroute
            ents = archcatalog.collect(VAULT)
            cur = VAULT / archcatalog.CATALOG
            want = archcatalog.render(ents, archcatalog._created(VAULT))
            cstate = "missing" if not cur.is_file() else ("ok" if cur.read_text(encoding="utf-8") == want else "stale")
            print(f"catalog\t{cstate}\tentities={len(ents)}" + ("" if cstate == "ok" else "\trun `archcatalog check`; the next gate4: commit rewrites it"))
            for f in archcatalog.findings(ents):
                print(f"WARN\t{f}")
            for p in sorted((VAULT / "01-Projects").glob("AD*-canvas.md")):
                ad = p.name.split("-", 1)[0]
                st, why = archroute.canvas_check(VAULT, ad)
                if st == "upgrade":
                    print(f"WARN\t{ad} canvas must become a folder: {'; '.join(why)} (a move: commit first, RL-0004)")
        except Exception as e:  # state must still print the rest
            print(f"catalog unavailable\t{type(e).__name__}: {e}")
        try:
            import arch_hook
            for ad, status, _sha, _changed, miss in arch_hook.verify(VAULT, []):
                if status in ("tampered", "missing"):
                    print(f"HIGH\t{ad}\tapproved snapshot {status} (D03)")
                elif miss != "-":
                    print(f"HIGH\t{ad}\tapproved elements changed with no new D: {miss} (blocks the next Gate 4, D03)")
        except Exception as e:
            print(f"anchors unavailable\t{type(e).__name__}: {e}")
        try:
            import archdue
            for row in archdue.due(VAULT, TODAY):
                print("\t".join(str(x) for x in row))
        except Exception as e:
            print(f"due unavailable\t{type(e).__name__}: {e}")
        try:
            import archprep   # T-16: the due files the daily preparation wrote (D10, W17)
            for ad, s in sorted(archprep.read_due(VAULT).items()):
                frozen = s.get("frozen")
                print(("WARN\t" if frozen else "") + f"duefile\t{ad}\t{s.get('status')}\tsince {s.get('first_due')}"
                      f"\t{s.get('triggers')}" + (f"\tfrozen {frozen}" if frozen else "")
                      + f"\t{archprep.DUE_DIR}/{ad}{archprep.SUFFIX}")
        except Exception as e:
            print(f"duefile unavailable\t{type(e).__name__}: {e}")
        try:
            import arch_contract as C
            STALE_DAYS = {"daily-prep": 2, "restore-test": 35, "opens": 2}   # P5: daily task, monthly restore test (D10, D12); opens timer (AD02 D12)
            runs = {}
            lr = VAULT / "AI-Agent/last-runs.md"
            if lr.is_file():
                for _n, ln in C.readable_lines(read(lr)):
                    r = C.last_run(ln)
                    if r and (r["job"] not in runs or r["day"] >= runs[r["job"]]["day"]):
                        runs[r["job"]] = r
            if not runs:
                print("lastrun\tnone recorded yet (P5)")
            for job in ("restore-test", "daily-prep", "opens"):   # expected from T-16b, T-16 and AD02 D12 (P5)
                if job not in runs:
                    print(f"WARN\tlastrun\t{job}\tnever run (P5): see AI-Agent/last-runs.md")
            for job, r in sorted(runs.items()):
                age = (TODAY - datetime.date.fromisoformat(r["day"])).days
                limit = STALE_DAYS.get(job, 8)
                flag = "WARN\t" if r["status"] == "fail" or age > limit else ""
                print(f"{flag}lastrun\t{job}\t{r['day']}\t{r['status']}\t{age} days (stale after {limit})")
        except Exception as e:
            print(f"lastrun unavailable\t{type(e).__name__}: {e}")
        try:
            import archmap   # AD02 D08: the architecture index against what is really there; warn only
            if (VAULT / archmap.INDEX).is_file():
                mfinds = [f for f in archmap.check(VAULT) if f[0] == "warn"]
                for _sev, rule, where, detail in mfinds:
                    print(f"WARN\tmap\t{rule}\t{where}\t{detail}")
                print(f"map\t{'ok' if not mfinds else str(len(mfinds)) + ' finds'}")
            else:
                print(f"map\tnone\tno index yet ({archmap.INDEX})")
        except Exception as e:
            print(f"map unavailable\t{type(e).__name__}: {e}")
        try:
            import archops   # D12, spec §3.24: integrity at session start and other agents' live signals (RL-0027)
            now = datetime.datetime.now().astimezone()
            finds = archops.check(VAULT, now)
            # Mask detailed integrity warnings to one summary line (AD13 M01)
            print(f"integrity: {'ok' if not finds else str(len(finds)) + ' findings'} (run archops check for details)")
            for ad, agent, at, age in archops.signals(VAULT, now):
                print(f"signal\t{ad}\t{agent} since {at} ({age}h): read the state note again before writing (RL-0027)")
        except Exception as e:
            print(f"integrity unavailable\t{type(e).__name__}: {e}")

    # 4e. ExampleClub club (AD03 D10, M11): guest permission, F10 and the pause, warn only
    CS = club_module() if check_on("club") else None
    if CS:
        print("\n## club")
        try:
            pw = []
            for l in CS.club_lines(CS.club_docs(), TODAY, pause_window(warnings=pw), pw):
                print(l)
        except Exception as e:  # state must still print the rest
            print(f"club unavailable\t{type(e).__name__}: {e}")

    # 5. Staleness guard: any written state is suspect by definition
    h = VAULT / "AI-Agent/handoff.md"
    m = re.search(r"as of (\d{1,2} \w{3} \d{4})", read(h)) if h.is_file() else None
    if m:
        print(f"\nSTALE\thandoff.md still carries a written state ('as of {m.group(1)}'); trust this output instead")


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    if argv is None:
        argv = sys.argv[1:]
    ap = standard_parser(__doc__, "state")
    ap.add_argument("--club-selftest", action="store_true", help="run the club window self-test and exit")
    ap.add_argument("--delta-only", action="store_true", help="print only what changed since the last state")
    ap.add_argument("--full", action="store_true", help="print every active work stream in full (default: streams idle over %d days are one line)" % STALE_DAYS)
    ap.add_argument("--days", type=int, default=DAYS, help="git history window in days (default %d)" % DAYS)
    ns = ap.parse_args(argv)
    if ns.club_selftest:
        CS = club_module()
        if CS is None:
            print("club self-test: the club section is not part of this release")
            return 0
        return CS.club_selftest()
    if ns.delta_only:
        run_delta_only()
        return 0
    run_default(ns.days, ns.full)
    return 0


if __name__ == "__main__":
    sys.exit(main())
