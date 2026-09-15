#!/usr/bin/env python3
"""
Design and implement all translation rules for the sci-notation.ctb
braille table.


DESIGN DECISIONS:

1. FUNCTION CONTRACTIONS — opcode: 'word'
   Evaluated alternatives:
   - 'always': matches the character sequence unconditionally, even inside
     other words. 'always sin 5-234' would contract the "sin" inside
     "since", "basin", etc. REJECTED.
   - 'sufword': matches when the sequence is at the beginning of a word
     or is the entire word. 'sufword sin 5-234' would contract "sin" in
     "since" because "sin" appears at the word start. REJECTED.
   - 'word': matches only when the sequence is surrounded by whitespace
     and/or punctuation. This prevents contraction inside longer words
     while still allowing 'sin(x)' since parentheses are punctuation
     and therefore word boundaries. SELECTED.

2. DECIMAL POINT — opcodes: 'midnum' + 'decpoint'
   - 'midnum . 46': handles periods BETWEEN digits (e.g., 3.14). The
     'midnum' opcode fires when the character appears between two digits.
   - 'decpoint . 46': handles leading decimals (e.g., .5). The 'decpoint'
     opcode treats the period as part of a number even without a preceding
     digit, triggering the numsign and decimal dot pattern.
   Using only 'midnum' fails for '.5' — the period has no preceding digit,
   so midnum doesn't fire, and it falls through to 'punctuation . 256'.

3. THOUSANDS SEPARATOR — opcode: 'midnum'
   - 'midnum , 2': keeps a comma between digits as part of the number
     sequence. Without this, the comma would end the number and the next
     digit group would get a new numsign.

4. SUPERSCRIPT/SUBSCRIPT — opcode: 'noback context'
   - Context rules operate during the first translation pass on INPUT
     characters, allowing pattern matching with attribute tests ($d for
     digit).
   - '["^"]$d @35': brackets enclose ONLY the caret. The $d test checks
     that a digit follows, but the digit stays in the input for normal
     translation. If brackets enclosed both (["^"$d]), the digit would
     be consumed by the replacement.
   - '["_"]$d @16': same logic for subscript.
   - 'noback' prefix is mandatory: context/multipass rules must be
     prefixed with either 'noback' (exclude from back-translation) or
     'nofor' (exclude from forward-translation). We want forward
     translation, so we use 'noback'.

5. PASS2 CLEANUP — opcode: 'noback pass2'
   - Pass2 operates on DOT PATTERNS, not input characters. After pass1:
     * Operators retain their defined dot patterns (+→346, -→36, =→2356)
     * Superscript indicator is dots 35 (produced by the context rule,
       NOT dots 45 which was the original caret sign)
     * Subscript indicator is dots 16 (produced by the context rule)
     * Number signs are dots 3456
   - Replacement brackets: '@346[@3456] ?' means match @346 followed by
     @3456, but only delete the bracketed @3456. Without brackets,
     '@346@3456 ?' would delete the entire match (both operator and
     numsign).
   - CRITICAL: the superscript cleanup must be '@35[@3456] ?' not
     '@45[@3456] ?'. By pass2, the caret has already been replaced by
     the superscript indicator (dots 35) during pass1. Using @45 would
     look for the original caret sign's pattern, which no longer exists.
"""

import subprocess
import os
import sys

TABLE = "/app/tables/sci-notation.ctb"

RULES = """
# ===================================================================
# Function Name Contractions
# 'word' opcode: match only standalone words (bounded by whitespace
# or punctuation). Prevents contraction inside words like 'since'.
# ===================================================================

word sin 5-234
word cos 5-14
word tan 5-2345
word log 5-123
word exp 5-15

# ===================================================================
# Decimal Point and Number Formatting
# 'midnum': period/comma between digits becomes part of the number.
# 'decpoint': leading decimal (.5) treated as start of a number.
# ===================================================================

midnum . 46
decpoint . 46
midnum , 2

# ===================================================================
# Superscript Notation (context rule, first pass)
# Replaces caret with superscript indicator when before a digit.
# Brackets enclose only the caret — digit is preserved in input.
# ===================================================================

noback context ["^"]$d @35

# ===================================================================
# Subscript Notation (context rule, first pass)
# Replaces underscore with subscript indicator when before a digit.
# Brackets enclose only the underscore — digit is preserved in input.
# ===================================================================

noback context ["_"]$d @16

# ===================================================================
# Pass 2: Remove Redundant Number Signs
# After operators and super/subscript indicators, the numsign
# (dots 3456) before the next digit group is redundant.
# Pattern: @INDICATOR[@3456] ?  (delete only the bracketed numsign)
# Note: superscript uses @35 (pass1 output), not @45 (original caret)
# ===================================================================

noback pass2 @346[@3456] ?
noback pass2 @36[@3456] ?
noback pass2 @2356[@3456] ?
noback pass2 @35[@3456] ?
noback pass2 @16[@3456] ?
"""

# Read the skeleton table
with open(TABLE, "r") as f:
    content = f.read()

# Append all translation rules
content += "\n" + RULES

with open(TABLE, "w") as f:
    f.write(content)

print("Translation rules appended to", TABLE)

# Validate the table
env = os.environ.copy()
env["LOUIS_TABLEPATH"] = "/usr/share/liblouis/tables"

result = subprocess.run(
    ["lou_checktable", TABLE],
    capture_output=True, text=True, env=env
)
if result.returncode != 0:
    print("ERROR: Table validation failed!")
    print(result.stderr)
    sys.exit(1)
print("Table validation passed")

# Spot-check critical translations
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
