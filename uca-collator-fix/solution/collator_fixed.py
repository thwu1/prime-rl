"""

Fixed Unicode Collation Algorithm (UCA) implementation.

Fixes applied:
1. Implicit weight BBBB formula for @implicitweights ranges:
   changed (cp & 0x7FFF) | 0x8000 → (cp - start) | 0x8000
2. Added variable element tracking: parse * vs . prefix in allkeys.txt,
   compute variable_max (highest L1 weight of any variable element).
3. Implemented Shifted variable weighting per UTS #10 Section 4 / Table 11.
4. Updated sort key formation to support 4 levels for Shifted mode.
"""

import re
import unicodedata


class _TrieNode:
    __slots__ = ('children', 'value')
    def __init__(self):
        self.children = {}
        self.value = None


class _Trie:
    def __init__(self):
        self.root = _TrieNode()

    def add(self, key, value):
        node = self.root
        for k in key:
            if k not in node.children:
                node.children[k] = _TrieNode()
            node = node.children[k]
        node.value = value

    def find_prefix(self, key):
        node = self.root
        last_match_value = None
        last_match_pos = 0
        for i, k in enumerate(key):
            if k not in node.children:
                break
            node = node.children[k]
            if node.value is not None:
                last_match_value = node.value
                last_match_pos = i + 1
        if last_match_value is not None:
            return key[:last_match_pos], last_match_value, key[last_match_pos:]
        return [], None, key


COLL_ELEMENT_PATTERN = re.compile(r"""
    \[
    (?:\*|\.)
    ([0-9A-Fa-f]{4})
    \.
    ([0-9A-Fa-f]{4})
    \.
    ([0-9A-Fa-f]{4})
    (?:\.[0-9A-Fa-f]{4,5})?
    \]
""", re.X)

# Matches only variable CEs (those prefixed with *) and captures L1 weight
_VAR_CE_L1_PATTERN = re.compile(r'\[\*([0-9A-Fa-f]{4})')


class Collator:
    def __init__(self, ducet_path, mode='non_ignorable'):
        if mode not in ('non_ignorable', 'shifted'):
            raise ValueError(f"Unknown mode: {mode}")
        self.table = _Trie()
        self.implicit_weights_ranges = []
        self.mode = mode
        self.variable_max = 0  # FIX: track max primary weight of variable CEs
        self._load(ducet_path)

    def _load(self, path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.split("#", 1)[0].rstrip()
                if not line or line.startswith("@version"):
                    continue
                if line.startswith("@implicitweights"):
                    payload = line[len("@implicitweights"):]
                    range_part, base_part = payload.split(";")
                    rng_start, rng_end = range_part.strip().split("..")
                    self.implicit_weights_ranges.append([
                        int(rng_start, 16),
                        int(rng_end, 16),
                        int(base_part.strip(), 16),
                    ])
                    continue
                a, b = line.split(";", 1)
                char_list = [int(x, 16) for x in a.split()]
                coll_elements = []
                for m in COLL_ELEMENT_PATTERN.finditer(b):
                    weights = [int(w, 16) for w in m.groups()]
                    coll_elements.append(weights)

                # FIX: track variable_max from CEs specifically marked with *
                for vm in _VAR_CE_L1_PATTERN.finditer(b):
                    l1 = int(vm.group(1), 16)
                    if l1 > self.variable_max:
                        self.variable_max = l1

                self.table.add(char_list, coll_elements)

    def sort_key(self, string):
        nfd = unicodedata.normalize("NFD", string)
        ces = self._build_collation_elements(nfd)
        if self.mode == 'shifted':
            ces = self._apply_shifted(ces)
        return self._form_sort_key(ces)

    def _build_collation_elements(self, nfd_string):
        result = []
        lookup_key = [ord(ch) for ch in nfd_string]

        while lookup_key:
            matched, value, lookup_key = self.table.find_prefix(lookup_key)

            last_class = None
            for i, C in enumerate(lookup_key):
                cc = unicodedata.combining(chr(C))
                if cc == 0 or cc == last_class:
                    break
                last_class = cc
                trial_s, trial_v, trial_rest = self.table.find_prefix(
                    matched + [C]
                )
                if trial_rest == [] and trial_v is not None:
                    lookup_key = lookup_key[:i] + lookup_key[i + 1:]
                    value = trial_v
                    break

            if value is None:
                cp = lookup_key.pop(0)
                value = self._implicit_weight(cp)

            result.extend(value)

        return result

    def _implicit_weight(self, cp):
        # FIX: @implicitweights ranges use range-relative offset for BBBB
        for start, end, base in self.implicit_weights_ranges:
            if start <= cp <= end:
                aaaa = base
                bbbb = (cp - start) | 0x8000  # FIX: was (cp & 0x7FFF) | 0x8000
                return [[aaaa, 0x0020, 0x0002], [bbbb, 0x0000, 0x0000]]

        if (0x4E00 <= cp <= 0x9FFF or
            cp in (0xFA0E, 0xFA0F, 0xFA11, 0xFA13, 0xFA14,
                   0xFA1F, 0xFA21, 0xFA23, 0xFA24,
                   0xFA27, 0xFA28, 0xFA29)):
            aaaa = 0xFB40 + (cp >> 15)
            bbbb = (cp & 0x7FFF) | 0x8000
            return [[aaaa, 0x0020, 0x0002], [bbbb, 0x0000, 0x0000]]

        if (0x3400 <= cp <= 0x4DBF or
            0x20000 <= cp <= 0x2A6DF or
            0x2A700 <= cp <= 0x2B739 or
            0x2B740 <= cp <= 0x2B81D or
            0x2B820 <= cp <= 0x2CEAF or
            0x2CEB0 <= cp <= 0x2EBE0 or
            0x2EBF0 <= cp <= 0x2F7FF or
            0x30000 <= cp <= 0x3134A or
            0x31350 <= cp <= 0x323AF):
            aaaa = 0xFB80 + (cp >> 15)
            bbbb = (cp & 0x7FFF) | 0x8000
            return [[aaaa, 0x0020, 0x0002], [bbbb, 0x0000, 0x0000]]

        aaaa = 0xFBC0 + (cp >> 15)
        bbbb = (cp & 0x7FFF) | 0x8000
        return [[aaaa, 0x0020, 0x0002], [bbbb, 0x0000, 0x0000]]

    # FIX: full Shifted variable weighting implementation (UTS #10 Section 4)
    def _apply_shifted(self, collation_elements):
        """Apply Shifted variable weighting per UTS #10 Section 4 / Table 11.

        Variable CEs (0 < L1 <= variable_max): zero L1-L3, L4 = old L1.
        Ignorable CEs following a variable: all four levels zeroed.
        Non-variable CEs: L1-L3 unchanged, L4 = 0xFFFF.
        Completely ignorable CEs (L1=L2=L3=0): always [0,0,0,0].
        """
        result = []
        after_variable = False

        for ce in collation_elements:
            l1 = ce[0]
            l2 = ce[1] if len(ce) > 1 else 0
            l3 = ce[2] if len(ce) > 2 else 0

            if l1 == 0 and l2 == 0 and l3 == 0:
                # Completely ignorable
                result.append([0, 0, 0, 0])
            elif 0 < l1 <= self.variable_max:
                # Variable element: zero L1-L3, L4 = old L1
                result.append([0, 0, 0, l1])
                after_variable = True
            elif l1 == 0 and after_variable:
                # Ignorable following a variable: all zero
                result.append([0, 0, 0, 0])
            elif l1 == 0:
                # Secondary/tertiary element, not following a variable
                result.append([0, l2, l3, 0xFFFF])
            else:
                # Non-variable primary element
                result.append([l1, l2, l3, 0xFFFF])
                after_variable = False

        return result

    # FIX: support 4-level sort keys for Shifted mode
    def _form_sort_key(self, collation_elements):
        sort_key = []
        num_levels = 4 if self.mode == 'shifted' else 3
        for level in range(num_levels):
            if level:
                sort_key.append(0)  # level separator
            for element in collation_elements:
                if len(element) > level:
                    weight = element[level]
                    if weight:
                        sort_key.append(weight)
        return tuple(sort_key)
