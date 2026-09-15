#!/usr/bin/env python3
"""
Generate Graphviz DOT visualizations of optimized DAGs.
Writes to /app/graphs/<name>.dot and renders to /app/graphs/<name>.svg.

"""
import os
import subprocess
import sys

sys.path.insert(0, "/app")

from dag_ir import DAG, Op, LEAF_OPS
from programs import PROGRAMS
from optimizer import optimize


def dag_to_dot(dag: DAG, name: str) -> str:
    """Convert an optimized DAG to Graphviz DOT format."""
    lines = [f"digraph {name} {{"]
    lines.append("  rankdir=BT;")
    lines.append('  node [fontname="monospace"];')

    for nid in dag.toposort():
        node = dag.nodes[nid]
        if node.op == Op.CONST:
            label = f"CONST({node.arg:#x})"
            lines.append(
                f'  n{nid} [label="{label}", shape=ellipse, '
                f"style=filled, fillcolor=lightblue];"
            )
        elif node.op == Op.ARG:
            label = f"ARG({node.arg})"
            lines.append(
                f'  n{nid} [label="{label}", shape=ellipse, '
                f"style=filled, fillcolor=lightgreen];"
            )
        else:
            label = node.op.name
            lines.append(f'  n{nid} [label="{label}", shape=box];')

        for src in node.srcs:
            lines.append(f"  n{src} -> n{nid};")

    for i, oid in enumerate(dag.outputs):
        out_id = f"out{i}"
        lines.append(f'  {out_id} [label="output_{i}", shape=doublecircle];')
        lines.append(f"  n{oid} -> {out_id};")

    lines.append("}")
    return "\n".join(lines)


def main():
    os.makedirs("/app/graphs", exist_ok=True)
    for name, builder in PROGRAMS.items():
        dag, _ = builder()
        opt = optimize(dag)
        dot = dag_to_dot(opt, name)
        dot_path = f"/app/graphs/{name}.dot"
        svg_path = f"/app/graphs/{name}.svg"
        with open(dot_path, "w") as f:
            f.write(dot)
        subprocess.run(
            ["dot", "-Tsvg", "-o", svg_path, dot_path], check=True
        )


if __name__ == "__main__":
    main()
