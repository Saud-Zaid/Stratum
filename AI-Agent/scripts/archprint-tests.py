# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0
# SPDX-FileCopyrightText: 2026 Saud Zaid
"""Self-tests for archprint (normalization, element split, status outside the hash). Usage: archprint-tests"""

def _U(s):
    """ASCII-escaped test data: the shipped sources hold no Arabic literal."""
    return s.encode("ascii").decode("unicode_escape")

import sys

from _vaultlib import locale_value
from archprint import compare, element_id, elements, fingerprint, normalize, snapshot

R = []


def ok(name, cond, got=""):
    R.append((name, bool(cond), got))


if locale_value("TATWEEL"):
    ok("nfc + tatweel + trailing + blank runs", normalize(_U(r"\u0642\u0640\u0631\u0627\u0631  \r\n\n\n\n\u0628")) == _U(r"\u0642\u0631\u0627\u0631\n\n\u0628"), repr(normalize(_U(r"\u0642\u0640\u0631\u0627\u0631  \r\n\n\n\n\u0628"))))
ok("letters unchanged", normalize(_U(r"\u0625\u062f\u0627\u0631\u0629 \u0623 \u0622 \u0649 \u0629")) == _U(r"\u0625\u062f\u0627\u0631\u0629 \u0623 \u0622 \u0649 \u0629"))
ok("id with dash", element_id(_U(r"D03 \u2014 \u0627\u0644\u0628\u0635\u0645\u0629")) == "D03")
ok("id SH before S", element_id(_U(r"SH02 \u00b7 \u0632\u0645\u064a\u0644")) == "SH02")
ok("no id in plain heading", element_id(_U(r"\u0627\u0644\u0645\u0644\u062e\u0635")) is None)
ok("no id for D in word", element_id("Decisions") is None)

DOC = _U(r"""# T
## \u0627\u0644\u0642\u0631\u0627\u0631\u0627\u062a
### D01 \u2014 \u0623\u0648\u0644
- \u0646\u0635
- **Status:** decided
### D02 \u2014 \u062b\u0627\u0646\u064a
\u0646\u0635 \u062b\u0627\u0646\u064a
#### \u062a\u0641\u0635\u064a\u0644 D02
\u062f\u0627\u062e\u0644 D02
## \u0633\u062c\u0644
- \u0633\u0637\u0631
""")
els = elements(DOC)
ok("two elements", sorted(els) == ["D01", "D02"], sorted(els))
ok("child heading inside parent element", _U(r"\u062f\u0627\u062e\u0644 D02") in els["D02"]["body"], els["D02"]["body"])
ok("element stops at higher heading", _U(r"\u0633\u0637\u0631") not in els["D02"]["body"])
s1 = snapshot(DOC)
s2 = snapshot(DOC.replace("decided", "withdrawn"))
ok("status outside the hash", s1["D01"]["fp"] == s2["D01"]["fp"])
_sw = locale_value("STATUS_WORD")
if _sw:   # the vault's own language names the status line differently; it stays outside the hash all the same
    ok("localized status word outside the hash", snapshot(DOC.replace("**Status:**", f"**{_sw}:**"))["D01"]["fp"] == s1["D01"]["fp"])
s3 = snapshot(DOC.replace(_U(r"- \u0646\u0635\n"), _U(r"- \u0646\u0635 \u0645\u0639\u062f\u0644\n")))
ok("body change changes hash", s1["D01"]["fp"] != s3["D01"]["fp"])
s4 = snapshot(DOC.replace(_U(r"- \u0646\u0635\n"), _U(r"- \u0646\u0635  \n\n\n")))
ok("whitespace-only change keeps hash", s1["D01"]["fp"] == s4["D01"]["fp"])
d = compare(s1, snapshot(DOC.replace(_U(r"### D02 \u2014 \u062b\u0627\u0646\u064a\n\u0646\u0635 \u062b\u0627\u0646\u064a\n#### \u062a\u0641\u0635\u064a\u0644 D02\n\u062f\u0627\u062e\u0644 D02\n"), _U(r"### D03 \u2014 \u062c\u062f\u064a\u062f\nx\n"))))
ok("compare added/removed", d["added"] == ["D03"] and d["removed"] == ["D02"], d)
ok("duplicate ids reported", elements("## D01 a\nx\n## D01 b\ny\n").get("__dup__") == ["D01"])
ok("fingerprint length", len(fingerprint("x")) == 16)

bad = [r for r in R if not r[1]]
for name, passed, got in R:
    print(("PASS" if passed else "FAIL") + "\t" + name + ("" if passed else f"\t{got}"))
print(f"SUMMARY {len(R) - len(bad)}/{len(R)} passed")
sys.exit(1 if bad else 0)
