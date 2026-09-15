
"""
Parametric Levenshtein DFA with fuzzy dictionary search and bitpacking.

Based on the algorithm from Schulz & Mihov's paper "Fast String Correction
with Levenshtein-Automata", as described in Paul Masurel's blog post on
Levenshtein automata implementations.
"""

import struct
import math
from collections import defaultdict


# ===========================================================================
# Parametric Levenshtein DFA
# ===========================================================================

class ParametricDFA:
    """
    Precomputes a universal parametric DFA for a given max edit distance.
    The DFA operates on characteristic vectors and is query-independent.
    """

    def __init__(self, max_distance):
        self.max_D = max_distance
        self.width = 3 * max_distance + 1
        self.dfa = {}  # normalized_state -> {chi_tuple: (offset_delta, normalized_state)}
        self._accepting = {}  # normalized_state -> max_d values for acceptance check
        self._build()

    def _transitions(self, state, chi):
        """NFA transitions for a single state given a characteristic vector."""
        (offset, d) = state
        results = set()
        if d > 0:
            # deletion: consume input char, don't advance in query
            results.add((offset, d - 1))
            # substitution: consume input char, advance in query
            results.add((offset + 1, d - 1))
        # character matches (with possible insertions before)
        for k in range(min(d + 1, len(chi) - offset)):
            if offset + k < len(chi) and chi[offset + k]:
                results.add((offset + k + 1, d - k))
        return results

    def _implies(self, state1, state2):
        """Returns True if state1 implies state2 (state2 is redundant)."""
        (offset1, d1) = state1
        (offset2, d2) = state2
        if d2 < d1:
            return d1 - d2 >= abs(offset2 - offset1)
        return False

    def _simplify(self, states):
        """Remove redundant states via implication pruning."""
        states = set(states)
        result = set()
        for s in states:
            useful = True
            for s2 in states:
                if s != s2 and self._implies(s2, s):
                    useful = False
                    break
            if useful:
                result.add(s)
        return frozenset(result)

    def _step(self, chi, states):
        """One NFA step: compute transitions for all states, then simplify."""
        next_states = set()
        for state in states:
            next_states |= self._transitions(state, chi)
        return self._simplify(next_states)

    def _normalize(self, states):
        """Normalize a set of states by shifting to minimum offset."""
        if not states:
            return (0, ())
        min_offset = min(offset for (offset, _) in states)
        shifted = tuple(sorted((offset - min_offset, d) for (offset, d) in states))
        return (min_offset, shifted)

    def _enumerate_chi(self):
        """Enumerate all possible characteristic vectors of given width."""
        width = self.width
        for i in range(1 << width):
            yield tuple(bool((i >> bit) & 1) for bit in range(width))

    def _build(self):
        """Build the parametric DFA via powerset construction."""
        chi_values = list(self._enumerate_chi())

        initial = frozenset({(0, self.max_D)})
        initial_simplified = self._simplify(initial)
        _, initial_norm = self._normalize(initial_simplified)

        self.dfa = {}
        yet_to_visit = [initial_norm]
        self.dfa[initial_norm] = {}

        while yet_to_visit:
            current_norm = yet_to_visit.pop()
            transitions = {}
            for chi in chi_values:
                # Expand normalized state back with offset=0
                expanded = frozenset(current_norm)
                next_states = self._step(chi, expanded)
                (min_offset, next_norm) = self._normalize(next_states)
                transitions[chi] = (min_offset, next_norm)
                if next_norm not in self.dfa:
                    self.dfa[next_norm] = {}
                    yet_to_visit.append(next_norm)
            self.dfa[current_norm] = transitions

    def _is_accepting(self, norm_state, query_len, global_offset):
        """Check if a normalized state is accepting given query length and offset."""
        for (offset, d) in norm_state:
            if query_len - (global_offset + offset) <= d:
                return True
        return False

    def _get_distance(self, norm_state, query_len, global_offset):
        """Get the minimum edit distance for an accepting state."""
        min_dist = float('inf')
        for (offset, d) in norm_state:
            remaining = query_len - (global_offset + offset)
            if remaining <= d:
                # Errors used so far = max_D - d
                # Plus any remaining query chars that need deletion
                dist = (self.max_D - d) + max(remaining, 0)
                min_dist = min(min_dist, dist)
        if min_dist == float('inf'):
            return -1
        return min_dist

    def build_dfa(self, query):
        """Build a concrete DFA for a specific query string."""
        return ConcreteDFA(self, query)


class ConcreteDFA:
    """A concrete DFA instantiated for a specific query from a ParametricDFA."""

    def __init__(self, parametric, query):
        self.parametric = parametric
        self.query = query
        self.query_len = len(query)
        self.max_D = parametric.max_D
        self.width = parametric.width

        # States are (global_offset, normalized_state_tuple)
        # We use integer state IDs for efficiency
        self._states = {}  # int_id -> (global_offset, norm_state)
        self._state_ids = {}  # (global_offset, norm_state) -> int_id
        self._transitions = {}  # (state_id, char) -> state_id or None
        self._next_id = 0

        # Initial state
        _, initial_norm = parametric._normalize(
            parametric._simplify(frozenset({(0, parametric.max_D)}))
        )
        self.initial_state = self._get_or_create_state(0, initial_norm)

    def _get_or_create_state(self, global_offset, norm_state):
        key = (global_offset, norm_state)
        if key in self._state_ids:
            return self._state_ids[key]
        state_id = self._next_id
        self._next_id += 1
        self._state_ids[key] = state_id
        self._states[state_id] = (global_offset, norm_state)
        return state_id

    def _characteristic(self, offset):
        """Compute characteristic vector for a character position."""
        result = []
        for d in range(self.width):
            pos = offset + d
            if pos < self.query_len:
                result.append(pos)
            else:
                result.append(None)
        return result

    def step(self, state, char):
        """Transition from state on input char. Returns None for dead state."""
        if state is None:
            return None

        cache_key = (state, char)
        if cache_key in self._transitions:
            return self._transitions[cache_key]

        (global_offset, norm_state) = self._states[state]

        if not norm_state:  # dead state
            self._transitions[cache_key] = None
            return None

        # Compute characteristic vector
        chi = tuple(
            self.query[global_offset + d] == char
            if global_offset + d < self.query_len
            else False
            for d in range(self.width)
        )

        # Look up parametric transition
        if chi not in self.parametric.dfa.get(norm_state, {}):
            self._transitions[cache_key] = None
            return None

        (offset_delta, next_norm) = self.parametric.dfa[norm_state][chi]
        new_global_offset = global_offset + offset_delta

        if not next_norm:  # dead state
            self._transitions[cache_key] = None
            return None

        next_state = self._get_or_create_state(new_global_offset, next_norm)
        self._transitions[cache_key] = next_state
        return next_state

    def is_match(self, state):
        """Check if state is accepting."""
        if state is None:
            return False
        (global_offset, norm_state) = self._states[state]
        return self.parametric._is_accepting(norm_state, self.query_len, global_offset)

    def distance(self, state):
        """Return the minimum edit distance at this state, or -1 if not accepting."""
        if state is None:
            return -1
        (global_offset, norm_state) = self._states[state]
        return self.parametric._get_distance(norm_state, self.query_len, global_offset)


# ===========================================================================
# Trie + Fuzzy Search
# ===========================================================================

class _TrieNode:
    __slots__ = ['children', 'word']

    def __init__(self):
        self.children = {}
        self.word = None


class FuzzySearcher:
    """Builds a trie from a word list and searches via DFA intersection."""

    def __init__(self, words):
        self.root = _TrieNode()
        for word in words:
            node = self.root
            for ch in word:
                if ch not in node.children:
                    node.children[ch] = _TrieNode()
                node = node.children[ch]
            node.word = word

    def search(self, parametric_dfa, query):
        """
        Intersect trie with DFA for the given query.
        Returns sorted list of (word, distance) tuples.
        """
        dfa = parametric_dfa.build_dfa(query)
        results = []
        self._dfs(self.root, dfa, dfa.initial_state, results)
        results.sort()
        return results

    def _dfs(self, trie_node, dfa, dfa_state, results):
        if dfa_state is None:
            return

        # Check if current trie node is a word and DFA state is accepting
        if trie_node.word is not None and dfa.is_match(dfa_state):
            dist = dfa.distance(dfa_state)
            results.append((trie_node.word, dist))

        # Recurse into trie children
        for ch, child_node in trie_node.children.items():
            next_state = dfa.step(dfa_state, ch)
            if next_state is not None:
                self._dfs(child_node, dfa, next_state, results)


# ===========================================================================
# Bitpacking for posting lists
# ===========================================================================

def _min_bits(val):
    """Minimum number of bits to represent val (at least 1)."""
    if val == 0:
        return 0
    return val.bit_length()


def bitpack_postings(doc_ids):
    """
    Delta-encode and bitpack a sorted list of u32 doc IDs.

    Format:
      - 4 bytes little-endian: total number of doc IDs
      - For each full block of 32 deltas:
        - 1 byte: bit_width
        - (32 * bit_width) / 8 bytes: packed bits
      - Remainder (< 32 elements) stored as raw little-endian u32 deltas.
    """
    if not doc_ids:
        return b""

    # Delta encode
    deltas = [doc_ids[0]]
    for i in range(1, len(doc_ids)):
        deltas.append(doc_ids[i] - doc_ids[i - 1])

    result = bytearray()
    # Write count header
    result.extend(struct.pack('<I', len(doc_ids)))

    i = 0
    while i + 32 <= len(deltas):
        block = deltas[i:i + 32]
        bit_width = max(_min_bits(v) for v in block)
        result.append(bit_width)

        if bit_width > 0:
            total_bytes = 32 * bit_width // 8
            packed = bytearray(total_bytes)

            buffer = 0
            bits_in_buffer = 0
            byte_pos = 0

            mask = (1 << bit_width) - 1
            for val in block:
                buffer |= (val & mask) << bits_in_buffer
                bits_in_buffer += bit_width
                while bits_in_buffer >= 8:
                    packed[byte_pos] = buffer & 0xFF
                    buffer >>= 8
                    bits_in_buffer -= 8
                    byte_pos += 1

            result.extend(packed)

        i += 32

    # Remainder: raw little-endian u32 deltas
    while i < len(deltas):
        result.extend(struct.pack('<I', deltas[i]))
        i += 1

    return bytes(result)


def unpack_postings(data):
    """Reverse of bitpack_postings."""
    if not data:
        return []

    # Read count header
    total_count = struct.unpack('<I', data[0:4])[0]
    pos = 4

    deltas = []
    num_full_blocks = total_count // 32
    remainder = total_count % 32

    # Read full blocks
    for _ in range(num_full_blocks):
        bit_width = data[pos]
        pos += 1

        if bit_width == 0:
            deltas.extend([0] * 32)
        else:
            data_bytes = 32 * bit_width // 8
            buffer = 0
            bits_in_buffer = 0
            mask = (1 << bit_width) - 1

            byte_idx = pos
            for _ in range(32):
                while bits_in_buffer < bit_width:
                    buffer |= data[byte_idx] << bits_in_buffer
                    byte_idx += 1
                    bits_in_buffer += 8
                deltas.append(buffer & mask)
                buffer >>= bit_width
                bits_in_buffer -= bit_width

            pos += data_bytes

    # Read remainder as raw u32 deltas
    for _ in range(remainder):
        val = struct.unpack('<I', data[pos:pos + 4])[0]
        deltas.append(val)
        pos += 4

    # Undo delta encoding
    if not deltas:
        return []

    doc_ids = [deltas[0]]
    for i in range(1, len(deltas)):
        doc_ids.append(doc_ids[-1] + deltas[i])

    return doc_ids
