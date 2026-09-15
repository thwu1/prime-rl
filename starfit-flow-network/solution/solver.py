#!/usr/bin/env python3
"""STARFIT Reservoir Network Simulator — Solution.


Reads network topology and parameters from SQLite, forcing from NetCDF,
implements the STARFIT model with sub-daily routing, writes NetCDF output.
"""

import math
import os
import sqlite3
from collections import deque

import numpy as np
from netCDF4 import Dataset

OMEGA = 1.0 / 52.0


def load_sim_config(conn):
    c = conn.cursor()
    cfg = {}
    for row in c.execute("SELECT param_key, param_value FROM simulation_config"):
        cfg[row[0]] = row[1]
    return cfg


def load_nodes(conn):
    c = conn.cursor()
    nodes = []
    for row in c.execute("SELECT id, node_type, downstream_id, reservoir_key FROM nodes ORDER BY id"):
        nodes.append({
            "id": row[0], "type": row[1],
            "downstream_id": row[2], "reservoir_key": row[3],
        })
    return nodes


def load_reservoir_params(conn):
    c = conn.cursor()
    params = {}
    q = """
    SELECT n.reservoir_key, n.capacity_mcm, n.obs_meanflow_cms,
           n.norhi_mu, n.norhi_alpha, n.norhi_beta, n.norhi_min, n.norhi_max,
           n.norlo_mu, n.norlo_alpha, n.norlo_beta, n.norlo_min, n.norlo_max,
           r.alpha1, r.alpha2, r.beta1, r.beta2, r.p1, r.p2, r.c_coeff,
           r.release_min, r.release_max
    FROM nor_parameters n
    JOIN release_parameters r ON n.reservoir_key = r.reservoir_key
    """
    for row in c.execute(q):
        key = row[0]
        params[key] = {
            "GRanD_CAP_MCM": row[1], "Obs_MEANFLOW_CUMECS": row[2],
            "NORhi_mu": row[3], "NORhi_alpha": row[4], "NORhi_beta": row[5],
            "NORhi_min": row[6], "NORhi_max": row[7],
            "NORlo_mu": row[8], "NORlo_alpha": row[9], "NORlo_beta": row[10],
            "NORlo_min": row[11], "NORlo_max": row[12],
            "Release_alpha1": row[13], "Release_alpha2": row[14],
            "Release_beta1": row[15], "Release_beta2": row[16],
            "Release_p1": row[17], "Release_p2": row[18],
            "Release_c": row[19],
            "Release_min": row[20], "Release_max": row[21],
        }
    return params


def load_forcing(path):
    ds = Dataset(path, "r")
    days = ds.variables["day"][:].data
    node_ids = ds.variables["node_id"][:].data
    inflow = ds.variables["lateral_inflow"][:, :].data
    ds.close()
    result = {}
    for di, d in enumerate(days):
        result[int(d)] = {}
        for ni, nid in enumerate(node_ids):
            result[int(d)][int(nid)] = float(inflow[di, ni])
    return result


def epiweek(day):
    return min(1 + (day - 1) // 7, 52)


def max_nor(p, ew):
    v = (p["NORhi_mu"]
         + p["NORhi_alpha"] * math.sin(2 * math.pi * OMEGA * ew)
         + p["NORhi_beta"] * math.cos(2 * math.pi * OMEGA * ew))
    return min(p["NORhi_max"], max(p["NORhi_min"], v))


def min_nor(p, ew):
    v = (p["NORlo_mu"]
         + p["NORlo_alpha"] * math.sin(2 * math.pi * OMEGA * ew)
         + p["NORlo_beta"] * math.cos(2 * math.pi * OMEGA * ew))
    return min(p["NORlo_max"], max(p["NORlo_min"], v))


def calc_release(ew, cap, stor, inflow, obs, p):
    s3 = stor * 1e6
    c3 = cap * 1e6
    mn = max_nor(p, ew)
    ln = min_nor(p, ew)
    fwv = 7.0 * inflow * 86400.0
    mwv = 7.0 * obs * 86400.0
    si = fwv / mwv - 1.0
    swr = (p["Release_alpha1"] * math.sin(2 * math.pi * OMEGA * ew)
           + p["Release_alpha2"] * math.sin(4 * math.pi * OMEGA * ew)
           + p["Release_beta1"] * math.cos(2 * math.pi * OMEGA * ew)
           + p["Release_beta2"] * math.cos(4 * math.pi * OMEGA * ew))
    r_lo = mwv * (1.0 + p["Release_min"]) / 7.0
    r_hi = mwv * (1.0 + p["Release_max"]) / 7.0
    avail = (100.0 * s3 / c3 - ln) / (mn - ln)
    rel = mwv * (1.0 + swr + p["Release_c"]
                 + p["Release_p1"] * avail
                 + p["Release_p2"] * si) / 7.0
    ra = (s3 - c3 * mn / 100.0 + fwv) / 7.0
    rb = (s3 - c3 * ln / 100.0 + fwv) / 7.0
    if avail > 1.0:
        rel = ra
    if avail < 0.0:
        rel = rb
    rel = max(r_lo, min(r_hi, rel))
    return rel


def topological_sort(nodes):
    n = len(nodes)
    adj = {nd["id"]: [] for nd in nodes}
    indeg = {nd["id"]: 0 for nd in nodes}
    for nd in nodes:
        to = nd["downstream_id"]
        if to >= 0:
            adj[nd["id"]].append(to)
            indeg[to] += 1
    queue = deque(nid for nid, d in indeg.items() if d == 0)
    order = []
    while queue:
        v = queue.popleft()
        order.append(v)
        for w in adj[v]:
            indeg[w] -= 1
            if indeg[w] == 0:
                queue.append(w)
    return order


def simulate(nodes, res_params, forcing, n_days, n_sub, dt):
    node_type = {nd["id"]: nd["type"] for nd in nodes}
    node_to = {nd["id"]: nd["downstream_id"] for nd in nodes}
    node_rkey = {nd["id"]: nd["reservoir_key"] for nd in nodes}
    topo = topological_sort(nodes)
    n_nodes = len(nodes)

    m2m = dt / 1e6
    m2f = 1e6 / dt

    storage = {}
    for nid, ntype in node_type.items():
        if ntype == "reservoir":
            p = res_params[node_rkey[nid]]
            hi = max_nor(p, 1)
            lo = min_nor(p, 1)
            storage[nid] = p["GRanD_CAP_MCM"] * (hi + lo) / 2.0 / 100.0

    out_arr = np.zeros((n_days, n_nodes))
    stor_arr = np.zeros((n_days, n_nodes))
    rel_arr = np.zeros((n_days, n_nodes))
    spill_arr = np.zeros((n_days, n_nodes))

    for day in range(1, n_days + 1):
        ew = epiweek(day)
        oa = [0.0] * n_nodes
        ra = [0.0] * n_nodes
        sa = [0.0] * n_nodes

        for _ in range(n_sub):
            upstream = [0.0] * n_nodes
            for inode in topo:
                lat = forcing[day][inode]
                total_in = upstream[inode] + lat
                if node_type[inode] == "passthrough":
                    out_sub = total_in
                    rel_sub = total_in
                    sp_sub = 0.0
                else:
                    p = res_params[node_rkey[inode]]
                    cap = p["GRanD_CAP_MCM"]
                    obs = p["Obs_MEANFLOW_CUMECS"]
                    rel_m3pd = calc_release(ew, cap, storage[inode],
                                            total_in, obs, p)
                    rel_sub = rel_m3pd / 86400.0
                    sc = (total_in - rel_sub) * m2m
                    if storage[inode] + sc < 0.0:
                        rel_sub = max(rel_sub + (storage[inode] + sc) * m2f,
                                      0.0)
                        sc = (total_in - rel_sub) * m2m
                    storage[inode] = max(storage[inode] + sc, 0.0)
                    sp_sub = 0.0
                    if storage[inode] > cap:
                        sp_sub = (storage[inode] - cap) * m2f
                        storage[inode] = cap
                    out_sub = rel_sub + sp_sub

                to = node_to[inode]
                if to >= 0:
                    upstream[to] += out_sub
                oa[inode] += out_sub
                ra[inode] += rel_sub
                sa[inode] += sp_sub

        di = day - 1
        for inode in range(n_nodes):
            out_arr[di, inode] = oa[inode] / n_sub
            stor_arr[di, inode] = storage.get(inode, 0.0)
            rel_arr[di, inode] = ra[inode] / n_sub
            spill_arr[di, inode] = sa[inode] / n_sub

    return out_arr, stor_arr, rel_arr, spill_arr


def write_output(path, n_days, n_nodes, out, stor, rel, spill):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ds = Dataset(path, "w", format="NETCDF4")
    ds.createDimension("day", n_days)
    ds.createDimension("node", n_nodes)
    dv = ds.createVariable("day", "i4", ("day",))
    dv[:] = np.arange(1, n_days + 1)
    dv.long_name = "simulation day"
    nv = ds.createVariable("node_id", "i4", ("node",))
    nv[:] = np.arange(n_nodes)
    nv.long_name = "node identifier"
    ov = ds.createVariable("outflow_cms", "f8", ("day", "node"))
    ov[:] = out
    ov.units = "m3 s-1"
    sv = ds.createVariable("storage_MCM", "f8", ("day", "node"))
    sv[:] = stor
    sv.units = "MCM"
    rv = ds.createVariable("release_cms", "f8", ("day", "node"))
    rv[:] = rel
    rv.units = "m3 s-1"
    pv = ds.createVariable("spill_cms", "f8", ("day", "node"))
    pv[:] = spill
    pv.units = "m3 s-1"
    ds.close()


def main():
    conn = sqlite3.connect("/app/network.db")
    cfg = load_sim_config(conn)
    nodes = load_nodes(conn)
    res_params = load_reservoir_params(conn)
    conn.close()

    forcing = load_forcing("/app/forcing.nc")

    n_days = int(cfg["n_days"])
    n_sub = int(cfg["n_substeps_per_day"])
    dt = float(cfg["substep_duration_seconds"])

    out, stor, rel, spill = simulate(nodes, res_params, forcing,
                                     n_days, n_sub, dt)
    write_output("/app/output/simulation.nc", n_days, len(nodes),
                 out, stor, rel, spill)
    print("Simulation complete. Output: /app/output/simulation.nc")


if __name__ == "__main__":
    main()
