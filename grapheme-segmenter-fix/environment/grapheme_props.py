"""
Unicode Grapheme Cluster Break property lookup.

Parses Unicode 16.0 data files and provides lookup functions for:
- Grapheme_Cluster_Break categories (CR, LF, Control, Extend, ZWJ, etc.)
- Extended_Pictographic property
- Indic_Conjunct_Break properties (Consonant, Extend, Linker)

"""

import bisect
import os
import re

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')

# Grapheme cluster break category constants
CR = 'CR'
LF = 'LF'
Control = 'Control'
Extend = 'Extend'
ZWJ = 'ZWJ'
Regional_Indicator = 'Regional_Indicator'
Prepend = 'Prepend'
SpacingMark = 'SpacingMark'
L = 'L'
V = 'V'
T = 'T'
LV = 'LV'
LVT = 'LVT'
Extended_Pictographic = 'Extended_Pictographic'
InCB_Consonant = 'InCB_Consonant'
Any = 'Any'

# InCB=Linker codepoints (small, stable set from Unicode 16.0)
_INCB_LINKER_CODEPOINTS = frozenset([
    0x094D,   # DEVANAGARI SIGN VIRAMA
    0x09CD,   # BENGALI SIGN VIRAMA
    0x0ACD,   # GUJARATI SIGN VIRAMA
    0x0B4D,   # ORIYA SIGN VIRAMA
    0x0C4D,   # TELUGU SIGN VIRAMA
    0x0D4D,   # MALAYALAM SIGN VIRAMA
    0x1039,   # MYANMAR SIGN VIRAMA
    0x17D2,   # KHMER SIGN COENG
    0x1A60,   # TAI THAM SIGN SAKOT
    0x1B44,   # BALINESE ADEG ADEG
    0x1BAB,   # SUNDANESE SIGN VIRAMA
    0xA9C0,   # JAVANESE PANGKON
    0xAAF6,   # MEETEI MAYEK VIRAMA
    0x10A3F,  # KHAROSHTHI VIRAMA
    0x11133,  # CHAKMA VIRAMA
    0x11839,  # DOGRA SIGN VIRAMA
    0x1193E,  # DIVES AKURU SIGN HALANTA
    0x11A47,  # ZANABAZAR SQUARE SUBJOINER
    0x11A99,  # SOYOMBO SUBJOINER
    0x11F42,  # KAWI CONJOINER
])


def _parse_unicode_file(filepath):
    """Parse a Unicode data file, yielding (lo, hi, property, value) tuples."""
    pattern = re.compile(
        r'^\s*([0-9A-Fa-f]+)(?:\.\.([0-9A-Fa-f]+))?\s*;\s*([\w_]+)(?:\s*;\s*(\w+))?'
    )
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # Strip inline comments
            comment_pos = line.find('#')
            if comment_pos >= 0:
                line = line[:comment_pos].strip()
            if not line:
                continue
            m = pattern.match(line)
            if not m:
                continue
            lo = int(m.group(1), 16)
            hi = int(m.group(2), 16) if m.group(2) else lo
            prop = m.group(3)
            value = m.group(4)
            # Skip surrogates
            if 0xD800 <= lo <= 0xDFFF:
                continue
            yield lo, hi, prop, value


class _RangeTable:
    """Sorted range table supporting binary search lookup."""

    def __init__(self):
        self._entries = []
        self._starts = []
        self._built = False

    def add(self, start, end, category):
        self._entries.append((start, end, category))
        self._built = False

    def build(self):
        self._entries.sort(key=lambda x: x[0])
        self._starts = [e[0] for e in self._entries]
        self._built = True

    def lookup(self, cp):
        if not self._built:
            self.build()
        idx = bisect.bisect_right(self._starts, cp) - 1
        if idx >= 0:
            start, end, cat = self._entries[idx]
            if start <= cp <= end:
                return cat
        return None


class _BoolRangeTable:
    """Sorted range table for boolean membership tests."""

    def __init__(self):
        self._ranges = []
        self._starts = []
        self._built = False

    def add(self, start, end):
        self._ranges.append((start, end))
        self._built = False

    def build(self):
        self._ranges.sort()
        self._starts = [r[0] for r in self._ranges]
        self._built = True

    def contains(self, cp):
        if not self._built:
            self.build()
        idx = bisect.bisect_right(self._starts, cp) - 1
        if idx >= 0:
            start, end = self._ranges[idx]
            return start <= cp <= end
        return False


# Global tables, lazily loaded
_grapheme_table = None
_incb_extend_table = None
_loaded = False


def _ensure_loaded():
    global _grapheme_table, _incb_extend_table, _loaded
    if _loaded:
        return

    _grapheme_table = _RangeTable()
    _incb_extend_table = _BoolRangeTable()

    # 1. Load Grapheme_Cluster_Break properties
    gbp_path = os.path.join(DATA_DIR, 'GraphemeBreakProperty.txt')
    for lo, hi, prop, value in _parse_unicode_file(gbp_path):
        _grapheme_table.add(lo, hi, prop)

    # 2. Load Extended_Pictographic from emoji-data.txt
    emoji_path = os.path.join(DATA_DIR, 'emoji-data.txt')
    for lo, hi, prop, value in _parse_unicode_file(emoji_path):
        if prop == 'Extended_Pictographic':
            _grapheme_table.add(lo, hi, Extended_Pictographic)

    # 3. Load InCB properties from DerivedCoreProperties.txt
    dcp_path = os.path.join(DATA_DIR, 'DerivedCoreProperties.txt')
    for lo, hi, prop, value in _parse_unicode_file(dcp_path):
        if prop == 'InCB' and value == 'Consonant':
            _grapheme_table.add(lo, hi, InCB_Consonant)
        elif prop == 'InCB' and value == 'Extend':
            _incb_extend_table.add(lo, hi)

    _grapheme_table.build()
    _incb_extend_table.build()
    _loaded = True


def grapheme_category(ch):
    """Return the effective Grapheme_Cluster_Break category for a character."""
    _ensure_loaded()
    cp = ord(ch)

    # Fast path for ASCII
    if cp <= 0x7E:
        if cp == 0x0A:
            return LF
        if cp == 0x0D:
            return CR
        if cp < 0x20:
            return Control
        return Any
    if cp == 0x7F:
        return Control

    cat = _grapheme_table.lookup(cp)
    return cat if cat is not None else Any


def is_incb_linker(ch):
    """Check if character has Indic_Conjunct_Break=Linker property."""
    return ord(ch) in _INCB_LINKER_CODEPOINTS


def is_incb_extend(ch):
    """Check if character has Indic_Conjunct_Break=Extend property."""
    _ensure_loaded()
    return _incb_extend_table.contains(ord(ch))
