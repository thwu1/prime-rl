#!/usr/bin/env python3

"""
Minimal flame graph SVG generator from folded stack format.
Fallback for when flamegraph.pl is unavailable.
"""

import sys
from collections import defaultdict

FRAME_HEIGHT = 16
FONT_SIZE = 12
MIN_WIDTH_FOR_TEXT = 40


def parse_folded(path):
    """Parse folded stack file into {stack: count} dict."""
    stacks = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.rsplit(" ", 1)
            stacks[parts[0]] = int(parts[1])
    return stacks


def build_tree(stacks):
    """Build a tree of nodes from folded stacks."""
    root = {"name": "root", "value": 0, "children": {}}
    for stack_str, count in stacks.items():
        funcs = stack_str.split(";")
        node = root
        for func in funcs:
            if func not in node["children"]:
                node["children"][func] = {"name": func, "value": 0, "children": {}}
            node = node["children"][func]
            node["value"] += count
        root["value"] += count
    return root


def color_hash(name):
    """Generate a warm color for a function name."""
    h = hash(name)
    r = 200 + (h % 55)
    g = 80 + ((h >> 8) % 80)
    b = 20 + ((h >> 16) % 40)
    return f"rgb({r},{g},{b})"


def render_svg(root, width=1200):
    """Render the tree as an SVG flame graph."""
    total = root["value"]
    if total == 0:
        total = 1

    rects = []
    texts = []

    def render_node(node, depth, x_offset, parent_width):
        w = (node["value"] / total) * width
        if w < 0.5:
            return
        y = depth * FRAME_HEIGHT
        color = color_hash(node["name"])
        rects.append(
            f'<rect x="{x_offset:.1f}" y="{y}" width="{w:.1f}" '
            f'height="{FRAME_HEIGHT - 1}" fill="{color}" '
            f'rx="1" ry="1"><title>{node["name"]} ({node["value"]} samples)</title></rect>'
        )
        if w > MIN_WIDTH_FOR_TEXT:
            tx = x_offset + 2
            ty = y + FRAME_HEIGHT - 4
            label = node["name"]
            max_chars = int(w / 7)
            if len(label) > max_chars:
                label = label[: max_chars - 2] + ".."
            texts.append(
                f'<text x="{tx:.1f}" y="{ty}" font-size="{FONT_SIZE}" '
                f'font-family="monospace" fill="black">{label}</text>'
            )
        cx = x_offset
        for child in sorted(node["children"].values(), key=lambda c: -c["value"]):
            render_node(child, depth + 1, cx, w)
            cx += (child["value"] / total) * width

    # Render all top-level children (skip the synthetic root)
    cx = 0.0
    max_depth = 0
    for child in sorted(root["children"].values(), key=lambda c: -c["value"]):
        render_node(child, 0, cx, width)
        cx += (child["value"] / total) * width

    # Calculate max depth for SVG height
    def get_max_depth(node, d):
        m = d
        for c in node["children"].values():
            m = max(m, get_max_depth(c, d + 1))
        return m

    max_depth = get_max_depth(root, 0)
    height = (max_depth + 2) * FRAME_HEIGHT + 40

    svg = [
        f'<?xml version="1.0" standalone="no"?>',
        f'<svg version="1.1" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg">',
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="white"/>',
        f'<text x="{width//2}" y="20" text-anchor="middle" font-size="14" '
        f'font-family="sans-serif" fill="black">Flame Graph</text>',
        '<g transform="translate(0, 30)">',
    ]
    svg.extend(rects)
    svg.extend(texts)
    svg.append("</g>")
    svg.append("</svg>")
    return "\n".join(svg)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <folded.txt> <output.svg>")
        sys.exit(1)

    folded_path = sys.argv[1]
    output_path = sys.argv[2]

    stacks = parse_folded(folded_path)
    root = build_tree(stacks)
    svg = render_svg(root)

    with open(output_path, "w") as f:
        f.write(svg)

    print(f"Flame graph written to {output_path} ({len(svg)} bytes)")


if __name__ == "__main__":
    main()
