#!/usr/bin/env python3

"""Restore the InCB_Consonant check in tables.py grapheme_category()."""

path = "/app/segmenter/tables.py"
with open(path) as f:
    content = f.read()

old_ending = '''    ranges = _CAT_RANGES.get("Extended_Pictographic")
    if ranges and _in_ranges(cp, ranges):
        return "Extended_Pictographic"

    return "Any"'''

new_ending = '''    ranges = _CAT_RANGES.get("Extended_Pictographic")
    if ranges and _in_ranges(cp, ranges):
        return "Extended_Pictographic"

    if _is_incb_consonant(cp):
        return "InCB_Consonant"

    return "Any"'''

content = content.replace(old_ending, new_ending)

with open(path, "w") as f:
    f.write(content)

print("tables.py fixed: InCB_Consonant lookup restored.")
