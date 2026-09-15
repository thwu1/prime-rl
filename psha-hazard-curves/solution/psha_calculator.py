#!/usr/bin/env python3
"""
PSHA Hazard Curve Calculator — reference solution.

Computes probabilistic seismic hazard curves from a JSON source model
with point and fault sources, weighted GMM logic tree branches, and
truncated log-normal exceedance.

"""

import json
import math
import csv
import os
from scipy.stats import norm


def main():
    with open("/app/model/sources.json") as f:
        sources_data = json.load(f)
    with open("/app/model/gmm.json") as f:
        gmm_data = json.load(f)
    with open("/app/model/site.json") as f:
        site_data = json.load(f)
    with open("/app/model/config.json") as f:
        config = json.load(f)

    site_lon = site_data["longitude"]
    site_lat = site_data["latitude"]
    vs30 = site_data["vs30"]

    imls = config["imls"]
    trunc_n = config["truncation"]["level"]
    exposure_t = config["exposure_years"]
    kpd = config["earth_approximation"]["km_per_degree"]
    fstep = config["rupture_scaling"]["floating_step_km"]

    mref = gmm_data["reference_magnitude"]
    vref = gmm_data["reference_vs30"]
    branches = gmm_data["branches"]

    total_rates = [0.0] * len(imls)
    source_contribs = {}

    for src in sources_data["sources"]:
        src_rates = [0.0] * len(imls)
        mag_rate_pairs = discretize_mfd(src["mfd"])

        for mag, rate in mag_rate_pairs:
            if src["type"] == "point":
                rjb_weights = [
                    (
                        horizontal_distance(
                            site_lon, site_lat,
                            src["longitude"], src["latitude"],
                            kpd,
                        ),
                        1.0,
                    )
                ]
            else:
                rjb_weights = fault_rjb_floating(
                    site_lon, site_lat, src["trace"], mag, kpd, fstep
                )

            for rjb, rw in rjb_weights:
                for br in branches:
                    c = br["coefficients"]
                    sig = br["sigma"]
                    bw = br["weight"]
                    R = math.sqrt(rjb ** 2 + c["h"] ** 2)
                    dm = mag - mref
                    mu = (
                        c["e1"]
                        + c["e2"] * dm
                        + c["e3"] * dm ** 2
                        + (c["c1"] + c["c2"] * dm) * math.log(R)
                        + c["s"] * math.log(vs30 / vref)
                    )

                    for i, y in enumerate(imls):
                        p = truncated_exceedance(y, mu, sig, trunc_n)
                        src_rates[i] += rate * p * bw * rw

        source_contribs[src["name"]] = list(src_rates)
        for i in range(len(imls)):
            total_rates[i] += src_rates[i]

    os.makedirs("/app/output", exist_ok=True)

    with open("/app/output/hazard_curves.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["iml", "annual_rate", "poisson_prob_50yr"])
        for i, y in enumerate(imls):
            ar = total_rates[i]
            pp = 1.0 - math.exp(-ar * exposure_t)
            w.writerow([format_num(y), format_sci(ar), format_sci(pp)])

    with open("/app/output/source_contributions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_name", "iml", "annual_rate"])
        for name, rates in source_contribs.items():
            for i, y in enumerate(imls):
                w.writerow([name, format_num(y), format_sci(rates[i])])


def format_num(v):
    return f"{v:.6g}"


def format_sci(v):
    return f"{v:.10e}"


def discretize_mfd(mfd):
    if mfd["type"] == "GR":
        a = mfd["a"]
        b = mfd["b"]
        m_min = mfd["mMin"]
        m_max = mfd["mMax"]
        dm = mfd["dMag"]
        pairs = []
        m = m_min + dm / 2.0
        while m < m_max - dm / 2.0 + 1e-6:
            r = 10.0 ** (a - b * (m - dm / 2.0)) - 10.0 ** (a - b * (m + dm / 2.0))
            pairs.append((round(m, 2), r))
            m += dm
        return pairs
    elif mfd["type"] == "INCR":
        return list(zip(mfd["magnitudes"], mfd["rates"]))
    return []


def horizontal_distance(lon1, lat1, lon2, lat2, kpd):
    lat_avg = (lat1 + lat2) / 2.0
    dx = (lon2 - lon1) * math.cos(math.radians(lat_avg)) * kpd
    dy = (lat2 - lat1) * kpd
    return math.sqrt(dx * dx + dy * dy)


def fault_rjb_floating(site_lon, site_lat, trace, mag, kpd, fstep):
    lat_ref = site_lat
    tkm = []
    for pt in trace:
        dx = (pt["longitude"] - site_lon) * math.cos(math.radians(lat_ref)) * kpd
        dy = (pt["latitude"] - site_lat) * kpd
        tkm.append((dx, dy))

    cum = [0.0]
    for i in range(len(tkm) - 1):
        seg = math.sqrt(
            (tkm[i + 1][0] - tkm[i][0]) ** 2 + (tkm[i + 1][1] - tkm[i][1]) ** 2
        )
        cum.append(cum[-1] + seg)
    fault_len = cum[-1]

    rup_len = 10.0 ** (-2.44 + 0.59 * mag)
    rup_len = min(rup_len, fault_len)

    if rup_len >= fault_len - 0.01:
        return [(pt_to_polyline(0.0, 0.0, tkm), 1.0)]

    positions = []
    s = 0.0
    while s <= fault_len - rup_len + 1e-6:
        positions.append(s)
        s += fstep

    n_pos = len(positions)
    result = []
    for sp in positions:
        ep = sp + rup_len
        sub = extract_sub_trace(tkm, cum, sp, ep)
        d = pt_to_polyline(0.0, 0.0, sub)
        result.append((d, 1.0 / n_pos))
    return result


def extract_sub_trace(tkm, cum, sp, ep):
    pts = []
    for i in range(len(tkm) - 1):
        seg_s = cum[i]
        seg_e = cum[i + 1]
        if seg_e <= sp or seg_s >= ep:
            continue
        sl = seg_e - seg_s
        if sl < 1e-10:
            continue
        dx = tkm[i + 1][0] - tkm[i][0]
        dy = tkm[i + 1][1] - tkm[i][1]
        cs = max(sp, seg_s)
        ce = min(ep, seg_e)
        ts = (cs - seg_s) / sl
        te = (ce - seg_s) / sl
        if not pts:
            pts.append((tkm[i][0] + ts * dx, tkm[i][1] + ts * dy))
        pts.append((tkm[i][0] + te * dx, tkm[i][1] + te * dy))
    return pts


def pt_to_polyline(px, py, polyline):
    min_d = float("inf")
    for i in range(len(polyline) - 1):
        d = pt_to_segment(
            px, py,
            polyline[i][0], polyline[i][1],
            polyline[i + 1][0], polyline[i + 1][1],
        )
        if d < min_d:
            min_d = d
    return min_d


def pt_to_segment(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-10:
        return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
    t = ((px - ax) * dx + (py - ay) * dy) / len_sq
    t = max(0.0, min(1.0, t))
    qx = ax + t * dx
    qy = ay + t * dy
    return math.sqrt((px - qx) ** 2 + (py - qy) ** 2)


def truncated_exceedance(y, mu, sigma, n):
    z = (math.log(y) - mu) / sigma
    if z >= n:
        return 0.0
    return (norm.cdf(n) - norm.cdf(z)) / norm.cdf(n)


if __name__ == "__main__":
    main()
