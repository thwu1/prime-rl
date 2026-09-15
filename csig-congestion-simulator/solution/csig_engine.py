#!/usr/bin/env python3
"""
CSIG Congestion Control Engine: AIMD Simulation + Progressive Filling Analysis.

Implements both CSIG-AIMD iterative simulation and the analytical progressive
filling algorithm for weighted max-min fair rate allocation in multi-bottleneck
datacenter topologies.

"""

import csv
import json
import os
import re
import subprocess
import sys


def parse_dot(filepath):
    """Extract link IDs and capacities from Graphviz DOT topology."""
    links = {}
    with open(filepath) as f:
        content = f.read()
    for match in re.finditer(r'\w+\s*--\s*\w+\s*\[([^\]]*)\]', content):
        attrs = match.group(1)
        lid = re.search(r'id\s*=\s*"([^"]*)"', attrs)
        cap = re.search(r'capacity\s*=\s*"([^"]*)"', attrs)
        if lid and cap:
            links[lid.group(1)] = float(cap.group(1))
    if not links:
        sys.exit("ERROR: no links found in DOT topology file")
    return links


def parse_flows(filepath):
    """Parse CSV flow definitions with colon-separated paths."""
    flows = {}
    with open(filepath) as f:
        for row in csv.DictReader(f):
            flows[row["flow_id"]] = {
                "path": row["path"].split(":"),
                "weight": int(row["weight"]),
            }
    if not flows:
        sys.exit("ERROR: no flows found in CSV file")
    return flows


def build_link_flow_map(links, flows):
    """Map each link to the flows that traverse it."""
    lf = {lid: [] for lid in links}
    for fid, fd in flows.items():
        for lid in fd["path"]:
            lf.setdefault(lid, []).append(fid)
    return lf


def csig_aimd_simulate(links, flows, alpha=1.0, beta=0.5, min_rate=0.01,
                       total_rounds=10000, warmup=7000):
    """Run CSIG-AIMD simulation, return time-averaged rates and diagnostics."""
    link_flows = build_link_flow_map(links, flows)
    flow_ids = sorted(flows)

    # Initialize rates: weight * alpha
    rates = {fid: flows[fid]["weight"] * alpha for fid in flows}
    rate_sums = {fid: 0.0 for fid in flows}
    avg_count = 0

    sample_interval = max(1, total_rounds // 100)
    conv_data = []
    max_changes = []
    prev_rates = dict(rates)

    for rnd in range(1, total_rounds + 1):
        # Step 1: Per-link utilization
        link_util = {}
        for lid, cap in links.items():
            load = sum(rates[fid] for fid in link_flows.get(lid, []))
            link_util[lid] = load / cap

        # Step 2: CSIG tag aggregation (max along path)
        csig_tag = {}
        for fid, fd in flows.items():
            csig_tag[fid] = max(link_util.get(lid, 0.0) for lid in fd["path"])

        # Step 3: AIMD rate adjustment
        for fid, fd in flows.items():
            if csig_tag[fid] > 1.0:
                excess = min(csig_tag[fid] - 1.0, 1.0)
                rates[fid] *= (1.0 - beta * excess)
            else:
                rates[fid] += alpha * fd["weight"]
            rates[fid] = max(rates[fid], min_rate)

        # Post-warmup accumulation
        if rnd > warmup:
            for fid in flows:
                rate_sums[fid] += rates[fid]
            avg_count += 1

        # Convergence tracking
        mc = max(abs(rates[fid] - prev_rates[fid]) for fid in flows)
        if rnd > total_rounds - 100:
            max_changes.append(mc)
        prev_rates = dict(rates)

        # Periodic sampling
        if rnd == 1 or rnd % sample_interval == 0:
            conv_data.append((rnd, {fid: rates[fid] for fid in flow_ids}))

    avg_rates = {fid: rate_sums[fid] / avg_count for fid in flows}

    # Final-round link utilization
    final_util = {}
    for lid, cap in links.items():
        load = sum(rates[fid] for fid in link_flows.get(lid, []))
        final_util[lid] = load / cap

    # Bottleneck: highest-utilization link on each flow's path
    sim_bn = {}
    for fid, fd in flows.items():
        sim_bn[fid] = max(fd["path"], key=lambda l: final_util.get(l, 0))

    converged = max(max_changes) < 1.0 if max_changes else False

    return avg_rates, final_util, sim_bn, total_rounds, converged, conv_data, flow_ids


def progressive_filling(links, flows):
    """Compute exact weighted max-min fair rates via progressive filling.

    Iteratively finds the link with the minimum per-weight fair share among
    remaining (unassigned) flows, fixes the rates of all flows traversing that
    link at the weighted share, subtracts their consumed bandwidth from all
    other links they traverse, and repeats until all flows are assigned.
    """
    remaining = set(flows)
    residual = dict(links)
    assigned = {}
    filling_order = []

    while remaining:
        # Find the tightest bottleneck among all links with remaining flows
        min_share = float('inf')
        bn_link = None

        for lid in links:
            active = [fid for fid in remaining if lid in flows[fid]["path"]]
            if not active:
                continue
            total_w = sum(flows[fid]["weight"] for fid in active)
            share = residual[lid] / total_w
            if share < min_share:
                min_share = share
                bn_link = lid

        if bn_link is None:
            break

        # Fix rates for all remaining flows on the bottleneck link
        bn_flows = [fid for fid in remaining if bn_link in flows[fid]["path"]]
        for fid in bn_flows:
            assigned[fid] = flows[fid]["weight"] * min_share
            remaining.discard(fid)

        # Subtract consumed bandwidth from all links these flows traverse
        for fid in bn_flows:
            for lid in flows[fid]["path"]:
                residual[lid] -= assigned[fid]

        filling_order.append([bn_link, round(min_share, 6)])

    # Analytical utilization
    ana_util = {}
    for lid, cap in links.items():
        load = sum(assigned.get(fid, 0) for fid in flows
                   if lid in flows[fid]["path"])
        ana_util[lid] = load / cap

    # Analytical bottleneck per flow
    ana_bn = {}
    for fid, fd in flows.items():
        ana_bn[fid] = max(fd["path"], key=lambda l: ana_util.get(l, 0))

    return assigned, ana_util, ana_bn, filling_order


def write_outputs(sim_rates, sim_util, sim_bn, total_rounds, converged,
                  conv_data, flow_ids, ana_rates, ana_util, ana_bn,
                  filling_order, outdir):
    """Write all output files and generate gnuplot convergence plot."""
    os.makedirs(outdir, exist_ok=True)

    # simulation_rates.json
    with open(os.path.join(outdir, "simulation_rates.json"), "w") as f:
        json.dump({k: round(v, 4) for k, v in sorted(sim_rates.items())},
                  f, indent=2)

    # analytical_rates.json
    with open(os.path.join(outdir, "analytical_rates.json"), "w") as f:
        json.dump({k: round(v, 4) for k, v in sorted(ana_rates.items())},
                  f, indent=2)

    # link_utilization.json (from simulation final round)
    with open(os.path.join(outdir, "link_utilization.json"), "w") as f:
        json.dump({k: round(v, 4) for k, v in sorted(sim_util.items())},
                  f, indent=2)

    # summary.json
    summary = {
        "total_rounds": total_rounds,
        "converged": converged,
        "bottleneck_links": ana_bn,
        "filling_order": filling_order,
    }
    with open(os.path.join(outdir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    # comparison.json
    comp = []
    for fid in sorted(sim_rates):
        s = sim_rates[fid]
        a = ana_rates.get(fid, 0)
        comp.append({
            "flow_id": fid,
            "simulated": round(s, 4),
            "analytical": round(a, 4),
            "relative_error": round(abs(s - a) / a, 6) if a > 0 else 0.0,
        })
    with open(os.path.join(outdir, "comparison.json"), "w") as f:
        json.dump(comp, f, indent=2)

    # convergence.dat (tab-separated)
    dat_path = os.path.join(outdir, "convergence.dat")
    with open(dat_path, "w") as f:
        f.write("round\t" + "\t".join(flow_ids) + "\n")
        for rnd, snap in conv_data:
            vals = "\t".join(f"{snap[fid]:.4f}" for fid in flow_ids)
            f.write(f"{rnd}\t{vals}\n")

    # gnuplot convergence plot
    gp_path = os.path.join(outdir, "convergence.gp")
    png_path = os.path.join(outdir, "convergence.png")
    plot_parts = []
    for i, fid in enumerate(flow_ids, 2):
        plot_parts.append(
            f"'{dat_path}' using 1:{i} with lines title '{fid}'"
        )
    gp_script = (
        f"set terminal png size 1200,600\n"
        f"set output '{png_path}'\n"
        "set title 'CSIG-AIMD Flow Rate Convergence'\n"
        "set xlabel 'Simulation Round'\n"
        "set ylabel 'Sending Rate (Mbps)'\n"
        "set key outside right\n"
        "plot " + ", \\\n     ".join(plot_parts) + "\n"
    )
    with open(gp_path, "w") as f:
        f.write(gp_script)

    subprocess.run(["gnuplot", gp_path], check=True)


def main():
    links = parse_dot("/app/topology.dot")
    flows = parse_flows("/app/flows.csv")

    # Run CSIG-AIMD simulation
    sim_rates, sim_util, sim_bn, total_rounds, converged, conv_data, flow_ids = \
        csig_aimd_simulate(links, flows)

    # Run progressive filling analytical solver
    ana_rates, ana_util, ana_bn, filling_order = progressive_filling(links, flows)

    # Write all outputs
    write_outputs(sim_rates, sim_util, sim_bn, total_rounds, converged,
                  conv_data, flow_ids, ana_rates, ana_util, ana_bn,
                  filling_order, "/app/output")


if __name__ == "__main__":
    main()
