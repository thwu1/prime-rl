#!/usr/bin/env python3
"""CLI for Aho-Corasick multi-pattern matching."""
import sys
import json
from aho_corasick import AhoCorasick, MatchKind


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 cli.py <match_kind> <pattern1> [pattern2 ...]",
              file=sys.stderr)
        print("  match_kind: standard|leftmost_first|leftmost_longest",
              file=sys.stderr)
        print("  Reads haystack from stdin.", file=sys.stderr)
        sys.exit(1)

    match_kind_str = sys.argv[1]
    patterns = [p.encode() for p in sys.argv[2:]]

    try:
        match_kind = MatchKind(match_kind_str)
    except ValueError:
        print(f"Invalid match kind: {match_kind_str}", file=sys.stderr)
        sys.exit(1)

    haystack = sys.stdin.buffer.read()
    ac = AhoCorasick(patterns)

    if match_kind == MatchKind.STANDARD:
        matches = ac.find_all(haystack)
    elif match_kind == MatchKind.LEFTMOST_FIRST:
        matches = ac.find_leftmost_first(haystack)
    elif match_kind == MatchKind.LEFTMOST_LONGEST:
        matches = ac.find_leftmost_longest(haystack)

    for m in matches:
        matched_text = haystack[m.start:m.end].decode(errors='replace')
        print(json.dumps({
            "pattern_id": m.pattern_id,
            "start": m.start,
            "end": m.end,
            "text": matched_text
        }))


if __name__ == "__main__":
    main()
