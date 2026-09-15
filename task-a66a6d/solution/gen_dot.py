#!/usr/bin/env python3
"""Generate Graphviz DOT file from manifest.json."""
import json
import os

with open("/app/manifest.json") as f:
    manifest = json.load(f)

all_nodes = {}
for section in ("nodes", "sources", "exposures"):
    if section in manifest:
        all_nodes.update(manifest[section])

SHAPES = {
    "model": "box",
    "seed": "hexagon",
    "test": "ellipse",
    "source": "invhouse",
    "exposure": "house",
}

os.makedirs("/app/output", exist_ok=True)

with open("/app/output/dag.dot", "w") as f:
    f.write("digraph pipeline {\n")
    f.write("    rankdir=LR;\n")

    for uid in sorted(all_nodes.keys()):
        node = all_nodes[uid]
        shape = SHAPES.get(node["resource_type"], "ellipse")
        f.write(f'    "{uid}" [shape={shape}];\n')

    for uid in sorted(all_nodes.keys()):
        node = all_nodes[uid]
        for parent in sorted(node.get("depends_on", {}).get("nodes", [])):
            if parent in all_nodes:
                f.write(f'    "{uid}" -> "{parent}";\n')

    f.write("}\n")

print("DOT file generated at /app/output/dag.dot")
