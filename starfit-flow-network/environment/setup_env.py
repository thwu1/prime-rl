#!/usr/bin/env python3
"""Set up the reservoir network task environment.

Creates:
  /app/network.db   — SQLite database with network topology, reservoir params,
                       and simulation configuration across multiple tables
  /app/forcing.nc   — NetCDF4 lateral inflow forcing data
  /app/observations.nc — NetCDF4 reference headwater reservoir output for validation
"""

import math
import os
import sqlite3

import numpy as np
from netCDF4 import Dataset

OMEGA = 1.0 / 52.0

RESERVOIRS = {
    "A": {
        "GRanD_CAP_MCM": 1200.0,
        "Obs_MEANFLOW_CUMECS": 85.0,
        "NORhi_min": 60.0, "NORhi_max": 95.0,
        "NORhi_alpha": 5.0, "NORhi_beta": 3.0, "NORhi_mu": 78.0,
        "NORlo_min": 20.0, "NORlo_max": 55.0,
        "NORlo_alpha": -3.0, "NORlo_beta": 2.0, "NORlo_mu": 35.0,
        "Release_min": -0.4, "Release_max": 1.8,
        "Release_alpha1": 0.12, "Release_alpha2": -0.04,
        "Release_beta1": 0.09, "Release_beta2": -0.025,
        "Release_p1": 0.18, "Release_p2": 0.08, "Release_c": -0.02,
    },
    "B": {
        "GRanD_CAP_MCM": 800.0,
        "Obs_MEANFLOW_CUMECS": 120.0,
        "NORhi_min": 55.0, "NORhi_max": 92.0,
        "NORhi_alpha": 4.0, "NORhi_beta": -2.5, "NORhi_mu": 75.0,
        "NORlo_min": 18.0, "NORlo_max": 50.0,
        "NORlo_alpha": -2.5, "NORlo_beta": 1.5, "NORlo_mu": 32.0,
        "Release_min": -0.3, "Release_max": 2.0,
        "Release_alpha1": 0.08, "Release_alpha2": -0.06,
        "Release_beta1": 0.11, "Release_beta2": -0.04,
        "Release_p1": 0.12, "Release_p2": 0.15, "Release_c": 0.01,
    },
    "C": {
        "GRanD_CAP_MCM": 350.0,
        "Obs_MEANFLOW_CUMECS": 30.0,
        "NORhi_min": 58.0, "NORhi_max": 90.0,
        "NORhi_alpha": 6.0, "NORhi_beta": -4.0, "NORhi_mu": 72.0,
        "NORlo_min": 15.0, "NORlo_max": 48.0,
        "NORlo_alpha": -4.0, "NORlo_beta": 3.0, "NORlo_mu": 30.0,
        "Release_min": -0.6, "Release_max": 1.5,
        "Release_alpha1": 0.15, "Release_alpha2": -0.03,
        "Release_beta1": 0.06, "Release_beta2": -0.02,
        "Release_p1": 0.20, "Release_p2": 0.05, "Release_c": -0.03,
    },
}

NODES = [
    (0, "reservoir", 1, "A"),
    (1, "passthrough", 2, None),
    (2, "reservoir", 3, "B"),
    (3, "passthrough", -1, None),
    (4, "reservoir", 3, "C"),
]


def get_lateral_inflow(day, node_id):
    d = day
    if node_id == 0:
        return (50.0
                + 30.0 * math.sin(2.0 * math.pi * d / 365.0)
                + 10.0 * math.sin(4.0 * math.pi * d / 365.0))
    elif node_id == 1:
        return 5.0
    elif node_id == 2:
        return 8.0
    elif node_id == 3:
        return 3.0
    elif node_id == 4:
        return (20.0
                + 15.0 * math.sin(2.0 * math.pi * d / 365.0 + math.pi / 4.0))
    return 0.0


def max_nor(params, ew):
    val = (params["NORhi_mu"]
           + params["NORhi_alpha"] * math.sin(2 * math.pi * OMEGA * ew)
           + params["NORhi_beta"] * math.cos(2 * math.pi * OMEGA * ew))
    return min(params["NORhi_max"], max(params["NORhi_min"], val))


def min_nor(params, ew):
    val = (params["NORlo_mu"]
           + params["NORlo_alpha"] * math.sin(2 * math.pi * OMEGA * ew)
           + params["NORlo_beta"] * math.cos(2 * math.pi * OMEGA * ew))
    return min(params["NORlo_max"], max(params["NORlo_min"], val))


def calc_release(ew, cap_MCM, stor_MCM, inflow_cms, obs_mean, params):
    s_m3 = stor_MCM * 1e6
    c_m3 = cap_MCM * 1e6
    mn = max_nor(params, ew)
    ln = min_nor(params, ew)
    fwv = 7.0 * inflow_cms * 86400.0
    mwv = 7.0 * obs_mean * 86400.0
    si = fwv / mwv - 1.0
    swr = (params["Release_alpha1"] * math.sin(2 * math.pi * OMEGA * ew)
           + params["Release_alpha2"] * math.sin(4 * math.pi * OMEGA * ew)
           + params["Release_beta1"] * math.cos(2 * math.pi * OMEGA * ew)
           + params["Release_beta2"] * math.cos(4 * math.pi * OMEGA * ew))
    r_min = mwv * (1.0 + params["Release_min"]) / 7.0
    r_max = mwv * (1.0 + params["Release_max"]) / 7.0
    avail = (100.0 * s_m3 / c_m3 - ln) / (mn - ln)
    rel = mwv * (1.0 + swr + params["Release_c"]
                 + params["Release_p1"] * avail
                 + params["Release_p2"] * si) / 7.0
    r_above = (s_m3 - c_m3 * mn / 100.0 + fwv) / 7.0
    r_below = (s_m3 - c_m3 * ln / 100.0 + fwv) / 7.0
    if avail > 1.0:
        rel = r_above
    if avail < 0.0:
        rel = r_below
    rel = max(r_min, min(r_max, rel))
    return rel


def ref_simulate_headwater(params, n_days=365, n_sub=24):
    cap = params["GRanD_CAP_MCM"]
    obs = params["Obs_MEANFLOW_CUMECS"]
    m2m = 3600.0 / 1e6
    m2f = 1e6 / 3600.0
    hi = max_nor(params, 1)
    lo = min_nor(params, 1)
    stor = cap * (hi + lo) / 2.0 / 100.0
    outflows = np.empty(n_days)
    storages = np.empty(n_days)
    for day in range(1, n_days + 1):
        ew = min(1 + (day - 1) // 7, 52)
        lat = get_lateral_inflow(day, _current_node_id)
        oa, ra, sa = 0.0, 0.0, 0.0
        for _ in range(n_sub):
            rel_m3pd = calc_release(ew, cap, stor, lat, obs, params)
            rs = rel_m3pd / 86400.0
            sc = (lat - rs) * m2m
            if stor + sc < 0.0:
                rs = max(rs + (stor + sc) * m2f, 0.0)
                sc = (lat - rs) * m2m
            stor = max(stor + sc, 0.0)
            sp = 0.0
            if stor > cap:
                sp = (stor - cap) * m2f
                stor = cap
            oa += rs + sp
            ra += rs
            sa += sp
        outflows[day - 1] = oa / n_sub
        storages[day - 1] = stor
    return outflows, storages


def create_database():
    conn = sqlite3.connect("/app/network.db")
    c = conn.cursor()

    c.execute("""CREATE TABLE nodes (
        id INTEGER PRIMARY KEY,
        node_type TEXT NOT NULL,
        downstream_id INTEGER DEFAULT -1,
        reservoir_key TEXT
    )""")
    for nid, ntype, ds, rk in NODES:
        c.execute("INSERT INTO nodes VALUES (?,?,?,?)", (nid, ntype, ds, rk))

    c.execute("""CREATE TABLE nor_parameters (
        reservoir_key TEXT PRIMARY KEY,
        capacity_mcm REAL NOT NULL,
        obs_meanflow_cms REAL NOT NULL,
        norhi_mu REAL, norhi_alpha REAL, norhi_beta REAL,
        norhi_min REAL, norhi_max REAL,
        norlo_mu REAL, norlo_alpha REAL, norlo_beta REAL,
        norlo_min REAL, norlo_max REAL
    )""")

    c.execute("""CREATE TABLE release_parameters (
        reservoir_key TEXT PRIMARY KEY,
        alpha1 REAL, alpha2 REAL,
        beta1 REAL, beta2 REAL,
        p1 REAL, p2 REAL,
        c_coeff REAL,
        release_min REAL, release_max REAL
    )""")

    for key, p in RESERVOIRS.items():
        c.execute(
            "INSERT INTO nor_parameters VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, p["GRanD_CAP_MCM"], p["Obs_MEANFLOW_CUMECS"],
             p["NORhi_mu"], p["NORhi_alpha"], p["NORhi_beta"],
             p["NORhi_min"], p["NORhi_max"],
             p["NORlo_mu"], p["NORlo_alpha"], p["NORlo_beta"],
             p["NORlo_min"], p["NORlo_max"]),
        )
        c.execute(
            "INSERT INTO release_parameters VALUES (?,?,?,?,?,?,?,?,?,?)",
            (key,
             p["Release_alpha1"], p["Release_alpha2"],
             p["Release_beta1"], p["Release_beta2"],
             p["Release_p1"], p["Release_p2"], p["Release_c"],
             p["Release_min"], p["Release_max"]),
        )

    c.execute("""CREATE TABLE simulation_config (
        param_key TEXT PRIMARY KEY,
        param_value TEXT NOT NULL
    )""")
    c.execute("INSERT INTO simulation_config VALUES (?,?)",
              ("n_days", "365"))
    c.execute("INSERT INTO simulation_config VALUES (?,?)",
              ("n_substeps_per_day", "24"))
    c.execute("INSERT INTO simulation_config VALUES (?,?)",
              ("substep_duration_seconds", "3600"))

    conn.commit()
    conn.close()


def create_forcing_nc():
    n_days = 365
    n_nodes = 5
    ds = Dataset("/app/forcing.nc", "w", format="NETCDF4")
    ds.createDimension("day", n_days)
    ds.createDimension("node", n_nodes)
    dv = ds.createVariable("day", "i4", ("day",))
    dv[:] = np.arange(1, n_days + 1)
    dv.long_name = "simulation day"
    dv.units = "1"
    nv = ds.createVariable("node_id", "i4", ("node",))
    nv[:] = np.arange(n_nodes)
    nv.long_name = "network node identifier"
    iv = ds.createVariable("lateral_inflow", "f8", ("day", "node"))
    iv.long_name = "lateral inflow"
    iv.units = "m3 s-1"
    for d in range(1, n_days + 1):
        for n in range(n_nodes):
            iv[d - 1, n] = get_lateral_inflow(d, n)
    ds.title = "Lateral inflow forcing for reservoir network"
    ds.Conventions = "CF-1.8"
    ds.close()


def create_observations_nc():
    global _current_node_id
    n_days = 365

    _current_node_id = 0
    out_a, stor_a = ref_simulate_headwater(RESERVOIRS["A"])
    _current_node_id = 4
    out_c, stor_c = ref_simulate_headwater(RESERVOIRS["C"])

    ds = Dataset("/app/observations.nc", "w", format="NETCDF4")
    ds.createDimension("day", n_days)
    ds.createDimension("headwater", 2)
    dv = ds.createVariable("day", "i4", ("day",))
    dv[:] = np.arange(1, n_days + 1)
    dv.long_name = "simulation day"
    rv = ds.createVariable("node_id", "i4", ("headwater",))
    rv[:] = [0, 4]
    rv.long_name = "headwater reservoir node id"
    ov = ds.createVariable("observed_outflow", "f8", ("day", "headwater"))
    ov.long_name = "observed daily mean outflow"
    ov.units = "m3 s-1"
    ov[:, 0] = out_a
    ov[:, 1] = out_c
    sv = ds.createVariable("observed_storage", "f8", ("day", "headwater"))
    sv.long_name = "observed end-of-day storage"
    sv.units = "MCM"
    sv[:, 0] = stor_a
    sv[:, 1] = stor_c
    ds.title = "Observed headwater reservoir data for validation"
    ds.Conventions = "CF-1.8"
    ds.close()


_current_node_id = 0

if __name__ == "__main__":
    os.makedirs("/app/output", exist_ok=True)
    create_database()
    create_forcing_nc()
    create_observations_nc()
    print("Environment setup complete.")
