# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for audit rules (R12, R13, R18, ADR-011, trap registry path, DEF deferrals, CLUB club rules); run after any change to audit.py or club_rules.py. Usage: audit-tests"""

def _U(s):
    """ASCII-escaped test data: the shipped sources hold no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")


import audit
try:
    import club_rules  # audit imports it lazily (T-02b), so the test imports it itself
except ImportError:   # a release does not ship the club rules
    club_rules = None
from _vaultlib import VAULT, parse

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


HAS_AR = bool(audit.locale_value("NORMALIZE", {}))   # the Arabic tables (and the mother's owner names) exist only in the mother vault


def aok(name, cond, got=""):
    """ok(), run only where the Arabic locale is present."""
    if HAS_AR:
        ok(name, cond, got)
    else:
        print(f"SKIP {name}: no Arabic locale in this tree")


def rules(path, text, checks=("links", "adr")):
    ctx = audit.Ctx({"T.md": TARGET, path: text}, {"T.md": parse(TARGET), path: parse(text)})
    return sorted({f[1] for f in audit.findings_for(path, text, set(checks), 4000, ctx)})


TARGET = "# T\n\n## real\n"
BAD = _U(r"\u0646\u0635[[T]]\u0645\u0644\u0635\u0648\u0642\n[[T#missing]]\n[[T#a#b]]\n[[open without close\n")
SECTIONS = "\n".join(f"## s{i}\n\nx\n" for i in range(1, 7))
TOC = "\n".join(f"- [[#s{i}]]" for i in range(1, 7))
LINK_RULES = {"R12-missing", "R12-nested", "R13-glued", "R13-unbalanced", "R18-manual-toc"}


def note(body):
    return "# N\n\n" + body + "\n" + SECTIONS


# Positive control: every rule fires on plain prose, so a silent rule below means "skipped", not "broken".
ok("prose: all link rules fire", LINK_RULES <= set(rules("P.md", note(BAD + "\n" + TOC + "\n"))), rules("P.md", note(BAD + "\n" + TOC + "\n")))
fenced = note("```text\n" + BAD + TOC + "\n```\n")
ok("fenced code: no link rule fires", not LINK_RULES & set(rules("F.md", fenced)), rules("F.md", fenced))
indented = note("\n".join("    " + x for x in (BAD + TOC).split("\n")) + "\n")
ok("indented code: no link rule fires", not LINK_RULES & set(rules("I.md", indented)), rules("I.md", indented))

# ADR-011: retired system path, driven by the names that exist in the system folder today
old = f"see `Claude/scripts/audit.py` and Claude/traps/ and Claude/{audit.SYSTEM_DIR}\n"
ok("ADR-011 fires on Claude/<system name>", "ADR-011-oldpath" in rules("O.md", note(old)), rules("O.md", note(old)))
ok("ADR-011 fires inside code too", "ADR-011-oldpath" in rules("C.md", note("```\ncd Claude/scripts\n```\n")))
clean = "~/.config/Claude/claude_desktop_config.json · Claude/ alone · Claude/Desktop · AI-Agent/scripts\n"
ok("ADR-011 ignores non-vault Claude/ paths", "ADR-011-oldpath" not in rules("K.md", note(clean)), rules("K.md", note(clean)))
ok("ADR-011 skips 04-Archive/", "ADR-011-oldpath" not in rules("04-Archive/A.md", note(old)))
waived = "---\naudit_waive:\n  ADR-011-oldpath: test\n---\n" + note(old)
kept = audit.apply_waivers("W.md", parse(waived).fm, [f for f in audit.findings_for("W.md", waived, {"adr"}, 4000, audit.Ctx({}, {}))], {"adr", "waivers"})
ok("ADR-011 honours audit_waive", not [f for f in kept if f[1] == "ADR-011-oldpath"], kept)

# ADR-007 registry path comes from the schema and points at a real folder
reg = audit.trap_registry()
ok("trap registry read from schema", reg.endswith("/") and (VAULT / reg).is_dir() and any((VAULT / reg).glob("TR-*.md")), reg)

# Package : deferral rules (warn-only), positive and negative controls
D = ("def",)
SPEC = "---\ntags:\n  - task-spec\n---\n"
zombie = note("- [ ] old task \U0001F4C5 2026-01-01\n")
ok("DEF-archived fires in 04-Archive/", "DEF-archived" in rules("04-Archive/Z.md", zombie, D), rules("04-Archive/Z.md", zombie, D))
ok("DEF-archived silent outside archive", "DEF-archived" not in rules("01-Projects/Z.md", zombie, D))
loose = SPEC + note(_U(r"\u0646\u0628\u0646\u064a\u0647 \u0644\u0627\u062d\u0642\u0627\u064b \u0644\u0645\u0627 \u064a\u062c\u0647\u0632 \u0627\u0644\u0628\u0646\u0643\n"))
aok("DEF-untracked fires in a task-spec", "DEF-untracked" in rules("U.md", loose, D), rules("U.md", loose, D))
tracked = SPEC + note(_U(r"- [ ] \u0646\u0628\u0646\u064a\u0647 \u0644\u0627\u062d\u0642\u0627\u064b [id:: D-01] [state:: \"a\"] [kill:: \"b\"]\n"))
ok("DEF-untracked silent with an id in the paragraph", "DEF-untracked" not in rules("V.md", tracked, D), rules("V.md", tracked, D))
noun = SPEC + note(_U(r"## \u0627\u0644\u0645\u0624\u062c\u064e\u0651\u0644\u0627\u062a\n\n\u0642\u0633\u0645 \u0627\u0644\u0645\u0624\u062c\u064e\u0651\u0644\u0627\u062a \u0628\u0627\u0644\u0645\u0646\u0637\u0642\u0629\n"))
ok(_U(r"DEF-untracked ignores the noun \u00ab\u0627\u0644\u0645\u0624\u062c\u0644\u0627\u062a\u00bb"), "DEF-untracked" not in rules("N.md", noun, D), rules("N.md", noun, D))
ok("DEF-untracked skips archived specs", "DEF-untracked" not in rules("04-Archive/U.md", loose, D))
ok("DEF-untracked silent in untagged notes", "DEF-untracked" not in rules("W.md", note(_U(r"\u0646\u0628\u0646\u064a\u0647 \u0644\u0627\u062d\u0642\u0627\u064b\n")), D))
ok("DEF-untracked silent inside fenced code", "DEF-untracked" not in rules("X.md", SPEC + note("```\nlater\n```\n"), D))
half = note("- [ ] x [id:: D-02] [state:: \"a\"] \U0001F4C5 2026-12-01\n")
ok("DEF-incomplete fires without kill", "DEF-incomplete" in rules("H.md", half, D), rules("H.md", half, D))
ok("DEF-incomplete silent on a full item", "DEF-incomplete" not in rules("V.md", tracked, D))
ok("DEF-snooze fires at 2", "DEF-snooze" in rules("S.md", note("- [ ] x [id:: D-03] [state:: \"a\"] [kill:: \"b\"] [snoozed:: 2]\n"), D))
ok("DEF-snooze silent at 1", "DEF-snooze" not in rules("S.md", note("- [ ] x [id:: D-03] [state:: \"a\"] [kill:: \"b\"] [snoozed:: 1]\n"), D))


# The club rules live in the mother vault only; a release ships neither the rules nor their tests.
if club_rules is None:
    print("SKIP CLUB-*: the club rules are not part of this tree")
else:
    # ExampleClub club rules (club_rules.py, warn-only), positive and negative controls
    def club(path, text, extra=None):
        texts = {path: text, **(extra or {})}
        ctx = audit.Ctx(texts, {k: parse(v) for k, v in texts.items()})
        return sorted({f[1] for f in audit.findings_for(path, text, {"club"}, 4000, ctx)})


    def fm(*lines):
        return "---\n" + "\n".join(lines) + "\n---\n"


    EV = ("tags:", "  - exampleclub-event", "contexts:", "  - exampleclub-tech")
    done = fm(*EV, "status: done")
    ok("CLUB-no-aar fires on a done event without the fixed heading", "CLUB-no-aar" in club("01-Projects/E.md", done + note(_U(r"## \u0628\u0639\u062f \u0627\u0644\u0633\u064a\u0634\u0646\n"))), club("01-Projects/E.md", done + note(_U(r"## \u0628\u0639\u062f \u0627\u0644\u0633\u064a\u0634\u0646\n"))))
    ok(_U(r"CLUB-no-aar silent with \u00ab\u0628\u0639\u062f \u0627\u0644\u0641\u0639\u0627\u0644\u064a\u0629 (AAR)\u00bb"), "CLUB-no-aar" not in club("01-Projects/E.md", done + note(_U(r"## \u0628\u0639\u062f \u0627\u0644\u0641\u0639\u0627\u0644\u064a\u0629 (AAR)\n"))))
    ok("CLUB-no-aar silent while active", "CLUB-no-aar" not in club("01-Projects/E.md", fm(*EV, "status: active") + note("")))
    PROJ = {_U(r"01-Projects/\u062d\u062f\u062b.md"): _U(r"# \u062d\u062f\u062b\n")}
    sched = fm("idea_stage: scheduled")
    ok("CLUB-idea-unlinked fires without a project link", "CLUB-idea-unlinked" in club("B/I.md", sched + note(_U(r"\u0641\u0643\u0631\u0629\n")), PROJ), club("B/I.md", sched + note(_U(r"\u0641\u0643\u0631\u0629\n")), PROJ))
    ok("CLUB-idea-unlinked silent with a project link", "CLUB-idea-unlinked" not in club("B/I.md", sched + note(_U(r"\u0645\u0634\u0631\u0648\u0639\u0647\u0627 [[\u062d\u062f\u062b]]\n")), PROJ))
    ok("CLUB-idea-unlinked silent on a seed", "CLUB-idea-unlinked" not in club("B/I.md", fm("idea_stage: seed") + note(_U(r"\u0641\u0643\u0631\u0629\n")), PROJ))
    person = fm("contexts:", "  - exampleclub-tech/pr")
    ok("CLUB-no-consent fires on a club person", "CLUB-no-consent" in club(_U(r"02-Areas/\u0627\u0644\u0623\u0634\u062e\u0627\u0635/P.md"), person + note("")), club(_U(r"02-Areas/\u0627\u0644\u0623\u0634\u062e\u0627\u0635/P.md"), person + note("")))
    ok("CLUB-no-consent silent with consent_on", "CLUB-no-consent" not in club(_U(r"02-Areas/\u0627\u0644\u0623\u0634\u062e\u0627\u0635/P.md"), fm("contexts:", "  - ai-community", "consent_on: 2026-10-01") + note("")))
    ok("CLUB-no-consent silent on a non-club person", "CLUB-no-consent" not in club(_U(r"02-Areas/\u0627\u0644\u0623\u0634\u062e\u0627\u0635/P.md"), fm("contexts:", "  - contest/x-1") + note("")))
    ok("CLUB-context reads the guide dictionary", club_rules_dict := club_rules.dictionary(), "guide table missing")
    good = fm("contexts:", "  - exampleschool-cohort-7", "  - contest/x-1", "  - exampleclub-tech/activities")
    ok("CLUB-context silent on dictionary values", "CLUB-context" not in club("N.md", good + note("")), club("N.md", good + note("")))
    ok("CLUB-context fires on an unknown value", "CLUB-context" in club("N.md", fm("contexts:", "  - exampleclub") + note("")))
    ok("CLUB-context fires on a reserved value", "CLUB-context" in club("N.md", fm("contexts:", "  - ai-community/ai") + note("")))
    ok("CLUB-context fires on an event with empty contexts", "CLUB-context" in club("01-Projects/E.md", fm("tags:", "  - exampleclub-event", "contexts: []") + note("")))
    ok("CLUB rules skip Templates/", not club("Templates/Club-Event.md", fm("tags:", "  - exampleclub-event", "contexts: []", "attendance: 0") + note("")))
    for bad in ("attendance: 0", "attendance: \"20\"", "attendance: true", "attendance: 12.5"):
        ok(f"CLUB-attendance fires on {bad}", "CLUB-attendance" in club("N.md", fm(bad) + note("")), club("N.md", fm(bad) + note("")))
    ok("CLUB-attendance silent on 20", "CLUB-attendance" not in club("N.md", fm("attendance: 20") + note("")))
    ok("CLUB-attendance fires on an inline estimate", "CLUB-attendance" in club("N.md", note(_U(r"- 2026-10-06 \u2014 \u062c\u0644\u0633\u0629 [attendance:: ~15]\n"))))
    ok("CLUB-attendance silent on an inline count", "CLUB-attendance" not in club("N.md", note(_U(r"- 2026-10-06 \u2014 \u062c\u0644\u0633\u0629 [attendance:: 12]\n"))))
    ok("CLUB-role reads the guide role card", club_rules.role_values(), "role card missing")
    P = _U(r"02-Areas/\u0627\u0644\u0623\u0634\u062e\u0627\u0635/P.md")
    CP = ("contexts:", "  - exampleclub-tech/pr", "consent_on: 2026-10-01")
    ok("CLUB-role fires on a value outside the card", "CLUB-role" in club(P, fm(*CP, "role:", _U(r"  - \u0631\u0626\u064a\u0633 \u0642\u0633\u0645 Sales")) + note("")), club(P, fm(*CP, "role:", _U(r"  - \u0631\u0626\u064a\u0633 \u0642\u0633\u0645 Sales")) + note("")))
    ok("CLUB-role fires on the old co-president title", "CLUB-role" in club(P, fm(*CP, "role:", _U(r"  - \u0631\u0626\u064a\u0633 \u0645\u0634\u0627\u0631\u0643")) + note("")))
    ok("CLUB-role silent on card values", "CLUB-role" not in club(P, fm(*CP, "role:", _U(r"  - \u0639\u0636\u0648 \u0642\u0633\u0645 Public Relations"), _U(r"  - \u0645\u0633\u062a\u0634\u0627\u0631\u0629 Marketing"), _U(r"  - \u0627\u0644\u0645\u0646\u062a\u0648\u0631\u0629 (Mentor \u00b7 Senior Lead)")) + note("")))
    ok("CLUB-role silent on a listed role outside the structure", "CLUB-role" not in club(P, fm(*CP, "role:", _U(r"  - \u0645\u0635\u0645\u0645\u0629")) + note("")))
    ok("CLUB-role silent on a non-club person", "CLUB-role" not in club(P, fm("contexts:", "  - contest/x-1", "role:", _U(r"  - \u0631\u0626\u064a\u0633 \u0642\u0633\u0645 Sales")) + note("")))
    ok("CLUB-role silent outside the people folder", "CLUB-role" not in club("N.md", fm(*CP, "role:", _U(r"  - \u0631\u0626\u064a\u0633 \u0642\u0633\u0645 Sales")) + note("")))

    # AD03 X05: stage-2 club rules, all warn; the day and the pause are pinned so the results do not drift
    from datetime import date as _day
    from _vaultlib import Pause as _Pause
    cr = club_rules
    cr.TODAY, cr._PAUSE = _day(2026, 10, 14), None
    E = "01-Projects/E.md"


    def ev(*extra, body=""):
        return fm(*EV, "status: active", *extra) + note(body)


    def logi(asked=None, ann=None, risk=True):
        rows = ([_U(r"- \u0627\u0644\u0625\u0630\u0646:: ") + f"{asked}"] if asked is not None else []) + ([_U(r"- \u0627\u0644\u0625\u0639\u0644\u0627\u0646:: ") + f"{ann}"] if ann is not None else [])
        return _U(r"## \u0627\u0644\u0644\u0648\u062c\u0633\u062a\u064a\u0627\u062a\n\n") + "\n".join(rows) + "\n" + (_U(r"\n## \u0627\u0644\u062e\u0637\u0631\n\n- **\u0627\u0644\u0645\u064a\u0632\u0627\u0646\u064a\u0629:** \u0635\u0641\u0631\n") if risk else "")


    ok("CLUB-announce-early fires: announced before the request", "CLUB-announce-early" in club(E, ev(body=logi("2026-10-05", "2026-10-01"))), club(E, ev(body=logi("2026-10-05", "2026-10-01"))))
    ok("CLUB-announce-early fires: announced with no request sent", "CLUB-announce-early" in club(E, ev(body=logi("", "2026-10-01"))))
    ok("CLUB-announce-early silent: announced after the request", "CLUB-announce-early" not in club(E, ev(body=logi("2026-09-01", "2026-09-05"))))
    ok("CLUB-announce-early silent: no guest line", "CLUB-announce-early" not in club(E, ev(body=logi(None, "2026-10-01"))))
    ok("CLUB-guest-lead fires: request 10 days before the date", "CLUB-guest-lead" in club(E, ev("date: 2026-11-10", body=logi("2026-10-31"))), club(E, ev("date: 2026-11-10", body=logi("2026-10-31"))))
    ok("CLUB-guest-lead silent: request 21 days before", "CLUB-guest-lead" not in club(E, ev("date: 2026-11-21", body=logi("2026-10-31"))))
    ok("CLUB-guest-lead fires: no request and the date is 10 days away", "CLUB-guest-lead" in club(E, ev("date: 2026-10-24", body=logi(""))))
    ok("CLUB-guest-lead silent: no request but the date is 30 days away", "CLUB-guest-lead" not in club(E, ev("date: 2026-11-13", body=logi(""))))
    ok("CLUB-guest-lead silent: no guest line", "CLUB-guest-lead" not in club(E, ev("date: 2026-10-24", body=logi(None, ""))))
    ok(_U(r"CLUB-no-risk fires: guest event without \u00ab\u0627\u0644\u062e\u0637\u0631\u00bb"), "CLUB-no-risk" in club(E, ev(body=logi("", None, risk=False))), club(E, ev(body=logi("", None, risk=False))))
    ok(_U(r"CLUB-no-risk fires: announced event without \u00ab\u0627\u0644\u062e\u0637\u0631\u00bb"), "CLUB-no-risk" in club(E, ev(body=logi(None, "2026-10-01", risk=False))))
    ok(_U(r"CLUB-no-risk silent: guest event with \u00ab\u0627\u0644\u062e\u0637\u0631\u00bb"), "CLUB-no-risk" not in club(E, ev(body=logi("", None))))
    ok("CLUB-no-risk silent: small session, no guest, not announced", "CLUB-no-risk" not in club(E, ev(body=logi(None, "", risk=False))))
    ok("CLUB-no-risk silent on the template", "CLUB-no-risk" not in club("Templates/Club-Event.md", ev(body=logi("", "", risk=False))))
    ok("CLUB-no-aar (widened) fires: date 8 days ago, not done", "CLUB-no-aar" in club(E, ev("date: 2026-10-06")), club(E, ev("date: 2026-10-06")))
    ok("CLUB-no-aar (widened) silent: date 7 days ago", "CLUB-no-aar" not in club(E, ev("date: 2026-10-07")))
    ok(_U(r"CLUB-no-aar (widened) silent on a series with \u00ab\u0633\u062c\u0644 \u0627\u0644\u062c\u0644\u0633\u0627\u062a\u00bb"), "CLUB-no-aar" not in club(E, ev("date: 2026-09-01", body=_U(r"## \u0633\u062c\u0644 \u0627\u0644\u062c\u0644\u0633\u0627\u062a\n"))))
    ok("stage-2 rules skip 04-Archive/", not {"CLUB-no-aar", "CLUB-no-risk", "CLUB-guest-lead"} & set(club("04-Archive/E.md", ev("date: 2026-09-01", body=logi("", "2026-09-01", risk=False)))))
    ok("CLUB-date-line fires on a non-date value", "CLUB-date-line" in club(E, ev(body=logi(_U(r"\u0642\u0631\u064a\u0628")))), club(E, ev(body=logi(_U(r"\u0642\u0631\u064a\u0628")))))
    ok("CLUB-date-line silent on an empty value", "CLUB-date-line" not in club(E, ev(body=logi("", ""))))
    ok("date lines inside code are not read", not {"CLUB-announce-early", "CLUB-no-risk"} & set(club(E, ev(body=_U(r"```\n- \u0627\u0644\u0625\u0630\u0646:: \n- \u0627\u0644\u0625\u0639\u0644\u0627\u0646:: 2026-10-01\n```\n")))))
    cr._PAUSE = _Pause(_day(2026, 10, 1), _day(2026, 10, 31))
    ok("pause: CLUB-no-aar window frozen (paused days do not count)", "CLUB-no-aar" not in club(E, ev("date: 2026-09-28")), club(E, ev("date: 2026-09-28")))
    ok("pause: CLUB-no-aar still fires on days before the pause", "CLUB-no-aar" in club(E, ev("date: 2026-09-20")))
    ok("pause: CLUB-guest-lead countdown frozen", "CLUB-guest-lead" not in club(E, ev("date: 2026-10-24", body=logi(""))))
    ok("pause: fixed request-to-date gap still checked", "CLUB-guest-lead" in club(E, ev("date: 2026-11-10", body=logi("2026-10-31"))))
    ok("active_days subtracts the paused days", cr.active_days(_day(2026, 9, 28), _day(2026, 11, 2), cr._PAUSE) == 4, cr.active_days(_day(2026, 9, 28), _day(2026, 11, 2), cr._PAUSE))
    cr._PAUSE = None
    IDEA = ("tags:", "  - exampleclub-idea", "idea_stage: ready", "contexts:", "  - exampleclub-tech")
    FULL = _U(r"## \u0645\u062a\u0637\u0644\u0628\u0627\u062a \u0627\u0644\u062a\u0646\u0641\u064a\u0630\n\n- **\u0635\u0627\u062d\u0628:** \u0633\u0639\u0648\u062f\n- **\u0625\u0630\u0646:** \u0645\u0627 \u064a\u062d\u062a\u0627\u062c\n- **\u062a\u0643\u0644\u0641\u0629:** \u0635\u0641\u0631\n- **\u0645\u0648\u0639\u062f:** \u0627\u0644\u0623\u0633\u0628\u0648\u0639 \u0627\u0644\u062c\u0627\u064a\n- **\u0641\u0631\u0636\u064a\u0629:** \u0646\u062a\u0648\u0642\u0639 \u0625\u0646 \u0662\u0660 \u064a\u062d\u0636\u0631\u0648\u0646\n")
    ok("CLUB-ready-unmet silent with all five lines", "CLUB-ready-unmet" not in club("B/I.md", fm(*IDEA) + note(FULL)), club("B/I.md", fm(*IDEA) + note(FULL)))
    ok("CLUB-ready-unmet fires when a line is missing", "CLUB-ready-unmet" in club("B/I.md", fm(*IDEA) + note(FULL.replace(_U(r"- **\u0645\u0648\u0639\u062f:** \u0627\u0644\u0623\u0633\u0628\u0648\u0639 \u0627\u0644\u062c\u0627\u064a\n"), ""))))
    ok("CLUB-ready-unmet fires when a line is empty", "CLUB-ready-unmet" in club("B/I.md", fm(*IDEA) + note(FULL.replace(_U(r"\u0627\u0644\u0623\u0633\u0628\u0648\u0639 \u0627\u0644\u062c\u0627\u064a"), ""))))
    ok("CLUB-ready-unmet silent on a seed", "CLUB-ready-unmet" not in club("B/I.md", fm(*IDEA[:2], "idea_stage: seed") + note("")))
    cr.TODAY, cr._PAUSE = None, cr._UNSET


# AD02 D10 (K16): a key written twice in one mapping
dup = audit.yaml_dup_keys("keys:\n  scope: {type: string}\n  other: 1\n  scope: {type: list}\nlist: [a, a]\n")
ok("FM-schema-dupkey finds the repeated key with both lines", dup == [(4, "scope", 2)], dup)
ok("FM-schema-dupkey: repeated list items are not keys", audit.yaml_dup_keys("a: [x, x]\nb:\n  - y\n  - y\n") == [])
ok("FM-schema-dupkey: the real schema has none", audit.yaml_dup_keys((VAULT / audit.SCHEMA_FILE).read_text(encoding="utf-8")) == [],
   audit.yaml_dup_keys((VAULT / audit.SCHEMA_FILE).read_text(encoding="utf-8")))

# T-20b, W13: the error registry kinds (tool, design, process, build); only tool needs `tools`
TRAP = "AI-Agent/traps/TR-9001.md"


def trap_rules(kind=None, tools=True):
    k = f"kind: {kind}\n" if kind else ""
    t = "" if not tools else "tools:\n  - exec_python\n"
    text = f"---\nid: TR-9001\n{k}{t}rule: x\nstatus: active\nsuperseded_by: \"\"\n---\n- body\n"
    caps = "`exec_python`"
    texts, docs = {TRAP: text, audit.CAPS: caps}, {TRAP: parse(text), audit.CAPS: parse(caps)}
    return sorted({f[1] for f in audit.registry_findings(texts, docs, {TRAP}, "AI-Agent/traps/")})


ok("RG-kind: build is a known trap kind", "RG-kind" not in trap_rules("build", tools=False), trap_rules("build", tools=False))
ok("RG-kind: design and process stay known", all("RG-kind" not in trap_rules(k, tools=False) for k in ("design", "process")))
ok("RG-kind: an unknown kind warns", "RG-kind" in trap_rules("habit", tools=False), trap_rules("habit", tools=False))
ok("RG-kind: no kind means tool", "RG-kind" not in trap_rules(None))
ok("RG-tools: a build error needs no tools", "RG-tools" not in trap_rules("build", tools=False))
ok("RG-tools: a tool error without tools is refused", "RG-tools" in trap_rules("tool", tools=False), trap_rules("tool", tools=False))

failed = [x for x in R if not x[1]]


# --- katex check (TR-0022, AD08-C2-02) ---
import audit as _A
_orig_read = _A.read
_texts = []
_A.read = lambda p: _texts[0]

def katex_of(text):
    _texts.clear(); _texts.append(text)
    return _A.katex_findings(["x.md"], {"x.md": None}, None)

ok("katex: bare dollar caught", katex_of("this costs $5 today") != [])
ok("katex: math span passes", katex_of("Euler said $x = 1$ nicely") == [])
ok("katex: block math passes", katex_of("$$\ne = mc^2\n$$") == [])
ok("katex: escaped dollar passes", katex_of("price is \\$5 only") == [])
ok("katex: dollar in inline code passes", katex_of("run `grep $HOME` now") == [])
ok("katex: dollar in fence passes", katex_of("```bash\necho $HOME\n```") == [])
_A.read = _orig_read

# --- T-02b: profile gating, lazy rule imports, genesis HEAD, overlay skip ---
import os as _os
import shutil as _shutil
import sqlite3 as _sq
import subprocess as _sp
import sys as _sys
import tempfile as _tf
from pathlib import Path as _P

_REAL = _A.VAULT


def _tmp_vault(profile_text, notes):
    root = _P(_tf.mkdtemp(prefix="audit-profile-"))
    (root / "AI-Agent" / "schema").mkdir(parents=True)
    (root / "AI-Agent" / "config").mkdir()
    _shutil.copy(_REAL / "AI-Agent" / "gate_baseline.json", root / "AI-Agent" / "gate_baseline.json")
    _shutil.copy(_REAL / "AI-Agent" / "schema" / "frontmatter.yaml", root / "AI-Agent" / "schema" / "frontmatter.yaml")
    if profile_text is not None:
        (root / "AI-Agent" / "config" / "release_profile.yaml").write_text(profile_text, encoding="utf-8")
    for name, body in notes.items():
        f = root / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
    return root


def _run_audit(root, *args):
    env = dict(_os.environ, VAULT=str(root))
    r = _sp.run([_sys.executable, str(_P(_A.__file__)), "--no-cache", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=120)
    return r.stdout + r.stderr


_PROF = "mode: vault\nlanguage: ar\nowner:\n  name: X\n  aliases: []\nheadings:\n  next_steps: []\n  progress_log: []\n"
_PROF += "checks:\n  disabled: %s\npaths:\n  live_doc: ''\n  system_homes: []\n  collector_exclude_prefixes: []\nmarkdown:\n  md024_siblings_only_files: []\n"
_DUP = "# T\n\n## same\n\nx\n\n## same\n\ny\n"
_roots = []
try:
    r0 = _tmp_vault(_PROF % "[]", {"n.md": _DUP}); _roots.append(r0)
    out0 = _run_audit(r0, "--check", "headings", "--min", "info")
    ok("T-02b: dup heading fires with no disabled checks", "R1-dup" in out0, out0[-300:])
    r1 = _tmp_vault(_PROF % "[headings]", {"n.md": _DUP}); _roots.append(r1)
    out1 = _run_audit(r1, "--check", "headings,schema", "--min", "info")
    ok("T-02b: profile disables headings", "R1-dup" not in out1 and "AUDIT" in out1, out1[-300:])
    r2 = _tmp_vault(_PROF % "[secrets]", {"n.md": _DUP}); _roots.append(r2)
    out2 = _run_audit(r2, "--check", "headings,schema,secrets", "--min", "info")
    ok("T-02b: untouchable check stays active and profile is reported invalid",
       "PROFILE-invalid" in out2 and "secrets" in next((l for l in out2.splitlines() if l.startswith("AUDIT")), ""), out2[-400:])
    r3 = _tmp_vault(_PROF % "[]", {"AI-Agent/release-overlay/o.md": _DUP, "n.md": "# T\n\n## a\n"}); _roots.append(r3)
    out3 = _run_audit(r3, "--check", "headings", "--min", "info")
    ok("T-02b: release-overlay notes are skipped", "release-overlay" not in out3 and "R1-dup" not in out3, out3[-300:])
    _probe = _sp.run([_sys.executable, "-c",
                      "import sys; sys.path.insert(0, %r); import audit; print(sorted(m for m in ('arch_rules', 'club_rules') if m in sys.modules))" % str(_P(_A.__file__).parent)],
                     capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(_os.environ, VAULT=str(_REAL)))
    ok("T-02b: arch_rules/club_rules not imported at module load", _probe.stdout.strip() == "[]", _probe.stdout + _probe.stderr)
finally:
    for _r in _roots:
        _shutil.rmtree(_r, ignore_errors=True)

# T-02d: operations.md ceiling replaces the drift rule when limits.operations_md_max_tokens is set
_roots2 = []
try:
    _big = "word " * 3000
    def _ops_vault(ceiling):
        v = _tmp_vault(_PROF % "[]" + f"limits:\n  read_cap_bytes: 0\n  operations_md_max_tokens: {ceiling}\n",
                       {"AI-Agent/operations.md": _big, "AI-Agent/rules.md": "r\n", "AI-Agent/handoff.md": "h\n"})
        _shutil.copy(_REAL / "AI-Agent" / "g06_baseline.json", v / "AI-Agent" / "g06_baseline.json")
        _roots2.append(v)
        return _run_audit(v, "--check", "g06", "--min", "info")
    o_off = _ops_vault(0)
    ok("T-02d: ceiling off keeps the drift rule on operations.md", "G06-tokens-loaded" in o_off and "G06-ops-ceiling" not in o_off, o_off[-300:])
    o_low = _ops_vault(100)
    ok("T-02d: over the ceiling warns G06-ops-ceiling and skips the drift rule",
       "G06-ops-ceiling" in o_low and not [l for l in o_low.splitlines() if "G06-tokens-loaded" in l and "operations_md_tokens" in l], o_low[-300:])
    o_hi = _ops_vault(25000)
    ok("T-02d: under the ceiling is silent", "G06-ops-ceiling" not in o_hi and not [l for l in o_hi.splitlines() if "G06-tokens-loaded" in l and "operations_md_tokens" in l], o_hi[-300:])
finally:
    for _r in _roots2:
        _shutil.rmtree(_r, ignore_errors=True)

# T-02d: owner and people folder come from the profile
aok("T-02d: owner recognised by Arabic name", _A.is_vault_owner(_U(r"\u0633\u0639\u0648\u062f \u0627\u0644\u062d\u0645\u0627\u062f\u064a")))
_latin = [x for x in _A.load_profile(_A.VAULT)["owner"]["aliases"] if x.isascii()]
aok("T-02d: owner recognised by Latin alias, any case", bool(_latin) and all(_A.is_vault_owner(x.lower()) and _A.is_vault_owner(x.upper() + " (lead)") for x in _latin))
ok("T-02d: a stranger is not the owner", not _A.is_vault_owner(_U(r"[[\u0644\u064a\u0644\u0649-\u0627\u0644\u063a\u0627\u0645\u062f\u064a]]")) and not _A.is_vault_owner("Layla"))
ok("T-02d: people_dir default", _A.people_dir() == _A.locale_value("PEOPLE_DIR", "02-Areas/People"), _A.people_dir())
_rv = _tmp_vault(_PROF.replace("name: X\n  aliases: []", "name: Rhea Stone\n  aliases: [R. Stone]") % "[]"
                 + "limits:\n  read_cap_bytes: 0\n  operations_md_max_tokens: 0\n", {})
_old_v = _A.VAULT
try:
    _A.VAULT = _rv
    ok("T-02d: profile owner replaces the built-in names",
       _A.is_vault_owner("rhea stone") and _A.is_vault_owner("R. Stone") and not _A.is_vault_owner(_U(r"\u0633\u0639\u0648\u062f \u0627\u0644\u062d\u0645\u0627\u062f\u064a")))
    ok("T-02d: people_dir falls back when the profile leaves it empty", _A.people_dir() == _A.locale_value("PEOPLE_DIR", "02-Areas/People"))
    (_rv / "AI-Agent" / "config" / "release_profile.yaml").write_text(
        (_rv / "AI-Agent" / "config" / "release_profile.yaml").read_text(encoding="utf-8").replace("paths:\n", "paths:\n  people_dir: 02-Areas/People/\n"), encoding="utf-8")
    _A._PROFILE_CACHE.clear()
    ok("T-02d: people_dir from the profile, trailing slash trimmed", _A.people_dir() == "02-Areas/People", _A.people_dir())
finally:
    _A.VAULT = _old_v
    _A._PROFILE_CACHE.clear()
    _shutil.rmtree(_rv, ignore_errors=True)

# genesis repo: no HEAD yet -> gatehash must not fail-closed on the committed-ledger comparison
# A git hook runs with GIT_DIR / GIT_INDEX_FILE (and friends) set; a child git in a temp repo must not inherit them
# (it failed under the pre-commit hook of a linked worktree). Scrub them for the rest of this run.
from _vaultlib import scrub_git_env as _scrub_git_env
_scrub_git_env()
_g = _P(_tf.mkdtemp(prefix="audit-genesis-"))
try:
    _sp.run(["git", "-C", str(_g), "init", "-q"], check=True)
    _led = _g / "ledger.sqlite3"
    _c = _sq.connect(str(_led)); _c.execute("CREATE TABLE decisions (id INTEGER PRIMARY KEY, body TEXT)"); _c.commit(); _c.close()
    _A.VAULT = _g
    gen = _A.gatehash_findings({}, _led, "ledger.sqlite3", _A.git_bytes)
    ok("T-02b: genesis HEAD gives no gatehash-no-ledger", not [f for f in gen if f[1] == "gatehash-no-ledger"], gen)
    _sp.run(["git", "-C", str(_g), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    withhead = _A.gatehash_findings({}, _led, "ledger.sqlite3", _A.git_bytes)
    ok("T-02b: with HEAD but untracked ledger still fails closed", [f for f in withhead if f[1] == "gatehash-no-ledger"], withhead)
finally:
    _A.VAULT = _REAL
    _shutil.rmtree(_g, ignore_errors=True)

# T-02 gate: a vault without AI-Agent/operations.md must not crash the full audit (release ships no ops log)
_rn = _tmp_vault(_PROF % "[]", {"n.md": "# T\n\n## a\n"})
try:
    _on = _run_audit(_rn, "--ratchet")
    ok("T-02gate: no operations.md -> no traceback, gate verdict printed", "Traceback" not in _on and "GATE " in _on, _on[-400:])
finally:
    _shutil.rmtree(_rn, ignore_errors=True)

# T-04b: consumer_drift in a release has no progress note; the profile decides which counters are required
_MAP = "---\nstatus: active\ntags: [x]\ncreated: 2026-11-12\n---\ncounters:\n  skills: 1\n  tools: 1\n"
_rv = _tmp_vault(_PROF.replace("mode: vault", "mode: release") % "[]", {"AI-Agent/schema/consumer-map.yaml": _MAP, "AI-Agent/skills/s/SKILL.md": "---\nname: s\ndescription: d\n---\n# S\n", "AI-Agent/scripts/t.py": "x = 1\n"})
_vv = _tmp_vault(_PROF % "[]", {"AI-Agent/schema/consumer-map.yaml": _MAP, "AI-Agent/skills/s/SKILL.md": "---\nname: s\ndescription: d\n---\n# S\n", "AI-Agent/scripts/t.py": "x = 1\n"})
try:
    _o = _run_audit(_rv, "--check", "consumer_drift", "--min", "info")
    ok("T-04b: release mode needs no progress note for consumer_drift", "CDRIFT" not in _o and "Traceback" not in _o, _o[-300:])
    _o = _run_audit(_vv, "--check", "consumer_drift", "--min", "info")
    ok("T-04b: vault mode still requires the progress counter (map or note missing is reported)", "CDRIFT" in _o, _o[-300:])
    (_rv / "AI-Agent" / "scripts" / "u.py").write_text("x = 2\n", encoding="utf-8")
    _o = _run_audit(_rv, "--check", "consumer_drift", "--min", "info")
    ok("T-04b: release mode still catches a tool-count drift", "CDRIFT-drift" in _o and "tools" in _o, _o[-300:])
finally:
    _shutil.rmtree(_rv, ignore_errors=True)
    _shutil.rmtree(_vv, ignore_errors=True)

# T-05a: markdown.md024_siblings_only_files is read (it was defined in the profile but never applied)
_CHG = "# Changelog\n\n## [1.1.0]\n\n### Added\n- a\n\n## [1.0.0]\n\n### Added\n- b\n"
_SIB = _PROF.replace("markdown:\n  md024_siblings_only_files: []\n", "markdown:\n  md024_siblings_only_files: ['CHANGELOG.md']\n")
_rs1, _rs2 = _tmp_vault(_SIB % "[]", {"CHANGELOG.md": _CHG, "other.md": _CHG}), _tmp_vault(_PROF % "[]", {"CHANGELOG.md": _CHG})
_rs3 = _tmp_vault(_SIB % "[]", {"CHANGELOG.md": "# Changelog\n\n## [1.0.0]\n\n### Added\n- a\n\n### Added\n- b\n"})
try:
    _o1 = _run_audit(_rs1, "--check", "headings", "--min", "info")
    ok("T-05a: a listed file may repeat a heading under different parents", "R1-dup\tCHANGELOG.md" not in _o1, _o1[-300:])
    ok("T-05a: an unlisted file with the same repeats is still R1-dup", "R1-dup" in _o1 and "other.md" in _o1, _o1[-300:])
    ok("T-05a: without the profile key the changelog repeats are R1-dup", "R1-dup" in _run_audit(_rs2, "--check", "headings", "--min", "info"))
    ok("T-05a: true siblings with the same title are still R1-dup in a listed file", "R1-dup" in _run_audit(_rs3, "--check", "headings", "--min", "info"))
finally:
    for _r in (_rs1, _rs2, _rs3):
        _shutil.rmtree(_r, ignore_errors=True)

# T-05: the secrets check scans hidden text everywhere and, in a release, every note; the mother vault keeps the narrow scope
_ghp = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
_hi = "Zx9Qp" + "L2mVb" + "7TnR4" + "sKc8W" + "dE1yU" + "h5Jg3Aa"
_NOTE = "---\ntags: [x]\ncreated: 2026-11-01\narea: '[[n]]'\n---\n# T\n\nleak " + _ghp + "\n\nAPI_KEY = " + _hi + "\n"
_BIDI = "---\ntags: [x]\ncreated: 2026-11-01\narea: '[[n]]'\n---\n# T\n\nhidden \u202e text\n"
_sv = _tmp_vault(_PROF % "[]", {"03-Resources/r.md": _NOTE, "03-Resources/b.md": _BIDI, "AI-Agent/handoff.md": "---\ntags: [x]\ncreated: 2026-11-01\n---\n# H\n\n" + _ghp + "\n"})
_sr = _tmp_vault(_PROF.replace("mode: vault", "mode: release") % "[]", {"03-Resources/r.md": _NOTE, "03-Resources/b.md": _BIDI})
try:
    _ov = _run_audit(_sv, "--check", "secrets", "--min", "info")
    # AD13 D7 changed this policy (decided at Gate 2): a credential shape is an error in every note, entropy stays narrow
    ok("T-05: vault mode flags a credential shape in a research note (AD13 D7) but not entropy",
       "SECRET-leak-2\t03-Resources/r.md" in _ov.replace(" ", "\t") or ("SECRET-leak-2" in _ov and "03-Resources/r.md" in _ov), _ov[-400:])
    ok("T-05: vault mode does not report entropy for a research note", "SECRET-entropy" not in _ov, _ov[-400:])
    ok("T-05: vault mode still scans an instruction-path file", "SECRET-leak-2" in _ov and "handoff.md" in _ov, _ov[-400:])
    ok("T-05: hidden bidirectional text is an error in any mode", "BIDI-control" in _ov and "03-Resources/b.md" in _ov, _ov[-400:])
    _orr = _run_audit(_sr, "--check", "secrets", "--min", "info")
    ok("T-05: release mode scans every note: credential shape and entropy are errors", "SECRET-leak-2" in _orr and "SECRET-entropy" in _orr and "03-Resources/r.md" in _orr, _orr[-400:])
    ok("T-05: release mode also reports the bidi note", "BIDI-control" in _orr, _orr[-300:])
    ok("T-05: a leak blocks the gate (exit 1 under --ratchet)", _sp.run([_sys.executable, str(_P(_A.__file__)), "--no-cache", "--ratchet", "--check", "secrets"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(_os.environ, VAULT=str(_sr)), timeout=120).returncode == 1)
    # AD13 D7: placeholder-aware wide scope, non-note files, people-folder warnings
    _fk = "sk" + "_live" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
    _ph = "sk" + "_live" + "_" + "x" * 24
    _hdr = "---\ntags: [x]\ncreated: 2026-11-01\narea: '[[n]]'\n---\n# T\n\n"
    _PEOPLE = _A.locale_value("PEOPLE_DIR", "02-Areas/People") + "/p.md"   # the folder of this tree: Arabic in the mother, English in a release
    _iban = "SA" + "03" + "8000" + "0000" + "6080" + "1016" + "7519"
    _d7 = _tmp_vault(_PROF % "[]", {"03-Resources/live.md": _hdr + "key " + _fk + "\n", "03-Resources/doc.md": _hdr + "key " + _ph + "\n",
                                    "AI-Agent/cfg.json": '{"k": "' + _fk + '"}\n', "AI-Agent/state/run.json": '{"k": "' + _fk + '"}\n',
                                    "AI-Agent/scripts/ok.py": 'KEY = "' + _ph + '"\n', "AI-Agent/big.json": '{"k": "' + _fk + '"}' + " " * 1_100_000,
                                    _PEOPLE: _hdr + "iban " + _iban + "\nmobile 0512345678\nid number 1234567890\n",
                                    "03-Resources/notpeople.md": _hdr + "iban " + _iban + "\n"})
    try:
        _o7 = _run_audit(_d7, "--check", "secrets", "--min", "info")
        _leaks = [l for l in _o7.splitlines() if "SECRET-leak" in l]
        ok("T-d7a: a credential shape in a note is an error, a placeholder in a note is not",
           any("03-Resources/live.md" in l for l in _leaks) and not any("doc.md" in l for l in _leaks), _o7[-500:])
        ok("T-d7b: a credential shape in a config file is an error; run data, a placeholder in a script and a file over 1 MB are not",
           any("AI-Agent/cfg.json" in l for l in _leaks) and not any(x in l for l in _leaks for x in ("state/run.json", "scripts/ok.py", "big.json")), _o7[-500:])
        ok("T-d7c: the finding never prints the value", _fk[:20] not in _o7, _o7[-300:])
        ok("T-d7d: the people folder warns about IBAN, mobile and a named identity number",
           all(any(k in l and "\twarn\t" in l.replace(" ", "\t") or (k in l and "warn" in l) for l in _o7.splitlines()) for k in ("PII-iban", "PII-mobile", "PII-national-id")), _o7[-600:])
        ok("T-d7e: personal-data shapes outside the people folder are not reported", "notpeople.md" not in "\n".join(l for l in _o7.splitlines() if "PII" in l), _o7[-400:])
        # a git repository: an ignored local file is never scanned, a tracked one is
        import subprocess as _sp2
        _g = _tmp_vault(_PROF % "[]", {"cfg.json": '{"k": "' + _fk + '"}\n', "local.json": '{"k": "' + _fk + '"}\n', ".gitignore": "local.json\n"})
        try:
            _sp2.run(["git", "init", "-q"], cwd=_g, check=True)
            _og = _run_audit(_g, "--check", "secrets", "--min", "info")
            ok("T-d7f: with a repository, an ignored file is skipped and an unignored one is scanned", "cfg.json" in _og and "local.json" not in _og, _og[-400:])
        finally:
            _shutil.rmtree(_g, ignore_errors=True)
        _only_pii = _tmp_vault(_PROF % "[]", {_PEOPLE: _hdr + "iban " + _iban + "\n"})
        try:
            ok("T-d7g: a personal-data warning does not block the gate", _sp.run([_sys.executable, str(_P(_A.__file__)), "--no-cache", "--ratchet", "--check", "secrets"], capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(_os.environ, VAULT=str(_only_pii)), timeout=120).returncode == 0)
        finally:
            _shutil.rmtree(_only_pii, ignore_errors=True)
        # D7 retrofit: shapes adapted from gitleaks reach notes and non-note files, with exclusions
        _npm = "npm" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        _ghp2 = "gh" + "p_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
        _fill = "filler " * 30000
        _d7b = _tmp_vault(_PROF % "[]", {"03-Resources/npm.md": _hdr + "token " + _npm + "\n", "AI-Agent/schema/secret-shapes.json": '{"x": "' + _npm + '"}\n',
                                         ".obsidian/plugins/x/main.js": 'var t = "' + _npm + '";\n', "AI-Agent/cfg.js": 'var t = "' + _npm + '";\n',
                                         "AI-Agent/bignpm.js": 'var t = "' + _npm + '";\n' + _fill, "AI-Agent/bigghp.js": 'var t = "' + _ghp2 + '";\n' + _fill})
        try:
            _ob = [l for l in _run_audit(_d7b, "--check", "secrets", "--min", "info").splitlines() if "SECRET-leak" in l]
            ok("T-d7h: an adapted shape in a note is an error named by its gitleaks rule", any("SECRET-leak-gl-npm-access-token" in l and "npm.md" in l for l in _ob), _ob)
            ok("T-d7i: an adapted shape in a script is an error", any("AI-Agent/cfg.js" in l for l in _ob), _ob)
            ok("T-d7j: the shapes file and third-party plugin code are not scanned", not any(x in l for l in _ob for x in ("secret-shapes.json", ".obsidian")), _ob)
            ok("T-d7k: over the size cap only the built-in shapes run", any("bigghp.js" in l and "SECRET-leak-2" in l for l in _ob) and not any("bignpm.js" in l for l in _ob), _ob)
        finally:
            _shutil.rmtree(_d7b, ignore_errors=True)
        # E7 prior-art retrofit: string-literal dynamic imports are judged by the ADR-006 policy too
        _dv = _tmp_vault(_PROF % "[]", {"AI-Agent/scripts/dyn_bad.py": "import importlib\nm = importlib.import_module('requests')\n",
                                        "AI-Agent/scripts/dyn_ok.py": "import importlib\nm = importlib.import_module('json')\nn = __import__('os')\n",
                                        "AI-Agent/scripts/dyn_computed.py": "import importlib\nname = 'req' + 'uests'\nm = importlib.import_module(name)\n",
                                        "AI-Agent/scripts/dyn_static.py": "import requests\n"})
        try:
            _ov2 = [l for l in _run_audit(_dv, "--check", "adr", "--min", "info").splitlines() if "ADR-006-imports" in l]
            ok("T-e7a: a string-literal dynamic import of an unapproved module is an ADR-006 error", any("dyn_bad.py" in l and "requests" in l for l in _ov2), _ov2)
            ok("T-e7b: allowed or computed dynamic imports are not findings", not any(x in l for l in _ov2 for x in ("dyn_ok.py", "dyn_computed.py")), _ov2)
            ok("T-e7c: the static import is still found", any("dyn_static.py" in l for l in _ov2), _ov2)
            # a cache row written before the dynamic-import rule (a plain sha1, module set without `requests`) must not hide the finding
            import sqlite3 as _sq
            def _cached(*a):
                r = _sp.run([_sys.executable, str(_P(_A.__file__)), *a], capture_output=True, text=True, encoding="utf-8", errors="replace", env=dict(_os.environ, VAULT=str(_dv)), timeout=120)
                return r.stdout + r.stderr
            _cached("--check", "adr", "--min", "info")
            _dbp = _dv / "AI-Agent" / "state" / "vault-index.sqlite3"
            _stale_done = False
            if _dbp.exists():
                _c = _sq.connect(str(_dbp))
                try:
                    rows = _c.execute("SELECT path, sha1 FROM adr_py_cache").fetchall()
                    for p_, s_ in rows:
                        _c.execute("UPDATE adr_py_cache SET sha1 = ?, mods_json = ? WHERE path = ?", (s_.replace("+dyn", ""), '["importlib"]', p_))
                    _c.commit()
                    _stale_done = bool(rows)
                finally:
                    _c.close()
            _again = [l for l in _cached("--check", "adr", "--min", "info").splitlines() if "ADR-006-imports" in l]
            ok("T-e7d: a cache row from before the rule does not hide a dynamic import", _stale_done and any("dyn_bad.py" in l and "requests" in l for l in _again), (_stale_done, _again))
        finally:
            _shutil.rmtree(_dv, ignore_errors=True)
    finally:
        _shutil.rmtree(_d7, ignore_errors=True)
finally:
    _shutil.rmtree(_sv, ignore_errors=True)
    _shutil.rmtree(_sr, ignore_errors=True)

# --- AD13 E1: R19 (wikilink to a missing file) and R20 (backtick path that does not exist) ---
def finds(path, text, rule):
    ctx = audit.Ctx({"T.md": TARGET, path: text}, {"T.md": parse(TARGET), path: parse(text)})
    return [f for f in audit.findings_for(path, text, {"links"}, 4000, ctx) if f[1] == rule]


NOPE = "zzNoSuchNoteQ9"
ok("R19: a link to a missing note is flagged (warn)", [f[0] for f in finds("A.md", f"x [[{NOPE}]]\n", "R19-missing-note")] == ["warn"])
ok("R19: an existing note is not flagged", finds("A.md", "x [[T]]\n", "R19-missing-note") == [])
ok("R19: alias text does not matter, the target does", finds("A.md", "x [[T|label]]\n", "R19-missing-note") == []
   and len(finds("A.md", f"x [[{NOPE}|label]]\n", "R19-missing-note")) == 1)
ok("R19: fragment and block links check the note", finds("A.md", "x [[T#real]] [[T#^b1]]\n", "R19-missing-note") == []
   and len(finds("A.md", f"x [[{NOPE}#h]]\n", "R19-missing-note")) == 1)
ok("R19: a path form resolves by its file name, case-insensitively", finds("A.md", "x [[some/dir/t]] [[T.md]]\n", "R19-missing-note") == [])
ok("R19: an escaped pipe inside a table cell still names the note", len(finds("A.md", f"| a |\n|---|\n| [[{NOPE}\\|x]] |\n", "R19-missing-note")) == 1)
ok("R19: placeholders and empty targets are not flagged", finds("A.md", "x [[<% tp.file.title %>]] [[...]] [[{{name}}]]\n", "R19-missing-note") == [])
ok("R19: code spans and fenced code are not flagged", finds("A.md", f"`[[{NOPE}]]`\n\n```\n[[{NOPE}]]\n```\n", "R19-missing-note") == [])
ok("R19: templates, fixtures and raw research are skipped", all(finds(pth, f"x [[{NOPE}]]\n", "R19-missing-note") == []
   for pth in ("Templates/x.md", "AI-Agent/fixtures/x.md", "AI-Agent/handoff/research/x.md", "card-template/x.md")))
ok("R19: the archive is info, not warn", [f[0] for f in finds("04-Archive/x.md", f"x [[{NOPE}]]\n", "R19-missing-note")] == ["info"])
ok("R19: a missing image embed is flagged, the line number is right", [f[3] for f in finds("A.md", f"a\n\n![[{NOPE}.png]]\n", "R19-missing-note")] == [3])
aok("R19: the vault owner is never a missing note", finds("A.md", "x [[" + audit._profile_cached()["owner"]["name"] + "]]\n", "R19-missing-note") == [])
GONE = "01-Projects/zzNoSuchFolderQ9/gone.md"
ok("R20: a missing backtick path is flagged (info)", [f[0] for f in finds("A.md", f"see `{GONE}`\n", "R20-missing-path")] == ["info"])
ok("R20: an existing path, with a line suffix or a closing period, is not flagged",
   finds("A.md", "see `AI-Agent/handoff.md:16` and `AI-Agent/handoff.md`.\n", "R20-missing-path") == [])
ok("R20: a marker word on the line exempts it", finds("A.md", f"planned: `{GONE}`\n", "R20-missing-path") == []
   and finds("A.md", f"`{GONE}` (renamed)\n", "R20-missing-path") == [])
ok("R20: fenced code, placeholders, ellipsis and generated folders are not flagged",
   finds("A.md", f"```\n`{GONE}`\n```\n`01-Projects/<name>/x.md` `01-Projects/a/*.md` `01-Projects/long\u2026` `AI-Agent/state/zz.json`\n", "R20-missing-path") == [])
ok("R20: archive and skill files are skipped", all(finds(pth, f"see `{GONE}`\n", "R20-missing-path") == [] for pth in ("04-Archive/x.md", "AI-Agent/skills/x/SKILL.md")))
ok("R20: only vault-folder paths count (a URL or a bare file name does not)", finds("A.md", "`https://x.org/a/b.md` `notes.md` `zzother/app.py`\n", "R20-missing-path") == [])
ok("R20: negative control, the same line without a marker fires", len(finds("A.md", f"see `{GONE}`\n", "R20-missing-path")) == 1)

# --- Fable review: a task line with an impossible due date must not crash the gate ---
_rd = _tmp_vault(_PROF % "[]", {"n.md": "# T\n\n- [ ] typo \U0001F4C5 2026-02-30\n- [ ] real \U0001F4C5 2020-01-01\n"})
try:
    _od = _run_audit(_rd, "--check", "due", "--min", "info")
    ok("due: an impossible date on a task line does not crash the audit", "Traceback" not in _od and "AUDIT " in _od, _od[-400:])
    ok("due: the impossible date is reported on its line (warn, never blocks)", "warn\tDUE-invalid\tn.md:3" in _od, _od[-400:])
    ok("due: control, the valid overdue line next to it is still reported", "DUE-now\tn.md:4" in _od, _od[-400:])
finally:
    _shutil.rmtree(_rd, ignore_errors=True)

# --- Fable review: --new-since must see changed notes whose names are not ASCII (git quotes such paths by default) ---
_AR1, _AR2 = _U(r"\u0645\u0644\u0627\u062d\u0638\u0629.md"), _U(r"\u062c\u062f\u064a\u062f\u0629.md")
_rg = _tmp_vault(_PROF % "[]", {_AR1: "# T\n\n## a\n", "ascii.md": "# T\n\n## a\n"})
try:
    _gitc = ["git", "-C", str(_rg), "-c", "user.name=t", "-c", "user.email=t@t"]
    _sp.run(_gitc + ["init", "-q"], check=True)
    _sp.run(_gitc + ["add", "-A"], check=True)
    _sp.run(_gitc + ["commit", "-q", "-m", "base"], check=True)
    (_rg / _AR1).write_text(_DUP, encoding="utf-8")        # tracked, modified
    (_rg / "ascii.md").write_text(_DUP, encoding="utf-8")  # control: an ASCII name was always seen
    (_rg / _AR2).write_text(_DUP, encoding="utf-8")        # untracked
    _og = _run_audit(_rg, "--new-since", "HEAD", "--check", "headings", "--min", "info")
    ok("new-since: control, a changed ASCII-named note is audited", "R1-dup\tascii.md" in _og, _og[-500:])
    ok("new-since: a changed non-ASCII-named note is audited", "R1-dup\t" + _AR1 in _og, _og[-500:])
    ok("new-since: an untracked non-ASCII-named note is audited", "R1-dup\t" + _AR2 in _og, _og[-500:])
finally:
    _shutil.rmtree(_rg, ignore_errors=True)

# --- Fable review: `created` must be a date; only a str was refused, so an empty value or a number passed the gate ---
_fmn = lambda v: "---\ntags:\n  - x\ncreated: %s\n---\n# T\n" % v
_rc = _tmp_vault(_PROF % "[]", {"01-Projects/empty.md": _fmn(""), "01-Projects/num.md": _fmn("20261116"), "01-Projects/stamp.md": _fmn("2026-11-16 10:30:00"),
                               "01-Projects/quoted.md": _fmn('"2026-11-16"'), "01-Projects/good.md": _fmn("2026-11-16"), "Templates/t.md": _fmn('"<% tp.date.now() %>"')})
try:
    _oc = _run_audit(_rc, "--check", "schema", "--min", "info", "--limit", "200")
    _hit = lambda n: ("FM-created-type\t" + n + ":") in _oc
    ok("created: control, a quoted date (str) is refused as before", _hit("01-Projects/quoted.md"), _oc[-500:])
    ok("created: an empty value is refused", _hit("01-Projects/empty.md"), _oc[-500:])
    ok("created: a number is refused", _hit("01-Projects/num.md"), _oc[-500:])
    ok("created: a timestamp is refused (ADR-010: a raw date, never a timestamp)", _hit("01-Projects/stamp.md"), _oc[-500:])
    ok("created: a raw ISO date passes and a template placeholder stays exempt", not _hit("01-Projects/good.md") and not _hit("Templates/t.md") and "Traceback" not in _oc, _oc[-500:])
finally:
    _shutil.rmtree(_rc, ignore_errors=True)

# --- Step 5: FM-nonlatin-digit covers the date keys FM-created-type does not ---
_fmd = lambda k, v: "---\ntags:\n  - x\ncreated: 2026-11-16\n%s: %s\n---\n# T\n" % (k, v)
_rd = _tmp_vault(_PROF % "[]", {"01-Projects/ar-due.md": _fmd("due", _U(r"\u0662\u0660\u0662\u0666-\u0661\u0661-\u0662\u0660")), "01-Projects/fa-reviewed.md": _fmd("last_reviewed", _U(r"\u06f2\u06f0\u06f2\u06f6-\u06f1\u06f1-\u06f2\u06f0")),
                               "01-Projects/ok-due.md": _fmd("due", "2026-11-20"), "01-Projects/title-digits.md": _U(r"---\ntags:\n  - x\ncreated: 2026-11-16\ntitle: \u0662\u0660\u0662\u0666\n---\n# T\n")})
try:
    _od = _run_audit(_rd, "--check", "schema", "--min", "info", "--limit", "200")
    _hd = lambda n: ("FM-nonlatin-digit\t" + n + ":") in _od
    ok("nonlatin-digit: an Arabic-Indic due date is flagged", _hd("01-Projects/ar-due.md"), _od[-500:])
    ok("nonlatin-digit: an Extended Arabic-Indic last_reviewed is flagged", _hd("01-Projects/fa-reviewed.md"), _od[-500:])
    ok("nonlatin-digit: an ASCII date and a non-date key with digits are not", not _hd("01-Projects/ok-due.md") and not _hd("01-Projects/title-digits.md") and "Traceback" not in _od, _od[-500:])
finally:
    _shutil.rmtree(_rd, ignore_errors=True)

# --- AD13 E1 prior-art retrofit: R21 inline Markdown links (MkDocs validation classes not_found, absolute_links, unrecognized_links) ---
NOF = "zzNoSuchFileQ9.md"
ok("R21: a relative link to a missing file is flagged (warn)", [f[0] for f in finds("A.md", f"x [t]({NOF}) y\n", "R21-missing-link")] == ["warn"])
ok("R21: an existing target passes with a fragment, a query and percent escapes",
   finds("A.md", "[t](AI-Agent/handoff.md#x) [u](AI-Agent/handoff.md?a=1) [v](AI-Agent/schema/consumer%2Dmap.yaml)\n", "R21-missing-link") == [])
ok("R21: a missing image is flagged", len(finds("A.md", "![i](zzNoPicQ9.png)\n", "R21-missing-link")) == 1)
ok("R21: external links, mail links and anchors are not checked",
   finds("A.md", "[a](https://example.com/zz) [b](mailto:x@y.z) [c](#section) [d](tel:123)\n", "R21-missing-link") == [])
ok("R21: fenced code and inline code are ignored", finds("A.md", f"```\n[t]({NOF})\n```\n\nand `[t]({NOF})` here\n", "R21-missing-link") == [])
ok("R21: the angle-bracket destination form is read and checked", len(finds("A.md", "[t](<zz No Such Q9.md>)\n", "R21-missing-link")) == 1)
ok("R21: a target without an extension resolves as a note name", finds("A.md", "[t](T)\n", "R21-missing-link") == [] and len(finds("A.md", "[t](zzNoStemQ9)\n", "R21-missing-link")) == 1)
ok("R21: a wikilink is not an inline link", finds("A.md", "[[T]] [[zzNoSuchNoteQ9]]\n", "R21-missing-link") == [])
ok("R21: the archive reports at info, a skipped folder reports nothing",
   [f[0] for f in finds("04-Archive/A.md", f"[t]({NOF})\n", "R21-missing-link")] == ["info"] and finds("Templates/A.md", f"[t]({NOF})\n", "R21-missing-link") == [])
ok("R21: a file URL and an absolute path are absolute links (warn)",
   [f[0] for f in finds("A.md", "[a](file:///home/alice/x/y.md)\n", "R21-absolute-link")] == ["warn"] and len(finds("A.md", "[b](/home/alice/x/y.md)\n", "R21-absolute-link")) == 1
   and len(finds("A.md", "[c](C:/Users/x/y.md)\n", "R21-absolute-link")) == 1)
ok("R21: a destination with an unencoded space or parenthesis is a malformed link",
   len(finds("A.md", "[a](file:///home/alice/My Vault (Work) (Copy)/x.md)\n", "R21-malformed-link")) == 1 and finds("A.md", "[a](file:///home/alice/My Vault (Work) (Copy)/x.md)\n", "R21-absolute-link") == [])
many = "\n\n".join(f"[l{i}](file:///home/alice/My Vault (Work) (Copy)/n{i}.md)" for i in range(5)) + "\n"
got21 = finds("A.md", many, "R21-malformed-link")
ok("R21: repeated bad links in one note give one finding with their count", len(got21) == 1 and "5 such links" in got21[0][-1], got21)
ok("R21: an encoded file URL is absolute, not malformed", len(finds("A.md", "[a](file:///home/alice/My%20Vault%20%28Work%29/x.md)\n", "R21-absolute-link")) == 1
   and finds("A.md", "[a](file:///home/alice/My%20Vault%20%28Work%29/x.md)\n", "R21-malformed-link") == [])
ok("R21: a path written with ./ resolves like any relative path", finds("A.md", "[a](./AI-Agent/handoff.md) [b](./AI-Agent/schema/consumer%2Dmap.yaml#L3)\n", "R21-missing-link") == []
   and len(finds("A.md", "[a](./zzNoSuchFileQ9.md)\n", "R21-missing-link")) == 1)
ok("R21: a relative link written with an ordinary slash path is never absolute", finds("A.md", "[a](AI-Agent/handoff.md) [b](../AI-Agent/handoff.md)\n", "R21-absolute-link") == [])

# --- secrets scan cache (AD13 perf, 2026-11-19): findings cached by the text's sha1; a cached run equals a no-cache run ---
import re as _re_c
import sqlite3 as _sq3
_fk2 = "sk" + "_live" + "_" + "A1b2C3d4E5f6G7h8I9j0K1l2"
_hd = "---\ntags: [x]\ncreated: 2026-11-01\narea: '[[n]]'\n---\n# T\n\n"
_cv = _tmp_vault(_PROF % "[]", {"03-Resources/leak.md": _hd + "key " + _fk2 + "\n", "03-Resources/clean.md": _hd + "nothing here\n"})


def _run_cached(root, *args):
    env = dict(_os.environ, VAULT=str(root))
    r = _sp.run([_sys.executable, str(_P(_A.__file__)), "--ratchet", "--check", "secrets", "--min", "info", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=180)
    return r.stdout + r.stderr


def _cs(o):
    m = _re_c.search(r"CACHE-SECRETS hits=(\d+) misses=(\d+)", o)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _fl(o):
    return sorted(l for l in o.splitlines() if "SECRET-" in l)


try:
    _c1 = _run_cached(_cv)
    _c2 = _run_cached(_cv)
    _nc = _run_cached(_cv, "--no-cache")
    ok("secrets cache: the first run scans every text, the second reads them all from the cache", _cs(_c1) and _cs(_c1)[0] == 0 and _cs(_c1)[1] >= 2 and _cs(_c2) == (_cs(_c1)[1], 0), (_cs(_c1), _cs(_c2)))
    ok("secrets cache: the findings of a cached run equal those of a no-cache run", _fl(_c1) == _fl(_c2) == _fl(_nc) and len(_fl(_c1)) >= 1, (_fl(_c1), _fl(_c2), _fl(_nc)))
    ok("secrets cache: --no-cache never touches the cache", _cs(_nc) is None, _cs(_nc))
    (_cv / "03-Resources" / "clean.md").write_text(_hd + "now key " + _fk2 + "\n", encoding="utf-8")
    _c3 = _run_cached(_cv)
    ok("secrets cache: an edited text is rescanned and its new finding appears", _cs(_c3) and _cs(_c3)[1] == 1 and "clean.md" in "\n".join(_fl(_c3))
       and "clean.md" not in "\n".join(_fl(_c1)), (_cs(_c3), _fl(_c3)))
    _db = _cv / "AI-Agent" / "state" / "vault-index.sqlite3"
    _cn = _sq3.connect(str(_db))
    _cn.execute("UPDATE secrets_scan_cache SET code_sha1 = 'other-code'")
    _cn.commit(); _cn.close()
    _c4 = _run_cached(_cv)
    ok("secrets cache: rows made by other code or another shapes file are dropped and rescanned", _cs(_c4) and _cs(_c4)[0] == 0 and _fl(_c4) == _fl(_c3), (_cs(_c4), _fl(_c4)))
finally:
    _shutil.rmtree(_cv, ignore_errors=True)

# --- sigkey reads key_file and fingerprint from release_profile.yaml ---
_skv = _tmp_vault(_PROF % "[]" + "sigkey:\n  key_file: ''\n  fingerprint: ''\n", {})
try:
    _skr = _run_audit(_skv, "--check", "sigkey", "--min", "info")
    ok("sigkey: reads configuration from release_profile.yaml and flags missing config loudly",
       "SIGKEY-missing" in _skr and "release_profile.yaml" in _skr and "Traceback" not in _skr, _skr[-300:])
finally:
    _shutil.rmtree(_skv, ignore_errors=True)

# --- final summary (must be last) ---
for name, passed, got in R:
    print(("PASS" if passed else "FAIL"), name, "" if passed else f"-> {got}")
failed = [x for x in R if not x[1]]   # recomputed: tests appended after the first `failed` snapshot must count too
print(f"{len(R) - len(failed)}/{len(R)} passed")
_sys.exit(1 if failed else 0)
