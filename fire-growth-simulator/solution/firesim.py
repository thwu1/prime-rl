#!/usr/bin/env python3

"""Wildland fire behavior and growth simulator with GDAL raster I/O and SQLite fuel parameters."""

import json
import math
import os
import sqlite3
import sys
import heapq
from math import gcd

import numpy as np
from osgeo import gdal

# ============================================================================
# Physical constants
# ============================================================================
PARTICLE_DENSITY = 32.0       # rho_p, lb/ft^3
TOTAL_MINERAL = 0.0555        # S_T
EFFECTIVE_MINERAL = 0.010     # S_e
HEAT_CONTENT = 8000.0         # Btu/lb
SIGMA_10H = 109.0             # 1/ft
SIGMA_100H = 30.0             # 1/ft
TONS_ACRE_TO_LB_FT2 = 2000.0 / 43560.0
SIZE_CLASS_BOUNDS = [1200.0, 192.0, 96.0, 48.0, 16.0]
CURE_WET = 1.20
CURE_DRY = 0.30
MAX_LB = 8.0                  # Anderson L/B cap
NB_NUMBERS = {91, 92, 93, 98, 99}
NODATA = -9999.0


# ============================================================================
# GDAL raster I/O
# ============================================================================
def read_raster(path):
    """Read a GDAL-supported raster and return (data_array, geotransform, projection_wkt)."""
    ds = gdal.Open(path)
    if ds is None:
        raise FileNotFoundError(f"Cannot open raster: {path}")
    band = ds.GetRasterBand(1)
    data = band.ReadAsArray()
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    ds = None
    return data, gt, proj


def write_geotiff(path, data, gt, proj, nodata=NODATA):
    """Write a Float32 GeoTIFF with given geotransform, projection, and nodata."""
    rows, cols = data.shape
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, cols, rows, 1, gdal.GDT_Float32)
    ds.SetGeoTransform(gt)
    if proj:
        ds.SetProjection(proj)
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(nodata)
    band.WriteArray(data.astype(np.float32))
    ds.FlushCache()
    ds = None


# ============================================================================
# Fuel model loading from SQLite
# ============================================================================
def load_fuel_models_sqlite(db_path):
    """Load fuel model parameters from SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM fuel_models").fetchall()
    models = {}
    t = TONS_ACRE_TO_LB_FT2
    for row in rows:
        num = int(row["fm_num"])
        if num in NB_NUMBERS:
            models[num] = {
                "n": num, "l1": 0, "l10": 0, "l100": 0,
                "lh": 0, "lw": 0, "s1": 1, "sh": 0, "sw": 0,
                "d": 0.1, "mx": 0.10,
                "hd": HEAT_CONTENT, "hl": HEAT_CONTENT,
                "dyn": False, "burn": False,
            }
        else:
            models[num] = {
                "n": num,
                "l1": float(row["load_1h_tpa"]) * t,
                "l10": float(row["load_10h_tpa"]) * t,
                "l100": float(row["load_100h_tpa"]) * t,
                "lh": float(row["load_herb_tpa"]) * t,
                "lw": float(row["load_woody_tpa"]) * t,
                "s1": float(row["sav_1h"]),
                "sh": float(row["sav_herb"]),
                "sw": float(row["sav_woody"]),
                "d": float(row["depth_ft"]),
                "mx": float(row["mx_dead_pct"]) / 100.0,
                "hd": HEAT_CONTENT, "hl": HEAT_CONTENT,
                "dyn": int(row["is_dynamic"]) == 1,
                "burn": True,
            }
    conn.close()
    return models


# ============================================================================
# Rothermel model helpers
# ============================================================================
def _size_class(sigma):
    for i, b in enumerate(SIZE_CLASS_BOUNDS):
        if sigma >= b:
            return i
    return len(SIZE_CLASS_BOUNDS)


def _pack(loads, savs, moists):
    ol, os_, om = [], [], []
    for l, s, m in zip(loads, savs, moists):
        if l > 0:
            ol.append(l)
            os_.append(s)
            om.append(m)
    return ol, os_, om


def _cat_weights(load, sav):
    area = [s * l / PARTICLE_DENSITY for s, l in zip(sav, load)]
    total = sum(area)
    if total <= 0:
        return [0.0] * len(area), 0.0
    return [a / total for a in area], total


def _net_load(load, sav, f):
    net = [l * (1.0 - TOTAL_MINERAL) for l in load]
    classes = [_size_class(s) for s in sav]
    unique_classes = set(classes)
    out = 0.0
    for k in unique_classes:
        g = sum(fi for fi, ci in zip(f, classes) if ci == k)
        net_sum = sum(ni for ni, ci in zip(net, classes) if ci == k)
        out += g * net_sum
    return out


def _moisture_damping(mf, mx):
    if mx <= 0:
        return 0.0
    r = min(mf / mx, 1.0)
    return 1.0 - 2.59 * r + 5.11 * r * r - 3.52 * r * r * r


def _cured_fraction(m_live_herb):
    frac = (CURE_WET - m_live_herb) / (CURE_WET - CURE_DRY)
    return max(0.0, min(frac, 1.0))


# ============================================================================
# Rothermel kernel
# ============================================================================
def rothermel_kernel(fm, m_1h, m_10h, m_100h, m_live_herb, m_live_woody):
    """Compute wind/slope-independent terms. Returns dict with r0, C, B, E, etc."""
    if not fm["burn"]:
        return {"r0": 0, "C": 0, "B": 0, "E": 0, "beta_ratio": 1,
                "beta": 0, "ri": 0, "hpa": 0, "sigma": 0}

    cured = _cured_fraction(m_live_herb) if fm["dyn"] else 0.0
    dead_herb_load = fm["lh"] * cured
    live_herb_load = fm["lh"] * (1.0 - cured)

    dead_load, dead_sav, dead_moist = _pack(
        [fm["l1"], fm["l10"], fm["l100"], dead_herb_load],
        [fm["s1"], SIGMA_10H, SIGMA_100H, fm["sh"]],
        [m_1h, m_10h, m_100h, m_1h],
    )
    live_load, live_sav, live_moist = _pack(
        [live_herb_load, fm["lw"]],
        [fm["sh"], fm["sw"]],
        [m_live_herb, m_live_woody],
    )

    has_live = sum(live_load) > 0
    f_dead, a_dead = _cat_weights(dead_load, dead_sav)
    f_live, a_live = _cat_weights(live_load, live_sav) if has_live else ([], 0.0)
    a_total = a_dead + a_live
    if a_total <= 0:
        return {"r0": 0, "C": 0, "B": 0, "E": 0, "beta_ratio": 1,
                "beta": 0, "ri": 0, "hpa": 0, "sigma": 0}
    f_cat_dead = a_dead / a_total
    f_cat_live = a_live / a_total

    sigma_dead = sum(fi * si for fi, si in zip(f_dead, dead_sav))
    sigma_live = sum(fi * si for fi, si in zip(f_live, live_sav)) if has_live else 0.0
    sigma = f_cat_dead * sigma_dead + f_cat_live * sigma_live
    if sigma <= 0:
        return {"r0": 0, "C": 0, "B": 0, "E": 0, "beta_ratio": 1,
                "beta": 0, "ri": 0, "hpa": 0, "sigma": 0}

    total_load = sum(dead_load) + sum(live_load)
    depth = fm["d"]
    rho_b = total_load / depth if depth > 0 else 0
    beta = rho_b / PARTICLE_DENSITY
    beta_op = 3.348 * sigma ** (-0.8189)
    ratio = beta / beta_op if beta_op > 0 else 0

    mf_dead = sum(fi * mi for fi, mi in zip(f_dead, dead_moist))
    mf_live = sum(fi * mi for fi, mi in zip(f_live, live_moist)) if has_live else 0.0
    mx_dead = fm["mx"]

    mx_live = mx_dead
    if has_live:
        fine_dead_w = [l * math.exp(-138.0 / s) for l, s in zip(dead_load, dead_sav)]
        fine_live_w = [l * math.exp(-500.0 / s) for l, s in zip(live_load, live_sav)]
        sum_fdw = sum(fine_dead_w)
        sum_flw = sum(fine_live_w)
        if sum_flw > 0:
            w_ratio = sum_fdw / sum_flw
            fine_dead_moist = (
                sum(m * w for m, w in zip(dead_moist, fine_dead_w)) / sum_fdw
            ) if sum_fdw > 0 else 0
            mx_live = max(
                2.9 * w_ratio * (1.0 - fine_dead_moist / mx_dead) - 0.226,
                mx_dead,
            )

    eta_m_dead = _moisture_damping(mf_dead, mx_dead)
    eta_m_live = _moisture_damping(mf_live, mx_live) if has_live else 0.0
    eta_s = min(0.174 * EFFECTIVE_MINERAL ** (-0.19), 1.0)

    wn_dead = _net_load(dead_load, dead_sav, f_dead)
    wn_live = _net_load(live_load, live_sav, f_live) if has_live else 0.0

    a = 133.0 * sigma ** (-0.7913)
    gamma_max = sigma ** 1.5 / (495.0 + 0.0594 * sigma ** 1.5)
    gamma = gamma_max * (ratio ** a) * math.exp(a * (1.0 - ratio))

    ri = gamma * (
        wn_dead * fm["hd"] * eta_m_dead * eta_s
        + wn_live * fm["hl"] * eta_m_live * eta_s
    )

    xi = math.exp((0.792 + 0.681 * math.sqrt(sigma)) * (beta + 0.1)) / (
        192.0 + 0.2595 * sigma
    )

    C = 7.47 * math.exp(-0.133 * sigma ** 0.55)
    B = 0.02526 * sigma ** 0.54
    E = 0.715 * math.exp(-3.59e-4 * sigma)

    eps_dead = [math.exp(-138.0 / s) for s in dead_sav]
    eps_live = [math.exp(-138.0 / s) for s in live_sav] if has_live else []
    qig_dead = [250.0 + 1116.0 * m for m in dead_moist]
    qig_live = [250.0 + 1116.0 * m for m in live_moist]

    hs_dead = sum(f * e * q for f, e, q in zip(f_dead, eps_dead, qig_dead))
    hs_live = sum(f * e * q for f, e, q in zip(f_live, eps_live, qig_live)) if has_live else 0.0
    heat_sink = rho_b * (f_cat_dead * hs_dead + f_cat_live * hs_live)

    r0 = ri * xi / heat_sink if heat_sink > 0 else 0.0

    tau = 384.0 / sigma if sigma > 0 else 0.0
    hpa = ri * tau

    return {
        "r0": r0, "C": C, "B": B, "E": E,
        "beta_ratio": ratio, "beta": beta,
        "ri": ri, "hpa": hpa, "sigma": sigma,
    }


def wind_factor(kern, u):
    if u <= 0 or kern["C"] <= 0 or kern["B"] <= 0:
        return 0.0
    return kern["C"] * (u ** kern["B"]) * (kern["beta_ratio"] ** (-kern["E"]))


def slope_factor(kern, tan_slope):
    if tan_slope <= 0 or kern["beta"] <= 0:
        return 0.0
    return 5.275 * (kern["beta"] ** (-0.3)) * (tan_slope ** 2)


# ============================================================================
# Spread field computation
# ============================================================================
def compute_spread_field(fuel_grid, slope_grid, aspect_grid, moisture, wind, fuel_models):
    """Compute per-cell heading ROS, eccentricity, heading direction, FLI, FL."""
    rows, cols = fuel_grid.shape
    wind_mph = wind["speed_mph"]
    wind_from = wind["direction_from_deg"]
    wind_ftmin = wind_mph * 88.0
    wind_toward_rad = math.radians((wind_from + 180.0) % 360.0)

    ros_max = np.full((rows, cols), NODATA, dtype=np.float32)
    ecc = np.full((rows, cols), NODATA, dtype=np.float32)
    heading = np.full((rows, cols), NODATA, dtype=np.float32)
    fli_out = np.full((rows, cols), NODATA, dtype=np.float32)
    fl_out = np.full((rows, cols), NODATA, dtype=np.float32)

    kernel_cache = {}

    for r in range(rows):
        for c in range(cols):
            fm_num = int(fuel_grid[r, c])
            fm = fuel_models.get(fm_num)
            if fm is None or not fm["burn"]:
                continue

            if fm_num not in kernel_cache:
                kernel_cache[fm_num] = rothermel_kernel(
                    fm, moisture["m_1h"], moisture["m_10h"], moisture["m_100h"],
                    moisture["m_live_herb"], moisture["m_live_woody"],
                )
            kern = kernel_cache[fm_num]
            if kern["r0"] <= 0:
                continue

            sdeg = float(slope_grid[r, c])
            tan_s = math.tan(math.radians(min(max(sdeg, 0), 89.9))) if sdeg > 0 else 0.0
            aspect_deg = float(aspect_grid[r, c])
            upslope_rad = math.radians((aspect_deg + 180.0) % 360.0)

            phi_w = wind_factor(kern, wind_ftmin)
            phi_s = slope_factor(kern, tan_s)

            wx = phi_w * math.sin(wind_toward_rad)
            wy = phi_w * math.cos(wind_toward_rad)
            sx = phi_s * math.sin(upslope_rad)
            sy = phi_s * math.cos(upslope_rad)
            vx = wx + sx
            vy = wy + sy
            phi_eff = math.hypot(vx, vy)

            head_deg = math.degrees(math.atan2(vx, vy)) % 360.0
            r_max = kern["r0"] * (1.0 + phi_eff)

            if kern["C"] > 0 and kern["B"] > 0 and phi_eff > 0:
                u_eff = (phi_eff * kern["beta_ratio"] ** kern["E"]
                         / kern["C"]) ** (1.0 / kern["B"])
            else:
                u_eff = 0.0

            u_eff_mph = u_eff / 88.0
            lb = (0.936 * math.exp(0.2566 * u_eff_mph)
                  + 0.461 * math.exp(-0.1548 * u_eff_mph)
                  - 0.397)
            lb = max(1.0, min(lb, MAX_LB))
            e = math.sqrt(1.0 - 1.0 / (lb * lb)) if lb > 1 else 0.0

            ros_max[r, c] = r_max
            ecc[r, c] = e
            heading[r, c] = head_deg

            i_b = kern["hpa"] * r_max / 60.0
            fli_out[r, c] = i_b
            fl_out[r, c] = 0.45 * (i_b ** 0.46) if i_b > 0 else 0.0

    return ros_max, ecc, heading, fli_out, fl_out


# ============================================================================
# Fire growth (Dijkstra shortest-path)
# ============================================================================
def _lattice_template(ring=2):
    offsets = []
    for dr in range(-ring, ring + 1):
        for dc in range(-ring, ring + 1):
            if dr == 0 and dc == 0:
                continue
            if gcd(abs(dr), abs(dc)) == 1:
                offsets.append((dr, dc))
    return offsets


def _directional_ros(r_max, e, head_deg, az_deg):
    if r_max <= 0:
        return 0.0
    psi = math.radians(az_deg - head_deg)
    denom = 1.0 - e * math.cos(psi)
    if denom <= 0:
        return 0.0
    return r_max * (1.0 - e) / denom


def mtt_dijkstra(ros_max, ecc, heading, cellsize, ignitions, max_time):
    """Fire growth using heap-based shortest-path search."""
    nrows, ncols = ros_max.shape

    offsets = _lattice_template(2)
    geom = []
    for dr, dc in offsets:
        dx = dc * cellsize
        dy = -dr * cellsize
        dist = math.hypot(dx, dy)
        az = math.degrees(math.atan2(dx, dy)) % 360.0
        geom.append((dr, dc, dist, az))

    INF = float("inf")
    arrival = np.full((nrows, ncols), INF, dtype=np.float64)
    heap = []

    for ri, ci in ignitions:
        if 0 <= ri < nrows and 0 <= ci < ncols and float(ros_max[ri, ci]) > 0:
            arrival[ri, ci] = 0.0
            heapq.heappush(heap, (0.0, ri, ci))

    while heap:
        t, r, c = heapq.heappop(heap)
        if t > float(arrival[r, c]) or t > max_time:
            continue
        e_s = float(ecc[r, c])
        h_s = float(heading[r, c])
        rm_s = float(ros_max[r, c])

        for dr, dc, dist, az in geom:
            nr = r + dr
            nc = c + dc
            if nr < 0 or nr >= nrows or nc < 0 or nc >= ncols:
                continue
            rm_t = float(ros_max[nr, nc])
            if rm_t <= 0:
                continue

            r_src = _directional_ros(rm_s, e_s, h_s, az)
            r_tgt = _directional_ros(rm_t, float(ecc[nr, nc]),
                                     float(heading[nr, nc]), az)
            if r_src <= 0 or r_tgt <= 0:
                continue

            r_seg = 2.0 * r_src * r_tgt / (r_src + r_tgt)
            nt = t + dist / r_seg

            if nt < float(arrival[nr, nc]) and nt <= max_time:
                arrival[nr, nc] = nt
                heapq.heappush(heap, (nt, nr, nc))

    return arrival


# ============================================================================
# Main
# ============================================================================
def main():
    if len(sys.argv) < 2:
        print("Usage: firesim.py <config.json>", file=sys.stderr)
        sys.exit(1)

    with open(sys.argv[1]) as f:
        cfg = json.load(f)

    landscape_dir = cfg["landscape_dir"]
    fuel_db_path = cfg["fuel_db"]
    output_dir = cfg["output_dir"]
    moisture = cfg["moisture"]
    wind = cfg["wind"]
    ignitions = [tuple(ig) for ig in cfg["ignitions"]]
    max_time = cfg["max_time_min"]

    # Read landscape rasters via GDAL
    fuel_data, gt, proj = read_raster(os.path.join(landscape_dir, "fuel_model.asc"))
    slope_data, _, _ = read_raster(os.path.join(landscape_dir, "slope.asc"))
    aspect_data, _, _ = read_raster(os.path.join(landscape_dir, "aspect.asc"))

    fuel_grid = fuel_data.astype(int)
    rows, cols = fuel_grid.shape

    # Derive cellsize from geotransform
    cellsize = gt[1]

    # Load fuel models from SQLite
    fuel_models = load_fuel_models_sqlite(fuel_db_path)

    # Compute per-cell fire behavior
    ros_max, ecc, heading_arr, fli, fl = compute_spread_field(
        fuel_grid, slope_data, aspect_data, moisture, wind, fuel_models,
    )

    # Run fire growth
    arrival = mtt_dijkstra(ros_max, ecc, heading_arr, cellsize, ignitions, max_time)

    # Convert arrival INF to NODATA
    INF = float("inf")
    arrival_out = np.where(arrival < INF, arrival, NODATA).astype(np.float32)

    # Compute burned area
    reached = int(np.sum(arrival < INF))
    burned_area = reached * cellsize * cellsize

    # Write output GeoTIFFs
    os.makedirs(output_dir, exist_ok=True)
    write_geotiff(os.path.join(output_dir, "rate_of_spread.tif"), ros_max, gt, proj)
    write_geotiff(os.path.join(output_dir, "fireline_intensity.tif"), fli, gt, proj)
    write_geotiff(os.path.join(output_dir, "flame_length.tif"), fl, gt, proj)
    write_geotiff(os.path.join(output_dir, "heading_direction.tif"), heading_arr, gt, proj)
    write_geotiff(os.path.join(output_dir, "eccentricity.tif"), ecc, gt, proj)
    write_geotiff(os.path.join(output_dir, "arrival_time.tif"), arrival_out, gt, proj)

    # Write summary
    summary = {"burned_area_ft2": burned_area}
    with open(os.path.join(output_dir, "summary.json"), "w") as f:
        json.dump(summary, f)


if __name__ == "__main__":
    main()
