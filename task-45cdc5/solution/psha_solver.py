#!/usr/bin/env python3
"""
PSHA Hazard Curve Computation from multi-format geoscience data.

Reads fault sources from GeoJSON, gridded seismicity from NetCDF (via ncdump),
GMM parameters from SQLite, and configuration from YAML. Validates data quality,
deduplicates sources, normalizes MFD weights, and computes the PSHA hazard curve.

"""

import json
import math
import os
import re
import sqlite3
import subprocess

import yaml


def phi(x):
    """Standard normal CDF via erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def flat_earth_dx(lon1, lon2, lat_ref):
    """East-west distance in km using flat-earth approximation."""
    return (lon2 - lon1) * math.cos(math.radians(lat_ref)) * 111.195


def flat_earth_dy(lat1, lat2):
    """North-south distance in km."""
    return (lat2 - lat1) * 111.195


def point_to_segment_dist(px, py, ax, ay, bx, by):
    abx = bx - ax
    aby = by - ay
    ab_sq = abx * abx + aby * aby
    if ab_sq < 1e-15:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
    t = ((px - ax) * abx + (py - ay) * aby) / ab_sq
    t = max(0.0, min(1.0, t))
    cx = ax + t * abx
    cy = ay + t * aby
    return math.sqrt((px - cx) ** 2 + (py - cy) ** 2)


def point_in_polygon(px, py, polygon):
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (
            px < (xj - xi) * (py - yi) / (yj - yi) + xi
        ):
            inside = not inside
        j = i
    return inside


def point_to_polygon_dist(px, py, polygon):
    if point_in_polygon(px, py, polygon):
        return 0.0
    n = len(polygon)
    min_d = float("inf")
    for i in range(n):
        j = (i + 1) % n
        d = point_to_segment_dist(
            px, py, polygon[i][0], polygon[i][1], polygon[j][0], polygon[j][1]
        )
        if d < min_d:
            min_d = d
    return min_d


def compute_rjb(site_lon, site_lat, trace, dip, dip_direction, width):
    trace_local = []
    for lon, lat in trace:
        x = flat_earth_dx(site_lon, lon, site_lat)
        y = flat_earth_dy(site_lat, lat)
        trace_local.append((x, y))

    if abs(dip - 90.0) < 1e-6:
        min_d = float("inf")
        for i in range(len(trace_local) - 1):
            d = point_to_segment_dist(
                0.0, 0.0,
                trace_local[i][0], trace_local[i][1],
                trace_local[i + 1][0], trace_local[i + 1][1],
            )
            if d < min_d:
                min_d = d
        return min_d
    else:
        dip_rad = math.radians(dip)
        horiz_ext = width * math.cos(dip_rad)
        dip_dirs = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}
        ddx, ddy = dip_dirs[dip_direction]
        extended = [
            (x + ddx * horiz_ext, y + ddy * horiz_ext) for x, y in trace_local
        ]
        polygon = list(trace_local) + list(reversed(extended))
        return point_to_polygon_dist(0.0, 0.0, polygon)


def compute_rhyp(site_lon, site_lat, src_lon, src_lat, depth):
    dx = flat_earth_dx(site_lon, src_lon, site_lat)
    dy = flat_earth_dy(site_lat, src_lat)
    r_h = math.sqrt(dx * dx + dy * dy)
    return math.sqrt(r_h * r_h + depth * depth)


def gr_incremental_rates(a, b, m_min, m_max, d_mag):
    n_bins = round((m_max - m_min) / d_mag) + 1
    magnitudes = []
    rates = []
    for i in range(n_bins):
        m = m_min + i * d_mag
        r = 10.0 ** (a - b * (m - d_mag / 2.0)) - 10.0 ** (a - b * (m + d_mag / 2.0))
        magnitudes.append(m)
        rates.append(max(r, 0.0))
    return magnitudes, rates


def gmm_eval(mag, dist, vs30, coeffs, mref, vref):
    dm = mag - mref
    c = coeffs
    r_eff = math.sqrt(dist * dist + c["c6"] ** 2)
    mean_ln = (
        c["c1"]
        + c["c2"] * dm
        + c["c3"] * dm * dm
        + (c["c4"] + c["c5"] * dm) * math.log(r_eff)
        + c["c7"] * math.log(vs30 / vref)
    )
    sigma = c["c8"] + c["c9"] * mag
    return mean_ln, sigma


def exceedance_prob(iml, mean_ln, sigma, trunc_level):
    epsilon = (math.log(iml) - mean_ln) / sigma
    if epsilon >= trunc_level:
        return 0.0
    phi_n = phi(trunc_level)
    return (phi_n - phi(epsilon)) / phi_n


def read_nc_vars(path, names):
    """Read variables from NetCDF file using ncdump CLI tool."""
    result = subprocess.run(
        ["ncdump", "-v", ",".join(names), path],
        capture_output=True, text=True, check=True,
    )
    text = result.stdout
    di = text.find("data:")
    data_section = text[di:]
    out = {}
    for v in names:
        m = re.search(rf"\b{v}\s*=\s*(.*?)\s*;", data_section, re.DOTALL)
        out[v] = [float(x.strip()) for x in m.group(1).split(",") if x.strip()]
    return out


def main():
    issues = []

    # ── Read configuration from YAML ──
    with open("/app/data/calc_config.yaml") as f:
        config = yaml.safe_load(f)
    site_lon = config["site"]["lon"]
    site_lat = config["site"]["lat"]
    vs30 = config["site"]["vs30"]
    imls = config["imls"]
    trunc_level = config["truncation_level"]

    # ── Read GMM data from SQLite ──
    conn = sqlite3.connect("/app/data/model.db")
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT value FROM metadata WHERE key = 'gmm_Mref'")
    mref = float(cur.fetchone()["value"])
    cur.execute("SELECT value FROM metadata WHERE key = 'gmm_Vref'")
    vref = float(cur.fetchone()["value"])

    cur.execute("SELECT id, model_name, weight FROM gmm_tree")
    gmm_tree_rows = cur.fetchall()
    gmm_models = []
    for row in gmm_tree_rows:
        if row["weight"] <= 0:
            continue
        cur.execute(
            "SELECT param, value FROM gmm_coefficients WHERE model_id = ?",
            (row["id"],),
        )
        coeffs = {r["param"]: r["value"] for r in cur.fetchall()}
        gmm_models.append({"weight": row["weight"], "coeffs": coeffs})
    conn.close()

    # ── Read fault sources from GeoJSON ──
    with open("/app/data/fault_sources.geojson") as f:
        geojson = json.load(f)

    seen_geom = {}
    valid_faults = []
    for feat in geojson["features"]:
        props = feat["properties"]
        coords_key = json.dumps(feat["geometry"]["coordinates"], sort_keys=True)
        geom_key = (coords_key, props["dip"], props["dip_dir"], props["width_km"])
        if geom_key in seen_geom:
            issues.append(
                f"Duplicate fault source: '{props['name']}' (id={props['src_id']}) "
                f"has identical geometry to '{seen_geom[geom_key]}' — excluded"
            )
        else:
            seen_geom[geom_key] = props["name"]
            valid_faults.append(feat)

    # Initialize hazard accumulator
    n_iml = len(imls)
    hazard = [0.0] * n_iml

    # Process fault sources
    for feat in valid_faults:
        props = feat["properties"]
        trace = [tuple(p) for p in feat["geometry"]["coordinates"]]
        rjb = compute_rjb(
            site_lon, site_lat, trace,
            props["dip"], props["dip_dir"], props["width_km"],
        )

        mfds = json.loads(props["mfd_json"])
        total_w = sum(m["weight"] for m in mfds)
        if abs(total_w - 1.0) > 1e-6:
            issues.append(
                f"MFD weights for '{props['name']}' sum to {total_w:.4f}, "
                f"not 1.0 — normalized to form valid probability distribution"
            )

        for mfd in mfds:
            w_branch = mfd["weight"] / total_w if total_w > 0 else mfd["weight"]

            if mfd["type"] == "GR":
                mags, rates = gr_incremental_rates(
                    mfd["a"], mfd["b"],
                    mfd["m_min"], mfd["m_max"], mfd["d_mag"],
                )
            elif mfd["type"] == "SINGLE":
                mags = [mfd["m"]]
                rates = [mfd["rate"]]
            else:
                continue

            for mag, rate in zip(mags, rates):
                if rate <= 0.0:
                    continue
                for gm in gmm_models:
                    mu, sig = gmm_eval(mag, rjb, vs30, gm["coeffs"], mref, vref)
                    for k in range(n_iml):
                        pe = exceedance_prob(imls[k], mu, sig, trunc_level)
                        hazard[k] += w_branch * gm["weight"] * rate * pe

    # ── Read grid seismicity from NetCDF ──
    nc = read_nc_vars(
        "/app/data/grid_seismicity.nc",
        ["lon", "lat", "depth_km", "a_val", "b_val", "m_min", "m_max", "d_mag"],
    )
    npts = len(nc["lon"])

    valid_grid = []
    for i in range(npts):
        if nc["m_min"][i] > nc["m_max"][i]:
            issues.append(
                f"Invalid grid point index {i}: m_min ({nc['m_min'][i]}) > "
                f"m_max ({nc['m_max'][i]}) — excluded as physically invalid"
            )
            continue
        if nc["a_val"][i] > 10.0:
            issues.append(
                f"Invalid grid point index {i}: a_val={nc['a_val'][i]} is "
                f"physically unreasonable (typical range 0-4) — excluded"
            )
            continue
        valid_grid.append(i)

    for i in valid_grid:
        rhyp = compute_rhyp(
            site_lon, site_lat, nc["lon"][i], nc["lat"][i], nc["depth_km"][i]
        )
        mags, rates = gr_incremental_rates(
            nc["a_val"][i], nc["b_val"][i],
            nc["m_min"][i], nc["m_max"][i], nc["d_mag"][i],
        )
        for mag, rate in zip(mags, rates):
            if rate <= 0.0:
                continue
            for gm in gmm_models:
                mu, sig = gmm_eval(mag, rhyp, vs30, gm["coeffs"], mref, vref)
                for k in range(n_iml):
                    pe = exceedance_prob(imls[k], mu, sig, trunc_level)
                    hazard[k] += gm["weight"] * rate * pe

    # ── Write outputs ──
    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/hazard_curve.csv", "w") as f:
        f.write("iml,annual_rate\n")
        for iml_val, rate_val in zip(imls, hazard):
            f.write(f"{iml_val},{rate_val:.12e}\n")

    with open("/app/output/validation_report.txt", "w") as f:
        for issue in issues:
            f.write(issue + "\n")

    print(f"Hazard curve written to /app/output/hazard_curve.csv")
    print(f"Validation report: {len(issues)} issues found")
    for issue in issues:
        print(f"  - {issue}")


if __name__ == "__main__":
    main()
