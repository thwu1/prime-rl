#!/usr/bin/env python3
"""Parse Graphviz DOT dependency graph into JSON edge list.

Robust DOT parser for standard Graphviz directed graph notation.
Handles quoted node identifiers with hyphenated names.
"""

import json
import re
import sys


def parse_dot_file(filepath):
    """Extract directed edges from a DOT digraph file.

    Parses standard Graphviz DOT notation, extracting all directed
    edges between quoted node identifiers.
    """
    edges = []
    with open(filepath) as f:
        content = f.read()

    # Match directed edges: "source" -> "target";
    pattern = r'"([^"]+)"\s*->\s*"([^"]+)"\s*;'

    for match in re.finditer(pattern, content):
        source = match.group(1)
        target = match.group(2)
        edges.append({"from": source, "to": target})

    return edges


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.dot> <output.json>", file=sys.stderr)
        sys.exit(1)

    dot_file = sys.argv[1]
    output_file = sys.argv[2]

    edges = parse_dot_file(dot_file)

    with open(output_file, 'w') as f:
        json.dump({"dependencies": edges}, f, indent=2)

    print(f"Parsed {len(edges)} edges from {dot_file}")


if __name__ == "__main__":
    main()
