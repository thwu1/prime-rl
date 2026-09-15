#!/usr/bin/env python3
"""
Generate DOT file from g2o graph and optimized poses for graphviz rendering.

"""
import sys


def main():
    if len(sys.argv) != 4:
        print("Usage: gen_dot.py <g2o_file> <poses_file> <dot_output>", file=sys.stderr)
        sys.exit(1)

    g2o_file = sys.argv[1]
    poses_file = sys.argv[2]
    dot_file = sys.argv[3]

    # Parse edges and fixed vertices from g2o
    edges = []
    fixed = set()
    with open(g2o_file) as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            if parts[0] == "EDGE_SE2":
                edges.append((int(parts[1]), int(parts[2])))
            elif parts[0] == "FIX":
                fixed.add(int(parts[1]))

    # Parse optimized poses
    poses = {}
    with open(poses_file) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 4:
                poses[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))

    # Write DOT format
    with open(dot_file, "w") as f:
        f.write("digraph pose_graph {\n")
        f.write("  rankdir=LR;\n")
        f.write("  node [shape=ellipse];\n")
        for vid in sorted(poses.keys()):
            x, y, t = poses[vid]
            color = "red" if vid in fixed else "blue"
            label = "%d\\n(%.1f,%.1f)" % (vid, x, y)
            f.write('  n%d [label="%s" color=%s];\n' % (vid, label, color))
        for i1, i2 in edges:
            f.write("  n%d -> n%d;\n" % (i1, i2))
        f.write("}\n")


if __name__ == "__main__":
    main()
