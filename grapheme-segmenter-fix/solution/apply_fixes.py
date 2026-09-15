"""
Apply fixes to grapheme_segment.py for the three UAX#29 rule bugs.

"""

import re

SEGMENTER_PATH = '/app/grapheme_segment.py'

with open(SEGMENTER_PATH, 'r', encoding='utf-8') as f:
    source = f.read()

# ---------------------------------------------------------------
# Fix 1: GB9c — _handle_incb_consonant
#
# Bug: The backward scan does not skip InCB=Extend characters.
# When an InCB=Extend char (e.g. nukta) appears between the
# preceding Consonant and the first Linker, the function
# mistakenly treats it as a non-matching char and returns True
# (break) instead of continuing the scan.
#
# Fix: Add an elif branch to skip InCB=Extend characters.
# ---------------------------------------------------------------

old_incb = '''\
    linker_count = 0
    j = pos - 1
    while j >= 0:
        ch = text[j]
        if is_incb_linker(ch):
            linker_count += 1
            j -= 1
        else:
            # Found a character that is not a linker.
            # Suppress break iff we saw at least one linker AND this char
            # is an InCB=Consonant.
            if linker_count > 0 and grapheme_category(ch) == InCB_Consonant:
                return False  # GB9c applies, no break
            return True       # break
    return True  # reached start of text'''

new_incb = '''\
    linker_count = 0
    j = pos - 1
    while j >= 0:
        ch = text[j]
        if is_incb_linker(ch):
            linker_count += 1
            j -= 1
        elif is_incb_extend(ch):
            j -= 1
        else:
            # Found a character that is neither a linker nor an extend.
            # Suppress break iff we saw at least one linker AND this char
            # is an InCB=Consonant.
            if linker_count > 0 and grapheme_category(ch) == InCB_Consonant:
                return False  # GB9c applies, no break
            return True       # break
    return True  # reached start of text'''

assert old_incb in source, "Could not find GB9c buggy code to patch"
source = source.replace(old_incb, new_incb, 1)

# ---------------------------------------------------------------
# Fix 2: GB11 — _handle_emoji
#
# Bug: The function only checks the single character at pos-2 for
# Extended_Pictographic.  It does not skip over intervening Extend
# characters (e.g. skin-tone modifiers, variation selectors) that
# may sit between the base emoji and the ZWJ.
#
# Fix: Add a while loop to walk past Extend characters before
# checking for Extended_Pictographic.
# ---------------------------------------------------------------

old_emoji = '''\
    j = pos - 2   # character before the ZWJ
    if j >= 0 and grapheme_category(text[j]) == Extended_Pictographic:
        return False  # no break
    return True       # break'''

new_emoji = '''\
    j = pos - 2   # character before the ZWJ
    while j >= 0 and grapheme_category(text[j]) == Extend:
        j -= 1
    if j >= 0 and grapheme_category(text[j]) == Extended_Pictographic:
        return False  # no break
    return True       # break'''

assert old_emoji in source, "Could not find GB11 buggy code to patch"
source = source.replace(old_emoji, new_emoji, 1)

# ---------------------------------------------------------------
# Fix 3: GB12/GB13 — _handle_regional
#
# Bug: The function uses a simplified two-character lookback that
# only checks text[pos-2].  This works for a single pair of RI
# characters but fails for sequences of 4+ RIs (e.g. two flag
# emoji back-to-back), because it doesn't count the full run of
# preceding RI characters.
#
# Fix: Count ALL consecutive RI characters backward from pos-1
# and break iff the count is even (meaning the current RI would
# start a new pair rather than completing one).
# ---------------------------------------------------------------

old_regional = '''\
    if pos >= 2 and grapheme_category(text[pos - 2]) == Regional_Indicator:
        return True   # the preceding RI is paired, start new pair → break
    return False      # first pair → no break'''

new_regional = '''\
    count = 0
    j = pos - 1
    while j >= 0 and grapheme_category(text[j]) == Regional_Indicator:
        count += 1
        j -= 1
    return count % 2 == 0  # break iff even number of preceding RIs'''

assert old_regional in source, "Could not find GB12/GB13 buggy code to patch"
source = source.replace(old_regional, new_regional, 1)

# Write the fixed file
with open(SEGMENTER_PATH, 'w', encoding='utf-8') as f:
    f.write(source)

print("All three fixes applied successfully.")
