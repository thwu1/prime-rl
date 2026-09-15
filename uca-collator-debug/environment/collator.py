#!/usr/bin/env python3
"""
Unicode Collation Algorithm (UCA) — Multi-component implementation.

Uses a C shared library (libimplicit.so) for implicit weight computation
and Python for the rest of the algorithm: DUCET trie lookup, CE array
construction, variable weighting, and sort key formation.

The C library must be built before this module can compute sort keys
for code points not found in the DUCET.
"""

import re
import unicodedata
import ctypes
import os


CE_PATTERN = re.compile(
    r'\[([.*])([0-9A-Fa-f]{4})\.([0-9A-Fa-f]{4})\.([0-9A-Fa-f]{4})'
    r'(?:\.([0-9A-Fa-f]{4,5}))?\]'
)


# ---------------------------------------------------------------------------
# ctypes interface for the C implicit weight library
# ---------------------------------------------------------------------------

class ImplicitWeight(ctypes.Structure):
    _fields_ = [("bbbb", ctypes.c_uint32), ("aaaa", ctypes.c_uint32)]


class ImplicitRange(ctypes.Structure):
    _fields_ = [("start", ctypes.c_uint32), ("end", ctypes.c_uint32),
                ("base", ctypes.c_uint32)]


_LIB = None


def _get_lib():
    global _LIB
    if _LIB is None:
        lib_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "lib", "libimplicit.so")
        _LIB = ctypes.CDLL(lib_path)
        _LIB.compute_implicit_weight.restype = ImplicitWeight
        _LIB.compute_implicit_weight.argtypes = [
            ctypes.c_uint32, ctypes.c_int,
            ctypes.POINTER(ImplicitRange), ctypes.c_int,
        ]
    return _LIB


# ---------------------------------------------------------------------------
# Trie data structure
# ---------------------------------------------------------------------------

class Trie:
    """Trie for longest-prefix matching of code point sequences."""

    def __init__(self):
        self._root = {}

    def insert(self, key_seq, value):
        node = self._root
        for cp in key_seq:
            if cp not in node:
                node[cp] = {}
            node = node[cp]
        node[None] = value

    def longest_prefix(self, seq):
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
        node = self._root
        for cp in seq:
            if cp not in node:
                return None
            node = node[cp]
        return node.get(None)


# ---------------------------------------------------------------------------
# UCA Collator
# ---------------------------------------------------------------------------

class UCACollator:
    """Unicode Collation Algorithm collator with C-accelerated implicit weights.

    Modes:
        NON_IGNORABLE: Variable elements retain their weights.
        SHIFTED:       Variable elements get quaternary weight; L1-L3 zeroed.
    """

    def __init__(self, allkeys_path, mode='NON_IGNORABLE'):
        if mode not in ('NON_IGNORABLE', 'SHIFTED'):
            raise ValueError(f"Unknown mode: {mode}")
        self.mode = mode
        self.trie = Trie()
        self.max_variable_primary = 0
        self.implicit_weight_ranges = []
        self._c_ranges = None
        self._c_num_ranges = 0
        self._load_ducet(allkeys_path)

    # -----------------------------------------------------------------------
    # DUCET loading
    # -----------------------------------------------------------------------

    def _load_ducet(self, path):
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
        rest = line[len('@implicitweights'):].strip()
        range_str, base_str = rest.split(';')
        start_str, end_str = range_str.strip().split('..')
        self.implicit_weight_ranges.append((
            int(start_str, 16),
            int(end_str, 16),
            int(base_str.strip(), 16),
        ))

    # -----------------------------------------------------------------------
    # Implicit weight computation (via C library)
    # -----------------------------------------------------------------------

    def _prepare_c_ranges(self):
        n = len(self.implicit_weight_ranges)
        arr_type = ImplicitRange * n
        arr = arr_type()
        for i, (start, end, base) in enumerate(self.implicit_weight_ranges):
            arr[i].start = start
            arr[i].end = end
            arr[i].base = base
        self._c_ranges = arr
        self._c_num_ranges = n

    def _compute_implicit(self, cp):
        if self._c_ranges is None:
            self._prepare_c_ranges()

        try:
            cat = unicodedata.category(chr(cp))
        except (ValueError, OverflowError):
            cat = 'Cn'

        is_assigned = 1 if cat != 'Cn' else 0
        lib = _get_lib()
        result = lib.compute_implicit_weight(
            cp, is_assigned, self._c_ranges, self._c_num_ranges
        )

        return [
            (False, result.aaaa, 0x0020, 0x0002),
            (False, result.bbbb, 0x0000, 0x0000),
        ]

    # -----------------------------------------------------------------------
    # CE array construction (S2.1-S2.5)
    # -----------------------------------------------------------------------

    def _build_ce_array(self, text):
        cps = [ord(ch) for ch in text]
        ces = []
        pos = 0

        while pos < len(cps):
            match_len, match_val = self.trie.longest_prefix(cps[pos:])

            if match_len > 0 and match_val is not None:
                matched_end = pos + match_len
                last_ccc = 0
                i = matched_end

                # S2.1.1: Try extending with unblocked non-starters
                while i < len(cps):
                    try:
                        ccc = unicodedata.combining(chr(cps[i]))
                    except (ValueError, OverflowError):
                        break
                    if ccc == 0:
                        break
                    if ccc == last_ccc:
                        last_ccc = ccc
                        i += 1
                        continue
                    last_ccc = ccc
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
                ces.extend(self._compute_implicit(cps[pos]))
                pos += 1

        return ces

    # -----------------------------------------------------------------------
    # Variable weighting
    # -----------------------------------------------------------------------

    def _apply_variable_weighting(self, ces):
        if self.mode == 'NON_IGNORABLE':
            return [(w1, w2, w3) for (_, w1, w2, w3) in ces]

        # SHIFTED mode
        result = []
        after_variable = False

        for is_var, w1, w2, w3 in ces:
            variable = is_var or (0 < w1 <= self.max_variable_primary)

            if variable:
                l4 = w1
                result.append((0, 0, 0, l4))
                after_variable = True
            elif w1 == 0 and w2 == 0 and w3 == 0:
                result.append((0, 0, 0, 0))
            elif w1 == 0 and after_variable:
                result.append((0, 0, 0, 0))
            elif w1 == 0:
                result.append((0, w2, w3, 0xFFFF))
            else:
                result.append((w1, w2, w3, 0xFFFF))

        return result

    # -----------------------------------------------------------------------
    # Sort key formation
    # -----------------------------------------------------------------------

    def sort_key(self, string):
        normalized = unicodedata.normalize("NFD", string)
        ce_array = self._build_ce_array(normalized)
        weighted = self._apply_variable_weighting(ce_array)

        num_levels = 4 if self.mode == 'SHIFTED' else 3
        key = []
        for level in range(num_levels):
            if level > 0:
                key.append(0)  # level separator
            for elem in weighted:
                w = elem[level]
                if w != 0:
                    key.append(w)

        return tuple(key)

    # -----------------------------------------------------------------------
    # Comparison
    # -----------------------------------------------------------------------

    def compare(self, s1, s2):
        k1 = self.sort_key(s1)
        k2 = self.sort_key(s2)
        if k1 < k2:
            return -1
        if k1 > k2:
            return 1
        n1 = unicodedata.normalize("NFD", s1)
        n2 = unicodedata.normalize("NFD", s2)
        if n1 < n2:
            return -1
        if n1 > n2:
            return 1
        return 0
