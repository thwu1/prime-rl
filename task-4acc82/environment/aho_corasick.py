"""
Aho-Corasick multi-pattern string matching implementation.

Supports standard (overlapping), leftmost-first, leftmost-longest,
and streaming search semantics.
"""

from collections import deque
from typing import List, Optional
from enum import Enum


class MatchKind(Enum):
    STANDARD = "standard"
    LEFTMOST_FIRST = "leftmost_first"
    LEFTMOST_LONGEST = "leftmost_longest"


class Match:
    """Represents a match found during search."""

    def __init__(self, pattern_id: int, start: int, end: int):
        self.pattern_id = pattern_id
        self.start = start
        self.end = end

    def __repr__(self):
        return f"Match(id={self.pattern_id}, start={self.start}, end={self.end})"

    def __eq__(self, other):
        if not isinstance(other, Match):
            return NotImplemented
        return (self.pattern_id == other.pattern_id and
                self.start == other.start and
                self.end == other.end)

    def __hash__(self):
        return hash((self.pattern_id, self.start, self.end))


class AhoCorasick:
    """
    Aho-Corasick automaton for multi-pattern string matching.

    Builds a finite state machine from a list of byte-string patterns
    and supports searching a haystack for all occurrences.
    """

    def __init__(self, patterns: List[bytes]):
        self.patterns = patterns
        self.goto = [{}]           # goto function: state -> {byte -> state}
        self.fail = [0]            # failure links
        self.output = [[]]         # output function: state -> [pattern_ids]
        self.num_states = 1
        self._build_trie()
        self._build_failure_links()

    def _build_trie(self):
        """Build the goto function (trie) from patterns."""
        for pid, pattern in enumerate(self.patterns):
            state = 0
            for byte in pattern:
                if byte not in self.goto[state]:
                    self.goto.append({})
                    self.fail.append(0)
                    self.output.append([])
                    self.goto[state][byte] = self.num_states
                    self.num_states += 1
                state = self.goto[state][byte]
            self.output[state].append(pid)

    def _build_failure_links(self):
        """Build failure links using BFS from root."""
        queue = deque()
        # Depth-1 states have failure link to root
        for byte, state in self.goto[0].items():
            self.fail[state] = 0
            queue.append(state)

        # BFS to compute failure links for deeper states
        while queue:
            r = queue.popleft()
            for byte, s in self.goto[r].items():
                queue.append(s)
                state = self.fail[r]
                while state != 0 and byte not in self.goto[state]:
                    state = self.fail[state]
                self.fail[s] = self.goto[state].get(byte, 0)

    def _next_state(self, state: int, byte: int) -> int:
        """Transition to next state, following failure links as needed."""
        while state != 0 and byte not in self.goto[state]:
            state = self.fail[state]
        return self.goto[state].get(byte, 0)

    def find_all(self, haystack: bytes) -> List[Match]:
        """Find all overlapping matches (STANDARD semantics)."""
        matches = []
        state = 0
        for i, byte in enumerate(haystack):
            state = self._next_state(state, byte)
            for pid in self.output[state]:
                pattern = self.patterns[pid]
                start = i - len(pattern) + 1
                matches.append(Match(pid, start, i + 1))
        return matches

    def find_leftmost_first(self, haystack: bytes) -> List[Match]:
        """
        Find non-overlapping matches with leftmost-first semantics.

        At each leftmost match position, the pattern appearing earliest
        in the pattern list wins (like Perl-style regex alternation).
        """
        raise NotImplementedError("leftmost-first matching not implemented")

    def find_leftmost_longest(self, haystack: bytes) -> List[Match]:
        """
        Find non-overlapping matches with leftmost-longest semantics.

        At each leftmost match position, the longest match wins.
        Ties broken by smallest pattern ID (POSIX-style).
        """
        raise NotImplementedError("leftmost-longest matching not implemented")

    def find_streaming(self, chunks: List[bytes],
                       match_kind: MatchKind = MatchKind.STANDARD) -> List[Match]:
        """
        Find matches across chunked input.

        Processes byte chunks sequentially while maintaining automaton state
        across chunk boundaries. Returns the same results as searching the
        concatenated input.
        """
        raise NotImplementedError("streaming search not implemented")
