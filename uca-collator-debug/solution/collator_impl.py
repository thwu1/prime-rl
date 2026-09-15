#!/usr/bin/env python3
"""
Complete Unicode Collation Algorithm (UCA) implementation.

This file replaces the skeleton at /app/collator.py with the full
working implementation of all algorithm methods.

Reference: Unicode Technical Standard #10 (UTS #10)
"""

import re
import unicodedata


CE_PATTERN = re.compile(
    r'\[([.*])([0-9A-Fa-f]{4})\.([0-9A-Fa-f]{4})\.([0-9A-Fa-f]{4})'
    r'(?:\.([0-9A-Fa-f]{4,5}))?\]'
)


class Trie:
    """Trie for longest-prefix matching of code point sequences."""

    def __init__(self):
        self._root = {}

    def insert(self, key_seq, value):
        """Insert a code point sequence with its value."""
        node = self._root
        for cp in key_seq:
            if cp not in node:
                node[cp] = {}
            node = node[cp]
        node[None] = value

    def longest_prefix(self, seq):
        """Find longest prefix of seq in the trie.

        Returns (matched_length, value).
        matched_length=0 and value=None if nothing matched.
        """
        node = self._root
        best_len = 0
        best_val = None
        for i, cp in enumerate(seq):
            if cp not in node:
                break
            node = node[cp]
            if None in node:
                best_len = i + 1
                best_val = node[None]
        return best_len, best_val

    def lookup(self, seq):
        """Exact match lookup for a code point sequence."""
        node = self._root
        for cp in seq:
            if cp not in node:
                return None
            node = node[cp]
        return node.get(None)


class UCACollator:
    """Unicode Collation Algorithm collator.

    Modes:
        NON_IGNORABLE: Variable elements keep their weights unchanged.
        SHIFTED: Variable elements get quaternary weight; L1-L3 zeroed.
    """

    def __init__(self, allkeys_path, mode='NON_IGNORABLE'):
        if mode not in ('NON_IGNORABLE', 'SHIFTED'):
            raise ValueError(f"Unknown mode: {mode}")
        self.mode = mode
        self.trie = Trie()
        self.max_variable_primary = 0
        self.implicit_weight_ranges = []
        self._load_ducet(allkeys_path)

    def _load_ducet(self, path):
        """Parse the DUCET from allkeys.txt."""
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.split('#', 1)[0].split('%', 1)[0].strip()

                if not line or line.startswith('@version'):
                    continue

                if line.startswith('@implicitweights'):
                    self._parse_implicit_directive(line)
                    continue

                if ';' not in line:
                    continue

                char_part, ce_part = line.split(';', 1)

                codepoints = [int(tok, 16) for tok in char_part.split()]

                ces = []
                for m in CE_PATTERN.finditer(ce_part):
                    is_var = m.group(1) == '*'
                    w1 = int(m.group(2), 16)
                    w2 = int(m.group(3), 16)
                    w3 = int(m.group(4), 16)
                    ces.append((is_var, w1, w2, w3))

                    if is_var and w1 > self.max_variable_primary:
                        self.max_variable_primary = w1

                if ces:
                    self.trie.insert(codepoints, ces)

    def _parse_implicit_directive(self, line):
        """Parse an @implicitweights directive from allkeys.txt."""
        rest = line[len('@implicitweights'):].strip()
        range_str, base_str = rest.split(';')
        start_str, end_str = range_str.strip().split('..')
        self.implicit_weight_ranges.append((
            int(start_str, 16),
            int(end_str, 16),
            int(base_str.strip(), 16),
        ))

    @staticmethod
    def _is_core_han(cp):
        """Check if cp is a Core Han Unified Ideograph."""
        if 0x4E00 <= cp <= 0x9FFF:
            return True
        return cp in (
            0xFA0E, 0xFA0F, 0xFA11, 0xFA13, 0xFA14,
            0xFA1F, 0xFA21, 0xFA23, 0xFA24,
            0xFA27, 0xFA28, 0xFA29,
        )

    @staticmethod
    def _is_other_han(cp):
        """Check if cp is an Other Han Unified Ideograph."""
        return (
            (0x3400 <= cp <= 0x4DBF) or
            (0x20000 <= cp <= 0x2A6DF) or
            (0x2A700 <= cp <= 0x2B739) or
            (0x2B740 <= cp <= 0x2B81D) or
            (0x2B820 <= cp <= 0x2CEA1) or
            (0x2CEB0 <= cp <= 0x2EBE0) or
            (0x30000 <= cp <= 0x3134A) or
            (0x31350 <= cp <= 0x323AF)
        )

    def _compute_implicit(self, cp):
        """Compute implicit collation elements for a code point not in DUCET.

        Returns a list of (is_variable, w1, w2, w3) tuples.
        """
        try:
            cat = unicodedata.category(chr(cp))
        except (ValueError, OverflowError):
            cat = 'Cn'

        # Siniform ideographic scripts (@implicitweights ranges)
        for start, end, base in self.implicit_weight_ranges:
            if start <= cp <= end and cat != 'Cn':
                aaaa = base
                bbbb = (cp - start) | 0x8000
                return [
                    (False, aaaa, 0x0020, 0x0002),
                    (False, bbbb, 0x0000, 0x0000),
                ]

        # Core Han Unified Ideographs
        if cat != 'Cn' and self._is_core_han(cp):
            aaaa = 0xFB40 + (cp >> 15)
            bbbb = (cp & 0x7FFF) | 0x8000
            return [
                (False, aaaa, 0x0020, 0x0002),
                (False, bbbb, 0x0000, 0x0000),
            ]

        # Other Han Unified Ideographs (extensions)
        if cat != 'Cn' and self._is_other_han(cp):
            aaaa = 0xFB80 + (cp >> 15)
            bbbb = (cp & 0x7FFF) | 0x8000
            return [
                (False, aaaa, 0x0020, 0x0002),
                (False, bbbb, 0x0000, 0x0000),
            ]

        # Unassigned and everything else
        aaaa = 0xFBC0 + (cp >> 15)
        bbbb = (cp & 0x7FFF) | 0x8000
        return [
            (False, aaaa, 0x0020, 0x0002),
            (False, bbbb, 0x0000, 0x0000),
        ]

    def _build_ce_array(self, text):
        """Build collation element array from (normalized) text.

        Implements Steps S2.1-S2.5 of the UCA main algorithm.
        """
        cps = [ord(ch) for ch in text]
        ces = []
        pos = 0

        while pos < len(cps):
            # S2.1: Find the longest initial substring with a match
            match_len, match_val = self.trie.longest_prefix(cps[pos:])

            if match_len > 0 and match_val is not None:
                # S2.1.1-S2.1.3: Check for discontiguous matches
                matched_end = pos + match_len
                last_ccc = 0
                i = matched_end
                while i < len(cps):
                    try:
                        ccc = unicodedata.combining(chr(cps[i]))
                    except (ValueError, OverflowError):
                        break
                    if ccc == 0:
                        break  # Reached a starter
                    if ccc == last_ccc:
                        # Blocked by same combining class
                        last_ccc = ccc
                        i += 1
                        continue
                    last_ccc = ccc
                    # Try extending the matched prefix with this non-starter
                    trial = cps[pos:matched_end] + [cps[i]]
                    trial_val = self.trie.lookup(trial)
                    if trial_val is not None:
                        match_val = trial_val
                        cps = cps[:i] + cps[i + 1:]
                        continue
                    i += 1

                ces.extend(match_val)
                pos = matched_end
            else:
                # S2.2: No match — derive implicit collation element
                ces.extend(self._compute_implicit(cps[pos]))
                pos += 1

        return ces

    def _apply_variable_weighting(self, ces):
        """Apply variable weighting to the collation element array.

        NON_IGNORABLE: no weight changes; strip the variable flag.
        SHIFTED: variable elements become quaternary, L1-L3 zeroed.
        """
        if self.mode == 'NON_IGNORABLE':
            return [(w1, w2, w3) for (_, w1, w2, w3) in ces]

        # SHIFTED mode
        result = []
        after_variable = False

        for is_var, w1, w2, w3 in ces:
            variable = is_var or (0 < w1 <= self.max_variable_primary)

            if variable:
                # Variable element: zero L1-L3, L4 = original primary weight
                l4 = w1
                result.append((0, 0, 0, l4))
                after_variable = True
            elif w1 == 0 and w2 == 0 and w3 == 0:
                # Completely ignorable
                result.append((0, 0, 0, 0))
            elif w1 == 0 and after_variable:
                # Ignorable CE following a variable — zero everything
                result.append((0, 0, 0, 0))
            elif w1 == 0:
                # Ignorable CE NOT following a variable
                result.append((0, w2, w3, 0xFFFF))
            else:
                # Non-variable, non-ignorable
                result.append((w1, w2, w3, 0xFFFF))
                after_variable = False

        return result

    def sort_key(self, string):
        """Generate a UCA sort key for *string*.

        Steps:
        1. Normalize input to NFD
        2. Build collation element array
        3. Apply variable weighting
        4. Form multi-level sort key
        """
        # Step 1: Normalize the input string to NFD
        normalized = unicodedata.normalize("NFD", string)

        # Step 2: Build CE array
        ce_array = self._build_ce_array(normalized)

        # Step 3: Apply variable weighting
        weighted = self._apply_variable_weighting(ce_array)

        # Step 4: Form sort key (levels 1-3 for NON_IGNORABLE, 1-4 for SHIFTED)
        num_levels = 4 if self.mode == 'SHIFTED' else 3
        key = []
        for level in range(num_levels):
            if level > 0:
                key.append(0)  # Level separator
            for elem in weighted:
                w = elem[level]
                if w != 0:
                    key.append(w)

        return tuple(key)

    def compare(self, s1, s2):
        """Compare two strings using UCA.

        Returns -1 if s1 < s2, 0 if equal, 1 if s1 > s2.
        Uses identical level (S3.10) as final tiebreaker.
        """
        k1 = self.sort_key(s1)
        k2 = self.sort_key(s2)

        if k1 < k2:
            return -1
        if k1 > k2:
            return 1

        # Identical level: compare NFD forms as binary strings
        n1 = unicodedata.normalize("NFD", s1)
        n2 = unicodedata.normalize("NFD", s2)
        if n1 < n2:
            return -1
        if n1 > n2:
            return 1
        return 0
