"""
Version parsing and comparison following the Gentoo Package Manager
Specification (PMS) algorithm.

Version format: [numeric][letter][suffixes][-revision]
  numeric:  dot-separated integers, e.g. 1.2.3
  letter:   single lowercase letter, optional, e.g. 1.2.3a
  suffixes: _alpha, _beta, _pre, _rc, _p with optional integer
  revision: -rN (integer)

Ordering rules per PMS:
  - Numeric parts compared component by component as integers
  - Letter: absent < a < b < ... < z
  - Suffixes: _alpha < _beta < _pre < _rc < (no suffix) < _p
  - Revision: -r0 is equivalent to absent; -r1 < -r2 < ...
"""

import re
from functools import total_ordering

# Suffix priority values per PMS specification
SUFFIX_ORDER = {
    'alpha': -4,
    'beta':  -3,
    'pre':   -2,
    'rc':    -1,
    # no suffix => 0
    'p':      1,
}

VERSION_RE = re.compile(
    r'^(\d+(?:\.\d+)*)'                      # numeric: 1.2.3
    r'([a-z])?'                                # letter: a
    r'((?:_(?:alpha|beta|pre|rc|p)\d*)*)'     # suffixes: _rc1_p2
    r'(?:-r(\d+))?$'                           # revision: -r1
)

SUFFIX_PART_RE = re.compile(r'_(alpha|beta|pre|rc|p)(\d*)')


@total_ordering
class Version:
    """A parsed and comparable Gentoo package version."""

    __slots__ = ('raw', 'numeric', 'letter', 'suffixes', 'revision')

    def __init__(self, version_str: str):
        self.raw = version_str
        m = VERSION_RE.match(version_str)
        if not m:
            raise ValueError(f"Invalid version string: {version_str}")

        self.numeric = tuple(int(c) for c in m.group(1).split('.'))
        self.letter = m.group(2) or ''

        self.suffixes = []
        if m.group(3):
            for sm in SUFFIX_PART_RE.finditer(m.group(3)):
                stype = sm.group(1)
                snum = int(sm.group(2)) if sm.group(2) else 0
                self.suffixes.append((stype, snum))

        self.revision = int(m.group(4)) if m.group(4) else 0

    def _cmp_key(self):
        """Build a comparison key tuple following PMS ordering rules."""
        num = self.numeric

        # Letter component: absent letter sorts before any letter.
        # 'a' -> ord('a')=97, 'b' -> 98, etc.
        # Absent letter -> 0 (before all printable letters)
        letter_val = ord(self.letter) if self.letter else float('inf')

        # Suffix components: map each suffix to its priority value
        suffix_key = []
        for stype, snum in self.suffixes:
            suffix_key.append((SUFFIX_ORDER.get(stype, 0), snum))
        if not suffix_key:
            suffix_key = [(0, 0)]  # no suffix has priority 0

        return (num, letter_val, tuple(suffix_key), self.revision)

    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._cmp_key() == other._cmp_key()

    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return self._cmp_key() < other._cmp_key()

    def __repr__(self):
        return f"Version('{self.raw}')"

    def __hash__(self):
        return hash(self._cmp_key())


def compare_versions(v1_str: str, v2_str: str) -> int:
    """Compare two version strings.  Returns -1, 0, or 1."""
    v1, v2 = Version(v1_str), Version(v2_str)
    if v1 < v2:
        return -1
    elif v1 == v2:
        return 0
    return 1
