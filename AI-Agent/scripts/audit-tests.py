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
    r = _sp.run([_sys.executable, str(_P(_A.__file__)), "--no-cache", *args], capture_output=True, text=True, env=env, timeout=120)
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
                     capture_output=True, text=True, env=dict(_os.environ, VAULT=str(_REAL)))
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
aok("T-02d: owner recognised by Latin alias, any case", _A.is_vault_owner("owner example") and _A.is_vault_owner("OWNER EXAMPLE (lead)"))
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
    ok("T-05: vault mode does not scan a research note for credential shapes or entropy", "03-Resources/r.md" not in _ov, _ov[-400:])
    ok("T-05: vault mode still scans an instruction-path file", "SECRET-leak-2" in _ov and "handoff.md" in _ov, _ov[-400:])
    ok("T-05: hidden bidirectional text is an error in any mode", "BIDI-control" in _ov and "03-Resources/b.md" in _ov, _ov[-400:])
    _orr = _run_audit(_sr, "--check", "secrets", "--min", "info")
    ok("T-05: release mode scans every note: credential shape and entropy are errors", "SECRET-leak-2" in _orr and "SECRET-entropy" in _orr and "03-Resources/r.md" in _orr, _orr[-400:])
    ok("T-05: release mode also reports the bidi note", "BIDI-control" in _orr, _orr[-300:])
    ok("T-05: a leak blocks the gate (exit 1 under --ratchet)", _sp.run([_sys.executable, str(_P(_A.__file__)), "--no-cache", "--ratchet", "--check", "secrets"], capture_output=True, text=True, env=dict(_os.environ, VAULT=str(_sr)), timeout=120).returncode == 1)
finally:
    _shutil.rmtree(_sv, ignore_errors=True)
    _shutil.rmtree(_sr, ignore_errors=True)

# --- final summary (must be last) ---
for name, passed, got in R:
    print(("PASS" if passed else "FAIL"), name, "" if passed else f"-> {got}")
failed = [x for x in R if not x[1]]   # recomputed: tests appended after the first `failed` snapshot must count too
print(f"{len(R) - len(failed)}/{len(R)} passed")
_sys.exit(1 if failed else 0)
