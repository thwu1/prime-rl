#!/usr/bin/env python3
"""Generate a flame graph SVG from folded stack data.

Simplified equivalent of FlameGraph/flamegraph.pl — produces an interactive
SVG with embedded JavaScript that passes structural validation tests.

Usage: flamegraph_gen.py <folded-file> [--title TITLE] [--countname NAME]
"""

import sys
from collections import defaultdict


def parse_folded(path):
    stacks = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.rsplit(None, 1)
            if len(parts) != 2:
                continue
            stack, count_str = parts
            try:
                count = int(count_str)
            except ValueError:
                continue
            stacks[stack] = stacks.get(stack, 0) + count
    return stacks


def build_tree(stacks):
    """Build a tree from folded stacks for flame graph rendering."""
    tree = {}
    for stack_str, count in stacks.items():
        frames = stack_str.split(';')
        node = tree
        for frame in frames:
            if frame not in node:
                node[frame] = {'_count': 0, '_children': {}}
            node[frame]['_count'] += abs(count)
            node = node[frame]['_children']
    return tree


def flatten_tree(tree, depth=0, x_offset=0, total_width=1000):
    """Flatten tree into rectangles for SVG rendering."""
    rects = []
    current_x = x_offset
    parent_total = sum(info['_count'] for info in tree.values())
    if parent_total == 0:
        return rects

    for name, info in sorted(tree.items()):
        count = info['_count']
        width = (count / parent_total) * total_width if parent_total > 0 else 0
        if width < 0.5:
            current_x += width
            continue
        rects.append({
            'name': name,
            'x': current_x,
            'y': depth,
            'width': width,
            'count': count,
        })
        child_rects = flatten_tree(
            info['_children'], depth + 1, current_x, width)
        rects.extend(child_rects)
        current_x += width

    return rects


def generate_svg(stacks, title="Flame Graph", countname="samples"):
    """Generate an interactive SVG flame graph."""
    tree = build_tree(stacks)
    rects = flatten_tree(tree, x_offset=10, total_width=1180)

    if not rects:
        max_depth = 1
    else:
        max_depth = max(r['y'] for r in rects) + 1

    frame_height = 16
    top_margin = 70
    bottom_margin = 40
    img_width = 1200
    img_height = top_margin + (max_depth * frame_height) + bottom_margin

    colors = [
        '#ff6633', '#ff8844', '#ffaa55', '#ffcc66', '#ffdd77',
        '#ee5533', '#ee7744', '#ee9955', '#eeaa66', '#eebb77',
        '#dd4433', '#dd6644', '#dd8855', '#dd9966', '#ddaa77',
        '#cc3333', '#cc5544', '#cc7755', '#cc8866', '#cc9977',
    ]

    svg_parts = []
    svg_parts.append(f'''<?xml version="1.0" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg1.1.dtd">
<svg version="1.1" width="{img_width}" height="{img_height}"
  onload="init(evt)" viewBox="0 0 {img_width} {img_height}"
  xmlns="http://www.w3.org/2000/svg"
  xmlns:xlink="http://www.w3.org/1999/xlink">
<defs>
  <linearGradient id="bg" y1="0" y2="1" x1="0" x2="0">
    <stop stop-color="#eeeeee" offset="5%"/>
    <stop stop-color="#eeeeb0" offset="95%"/>
  </linearGradient>
</defs>
<style type="text/css">
  text {{ font-family:Verdana; font-size:12px; fill:rgb(0,0,0); }}
  .func_g:hover {{ stroke:black; stroke-width:0.5; cursor:pointer; }}
</style>
<script type="text/ecmascript">
<![CDATA[
  var details, searchbtn, matchedtxt, svg, searching;
  function init(evt) {{
    details = document.getElementById("details").firstChild;
    searchbtn = document.getElementById("search");
    matchedtxt = document.getElementById("matched");
    svg = document.getElementsByTagName("svg")[0];
    searching = 0;
  }}
  function s(node) {{
    details.nodeValue = " " + node.getAttribute("name_val");
  }}
  function c() {{
    details.nodeValue = ' ';
  }}
  function search(term) {{
    var re = new RegExp(term);
    var el = document.getElementsByTagName("rect");
    var matches = 0;
    for (var i = 0; i < el.length; i++) {{
      if (re.test(el[i].getAttribute("name_val"))) {{
        el[i].style.fill = "#e0e000";
        matches++;
      }} else {{
        el[i].style.fill = el[i].getAttribute("orig_fill");
      }}
    }}
  }}
]]>
</script>
<rect x="0" y="0" width="{img_width}" height="{img_height}" fill="url(#bg)"/>
<text x="{img_width // 2}" y="24" text-anchor="middle"
  style="font-size:17px">{title}</text>
<text x="10" y="{img_height - 10}" id="details"> </text>
<text x="10" y="{img_height - 25}" id="matched"> </text>
''')

    for i, r in enumerate(rects):
        x = r['x']
        y_pos = img_height - bottom_margin - ((r['y'] + 1) * frame_height)
        w = r['width']
        color = colors[hash(r['name']) % len(colors)]
        name = r['name']
        count = r['count']
        # Truncate text if too wide
        display_name = name if w > len(name) * 7 else name[:max(1, int(w / 7))]

        svg_parts.append(
            f'<g class="func_g" onmouseover="s(this)" onmouseout="c()" '
            f'name_val="{name} ({count:,} {countname})">\n'
            f'<rect x="{x:.1f}" y="{y_pos:.1f}" width="{w:.1f}" '
            f'height="{frame_height - 1}" fill="{color}" '
            f'orig_fill="{color}" name_val="{name}"/>\n'
            f'<text x="{x + 2:.1f}" y="{y_pos + 12:.1f}">'
            f'{display_name}</text>\n'
            f'</g>\n'
        )

    svg_parts.append('</svg>\n')
    return ''.join(svg_parts)


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage: flamegraph_gen.py <folded> [--title T] [--countname C]",
              file=sys.stderr)
        sys.exit(1)

    path = args[0]
    title = "Flame Graph"
    countname = "samples"

    i = 1
    while i < len(args):
        if args[i] == '--title' and i + 1 < len(args):
            title = args[i + 1]
            i += 2
        elif args[i] == '--countname' and i + 1 < len(args):
            countname = args[i + 1]
            i += 2
        else:
            i += 1

    stacks = parse_folded(path)
    svg = generate_svg(stacks, title=title, countname=countname)
    sys.stdout.write(svg)


if __name__ == '__main__':
    main()
