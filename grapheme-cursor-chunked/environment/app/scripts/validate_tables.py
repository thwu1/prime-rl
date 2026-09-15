#!/usr/bin/env python3

"""Validate Unicode property table lookups against known correct values.

Checks that grapheme_category() returns the right category for a set of
representative codepoints spanning all major UAX#29 categories. Run this
after modifying tables.py or its data files to catch regressions.
"""

import sys
sys.path.insert(0, "/app")

from segmenter.tables import grapheme_category, is_incb_linker, is_incb_extend

# (codepoint, expected_category)
CATEGORY_CHECKS = [
    (0x000A, "LF"),
    (0x000D, "CR"),
    (0x0009, "Control"),
    (0x007F, "Control"),
    (0x0020, "Any"),
    (0x0041, "Any"),
    (0x0300, "Extend"),
    (0x0903, "SpacingMark"),
    (0x200D, "ZWJ"),
    (0x1F1FA, "Regional_Indicator"),
    (0x1F352, "Extended_Pictographic"),
    (0x1F469, "Extended_Pictographic"),
    (0x2764, "Extended_Pictographic"),
    (0x0915, "InCB_Consonant"),
    (0x0995, "InCB_Consonant"),
    (0x0600, "Prepend"),
    (0xAC00, "LV"),
    (0xAC01, "LVT"),
    (0x1100, "L"),
    (0x1160, "V"),
    (0x11A8, "T"),
]

INCB_CHECKS = [
    ("is_incb_linker", is_incb_linker, 0x094D, True),
    ("is_incb_linker", is_incb_linker, 0x09CD, True),
    ("is_incb_linker", is_incb_linker, 0x0041, False),
    ("is_incb_extend", is_incb_extend, 0x0300, True),
    ("is_incb_extend", is_incb_extend, 0x0041, False),
]


def main():
    errors = 0

    print("=== Grapheme category checks ===")
    for cp, expected in CATEGORY_CHECKS:
        actual = grapheme_category(cp)
        ok = actual == expected
        tag = "OK" if ok else "FAIL"
        if not ok:
            errors += 1
        print(f"  U+{cp:04X}: expected={expected:25s} got={actual:25s} [{tag}]")

    print("\n=== InCB function checks ===")
    for name, func, cp, expected in INCB_CHECKS:
        actual = func(cp)
        ok = actual == expected
        tag = "OK" if ok else "FAIL"
        if not ok:
            errors += 1
        print(f"  {name}(U+{cp:04X}): expected={expected!s:5s}  got={actual!s:5s}  [{tag}]")

    print(f"\n{errors} error(s) found")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
