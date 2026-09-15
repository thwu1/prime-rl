
"""
Corrected Aho-Corasick multi-pattern string matching implementation.

Fixes:
  - Dictionary suffix links: output lists are merged from failure link
    targets during BFS so that patterns which are proper suffixes of the
    current trie path are reported.

New features:
  - find_leftmost_first: non-overlapping, first-pattern-wins semantics
  - find_leftmost_longest: non-overlapping, longest-match-wins semantics
  - find_streaming: chunked input with state carried across boundaries
"""

from collections import deque
from typing import List, Optional
from enum import Enum


class MatchKind(Enum):
    STANDARD = "standard"
    LEFTMOST_FIRST = "leftmost_first"
    LEFTMOST_LONGEST = "leftmost_longest"


class Match:
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
    def __init__(self, patterns: List[bytes]):
        self.patterns = patterns
        self.goto = [{}]
        self.fail = [0]
        self.output = [[]]
        self.num_states = 1
        self._build_trie()
        self._build_failure_links()

    def _build_trie(self):
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
        queue = deque()
        for byte, state in self.goto[0].items():
            self.fail[state] = 0
            queue.append(state)

        while queue:
            r = queue.popleft()
            for byte, s in self.goto[r].items():
                queue.append(s)
                state = self.fail[r]
                while state != 0 and byte not in self.goto[state]:
                    state = self.fail[state]
                self.fail[s] = self.goto[state].get(byte, 0)
                # Guard against self-referential failure link
                if self.fail[s] == s:
                    self.fail[s] = 0
                # FIX: Merge outputs from the failure link target.
                # This propagates dictionary suffix links so that patterns
                # which are proper suffixes of the current path are reported.
                self.output[s] = self.output[s] + self.output[self.fail[s]]

    def _next_state(self, state: int, byte: int) -> int:
        while state != 0 and byte not in self.goto[state]:
            state = self.fail[state]
        return self.goto[state].get(byte, 0)

    def find_all(self, haystack: bytes) -> List[Match]:
        matches = []
        state = 0
        for i, byte in enumerate(haystack):
            state = self._next_state(state, byte)
            for pid in self.output[state]:
                pattern = self.patterns[pid]
                start = i - len(pattern) + 1
                matches.append(Match(pid, start, i + 1))
        return matches

    def _select_non_overlapping(self, all_matches, prefer_longest=False):
        """Select non-overlapping matches from all overlapping matches.

        Args:
            all_matches: list of Match objects (all overlapping matches).
            prefer_longest: if True, pick the longest match at each start
                position (leftmost-longest / POSIX). If False, pick the
                match with the smallest pattern_id (leftmost-first / Perl).
        """
        if not all_matches:
            return []

        by_start = {}
        for m in all_matches:
            if m.start not in by_start:
                by_start[m.start] = []
            by_start[m.start].append(m)

        result = []
        pos = 0
        for start in sorted(by_start.keys()):
            if start < pos:
                continue
            candidates = by_start[start]
            if prefer_longest:
                # Longest match wins; ties broken by smallest pattern_id
                winner = min(candidates,
                             key=lambda m: (-(m.end - m.start), m.pattern_id))
            else:
                # First-in-pattern-list wins
                winner = min(candidates, key=lambda m: m.pattern_id)
            result.append(winner)
            pos = winner.end

        return result

    def find_leftmost_first(self, haystack: bytes) -> List[Match]:
        all_matches = self.find_all(haystack)
        return self._select_non_overlapping(all_matches, prefer_longest=False)

    def find_leftmost_longest(self, haystack: bytes) -> List[Match]:
        all_matches = self.find_all(haystack)
        return self._select_non_overlapping(all_matches, prefer_longest=True)

    def find_streaming(self, chunks: List[bytes],
                       match_kind: MatchKind = MatchKind.STANDARD) -> List[Match]:
        """Search across chunked input, maintaining automaton state."""
        matches = []
        state = 0
        global_offset = 0
        for chunk in chunks:
            for i, byte in enumerate(chunk):
                state = self._next_state(state, byte)
                global_pos = global_offset + i
                for pid in self.output[state]:
                    pattern = self.patterns[pid]
                    start = global_pos - len(pattern) + 1
                    matches.append(Match(pid, start, global_pos + 1))
            global_offset += len(chunk)

        if match_kind == MatchKind.LEFTMOST_FIRST:
            return self._select_non_overlapping(matches, prefer_longest=False)
        elif match_kind == MatchKind.LEFTMOST_LONGEST:
            return self._select_non_overlapping(matches, prefer_longest=True)
        return matches
