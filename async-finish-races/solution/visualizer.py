#!/usr/bin/env python3
"""Visualizer: generates DOT files and renders PNGs via graphviz."""

import os
import subprocess
import sys
sys.path.insert(0, "/app")
from graph_utils import build_graph, load_trace

EDGE_COLORS = {"spawn": "red", "continue": "blue", "join": "green"}


def generate_dot(trace_name, steps, edges):
    lines = [f"digraph {trace_name} {{", "  rankdir=TB;"]
    for s in steps:
        lines.append(f'  S{s["id"]} [label="S{s["id"]} (cost={s["cost"]})"];')
    for u, v, etype in edges:
        color = EDGE_COLORS[etype]
        lines.append(f"  S{u} -> S{v} [color={color}];")
    lines.append("}")
    return "\n".join(lines) + "\n"


def main():
    os.makedirs("/app/graphs", exist_ok=True)
    for i in range(1, 7):
        name = f"trace{i}"
        program = load_trace(f"/app/traces/{name}.json")
        steps, edges = build_graph(program)
        dot_content = generate_dot(name, steps, edges)
        dot_path = f"/app/graphs/{name}.dot"
        png_path = f"/app/graphs/{name}.png"
        with open(dot_path, "w") as f:
            f.write(dot_content)
        subprocess.run(
            ["dot", "-Tpng", dot_path, "-o", png_path],
            check=True,
        )


if __name__ == "__main__":
    main()
