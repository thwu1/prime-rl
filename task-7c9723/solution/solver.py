#!/usr/bin/env python3
"""

Wormhole NoC DRAM Reader Placement Optimizer — Reference Solution

Uses PuLP ILP solver (CBC backend) for provably optimal congestion-free
placements. Generates SQLite database and Graphviz visualizations.

Return paths use dimension-ordered routing:
  - NoC #0 (left banks at x=0): East then South
  - NoC #1 (right banks at x=9): West then North

Congestion = two return paths on the same NoC sharing a directional link.
"""

import json
import os
import sqlite3
import subprocess
import sys

from pulp import (
    PULP_CBC_CMD,
    LpMinimize,
    LpProblem,
    LpVariable,
    lpSum,
    value,
)


def load_config(path="/app/chip_config.json"):
    with open(path) as f:
        return json.load(f)


def compute_return_path_links(bank_x, bank_y, reader_x, reader_y, noc):
    """Compute the set of directional links traversed by a return path.

    Each link is a tuple (direction, from_x, from_y, to_x, to_y).
    """
    links = set()
    if noc == 0:  # East then South
        for x in range(bank_x, reader_x):
            links.add(("E", x, bank_y, x + 1, bank_y))
        for y in range(bank_y, reader_y):
            links.add(("S", reader_x, y, reader_x, y + 1))
    elif noc == 1:  # West then North
        for x in range(bank_x, reader_x, -1):
            links.add(("W", x, bank_y, x - 1, bank_y))
        for y in range(bank_y, reader_y, -1):
            links.add(("N", reader_x, y, reader_x, y - 1))
    return links


def solve_scenario_ilp(grid, banks, harvested_rows):
    """Solve optimal congestion-free placement using Integer Linear Programming.

    Variables: x[bank_id, candidate_index] ∈ {0,1}
    Objective: minimize total Manhattan-distance hops
    Constraints:
      - Each bank assigned to exactly one position
      - No two banks share a position
      - No two return paths on the same NoC share a directional link
    """
    harvested = set(harvested_rows)
    wx_lo, wx_hi = grid["worker_x_range"]
    wy_lo, wy_hi = grid["worker_y_range"]

    # Generate candidate positions for each bank
    bank_cands = {}
    for bank in banks:
        bid = bank["id"]
        bx, by = bank["x"], bank["y"]
        noc = 0 if bx == 0 else 1
        cands = []
        for rx in range(wx_lo, wx_hi + 1):
            if noc == 0:
                y_range = range(by, wy_hi + 1)
            else:
                y_range = range(wy_lo, by + 1)
            for ry in y_range:
                if ry in harvested:
                    continue
                hops = abs(rx - bx) + abs(ry - by)
                links = compute_return_path_links(bx, by, rx, ry, noc)
                cands.append((rx, ry, hops, noc, links))
        bank_cands[bid] = cands

    # Create ILP problem
    prob = LpProblem("NoCPlacement", LpMinimize)

    # Binary decision variables
    x = {}
    for bid, cands in bank_cands.items():
        for i in range(len(cands)):
            x[bid, i] = LpVariable(f"x_{bid}_{i}", cat="Binary")

    # Objective: minimize total hops
    prob += lpSum(
        x[bid, i] * cands[i][2]
        for bid, cands in bank_cands.items()
        for i in range(len(cands))
    )

    # Constraint: each bank assigned exactly once
    for bid, cands in bank_cands.items():
        prob += lpSum(x[bid, i] for i in range(len(cands))) == 1

    # Constraint: no two banks share a position
    pos_vars = {}
    for bid, cands in bank_cands.items():
        for i, (rx, ry, _, _, _) in enumerate(cands):
            pos_vars.setdefault((rx, ry), []).append(x[bid, i])
    for pos_key, vlist in pos_vars.items():
        if len(vlist) > 1:
            prob += lpSum(vlist) <= 1

    # Constraint: no link conflicts on the same NoC
    link_vars = {}
    for bid, cands in bank_cands.items():
        for i, (rx, ry, hops, noc, links) in enumerate(cands):
            for lnk in links:
                link_vars.setdefault((noc, lnk), []).append(x[bid, i])
    for key, vlist in link_vars.items():
        if len(vlist) > 1:
            prob += lpSum(vlist) <= 1

    # Solve
    prob.solve(PULP_CBC_CMD(msg=0))

    if prob.status != 1:
        print(f"ERROR: ILP solver failed with status {prob.status}", file=sys.stderr)
        sys.exit(1)

    # Extract solution
    placements = {}
    for bid, cands in bank_cands.items():
        for i, (rx, ry, hops, noc, links) in enumerate(cands):
            if value(x[bid, i]) is not None and value(x[bid, i]) > 0.5:
                placements[bid] = {"x": rx, "y": ry, "noc": noc, "hops": hops}
                break

    return placements


def compute_bandwidth(placements, bank_bw, num_banks):
    """Compute bandwidth estimate using the linear hop-penalty model."""
    total_extra_hops = sum(max(0, p["hops"] - 1) for p in placements.values())
    theoretical = float(num_banks * bank_bw)
    utilization = 1.0 - 0.005 * total_extra_hops
    return {
        "theoretical_gbps": theoretical,
        "utilization_factor": round(utilization, 6),
        "estimated_gbps": round(theoretical * utilization, 2),
    }


def compute_link_analysis(placements, banks):
    """Compute per-link utilization metrics and return path link details."""
    link_counts = {}  # (noc, link_tuple) -> path_count
    bank_links = []  # list of (bank_id, noc, link_tuple)

    for bid, p in placements.items():
        bank = next(b for b in banks if b["id"] == bid)
        links = compute_return_path_links(
            bank["x"], bank["y"], p["x"], p["y"], p["noc"]
        )
        for lnk in links:
            key = (p["noc"], lnk)
            link_counts[key] = link_counts.get(key, 0) + 1
            bank_links.append((bid, p["noc"], lnk))

    noc0_links = sum(1 for (n, _) in link_counts if n == 0)
    noc1_links = sum(1 for (n, _) in link_counts if n == 1)
    max_load = max(link_counts.values()) if link_counts else 0

    analysis = {
        "total_links_used": len(link_counts),
        "max_link_load": max_load,
        "noc0_links_used": noc0_links,
        "noc1_links_used": noc1_links,
    }
    return analysis, link_counts, bank_links


def setup_database(db_path, schema_path):
    """Create SQLite database with the required schema."""
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    with open(schema_path) as f:
        conn.executescript(f.read())
    return conn


def store_scenario_data(conn, name, placements, banks, link_counts, bank_links,
                        bandwidth, total_hops):
    """Insert all scenario data into the SQLite database."""
    cur = conn.cursor()
    max_load = max(link_counts.values()) if link_counts else 0
    congestion_free = 1 if max_load <= 1 else 0

    # Insert placements
    for bid, p in placements.items():
        bank = next(b for b in banks if b["id"] == bid)
        cur.execute(
            "INSERT INTO placements VALUES (?,?,?,?,?,?,?,?)",
            (name, bid, bank["x"], bank["y"], p["x"], p["y"], p["noc"], p["hops"]),
        )

    # Insert return path links
    for bid, noc, lnk in bank_links:
        d, fx, fy, tx, ty = lnk
        cur.execute(
            "INSERT INTO return_path_links VALUES (?,?,?,?,?,?,?,?)",
            (name, bid, noc, d, fx, fy, tx, ty),
        )

    # Insert link utilization
    for (noc, lnk), cnt in link_counts.items():
        d, fx, fy, tx, ty = lnk
        cur.execute(
            "INSERT INTO link_utilization VALUES (?,?,?,?,?,?,?,?)",
            (name, noc, d, fx, fy, tx, ty, cnt),
        )

    # Insert scenario summary
    cur.execute(
        "INSERT INTO scenario_summary VALUES (?,?,?,?,?,?,?,?)",
        (
            name,
            total_hops,
            congestion_free,
            max_load,
            len(link_counts),
            bandwidth["theoretical_gbps"],
            bandwidth["utilization_factor"],
            bandwidth["estimated_gbps"],
        ),
    )

    conn.commit()


def generate_dot_and_svg(name, grid, banks, placements, harvested_rows, viz_dir):
    """Generate Graphviz DOT visualization and render to SVG."""
    rows, cols = grid["rows"], grid["cols"]
    bank_pos = {(b["x"], b["y"]): b["id"] for b in banks}
    reader_pos = {(p["x"], p["y"]): bid for bid, p in placements.items()}
    harv = set(harvested_rows)

    lines = [
        "digraph noc {",
        "  layout=neato;",
        "  overlap=false;",
        '  node [shape=box, width=0.6, height=0.4, fontsize=9];',
        "  edge [penwidth=1.5];",
        "",
    ]

    # Create nodes with pinned positions
    for y in range(rows):
        for x in range(cols):
            nm = f"t{x}_{y}"
            # neato y-axis is inverted relative to grid row numbering
            px = x * 1.2
            py = (rows - 1 - y) * 1.0

            if (x, y) in bank_pos:
                bid = bank_pos[(x, y)]
                lbl = f"D{bid}"
                clr = "lightblue"
            elif (x, y) in reader_pos:
                bid = reader_pos[(x, y)]
                lbl = f"R{bid}"
                clr = "lightgreen"
            elif y in harv and 1 <= x <= 8:
                lbl = "X"
                clr = "lightcoral"
            elif 1 <= x <= 8:
                lbl = ""
                clr = "white"
            else:
                lbl = ""
                clr = "lightyellow"

            lines.append(
                f'  {nm} [pos="{px},{py}!" label="{lbl}" '
                f'fillcolor="{clr}" style=filled];'
            )

    lines.append("")

    # Draw return path edges with NoC-specific colors
    noc_colors = {0: "darkorange", 1: "purple"}
    for bid in sorted(placements):
        p = placements[bid]
        bank = next(b for b in banks if b["id"] == bid)
        links = compute_return_path_links(
            bank["x"], bank["y"], p["x"], p["y"], p["noc"]
        )
        color = noc_colors[p["noc"]]
        for d, fx, fy, tx, ty in sorted(links):
            src = f"t{fx}_{fy}"
            dst = f"t{tx}_{ty}"
            lines.append(f'  {src} -> {dst} [color="{color}" tooltip="Bank {bid}"];')

    lines.append("}")

    dot_path = os.path.join(viz_dir, f"{name}.dot")
    svg_path = os.path.join(viz_dir, f"{name}.svg")

    with open(dot_path, "w") as f:
        f.write("\n".join(lines))

    subprocess.run(
        ["neato", "-n", "-Tsvg", dot_path, "-o", svg_path],
        check=True,
        capture_output=True,
    )

    return dot_path, svg_path


def main():
    config = load_config()
    grid = config["grid"]
    banks = grid["dram_banks"]
    bank_bw = grid["dram_bank_bandwidth_gbps"]
    num_banks = len(banks)

    viz_dir = "/app/viz"
    os.makedirs(viz_dir, exist_ok=True)

    conn = setup_database("/app/noc_analysis.db", "/app/db_schema.sql")

    results = {"scenarios": {}}

    for scenario in config["scenarios"]:
        name = scenario["name"]
        harvested = scenario["harvested_rows"]

        print(f"Solving scenario '{name}' (harvested rows: {harvested})...")

        # Solve placement via ILP
        placements = solve_scenario_ilp(grid, banks, harvested)
        total_hops = sum(p["hops"] for p in placements.values())

        # Compute bandwidth and link analysis
        bandwidth = compute_bandwidth(placements, bank_bw, num_banks)
        analysis, link_counts, bank_links = compute_link_analysis(placements, banks)
        congestion_free = analysis["max_link_load"] <= 1

        # Store in SQLite
        store_scenario_data(
            conn, name, placements, banks, link_counts, bank_links,
            bandwidth, total_hops,
        )

        # Generate Graphviz visualization
        generate_dot_and_svg(name, grid, banks, placements, harvested, viz_dir)

        # Build JSON result entry
        results["scenarios"][name] = {
            "placements": {
                str(k): {"x": v["x"], "y": v["y"], "noc": v["noc"], "hops": v["hops"]}
                for k, v in sorted(placements.items())
            },
            "total_hops": total_hops,
            "congestion_free": congestion_free,
            "bandwidth": bandwidth,
            "link_analysis": analysis,
        }

        print(
            f"  total_hops={total_hops}, "
            f"bw={bandwidth['estimated_gbps']} GB/s, "
            f"links={analysis['total_links_used']}, "
            f"congestion_free={congestion_free}"
        )

    conn.close()

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults written to /app/results.json")
    print(f"Database written to /app/noc_analysis.db")
    print(f"Visualizations written to /app/viz/")


if __name__ == "__main__":
    main()
