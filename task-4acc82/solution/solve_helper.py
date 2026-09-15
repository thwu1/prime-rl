#!/usr/bin/env python3

"""
Fixes both broken components of the pattern matching pipeline:

1. Aho-Corasick (/app/aho_corasick.py):
   - Bug: dictionary suffix links not propagated — during BFS failure link
     construction, each state's output list must be merged with the output
     of its failure link target. Without this, patterns that are proper
     suffixes of the current trie path (e.g., "he" inside "she") are missed.
   - Missing: find_leftmost_first — non-overlapping matches where the pattern
     with the smallest ID wins at each leftmost position (Perl-style).
   - Missing: find_leftmost_longest — non-overlapping matches where the
     longest pattern wins at each leftmost position (POSIX-style).
   - Missing: find_streaming — search across chunked input maintaining
     automaton state between chunks with global offset tracking.

2. Pipeline (/app/pipeline.sh):
   - Missing --hidden flag: .app_errors.log (hidden dotfile) is not searched
   - Missing -a flag: binary_mixed.log (contains NUL bytes) is skipped because
     ripgrep detects it as binary and suppresses output. Note: --binary is NOT
     sufficient — it searches but still suppresses output from binary-detected
     files. -a/--text disables binary detection entirely.
   - Missing -U flag + \\s+ pattern: exceptions.log has multiline entries where
     code= and msg= are on separate lines (continuation format)
   - Missing -i flag: app_events.log uses lowercase error codes (e001, e004)
   - Greedy .+ quantifier: overcaptures beyond the first closing quote;
     must be replaced with [^"]*
   - Missing normalization: -i causes lowercase codes to be extracted verbatim,
     which then fail the case-sensitive xsv join. An uppercase normalization
     step (awk toupper) is needed before the join.
"""

import os
import stat


def write_fixed_aho_corasick():
    """Write the corrected Aho-Corasick implementation."""
    code = '''"""
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
        self.goto = [{}]
        self.fail = [0]
        self.output = [[]]
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
        """
        Find non-overlapping matches with leftmost-first semantics.

        At each leftmost match position, the pattern appearing earliest
        in the pattern list wins (like Perl-style regex alternation).
        """
        all_matches = self.find_all(haystack)
        return self._select_non_overlapping(all_matches, prefer_longest=False)

    def find_leftmost_longest(self, haystack: bytes) -> List[Match]:
        """
        Find non-overlapping matches with leftmost-longest semantics.

        At each leftmost match position, the longest match wins.
        Ties broken by smallest pattern ID (POSIX-style).
        """
        all_matches = self.find_all(haystack)
        return self._select_non_overlapping(all_matches, prefer_longest=True)

    def find_streaming(self, chunks: List[bytes],
                       match_kind: MatchKind = MatchKind.STANDARD) -> List[Match]:
        """
        Find matches across chunked input.

        Processes byte chunks sequentially while maintaining automaton state
        across chunk boundaries. Returns the same results as searching the
        concatenated input.
        """
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
'''
    with open('/app/aho_corasick.py', 'w') as f:
        f.write(code)


def write_fixed_pipeline():
    """Write the corrected pipeline.sh."""
    pipeline = r'''#!/bin/bash
# Log analysis pipeline — corrected version
set -e

OUTPUT_DIR="/app/output"
mkdir -p "$OUTPUT_DIR"
TMP_DIR=$(mktemp -d)

# Step 1: Extract error code and message from ALL log files
# Flags:
#   -i           case-insensitive (handles lowercase codes like e001)
#   --hidden     include hidden dotfiles (.app_errors.log)
#   -a           treat binary files as text (binary_mixed.log); --binary
#                alone suppresses output from binary-detected files
#   -U           multiline mode so \s+ can cross line boundaries
# Pattern changes:
#   \s+ instead of single space (spans continuation lines)
#   [^"]* instead of .+ (non-greedy message capture)
rg -i -U --hidden -a \
   'code=([eE]\d{3})\s+msg="([^"]*)"' /app/logs/ \
   --no-filename -o -r '$1,$2' \
   > "$TMP_DIR/raw.csv"

# Step 2: Normalize error codes to uppercase and add CSV header
# The -i flag extracts lowercase codes verbatim (e001, e004 from
# app_events.log). These must be uppercased before the case-sensitive
# xsv join against reference.csv which uses uppercase keys.
echo "error_code,message" > "$TMP_DIR/errors.csv"
awk -F, '{$1=toupper($1); print $1","$2}' "$TMP_DIR/raw.csv" \
   >> "$TMP_DIR/errors.csv"

# Step 3: Join with reference data to add category and severity
xsv join error_code "$TMP_DIR/errors.csv" \
   error_code /app/reference.csv \
   > "$TMP_DIR/joined.csv"

# Step 4: Aggregate and produce final results
python3 /app/aggregate.py "$TMP_DIR/joined.csv" "$OUTPUT_DIR/results.csv"

rm -rf "$TMP_DIR"
'''
    with open('/app/pipeline.sh', 'w') as f:
        f.write(pipeline)
    os.chmod('/app/pipeline.sh', 0o755)


if __name__ == '__main__':
    print("Fixing Aho-Corasick implementation...")
    write_fixed_aho_corasick()
    print("  - Added dictionary suffix link propagation")
    print("  - Implemented find_leftmost_first")
    print("  - Implemented find_leftmost_longest")
    print("  - Implemented find_streaming")

    print("\nFixing pipeline.sh...")
    write_fixed_pipeline()
    print("  - Added -i (case-insensitive)")
    print("  - Added --hidden (dotfiles)")
    print("  - Added -a (binary-as-text)")
    print("  - Added -U (multiline)")
    print("  - Changed regex: \\s+ for line-spanning, [^\"]*  for non-greedy")
    print("  - Added awk toupper normalization before xsv join")
    print("\nReady to run pipeline.")
