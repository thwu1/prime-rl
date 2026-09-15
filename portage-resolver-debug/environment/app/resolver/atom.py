"""
Atom parser for Gentoo package dependency atoms.

An atom specifies a package with optional version, slot, and USE
constraints:

    [operator]category/name[-version][:slot[/subslot][=|*]][[use_deps]]

Examples::

    dev-libs/openssl                — any version
    >=dev-libs/openssl-1.1.0        — version >= 1.1.0
    =dev-libs/openssl-3.1.0:0/3    — exact version, specific slot
    dev-libs/boost:0=               — any version, slot-operator dep
    net-misc/curl[ssl,-static]      — constrain USE flags
"""

import re
from .version import Version

# Regex used as a fallback / quick-check; full parsing is done stepwise.
_VERSION_TAIL_RE = re.compile(r'-(\d[a-zA-Z0-9._]*(?:-r\d+)?)$')


class Atom:
    """A parsed Gentoo package dependency atom."""

    __slots__ = ('raw', 'operator', 'cp', 'category', 'name',
                 'version', 'slot', 'subslot', 'slot_operator', 'use_deps')

    def __init__(self, atom_str: str):
        self.raw = atom_str
        s = atom_str

        # --- 1. Strip version-comparison operator prefix ---------------
        self.operator = None
        for op in ('>=', '<=', '!=', '~', '>', '<', '='):
            if s.startswith(op):
                self.operator = op
                s = s[len(op):]
                break

        # --- 2. Strip USE dependency block  [flag1,-flag2] -------------
        self.use_deps = []
        bracket = s.find('[')
        if bracket != -1:
            end = s.index(']')
            self.use_deps = s[bracket + 1:end].split(',')
            s = s[:bracket]

        # --- 3. Strip slot specification  :slot/subslot= ---------------
        self.slot = None
        self.subslot = None
        self.slot_operator = None
        colon = s.find(':')
        if colon != -1:
            self._parse_slot(s[colon + 1:])
            s = s[:colon]

        # --- 4. Split category/name from version ----------------------
        #   The version always starts with a digit preceded by a hyphen.
        #   Package names may contain hyphens, so we match from the end.
        self.version = None
        m = _VERSION_TAIL_RE.search(s)
        if m:
            self.version = Version(m.group(1))
            s = s[:m.start()]

        self.cp = s
        parts = s.split('/', 1)
        self.category = parts[0]
        self.name = parts[1] if len(parts) > 1 else parts[0]

    # ------------------------------------------------------------------

    def _parse_slot(self, slot_str: str):
        """Parse ``slot[/subslot][=|*]``."""
        if slot_str.endswith('='):
            self.slot_operator = '='
            slot_str = slot_str[:-1]
        elif slot_str.endswith('*'):
            self.slot_operator = '*'
            slot_str = slot_str[:-1]

        if '/' in slot_str:
            self.slot, self.subslot = slot_str.split('/', 1)
        elif slot_str:
            self.slot = slot_str

    def matches_package(self, cp: str, version_str: str,
                        slot: str = None, subslot: str = None) -> bool:
        """Return whether a concrete installed package satisfies this atom."""
        if self.cp != cp:
            return False

        # No version constraint — matches anything with the right cp/slot
        if self.version is None:
            if self.slot and slot and self.slot != slot:
                return False
            return True

        pkg_ver = Version(version_str)
        op = self.operator

        if op == '>=':
            ok = pkg_ver >= self.version
        elif op == '<=':
            ok = pkg_ver <= self.version
        elif op == '>':
            ok = pkg_ver > self.version
        elif op == '<':
            ok = pkg_ver < self.version
        elif op == '~':
            # Match ignoring revision
            ok = (pkg_ver.numeric == self.version.numeric and
                  pkg_ver.letter == self.version.letter and
                  pkg_ver.suffixes == self.version.suffixes)
        elif op == '=' or op is None:
            ok = pkg_ver == self.version
        else:
            ok = False

        if ok and self.slot and slot:
            ok = self.slot == slot

        return ok

    def __repr__(self):
        return f"Atom('{self.raw}')"
