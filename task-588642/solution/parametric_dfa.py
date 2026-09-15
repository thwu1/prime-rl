#!/usr/bin/env python3
"""
Parametric Levenshtein DFA implementation.

Implements the Schulz-Mihov algorithm: precomputes a query-independent
parametric automaton that can be instantiated for any query string at
evaluation time using characteristic vectors.

"""


class LevenshteinParametricDFA:
    """A parametric DFA for Levenshtein distance matching.

    The DFA is precomputed once per max_distance and can be reused
    for any query string.
    """

    def __init__(self, max_distance):
        self.max_distance = max_distance
        self.dfa = {}
        self.initial_state = None
        self.dead_state = frozenset()
        self._build()

    # ------------------------------------------------------------------
    # NFA primitives
    # ------------------------------------------------------------------

    def _nfa_transitions(self, state, chi):
        """Compute NFA transitions for a single (offset, d) state.

        chi is a tuple of bools of width 3*D+1.
        """
        offset, d = state
        results = set()
        # deletion: skip candidate character, consume 1 edit
        if d > 0:
            results.add((offset, d - 1))
        # substitution: advance offset, consume 1 edit
        if d > 0:
            results.add((offset + 1, d - 1))
        # k insertions (from query) + exact match of candidate char
        for k in range(min(d + 1, len(chi) - offset)):
            if offset + k < len(chi) and chi[offset + k]:
                results.add((offset + k + 1, d - k))
        return results

    def _implies(self, s1, s2):
        """Check whether state s1 implies (subsumes) state s2.

        (o1,d1) implies (o2,d2) iff d1 >= d2 and d1 - d2 >= |o1 - o2|.
        Meaning: anything s2 can still match, s1 can also match.
        """
        o1, d1 = s1
        o2, d2 = s2
        return d1 >= d2 and (d1 - d2) >= abs(o1 - o2)

    def _simplify(self, states):
        """Remove states that are implied by another state in the set."""
        states = set(states)
        useful = set()
        for s in states:
            keep = True
            for s2 in states:
                if s != s2 and self._implies(s2, s):
                    keep = False
                    break
            if keep:
                useful.add(s)
        return frozenset(useful)

    def _normalize(self, states):
        """Shift all offsets so the minimum becomes 0.

        Returns (min_offset, normalized_frozenset).
        """
        if not states:
            return (0, frozenset())
        min_offset = min(o for o, _ in states)
        shifted = frozenset((o - min_offset, d) for o, d in states)
        return (min_offset, shifted)

    def _step(self, chi, states):
        """Compute the next simplified state set given chi and current states."""
        next_states = set()
        for state in states:
            next_states |= self._nfa_transitions(state, chi)
        return self._simplify(next_states)

    # ------------------------------------------------------------------
    # DFA construction
    # ------------------------------------------------------------------

    def _build(self):
        """Build the parametric DFA via powerset construction."""
        D = self.max_distance
        width = 3 * D + 1

        # Enumerate all 2^width possible characteristic vectors
        chi_values = []
        for i in range(1 << width):
            chi = tuple(bool(i & (1 << j)) for j in range(width))
            chi_values.append(chi)

        # Initial parametric state
        initial_raw = frozenset({(0, D)})
        _, norm_initial = self._normalize(initial_raw)
        self.initial_state = norm_initial

        # BFS over reachable parametric states
        self.dfa = {}
        queue = [norm_initial]
        visited = {norm_initial}

        while queue:
            current = queue.pop(0)
            transitions = {}
            for chi in chi_values:
                next_raw = self._step(chi, current)
                delta, norm_next = self._normalize(next_raw)
                transitions[chi] = (delta, norm_next)
                if norm_next not in visited:
                    visited.add(norm_next)
                    queue.append(norm_next)
            self.dfa[current] = transitions

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def eval(self, query, candidate):
        """Evaluate whether candidate is within max_distance of query.

        Returns (match: bool, distance: int).
        distance is -1 when not matching.
        """
        D = self.max_distance
        width = 3 * D + 1
        query_len = len(query)

        state = self.initial_state
        global_offset = 0

        for c in candidate:
            # Compute characteristic vector at current global offset
            chi = tuple(
                (global_offset + k < query_len
                 and query[global_offset + k] == c)
                for k in range(width)
            )

            if state not in self.dfa:
                return (False, -1)

            delta, next_state = self.dfa[state][chi]
            global_offset += delta
            state = next_state

            # Early exit on dead state
            if not state:
                return (False, -1)

        # Check acceptance: can we account for remaining query chars?
        min_dist = float('inf')
        for offset, d in state:
            remaining = query_len - (global_offset + offset)
            if remaining < 0:
                remaining = 0
            if remaining <= d:
                dist = (D - d) + remaining
                if dist < min_dist:
                    min_dist = dist

        if min_dist <= D:
            return (True, int(min_dist))
        return (False, -1)

    def fuzzy_search(self, query, dictionary):
        """Find all words in dictionary within max_distance of query.

        Returns list of (word, distance) sorted by (distance, word).
        """
        results = []
        for word in dictionary:
            match, dist = self.eval(query, word)
            if match:
                results.append((word, dist))
        return sorted(results, key=lambda x: (x[1], x[0]))

    def num_states(self):
        """Return the number of non-dead parametric states."""
        return len([s for s in self.dfa if s])
