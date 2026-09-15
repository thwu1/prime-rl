#!/usr/bin/env python3
"""
Diagnose and fix all bugs in the sci-extended.ctb braille translation table.

This solution identifies 5 distinct root causes by analyzing the table rules
against liblouis opcode semantics, then applies targeted fixes.


ROOT CAUSE ANALYSIS:

Bug 1 — Wrong contraction scope (5 rules affected)
  Symptom: 'sin' contracts inside 'since', 'cos' inside 'cosine', etc.
  Cause: The 'always' opcode matches the character sequence unconditionally,
         even when embedded within a longer word.
  Fix: Replace 'always' with 'word'. The 'word' opcode restricts matching
       to sequences bounded by whitespace or punctuation. This prevents
       contraction inside words but still allows 'sin(x)' since '(' is
       punctuation and therefore a word boundary.

Bug 2 — Missing decpoint rule (1 rule missing)
  Symptom: Leading decimal '.5' produces punctuation dot (256) instead of
           decimal point (46), and the digit gets a separate number sign.
  Cause: The table has 'midnum . 46' which only handles periods BETWEEN
         digits. A leading decimal like '.5' has no preceding digit, so
         midnum does not apply. The 'decpoint' opcode is needed to handle
         periods at the start of a number.
  Fix: Add 'decpoint . 46' after the midnum rule.

Bug 3 — Missing replacement brackets in pass2 operator rules (3 rules)
  Symptom: In expressions like '3+4', both the operator AND the number sign
           are deleted, not just the number sign.
  Cause: The pass2 rules use '@346@3456 ?' without square brackets. Without
         brackets, the '?' action deletes the entire matched sequence (both
         the operator and the numsign). Replacement brackets are needed to
         mark only the numsign for deletion.
  Fix: Change '@346@3456 ?' to '@346[@3456] ?' (and similarly for @36 and
       @2356). The brackets indicate that only the numsign portion should
       be replaced (deleted) while the operator is preserved.

Bug 4 — Context rule bracket encloses digit (1 rule)
  Symptom: In 'h_2', the subscript indicator appears but the digit '2' is
           lost from the output entirely.
  Cause: The context rule '["_"$d] @16' places both the underscore AND the
         following digit inside the replacement brackets. The action @16
         replaces everything in the brackets, consuming the digit.
  Fix: Change '["_"$d] @16' to '["_"]$d @16'. Now only the underscore is
       inside the brackets and gets replaced by the subscript indicator.
       The digit remains in the output and gets its normal translation.

Bug 5 — Pass2 superscript rule references wrong dot pattern (1 rule)
  Symptom: In 'x^2', the superscript indicator (dots 35) appears correctly
           but the redundant number sign is NOT removed.
  Cause: The pass2 rule uses '@45[@3456] ?' which looks for dots 45 (the
         caret sign) before the numsign. But during pass1, the context rule
         already replaced the caret with the superscript indicator (dots 35).
         By pass2, the dot pattern is @35, not @45. The rule never matches.
  Fix: Change '@45[@3456] ?' to '@35[@3456] ?'. This matches the actual
       superscript indicator dot pattern that exists after pass1.
"""

import subprocess
import os
import sys

TABLE = "/app/tables/sci-extended.ctb"

with open(TABLE) as f:
    content = f.read()

original = content

# ---------------------------------------------------------------
# Bug 1: 'always' -> 'word' for function contractions
# ---------------------------------------------------------------
for func, dots in [("sin", "5-234"), ("cos", "5-14"), ("tan", "5-2345"),
                   ("log", "5-123"), ("exp", "5-15")]:
    old = f"always {func} {dots}"
    new = f"word {func} {dots}"
    assert old in content, f"Expected to find '{old}' in table"
    content = content.replace(old, new)

# ---------------------------------------------------------------
# Bug 2: Add missing 'decpoint . 46' rule
# ---------------------------------------------------------------
assert "midnum . 46" in content, "Expected 'midnum . 46' in table"
assert "decpoint . 46" not in content, "decpoint already present"
content = content.replace("midnum . 46\n", "midnum . 46\ndecpoint . 46\n")

# ---------------------------------------------------------------
# Bug 3: Add replacement brackets in pass2 operator rules
# ---------------------------------------------------------------
for op_dots in ["346", "36", "2356"]:
    old = f"noback pass2 @{op_dots}@3456 ?"
    new = f"noback pass2 @{op_dots}[@3456] ?"
    assert old in content, f"Expected to find '{old}' in table"
    content = content.replace(old, new)

# ---------------------------------------------------------------
# Bug 4: Fix subscript context rule bracket placement
# ---------------------------------------------------------------
old_sub = 'noback context ["_"$d] @16'
new_sub = 'noback context ["_"]$d @16'
assert old_sub in content, f"Expected to find '{old_sub}' in table"
content = content.replace(old_sub, new_sub)

# ---------------------------------------------------------------
# Bug 5: Fix superscript pass2 dot pattern (45 -> 35)
# ---------------------------------------------------------------
old_sup = "noback pass2 @45[@3456] ?"
new_sup = "noback pass2 @35[@3456] ?"
assert old_sup in content, f"Expected to find '{old_sup}' in table"
content = content.replace(old_sup, new_sup)

# ---------------------------------------------------------------
# Write the fixed table
# ---------------------------------------------------------------
with open(TABLE, "w") as f:
    f.write(content)

print(f"Applied 5 fixes ({len(original)} -> {len(content)} bytes)")

# ---------------------------------------------------------------
# Validate the table
# ---------------------------------------------------------------
env = os.environ.copy()
env["LOUIS_TABLEPATH"] = "/usr/share/liblouis/tables"

result = subprocess.run(
    ["lou_checktable", TABLE],
    capture_output=True, text=True, env=env
)
if result.returncode != 0:
    print("ERROR: Table validation failed after fixes!")
    print(result.stderr)
    sys.exit(1)
print("Table validation passed")

# ---------------------------------------------------------------
# Quick spot-check: verify a few critical translations
# ---------------------------------------------------------------
def translate(text):
    r = subprocess.run(
        ["lou_translate", "-f", f"unicode.dis,{TABLE}"],
        input=text + "\n", capture_output=True, text=True,
        timeout=10, env=env,
    )
    return r.stdout.split("\n")[0] if r.returncode == 0 else None

checks = [
    ("sin",   "\u2810\u280e",   "standalone contraction"),
    ("since", "\u280e\u280a\u281d\u2809\u2811", "no false contraction"),
    (".5",    "\u283c\u2828\u2811", "leading decimal"),
    ("3+4",   "\u283c\u2809\u282c\u2819", "operator preserved"),
    ("h_2",   "\u2813\u2821\u2803", "subscript preserves digit"),
    ("x^2",   "\u282d\u2814\u2803", "superscript numsign removed"),
]

all_ok = True
for text, expected, label in checks:
    actual = translate(text)
    status = "OK" if actual == expected else "FAIL"
    if status == "FAIL":
        all_ok = False
    print(f"  [{status}] '{text}' -- {label}")

if all_ok:
    print("All spot-checks passed")
else:
    print("WARNING: Some spot-checks failed")
    sys.exit(1)
