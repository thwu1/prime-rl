#!/usr/bin/env python3
"""
CSIG Multi-Bottleneck Congestion Control Simulator

Parses topology from Graphviz DOT format and flows from CSV, runs the
CSIG-AIMD simulation to compute weighted max-min fair rate allocations,
and produces convergence data with gnuplot visualization.

"""

import csv
import json
import os
import re
import subprocess
import sys


def parse_dot_topology(filepath):
    """Parse Graphviz DOT file to extract link IDs and capacities.

    Matches edges of the form:
        NODE -- NODE [id="LINK_ID", capacity="VALUE"];
    Attribute order may vary.
    """
    links = {}
    with open(filepath) as f:
        content = f.read()

    edge_re = re.compile(r'\w+\s*--\s*\w+\s*\[([^\]]*)\]')
    for match in edge_re.finditer(content):
        attrs = match.group(1)
        id_m = re.search(r'id\s*=\s*"([^"]*)"', attrs)
        cap_m = re.search(r'capacity\s*=\s*"([^"]*)"', attrs)
        if id_m and cap_m:
            links[id_m.group(1)] = float(cap_m.group(1))

    if not links:
        sys.exit("ERROR: no links found in DOT topology file")
    return links


def parse_flows_csv(filepath):
    """Parse CSV flow definitions. Path is colon-separated list of link IDs."""
    flows = {}
    with open(filepath) as f:
        reader = csv.DictReader(f)
        for row in reader:
            flows[row["flow_id"]] = {
                "path": row["path"].split(":"),
                "weight": int(row["weight"]),
            }
    if not flows:
        sys.exit("ERROR: no flows found in CSV file")
    return flows


def build_link_flow_map(link_ids, flows):
    """Map each link to the list of flows that traverse it."""
    lf = {lid: [] for lid in link_ids}
    for fid, fdata in flows.items():
        for lid in fdata["path"]:
            if lid not in lf:
                lf[lid] = []
            lf[lid].append(fid)
    return lf


def run_simulation(links, flows, alpha=1.0, beta=0.5, min_rate=0.01,
                   total_rounds=10000, warmup=7000):
    """Run CSIG-AIMD simulation and return all results."""
    link_flows = build_link_flow_map(links, flows)
    flow_ids = sorted(flows.keys())

    # Initialize rates: weight * alpha
    rates = {fid: flows[fid]["weight"] * alpha for fid in flows}

    # Accumulators for post-warmup averaging
    rate_sums = {fid: 0.0 for fid in flows}
    avg_count = 0

    # Convergence tracking
    prev_rates = dict(rates)
    max_change_last_100 = []

    # Convergence data sampling
    sample_interval = max(1, total_rounds // 100)
    conv_data = []

    for rnd in range(1, total_rounds + 1):
        # Step 1: Compute per-link metrics
        link_util = {}
        link_vqd = {}
        for lid, cap in links.items():
            load = sum(rates[fid] for fid in link_flows.get(lid, []))
            link_util[lid] = load / cap
            link_vqd[lid] = max(0.0, load - cap) * 1000.0

        # Step 2: CSIG tag aggregation (compare-and-replace / max)
        csig_util = {}
        for fid, fdata in flows.items():
            max_u = 0.0
            for lid in fdata["path"]:
                if link_util[lid] > max_u:
                    max_u = link_util[lid]
            csig_util[fid] = max_u

        # Step 3: AIMD rate adjustment
        for fid, fdata in flows.items():
            if csig_util[fid] > 1.0:
                excess = min(csig_util[fid] - 1.0, 1.0)
                rates[fid] *= (1.0 - beta * excess)
            else:
                rates[fid] += alpha * fdata["weight"]

        # Step 4: Rate clamping
        for fid in flows:
            rates[fid] = max(rates[fid], min_rate)

        # Accumulate for averaging after warmup
        if rnd > warmup:
            for fid in flows:
                rate_sums[fid] += rates[fid]
            avg_count += 1

        # Convergence check window
        max_change = max(abs(rates[fid] - prev_rates[fid]) for fid in flows)
        if rnd > total_rounds - 100:
            max_change_last_100.append(max_change)
        prev_rates = dict(rates)

        # Sample convergence data periodically
        if rnd == 1 or rnd % sample_interval == 0:
            conv_data.append((rnd, {fid: rates[fid] for fid in flow_ids}))

    # Compute time-averaged rates
    avg_rates = {fid: rate_sums[fid] / avg_count for fid in flows}

    # Final-round link utilizations
    final_util = {}
    for lid, cap in links.items():
        load = sum(rates[fid] for fid in link_flows.get(lid, []))
        final_util[lid] = load / cap

    # Bottleneck identification (link with highest utilization on flow's path)
    bottleneck = {}
    for fid, fdata in flows.items():
        best_lid = max(fdata["path"], key=lambda lid: final_util[lid])
        bottleneck[fid] = best_lid

    converged = max(max_change_last_100) < 1.0 if max_change_last_100 else False

    return avg_rates, final_util, bottleneck, total_rounds, converged, conv_data, flow_ids


def write_outputs(avg_rates, final_util, bottleneck, total_rounds, converged,
                  conv_data, flow_ids, output_dir):
    """Write all output files and generate gnuplot convergence plot."""
    os.makedirs(output_dir, exist_ok=True)

    # flow_rates.json
    fr = {fid: round(r, 4) for fid, r in sorted(avg_rates.items())}
    with open(os.path.join(output_dir, "flow_rates.json"), "w") as f:
        json.dump(fr, f, indent=2)

    # link_utilization.json
    lu = {lid: round(u, 4) for lid, u in sorted(final_util.items())}
    with open(os.path.join(output_dir, "link_utilization.json"), "w") as f:
        json.dump(lu, f, indent=2)

    # summary.json
    summary = {
        "total_rounds": total_rounds,
        "converged": converged,
        "bottleneck_links": bottleneck,
    }
    with open(os.path.join(output_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    # convergence.dat (tab-separated)
    dat_path = os.path.join(output_dir, "convergence.dat")
    with open(dat_path, "w") as f:
        f.write("round\t" + "\t".join(flow_ids) + "\n")
        for rnd, rate_snap in conv_data:
            vals = "\t".join(f"{rate_snap[fid]:.4f}" for fid in flow_ids)
            f.write(f"{rnd}\t{vals}\n")

    # gnuplot script
    gp_path = os.path.join(output_dir, "convergence.gp")
    png_path = os.path.join(output_dir, "convergence.png")
    plot_parts = []
    for i, fid in enumerate(flow_ids, 2):
        plot_parts.append(
            f"'{dat_path}' using 1:{i} with lines title '{fid}'"
        )
    gp_lines = [
        "set terminal png size 1200,600",
        f"set output '{png_path}'",
        "set title 'CSIG-AIMD Flow Rate Convergence'",
        "set xlabel 'Simulation Round'",
        "set ylabel 'Sending Rate (Mbps)'",
        "set key outside right",
        "plot " + ", \\\n     ".join(plot_parts),
    ]
    with open(gp_path, "w") as f:
        f.write("\n".join(gp_lines) + "\n")

    subprocess.run(["gnuplot", gp_path], check=True)


def main():
    links = parse_dot_topology("/app/topology.dot")
    flows = parse_flows_csv("/app/flows.csv")

    results = run_simulation(links, flows)
    write_outputs(*results, output_dir="/app/output")


if __name__ == "__main__":
    main()
