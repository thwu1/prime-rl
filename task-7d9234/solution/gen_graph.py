#!/usr/bin/env python3
"""Generate feature dependency graph in DOT format from cargo metadata."""
import json


def main():
    with open("/app/metadata.json") as f:
        data = json.load(f)

    pkg = None
    for p in data["packages"]:
        if p.get("source") is None:
            pkg = p
            break

    features = pkg["features"]
    opt_deps = {d["name"] for d in pkg["dependencies"] if d.get("optional")}

    lines = ["digraph features {"]
    lines.append('    rankdir=LR;')
    lines.append('    node [fontname="Helvetica"];')
    lines.append("")
    lines.append("    // Feature nodes")

    for feat in sorted(features.keys()):
        lines.append(f'    "{feat}" [shape=box];')

    lines.append("")
    lines.append("    // Optional dependency nodes")

    for dep in sorted(opt_deps):
        lines.append(
            f'    "dep:{dep}" [shape=ellipse, style=filled, fillcolor=lightblue];'
        )

    lines.append("")
    lines.append("    // Edges")

    for feat in sorted(features.keys()):
        for entry in sorted(features[feat]):
            if entry.startswith("dep:"):
                dep = entry[4:]
                lines.append(f'    "{feat}" -> "dep:{dep}" [style=dashed];')
            elif "?/" in entry:
                dep, dfeat = entry.split("?/", 1)
                lines.append(
                    f'    "{feat}" -> "dep:{dep}" [style=dotted, label="{dfeat}"];'
                )
            elif "/" in entry:
                dep, dfeat = entry.split("/", 1)
                lines.append(
                    f'    "{feat}" -> "dep:{dep}" [style=dashed, label="{dfeat}"];'
                )
            else:
                if entry in features:
                    lines.append(f'    "{feat}" -> "{entry}" [style=solid];')

    lines.append("}")

    with open("/app/feature_graph.dot", "w") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
