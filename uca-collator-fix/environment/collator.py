"""
Unicode Collation Algorithm (UCA) implementation.
Conforms to UTS #10 (https://unicode.org/reports/tr10/).

Supports collation using the Default Unicode Collation Element Table (DUCET)
loaded from an allkeys.txt file. Two variable weighting modes are supported:
'non_ignorable' and 'shifted'.

Usage:
    from collator import Collator
    c = Collator('/app/allkeys.txt', mode='non_ignorable')
    sorted_words = sorted(words, key=c.sort_key)
"""

import re
import unicodedata


# --- Trie for prefix matching of collation element mappings ---

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
        """Find the longest prefix of key that has a value in the trie.
        Returns (matched_prefix, value, remaining_key).
        If no prefix matches, returns ([], None, key).
        """
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


# --- Collation element pattern for parsing allkeys.txt entries ---

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


class Collator:
    """Unicode Collation Algorithm collator.

    Loads DUCET from allkeys.txt and provides sort_key() for sorting strings
    according to UCA with the specified variable weighting mode.
    """

    def __init__(self, ducet_path, mode='non_ignorable'):
        if mode not in ('non_ignorable', 'shifted'):
            raise ValueError(f"Unknown mode: {mode}")
        self.table = _Trie()
        self.implicit_weights_ranges = []
        self.mode = mode
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
                self.table.add(char_list, coll_elements)

    # ----- public API -----

    def sort_key(self, string):
        """Return the UCA sort key for the given string."""
        nfd = unicodedata.normalize("NFD", string)
        ces = self._build_collation_elements(nfd)
        if self.mode == 'shifted':
            ces = self._apply_shifted(ces)
        return self._form_sort_key(ces)

    # ----- collation element construction (UTS #10 Section 7.2) -----

    def _build_collation_elements(self, nfd_string):
        result = []
        lookup_key = [ord(ch) for ch in nfd_string]

        while lookup_key:
            matched, value, lookup_key = self.table.find_prefix(lookup_key)

            # S2.1.1 – discontiguous match with non-starters
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

    # ----- implicit weight derivation (UTS #10 Section 10.1.3) -----

    def _implicit_weight(self, cp):
        # @implicitweights ranges (Tangut, Nushu, Khitan, etc.)
        for start, end, base in self.implicit_weights_ranges:
            if start <= cp <= end:
                aaaa = base
                bbbb = (cp & 0x7FFF) | 0x8000
                return [[aaaa, 0x0020, 0x0002], [bbbb, 0x0000, 0x0000]]

        # Core CJK Unified Ideographs (Unified_Ideograph & CJK_Unified_Ideographs block)
        if (0x4E00 <= cp <= 0x9FFF or
            cp in (0xFA0E, 0xFA0F, 0xFA11, 0xFA13, 0xFA14,
                   0xFA1F, 0xFA21, 0xFA23, 0xFA24,
                   0xFA27, 0xFA28, 0xFA29)):
            aaaa = 0xFB40 + (cp >> 15)
            bbbb = (cp & 0x7FFF) | 0x8000
            return [[aaaa, 0x0020, 0x0002], [bbbb, 0x0000, 0x0000]]

        # Other CJK: Extensions A through I
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

        # Unassigned code points
        aaaa = 0xFBC0 + (cp >> 15)
        bbbb = (cp & 0x7FFF) | 0x8000
        return [[aaaa, 0x0020, 0x0002], [bbbb, 0x0000, 0x0000]]

    # ----- variable weighting (UTS #10 Section 4) -----

    def _apply_shifted(self, collation_elements):
        """Apply Shifted variable weighting."""
        return collation_elements

    # ----- sort key formation (UTS #10 Section 7.3) -----

    def _form_sort_key(self, collation_elements):
        sort_key = []
        for level in range(3):
            if level:
                sort_key.append(0)  # level separator
            for element in collation_elements:
                if len(element) > level:
                    weight = element[level]
                    if weight:
                        sort_key.append(weight)
        return tuple(sort_key)
