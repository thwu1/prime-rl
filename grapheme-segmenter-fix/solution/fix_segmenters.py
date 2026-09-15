#!/usr/bin/env python3
"""
Fix all segmentation bugs in the grapheme and word segmenters.

Applies targeted patches to both grapheme_segment.py and word_segment.py
to bring them into full UAX#29 Unicode 16.0 conformance.

"""

# ============================================================
# Fix grapheme_segment.py — three context-scanning bugs
# ============================================================

with open('/app/grapheme_segment.py', 'r', encoding='utf-8') as f:
    gsrc = f.read()

# Fix 1: GB9c — backward scan must skip InCB=Extend characters
# The scan only checks for InCB=Linker but not InCB=Extend,
# causing incorrect breaks when Extend chars (e.g. nukta) appear
# between a preceding Consonant and the first Linker.

old_gb9c = """\
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
    return True  # reached start of text"""

new_gb9c = """\
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
            if linker_count > 0 and grapheme_category(ch) == InCB_Consonant:
                return False  # GB9c applies, no break
            return True       # break
    return True  # reached start of text"""

assert old_gb9c in gsrc, "Could not find GB9c buggy code"
gsrc = gsrc.replace(old_gb9c, new_gb9c, 1)

# Fix 2: GB11 — must skip Extend characters between base emoji and ZWJ
# The function only checks the single character at pos-2 but doesn't
# walk past intervening Extend characters (skin tones, variation selectors).

old_gb11 = """\
    j = pos - 2   # character before the ZWJ
    if j >= 0 and grapheme_category(text[j]) == Extended_Pictographic:
        return False  # no break
    return True       # break"""

new_gb11 = """\
    j = pos - 2   # character before the ZWJ
    while j >= 0 and grapheme_category(text[j]) == Extend:
        j -= 1
    if j >= 0 and grapheme_category(text[j]) == Extended_Pictographic:
        return False  # no break
    return True       # break"""

assert old_gb11 in gsrc, "Could not find GB11 buggy code"
gsrc = gsrc.replace(old_gb11, new_gb11, 1)

# Fix 3: GB12/GB13 — must count full run of RI characters backward
# The 2-char lookback only checks text[pos-2], which fails for 4+ RI
# sequences (e.g. two flag emoji back-to-back).

old_ri = """\
    if pos >= 2 and grapheme_category(text[pos - 2]) == Regional_Indicator:
        return True   # the preceding RI is paired, start new pair \u2192 break
    return False      # first pair \u2192 no break"""

new_ri = """\
    count = 0
    j = pos - 1
    while j >= 0 and grapheme_category(text[j]) == Regional_Indicator:
        count += 1
        j -= 1
    return count % 2 == 0  # even \u2192 break (new pair), odd \u2192 no break"""

assert old_ri in gsrc, "Could not find GB12/GB13 buggy code"
gsrc = gsrc.replace(old_ri, new_ri, 1)

with open('/app/grapheme_segment.py', 'w', encoding='utf-8') as f:
    f.write(gsrc)

print("Grapheme segment fixes applied (GB9c, GB11, GB12/GB13).")

# ============================================================
# Fix word_segment.py — three rule bugs
# ============================================================

with open('/app/word_segment.py', 'r', encoding='utf-8') as f:
    wsrc = f.read()

# Fix 4: Add missing WB3d (WSegSpace × WSegSpace)
# The rule that joins adjacent word-segmentation spaces is absent.

old_wb3d = """\
        skipped_efz = (base_i != i - 1)

        # WB5: AHLetter \u00d7 AHLetter"""

new_wb3d = """\
        skipped_efz = (base_i != i - 1)

        # WB3d: WSegSpace \u00d7 WSegSpace
        if base_wb == 'WSegSpace' and curr_wb == 'WSegSpace' and not skipped_efz:
            continue

        # WB5: AHLetter \u00d7 AHLetter"""

assert old_wb3d in wsrc, "Could not find WB3d insertion point"
wsrc = wsrc.replace(old_wb3d, new_wb3d, 1)

# Fix 5: Add missing WB7a (Hebrew_Letter × Single_Quote)
# The rule that keeps Hebrew letters joined to following single quotes
# is absent.

old_wb7a = """\
        # WB7b: Hebrew_Letter \u00d7 Double_Quote Hebrew_Letter"""

new_wb7a = """\
        # WB7a: Hebrew_Letter \u00d7 Single_Quote
        if base_wb == 'Hebrew_Letter' and curr_wb == 'Single_Quote':
            continue

        # WB7b: Hebrew_Letter \u00d7 Double_Quote Hebrew_Letter"""

assert old_wb7a in wsrc, "Could not find WB7a insertion point"
wsrc = wsrc.replace(old_wb7a, new_wb7a, 1)

# Fix 6: WB13a — add missing ExtendNumLet self-joining
# The rule should allow ExtendNumLet × ExtendNumLet but the
# implementation omits ExtendNumLet from the base category set.

old_wb13a = """\
        # WB13a: (AHLetter | Numeric | Katakana) \u00d7 ExtendNumLet
        if curr_wb == 'ExtendNumLet' and base_wb in (
            'ALetter', 'Hebrew_Letter', 'Numeric', 'Katakana'
        ):"""

new_wb13a = """\
        # WB13a: (AHLetter | Numeric | Katakana | ExtendNumLet) \u00d7 ExtendNumLet
        if curr_wb == 'ExtendNumLet' and base_wb in (
            'ALetter', 'Hebrew_Letter', 'Numeric', 'Katakana', 'ExtendNumLet'
        ):"""

assert old_wb13a in wsrc, "Could not find WB13a buggy code"
wsrc = wsrc.replace(old_wb13a, new_wb13a, 1)

with open('/app/word_segment.py', 'w', encoding='utf-8') as f:
    f.write(wsrc)

print("Word segment fixes applied (WB3d, WB7a, WB13a).")
print("All six fixes applied successfully.")
