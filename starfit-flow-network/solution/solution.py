#!/usr/bin/env python3
"""STARFIT Reservoir Network Simulator.


Implements a multi-reservoir flow network simulation using the STARFIT
(Storage Targets And Release Function Inference Tool) model with DAG-based
routing and 24 hourly substeps per daily timestep.
"""

import csv
import json
import math
import os
from collections import deque


OMEGA = 1.0 / 52.0
M3PS_TO_MCM = 3600.0 / 1.0e6   # hourly substep: 1 hr * 3600 s / 1e6
MCM_TO_M3PS = 1.0e6 / 3600.0


def load_config(path):
    with open(path) as f:
        return json.load(f)


def load_inflows(path):
    """Load lateral inflows CSV. Returns {day: {node_id: inflow_cms}}."""
    data = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            day = int(row['day'])
            data[day] = {}
            for key in row:
                if key.startswith('node_'):
                    nid = int(key.split('_')[1])
                    data[day][nid] = float(row[key])
    return data


def epiweek(day):
    return min(1 + (day - 1) // 7, 52)


def max_nor(params, ew):
    val = (params['NORhi_mu']
           + params['NORhi_alpha'] * math.sin(2.0 * math.pi * OMEGA * ew)
           + params['NORhi_beta'] * math.cos(2.0 * math.pi * OMEGA * ew))
    return min(params['NORhi_max'], max(params['NORhi_min'], val))


def min_nor(params, ew):
    val = (params['NORlo_mu']
           + params['NORlo_alpha'] * math.sin(2.0 * math.pi * OMEGA * ew)
           + params['NORlo_beta'] * math.cos(2.0 * math.pi * OMEGA * ew))
    return min(params['NORlo_max'], max(params['NORlo_min'], val))


def calc_release(ew, capacity_MCM, storage_MCM, inflow_cms,
                 obs_meanflow_cms, params):
    """STARFIT release calculation.

    Returns (release_m3_per_day, availability_status).
    """
    storage_m3 = storage_MCM * 1.0e6
    capacity_m3 = capacity_MCM * 1.0e6

    max_normal = max_nor(params, ew)
    min_normal = min_nor(params, ew)

    forecasted_weekly_volume = 7.0 * inflow_cms * 24.0 * 60.0 * 60.0
    mean_weekly_volume = 7.0 * obs_meanflow_cms * 24.0 * 60.0 * 60.0

    standardized_inflow = (forecasted_weekly_volume / mean_weekly_volume) - 1.0

    standardized_weekly_release = (
        params['Release_alpha1'] * math.sin(2.0 * math.pi * OMEGA * ew)
        + params['Release_alpha2'] * math.sin(4.0 * math.pi * OMEGA * ew)
        + params['Release_beta1'] * math.cos(2.0 * math.pi * OMEGA * ew)
        + params['Release_beta2'] * math.cos(4.0 * math.pi * OMEGA * ew)
    )

    release_min_vol = mean_weekly_volume * (1.0 + params['Release_min']) / 7.0
    release_max_vol = mean_weekly_volume * (1.0 + params['Release_max']) / 7.0

    availability_status = (
        (100.0 * storage_m3 / capacity_m3 - min_normal)
        / (max_normal - min_normal)
    )

    release = (
        mean_weekly_volume
        * (1.0 + (standardized_weekly_release
                  + params['Release_c']
                  + params['Release_p1'] * availability_status
                  + params['Release_p2'] * standardized_inflow))
        / 7.0
    )

    release_above = (
        storage_m3 - capacity_m3 * max_normal / 100.0
        + forecasted_weekly_volume
    ) / 7.0

    release_below = (
        storage_m3 - capacity_m3 * min_normal / 100.0
        + forecasted_weekly_volume
    ) / 7.0

    if availability_status > 1.0:
        release = release_above
    if availability_status < 0.0:
        release = release_below

    release = max(release_min_vol, min(release_max_vol, release))

    return release, availability_status


def topological_sort(nodes):
    """Kahn's algorithm for topological ordering of the network DAG."""
    n = len(nodes)
    adj = {i: [] for i in range(n)}
    in_degree = {i: 0 for i in range(n)}

    for node in nodes:
        to = node['to']
        if to >= 0:
            adj[node['id']].append(to)
            in_degree[to] += 1

    queue = deque(i for i in range(n) if in_degree[i] == 0)
    order = []
    while queue:
        v = queue.popleft()
        order.append(v)
        for w in adj[v]:
            in_degree[w] -= 1
            if in_degree[w] == 0:
                queue.append(w)

    if len(order) != n:
        raise ValueError("Network contains a cycle — not a valid DAG")
    return order


def simulate(config, inflows):
    """Run the 365-day, 24-substep STARFIT network simulation."""
    nodes = config['network']['nodes']
    n_nodes = len(nodes)
    n_days = config['simulation']['n_days']
    n_substeps = config['simulation']['n_substeps']

    # Node metadata
    node_type = {}
    node_to = {}
    res_params = {}
    for node in nodes:
        nid = node['id']
        node_type[nid] = node['type']
        node_to[nid] = node['to']
        if node['type'] == 'reservoir':
            res_params[nid] = config['reservoirs'][node['reservoir_key']]

    # Topological order
    topo_order = topological_sort(nodes)

    # Initialise reservoir storage
    storage = {}
    for nid, params in res_params.items():
        hi = max_nor(params, 1)
        lo = min_nor(params, 1)
        storage[nid] = params['GRanD_CAP_MCM'] * (hi + lo) / 2.0 / 100.0

    results = []

    for day in range(1, n_days + 1):
        ew = epiweek(day)

        # Per-node daily accumulators
        outflow_acc = [0.0] * n_nodes
        release_acc = [0.0] * n_nodes
        spill_acc = [0.0] * n_nodes

        for istep in range(n_substeps):
            upstream_inflow = [0.0] * n_nodes

            for inode in topo_order:
                lateral = inflows[day][inode]
                total_inflow = upstream_inflow[inode] + lateral

                if node_type[inode] == 'passthrough':
                    outflow_sub = total_inflow
                    release_sub = total_inflow
                    spill_sub = 0.0
                else:
                    params = res_params[inode]
                    capacity = params['GRanD_CAP_MCM']
                    obs_mean = params['Obs_MEANFLOW_CUMECS']

                    inflow_sub = total_inflow

                    release_m3pd, _ = calc_release(
                        ew, capacity, storage[inode],
                        inflow_sub, obs_mean, params
                    )
                    release_sub = release_m3pd / 86400.0

                    sc = (inflow_sub - release_sub) * M3PS_TO_MCM

                    if (storage[inode] + sc) < 0.0:
                        potential = (release_sub
                                     + (storage[inode] + sc) * MCM_TO_M3PS)
                        release_sub = max(potential, 0.0)
                        sc = (inflow_sub - release_sub) * M3PS_TO_MCM

                    storage[inode] = max(storage[inode] + sc, 0.0)

                    spill_sub = 0.0
                    if storage[inode] > capacity:
                        spill_sub = ((storage[inode] - capacity) * MCM_TO_M3PS)
                        storage[inode] = capacity

                    outflow_sub = release_sub + spill_sub

                # Propagate downstream
                to = node_to[inode]
                if to >= 0:
                    upstream_inflow[to] += outflow_sub

                # Accumulate
                outflow_acc[inode] += outflow_sub
                release_acc[inode] += release_sub
                spill_acc[inode] += spill_sub

        # Record daily results for each node
        for inode in range(n_nodes):
            results.append({
                'day': day,
                'node_id': inode,
                'outflow_cms': outflow_acc[inode] / n_substeps,
                'storage_MCM': storage.get(inode, 0.0),
                'release_cms': release_acc[inode] / n_substeps,
                'spill_cms': spill_acc[inode] / n_substeps,
            })

    return results


def write_results(results, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fieldnames = ['day', 'node_id', 'outflow_cms', 'storage_MCM',
                  'release_cms', 'spill_cms']
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            out = {}
            for k, v in row.items():
                if isinstance(v, float):
                    out[k] = f'{v:.12f}'
                else:
                    out[k] = v
            writer.writerow(out)


def main():
    config = load_config('/app/config.json')
    inflows = load_inflows('/app/forcing/inflows.csv')
    results = simulate(config, inflows)
    write_results(results, '/app/output/results.csv')
    print("Simulation complete. Results written to /app/output/results.csv")


if __name__ == '__main__':
    main()
