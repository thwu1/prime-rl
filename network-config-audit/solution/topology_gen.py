#!/usr/bin/env python3
"""
Generate Graphviz DOT topology diagram with defect annotations.

"""

import json


def load_design_spec():
    with open("/app/design_spec.json", "r") as f:
        return json.load(f)


def load_report():
    with open("/app/audit_report.json", "r") as f:
        return json.load(f)


def main():
    design = load_design_spec()
    report = load_report()

    # Build defect annotations per router
    router_defects = {}
    for d in report["defects"]:
        r = d["router"]
        if r not in router_defects:
            router_defects[r] = []
        short_desc = d["affected_config"][:50]
        router_defects[r].append(
            f"[{d['severity'].upper()}] {d['category']}: {short_desc}"
        )

    # Build topology edges from design spec
    edges = []
    routers_info = design.get("routers", {})
    seen_edges = set()
    for rname, rdata in routers_info.items():
        for iname, idata in rdata.get("interfaces", {}).items():
            conn = idata.get("connects_to", "")
            if conn:
                peer_router = conn.split(":")[0]
                edge_key = tuple(sorted([rname, peer_router]))
                if edge_key not in seen_edges:
                    seen_edges.add(edge_key)
                    area = idata.get("ospf_area")
                    cost = idata.get("ospf_cost")
                    label_parts = []
                    if area is not None:
                        label_parts.append(f"Area {area}")
                    if cost is not None:
                        label_parts.append(f"cost={cost}")
                    edges.append((rname, peer_router, ", ".join(label_parts)))

    # Generate DOT
    dot_lines = [
        'graph enterprise_network {',
        '  rankdir=LR;',
        '  node [shape=box, style=filled, fontname="Helvetica"];',
        '  edge [fontname="Helvetica", fontsize=10];',
        '',
    ]

    # Color coding: red for routers with critical defects, orange for high, green for clean
    for rname in sorted(routers_info.keys()):
        role = routers_info[rname].get("role", "")
        defect_list = router_defects.get(rname, [])

        if any("[CRITICAL]" in d for d in defect_list):
            color = "#ff6b6b"
        elif any("[HIGH]" in d for d in defect_list):
            color = "#ffa07a"
        elif defect_list:
            color = "#ffe4b5"
        else:
            color = "#90ee90"

        label_lines = [f"{rname} ({role})"]
        for dd in defect_list:
            # Escape special chars for DOT
            dd_escaped = dd.replace('"', '\\"').replace('\n', '\\n')
            label_lines.append(dd_escaped)

        label = "\\n".join(label_lines)
        dot_lines.append(
            f'  {rname} [label="{label}", fillcolor="{color}"];'
        )

    dot_lines.append("")

    # Edges
    for src, dst, label in edges:
        # Check if this link has defects (cost mismatch, BFD issues)
        edge_color = "black"
        edge_style = "solid"
        edge_defects = []

        # Check for cost-related defects on this edge
        for d in report["defects"]:
            if d["router"] in (src, dst):
                ac = d["affected_config"].lower()
                if "cost" in ac or "bfd" in ac:
                    edge_color = "red"
                    edge_style = "dashed"
                    edge_defects.append(f"{d['router']}: {d['category']}")

        edge_label = label
        if edge_defects:
            edge_label += "\\n" + "\\n".join(edge_defects)

        dot_lines.append(
            f'  {src} -- {dst} [label="{edge_label}", '
            f'color="{edge_color}", style="{edge_style}"];'
        )

    dot_lines.append("}")

    dot_content = "\n".join(dot_lines) + "\n"

    dot_path = "/app/topology.dot"
    with open(dot_path, "w") as f:
        f.write(dot_content)

    print(f"DOT file written to {dot_path}")


if __name__ == "__main__":
    main()
