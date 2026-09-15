"""
UAX#29 Extended Grapheme Cluster segmentation.

Implements the Unicode 16.0 grapheme cluster boundary algorithm
as specified in https://www.unicode.org/reports/tr29/

"""

from grapheme_props import (
    grapheme_category, is_incb_linker, is_incb_extend,
    CR, LF, Control, Extend, ZWJ, Regional_Indicator,
    Prepend, SpacingMark, L, V, T, LV, LVT,
    Extended_Pictographic, InCB_Consonant, Any,
)


def check_pair(cat_before, cat_after):
    """
    Determine the basic break disposition for a pair of adjacent grapheme
    categories.  Returns one of:

        'no_break'        - definitely not a boundary
        'break'           - definitely a boundary
        'extended'        - boundary in legacy mode only (suppressed in
                            extended mode, which is the default)
        'incb_consonant'  - needs backward context check for GB9c
        'emoji'           - needs backward context check for GB11
        'regional'        - needs backward context check for GB12/GB13
    """
    # GB3: CR × LF
    if cat_before == CR and cat_after == LF:
        return 'no_break'
    # GB4: (Control | CR | LF) ÷
    if cat_before in (Control, CR, LF):
        return 'break'
    # GB5: ÷ (Control | CR | LF)
    if cat_after in (Control, CR, LF):
        return 'break'
    # GB6: L × (L | V | LV | LVT)
    if cat_before == L and cat_after in (L, V, LV, LVT):
        return 'no_break'
    # GB7: (LV | V) × (V | T)
    if cat_before in (LV, V) and cat_after in (V, T):
        return 'no_break'
    # GB8: (LVT | T) × T
    if cat_before in (LVT, T) and cat_after == T:
        return 'no_break'
    # GB9: × (Extend | ZWJ)
    if cat_after in (Extend, ZWJ):
        return 'no_break'
    # GB9a: × SpacingMark
    if cat_after == SpacingMark:
        return 'extended'
    # GB9b: Prepend ×
    if cat_before == Prepend:
        return 'extended'
    # GB9c: × InCB_Consonant  (context-dependent)
    if cat_after == InCB_Consonant:
        return 'incb_consonant'
    # GB11: ZWJ × Extended_Pictographic  (context-dependent)
    if cat_before == ZWJ and cat_after == Extended_Pictographic:
        return 'emoji'
    # GB12/GB13: RI × RI  (context-dependent)
    if cat_before == Regional_Indicator and cat_after == Regional_Indicator:
        return 'regional'
    # GB999: ÷ Any
    return 'break'


def _handle_incb_consonant(text, pos):
    """
    Handle GB9c.

    Rule:  \\p{InCB=Consonant} [{\\p{InCB=Extend}|\\p{InCB=Linker}}]*
           \\p{InCB=Linker} [{\\p{InCB=Extend}|\\p{InCB=Linker}}]* × \\p{InCB=Consonant}

    Scan backward from *pos* looking for an InCB=Linker preceded (possibly
    with intervening InCB=Extend or InCB=Linker chars) by an InCB=Consonant.
    Return False (no break) if found, True (break) otherwise.
    """
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
    return True  # reached start of text


def _handle_emoji(text, pos):
    """
    Handle GB11.

    Rule:  \\p{Extended_Pictographic} Extend* ZWJ × \\p{Extended_Pictographic}

    text[pos] has category Extended_Pictographic and text[pos-1] is ZWJ.
    Check whether there is an Extended_Pictographic before the ZWJ,
    skipping past any intervening Extend characters.
    Return False (no break) if so.
    """
    j = pos - 2   # character before the ZWJ
    while j >= 0 and grapheme_category(text[j]) == Extend:
        j -= 1
    if j >= 0 and grapheme_category(text[j]) == Extended_Pictographic:
        return False  # no break
    return True       # break


def _handle_regional(text, pos):
    """
    Handle GB12/GB13.

    Rules: sot  (RI RI)* RI × RI       (GB12)
           [^RI](RI RI)* RI × RI       (GB13)

    Count the full run of RI characters before pos.
    If odd count, the preceding RI needs a partner → no break.
    If even count, all are paired → break (start new pair).
    """
    count = 0
    j = pos - 1
    while j >= 0 and grapheme_category(text[j]) == Regional_Indicator:
        count += 1
        j -= 1
    return count % 2 == 0  # even → break (new pair), odd → no break


def segment_graphemes(text):
    """
    Segment *text* into Extended Grapheme Clusters per UAX#29.

    Returns a list of strings, each being one grapheme cluster.
    """
    if not text:
        return []

    clusters = []
    start = 0

    for i in range(1, len(text)):
        cat_before = grapheme_category(text[i - 1])
        cat_after = grapheme_category(text[i])

        pair = check_pair(cat_before, cat_after)

        if pair == 'no_break':
            should_break = False
        elif pair == 'break':
            should_break = True
        elif pair == 'extended':
            # We always use extended mode.
            should_break = False
        elif pair == 'incb_consonant':
            should_break = _handle_incb_consonant(text, i)
        elif pair == 'emoji':
            should_break = _handle_emoji(text, i)
        elif pair == 'regional':
            should_break = _handle_regional(text, i)
        else:
            should_break = True

        if should_break:
            clusters.append(text[start:i])
            start = i

    if start < len(text):
        clusters.append(text[start:])

    return clusters
