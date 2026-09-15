#!/usr/bin/env python3
"""
Solve min-cost max-flow with node capacities via LP using GLPK.

Two-phase approach per test case:
  Phase 1: Maximize total source-to-sink flow (LP)
  Phase 2: Minimize cost subject to total flow = max_flow from Phase 1 (LP)

Each phase generates a GMPL model file and invokes glpsol.
GMPL printf statements produce structured output parsed by this script.
"""

import json
import subprocess
import os
import sys


def generate_gmpl(tc, phase, max_flow_val=None):
    """Generate a complete GMPL file (model + inline data) for one phase."""
    nodes = list(range(tc["num_nodes"]))
    edges = tc["edges"]
    source = tc["source"]
    sink = tc["sink"]
    node_caps = tc.get("node_capacities", {})

    lines = []

    # Model section
    lines.append("/* Min-Cost Max-Flow LP — Phase %d */" % phase)
    lines.append("set NODES;")
    lines.append("set ARCS within NODES cross NODES;")
    lines.append("param s in NODES;")
    lines.append("param t in NODES;")
    lines.append("param cap{ARCS}, >= 0;")
    lines.append("param cost{ARCS}, >= 0;")
    lines.append("set NCAP_NODES within NODES, default {};")
    lines.append("param ncap{NCAP_NODES}, >= 0;")

    if phase == 2:
        lines.append("param max_flow_val, >= 0;")

    lines.append("")
    lines.append("var flow{(i,j) in ARCS}, >= 0, <= cap[i,j];")
    lines.append("")

    if phase == 1:
        lines.append("maximize total_flow: sum{(i,j) in ARCS: i = s} flow[i,j];")
    else:
        lines.append(
            "minimize total_cost: sum{(i,j) in ARCS} cost[i,j] * flow[i,j];"
        )
        lines.append("")
        lines.append(
            "s.t. fix_flow: sum{(i,j) in ARCS: i = s} flow[i,j] = max_flow_val;"
        )

    lines.append("")
    lines.append("s.t. conservation{k in NODES: k != s and k != t}:")
    lines.append(
        "    sum{(i,k) in ARCS} flow[i,k] = sum{(k,j) in ARCS} flow[k,j];"
    )

    if node_caps:
        lines.append("")
        lines.append("s.t. node_cap_cstr{k in NCAP_NODES}:")
        lines.append("    sum{(i,k) in ARCS} flow[i,k] <= ncap[k];")

    lines.append("")
    lines.append("solve;")
    lines.append("")

    if phase == 1:
        lines.append(
            'printf "OBJECTIVE %.0f\\n", sum{(i,j) in ARCS: i = s} flow[i,j];'
        )
    else:
        lines.append(
            'printf "OBJECTIVE %.0f\\n", '
            "sum{(i,j) in ARCS} cost[i,j] * flow[i,j];"
        )

    lines.append(
        'printf{(i,j) in ARCS: flow[i,j] > 0.5} '
        '"FLOW %d %d %.0f\\n", i, j, flow[i,j];'
    )
    lines.append("")

    # Data section
    lines.append("data;")
    lines.append("")
    lines.append("set NODES := %s;" % " ".join(str(n) for n in nodes))

    arcs_str = " ".join("(%d,%d)" % (e["from"], e["to"]) for e in edges)
    lines.append("set ARCS := %s;" % arcs_str)

    lines.append("param s := %d;" % source)
    lines.append("param t := %d;" % sink)

    cap_parts = " ".join(
        "[%d,%d] %d" % (e["from"], e["to"], e["capacity"]) for e in edges
    )
    lines.append("param cap := %s;" % cap_parts)

    cost_parts = " ".join(
        "[%d,%d] %d" % (e["from"], e["to"], e["cost"]) for e in edges
    )
    lines.append("param cost := %s;" % cost_parts)

    if node_caps:
        ncap_nodes_str = " ".join(str(k) for k in node_caps.keys())
        lines.append("set NCAP_NODES := %s;" % ncap_nodes_str)
        ncap_str = " ".join("[%s] %d" % (k, v) for k, v in node_caps.items())
        lines.append("param ncap := %s;" % ncap_str)

    if phase == 2 and max_flow_val is not None:
        lines.append("param max_flow_val := %d;" % max_flow_val)

    lines.append("")
    lines.append("end;")

    return "\n".join(lines)


def parse_glpsol_stdout(stdout):
    """Parse structured printf output from GMPL model."""
    objective = None
    flows = {}
    for line in stdout.strip().split("\n"):
        line = line.strip()
        if line.startswith("OBJECTIVE"):
            objective = int(float(line.split()[1]))
        elif line.startswith("FLOW"):
            parts = line.split()
            u, v, f = int(parts[1]), int(parts[2]), int(float(parts[3]))
            if f > 0:
                flows["%d,%d" % (u, v)] = f
    return objective, flows


def main():
    with open("/app/network_data.json") as f:
        data = json.load(f)

    artifacts_dir = "/app/lp_artifacts"
    os.makedirs(artifacts_dir, exist_ok=True)

    results = {"test_cases": []}

    for tc in data["test_cases"]:
        name = tc["name"]
        print("Solving test case: %s" % name)

        # Phase 1: Maximize flow
        p1_mod = os.path.join(artifacts_dir, "%s_phase1.mod" % name)
        p1_sol = os.path.join(artifacts_dir, "%s_phase1.sol" % name)

        with open(p1_mod, "w") as f:
            f.write(generate_gmpl(tc, phase=1))

        p1 = subprocess.run(
            ["glpsol", "--model", p1_mod, "--output", p1_sol],
            capture_output=True,
            text=True,
        )
        if p1.returncode != 0:
            print("glpsol Phase 1 failed for %s:" % name, file=sys.stderr)
            print(p1.stderr, file=sys.stderr)
            sys.exit(1)

        max_flow, _ = parse_glpsol_stdout(p1.stdout)
        print("  Phase 1 max_flow = %d" % max_flow)

        # Phase 2: Minimize cost at fixed max flow
        p2_mod = os.path.join(artifacts_dir, "%s_phase2.mod" % name)
        p2_sol = os.path.join(artifacts_dir, "%s_phase2.sol" % name)

        with open(p2_mod, "w") as f:
            f.write(generate_gmpl(tc, phase=2, max_flow_val=max_flow))

        p2 = subprocess.run(
            ["glpsol", "--model", p2_mod, "--output", p2_sol],
            capture_output=True,
            text=True,
        )
        if p2.returncode != 0:
            print("glpsol Phase 2 failed for %s:" % name, file=sys.stderr)
            print(p2.stderr, file=sys.stderr)
            sys.exit(1)

        min_cost, edge_flows = parse_glpsol_stdout(p2.stdout)
        print("  Phase 2 min_cost = %d" % min_cost)

        results["test_cases"].append(
            {
                "name": name,
                "max_flow": max_flow,
                "min_cost": min_cost,
                "edge_flows": edge_flows,
            }
        )

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")


if __name__ == "__main__":
    main()
