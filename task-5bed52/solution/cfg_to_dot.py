#!/usr/bin/env python3
"""Convert a CFG adjacency-list JSON file to Graphviz DOT format."""
import json
import sys

with open(sys.argv[1]) as f:
    cfg = json.load(f)

print("digraph CFG {")
print("  rankdir=TB;")
print("  node [shape=box, fontname=\"monospace\"];")
for block in cfg:
    print(f'  "{block}";')
for block, succs in cfg.items():
    for s in succs:
        print(f'  "{block}" -> "{s}";')
print("}")
