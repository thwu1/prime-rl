#!/usr/bin/env python3
"""Suffix array-accelerated code search engine.

"""

import os
import sys
import re
import pickle
import bisect
import argparse
from functools import cmp_to_key


def build_suffix_array(text):
    """Build suffix array using prefix doubling in O(n log^2 n) time.

    Returns a list of indices representing the sorted order of all suffixes.
    """
    n = len(text)
    if n == 0:
        return []

    # Initial ranking by single character
    sa = list(range(n))
    rank = [ord(c) for c in text]
    new_rank = [0] * n

    k = 1
    while k < n:
        # Sort by (rank[i], rank[i+k]) pairs
        def sort_key(i, _k=k, _rank=rank, _n=n):
            return (_rank[i], _rank[i + _k] if i + _k < _n else -1)

        sa.sort(key=sort_key)

        # Recompute ranks based on sorted order
        new_rank[sa[0]] = 0
        for i in range(1, n):
            new_rank[sa[i]] = new_rank[sa[i - 1]]
            if sort_key(sa[i]) != sort_key(sa[i - 1]):
                new_rank[sa[i]] += 1

        rank = new_rank[:]

        # Early termination: all ranks are unique
        if rank[sa[-1]] == n - 1:
            break

        k *= 2

    return sa


def extract_literal_factor(pattern):
    """Extract the longest guaranteed literal substring from a regex pattern.

    Walks the pattern character by character, identifying contiguous literal
    segments. Metacharacters and quantifiers break segments. Quantifiers that
    allow zero occurrences (*, ?) cause the preceding character to be excluded
    from the literal.

    Returns the longest such segment.
    """
    segments = []
    current = []
    i = 0
    n = len(pattern)

    while i < n:
        c = pattern[i]

        if c == '\\' and i + 1 < n:
            next_c = pattern[i + 1]
            # Regex-specific escape sequences are not literal
            if next_c in 'dDwWsSbBAZB':
                if current:
                    segments.append(''.join(current))
                    current = []
                i += 2
            elif next_c.isdigit():
                # Backreference
                if current:
                    segments.append(''.join(current))
                    current = []
                i += 2
            else:
                # Escaped metacharacter is literal
                current.append(next_c)
                i += 2
        elif c in '*?':
            # Zero-or-more / zero-or-one: previous char may not appear
            if current:
                current.pop()
                if current:
                    segments.append(''.join(current))
                    current = []
            i += 1
        elif c == '+':
            # One-or-more: previous char guaranteed at least once, but
            # conservatively drop it to avoid edge cases with groups
            if current:
                current.pop()
                if current:
                    segments.append(''.join(current))
                    current = []
            i += 1
        elif c == '{':
            # Quantifier {n,m}: conservatively drop previous char
            if current:
                current.pop()
                if current:
                    segments.append(''.join(current))
                    current = []
            # Skip to closing brace
            while i < n and pattern[i] != '}':
                i += 1
            if i < n:
                i += 1  # skip '}'
        elif c == '[':
            # Character class: not a literal
            if current:
                segments.append(''.join(current))
                current = []
            i += 1
            # Handle negated class
            if i < n and pattern[i] == '^':
                i += 1
            # Handle ] as first char in class
            if i < n and pattern[i] == ']':
                i += 1
            while i < n and pattern[i] != ']':
                if pattern[i] == '\\' and i + 1 < n:
                    i += 1  # skip escaped char inside class
                i += 1
            if i < n:
                i += 1  # skip ']'
        elif c in '()|.^$':
            # Group, alternation, any-char, anchors: break literal
            if current:
                segments.append(''.join(current))
                current = []
            i += 1
        else:
            # Literal character
            current.append(c)
            i += 1

    if current:
        segments.append(''.join(current))

    if not segments:
        return ""

    return max(segments, key=len)


def sa_search_range(text, sa, pattern):
    """Binary search on suffix array to find range of matching suffixes.

    Returns (left, right) indices in sa where text[sa[i]:sa[i]+len(pattern)] == pattern.
    """
    n = len(sa)
    plen = len(pattern)

    if plen == 0 or n == 0:
        return 0, 0

    # Find leftmost position
    lo, hi = 0, n
    while lo < hi:
        mid = (lo + hi) // 2
        pos = sa[mid]
        suffix_prefix = text[pos:pos + plen]
        if suffix_prefix < pattern:
            lo = mid + 1
        else:
            hi = mid
    left = lo

    # Find rightmost position (exclusive)
    lo, hi = left, n
    while lo < hi:
        mid = (lo + hi) // 2
        pos = sa[mid]
        suffix_prefix = text[pos:pos + plen]
        if suffix_prefix <= pattern:
            lo = mid + 1
        else:
            hi = mid
    right = lo

    return left, right


def sa_search(text, sa, pattern):
    """Return all positions where pattern occurs using SA binary search."""
    left, right = sa_search_range(text, sa, pattern)
    return [sa[i] for i in range(left, right)]


class SearchIndex:
    """Suffix array index for multi-file code search."""

    def __init__(self):
        self.text = ""
        self.sa = []
        self.lower_text = ""
        self.lower_sa = []
        self.file_info = []       # [(start_byte, end_byte, filename), ...]
        self.line_starts = []     # Global byte offset of each line start

    def build(self, corpus_dir):
        """Build suffix array index over all files in corpus_dir."""
        parts = []
        current_pos = 0

        # Deterministic file ordering
        filenames = sorted(
            f for f in os.listdir(corpus_dir)
            if os.path.isfile(os.path.join(corpus_dir, f))
        )

        for fname in filenames:
            fpath = os.path.join(corpus_dir, fname)
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
            except Exception:
                continue

            start = current_pos
            parts.append(content)
            current_pos += len(content)
            end = current_pos

            # Null separator between files to prevent cross-file matches
            parts.append("\x00")
            current_pos += 1

            self.file_info.append((start, end, fname))

        self.text = "".join(parts)

        # Precompute line start offsets (global)
        self.line_starts = [0]
        for i, ch in enumerate(self.text):
            if ch == '\n':
                self.line_starts.append(i + 1)

        # Build case-sensitive suffix array
        self.sa = build_suffix_array(self.text)

        # Build case-insensitive suffix array
        self.lower_text = self.text.lower()
        self.lower_sa = build_suffix_array(self.lower_text)

    def save(self, path):
        """Serialize index to disk."""
        data = {
            'text': self.text,
            'sa': self.sa,
            'lower_text': self.lower_text,
            'lower_sa': self.lower_sa,
            'file_info': self.file_info,
            'line_starts': self.line_starts,
        }
        with open(path, 'wb') as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)

    def load(self, path):
        """Load index from disk."""
        with open(path, 'rb') as f:
            data = pickle.load(f)
        self.text = data['text']
        self.sa = data['sa']
        self.lower_text = data['lower_text']
        self.lower_sa = data['lower_sa']
        self.file_info = data['file_info']
        self.line_starts = data['line_starts']

    def _pos_to_file(self, pos):
        """Map byte position to (filename, file_start) or None if in separator."""
        for start, end, fname in self.file_info:
            if start <= pos < end:
                return fname, start
        return None

    def _pos_to_line_info(self, pos):
        """Map byte position to (filename, line_number, line_content) or None."""
        file_result = self._pos_to_file(pos)
        if file_result is None:
            return None
        fname, file_start = file_result

        # Find the file's end
        file_end = None
        for s, e, fn in self.file_info:
            if fn == fname:
                file_end = e
                break

        # Calculate line number relative to file
        file_content = self.text[file_start:file_end]
        relative_pos = pos - file_start
        line_num = file_content[:relative_pos].count('\n') + 1

        # Get full line content
        # Find line start: search backwards from pos for newline or file start
        line_begin = pos
        while line_begin > file_start and self.text[line_begin - 1] != '\n':
            line_begin -= 1

        # Find line end: search forward for newline or file end
        line_end = pos
        while line_end < file_end and self.text[line_end] != '\n':
            line_end += 1

        line_content = self.text[line_begin:line_end]

        return fname, line_num, line_content

    def search_literal(self, pattern, ignore_case=False):
        """Search for literal pattern using suffix array binary search."""
        if not pattern:
            return []

        if ignore_case:
            positions = sa_search(self.lower_text, self.lower_sa, pattern.lower())
        else:
            positions = sa_search(self.text, self.sa, pattern)

        # Deduplicate by (file, line) and collect results
        seen = set()
        results = []
        for pos in positions:
            info = self._pos_to_line_info(pos)
            if info is None:
                continue
            fname, lineno, content = info
            key = (fname, lineno)
            if key not in seen:
                seen.add(key)
                results.append((fname, lineno, content))

        results.sort(key=lambda r: (r[0], r[1]))
        return results

    def search_regex(self, pattern, ignore_case=False, explain=False):
        """Search for regex pattern with optional suffix array acceleration."""
        literal = extract_literal_factor(pattern)

        flags = re.IGNORECASE if ignore_case else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error:
            return []

        if explain:
            print(f"LITERAL_FACTOR: {literal!r}", file=sys.stderr)

        if literal and len(literal) >= 2:
            # Use suffix array to narrow candidates
            if ignore_case:
                candidate_positions = sa_search(
                    self.lower_text, self.lower_sa, literal.lower()
                )
            else:
                candidate_positions = sa_search(self.text, self.sa, literal)

            if explain:
                print(f"CANDIDATES: {len(candidate_positions)}", file=sys.stderr)

            # Check each candidate line against full regex
            seen = set()
            results = []
            for pos in candidate_positions:
                info = self._pos_to_line_info(pos)
                if info is None:
                    continue
                fname, lineno, content = info
                key = (fname, lineno)
                if key in seen:
                    continue
                seen.add(key)
                if compiled.search(content):
                    results.append((fname, lineno, content))
        else:
            # No useful literal factor: full scan
            if explain:
                print("CANDIDATES: full_scan", file=sys.stderr)

            results = []
            for start, end, fname in self.file_info:
                file_content = self.text[start:end]
                for i, line in enumerate(file_content.split('\n'), 1):
                    if compiled.search(line):
                        results.append((fname, i, line))

        if explain:
            print(f"MATCHES: {len(results)}", file=sys.stderr)

        results.sort(key=lambda r: (r[0], r[1]))
        return results


def main():
    parser = argparse.ArgumentParser(
        description="Suffix array-accelerated code search"
    )
    subparsers = parser.add_subparsers(dest="command")

    # Index subcommand
    idx_parser = subparsers.add_parser("index", help="Build search index")
    idx_parser.add_argument("corpus_dir", help="Directory of source files")
    idx_parser.add_argument("index_file", help="Output index file path")

    # Search subcommand
    search_parser = subparsers.add_parser("search", help="Search the index")
    search_parser.add_argument("index_file", help="Index file path")
    search_parser.add_argument("pattern", help="Search pattern")
    search_parser.add_argument("--regex", action="store_true",
                                help="Treat pattern as regex")
    search_parser.add_argument("--ignore-case", action="store_true",
                                help="Case-insensitive search")
    search_parser.add_argument("--explain", action="store_true",
                                help="Show regex factoring diagnostics")

    args = parser.parse_args()

    if args.command == "index":
        index = SearchIndex()
        index.build(args.corpus_dir)
        index.save(args.index_file)
        total = len(index.text)
        files = len(index.file_info)
        print(f"Indexed {files} files, {total} bytes, SA size {len(index.sa)}")

    elif args.command == "search":
        if not os.path.exists(args.index_file):
            print(f"Error: index file not found: {args.index_file}", file=sys.stderr)
            sys.exit(1)

        index = SearchIndex()
        index.load(args.index_file)

        if args.regex:
            results = index.search_regex(
                args.pattern, args.ignore_case, args.explain
            )
        else:
            results = index.search_literal(args.pattern, args.ignore_case)

        for fname, lineno, content in results:
            print(f"{fname}:{lineno}:{content}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
