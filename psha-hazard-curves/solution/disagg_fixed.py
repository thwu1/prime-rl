"""Seismic hazard disaggregation module — corrected version.

Decomposes total hazard at a target return period into
magnitude-distance-epsilon contributions following the
standard PSHA disaggregation methodology.

Fixes applied:
  1. Log-log interpolation instead of linear for hazard curve.
  2. Correct epsilon sign: (ln(y) - mu) / sigma.
  3. Full SQLite and JSON output implementation.

"""

import json
import math
import os
import sqlite3

from pipeline.mfd import discretize_mfd
from pipeline.distance import horizontal_distance
from pipeline.gmm import evaluate_gmm, compute_exceedance
from pipeline.hazard import _floating_rupture_rjb


def interpolate_target_iml(imls, rates, target_rate):
    """Find the IML corresponding to a target annual exceedance rate.

    Uses log-log interpolation for accuracy, since hazard curves are
    approximately linear on log-log axes.
    """
    for i in range(len(rates) - 1):
        if rates[i] >= target_rate >= rates[i + 1]:
            log_r0 = math.log(rates[i])
            log_r1 = math.log(rates[i + 1])
            log_y0 = math.log(imls[i])
            log_y1 = math.log(imls[i + 1])
            frac = (math.log(target_rate) - log_r0) / (log_r1 - log_r0)
            return math.exp(log_y0 + frac * (log_y1 - log_y0))
    if target_rate >= rates[0]:
        return imls[0]
    return imls[-1]


def _find_bin_center(value, vmin, vmax, width):
    """Find the bin center for a value within a binning scheme."""
    if value < vmin or value >= vmax:
        return None
    idx = int((value - vmin) / width)
    return round(vmin + (idx + 0.5) * width, 4)


def run_disaggregation(total_rates, imls, sources_data,
                       site_data, gmm_data, config):
    """Run disaggregation and write output files.

    Decomposes total hazard at the configured return period into
    (magnitude, distance, epsilon) bin contributions. Writes:
      /app/output/disagg.db          — SQLite database
      /app/output/disagg_summary.json — JSON summary
    """
    disagg_cfg = config["disaggregation"]
    target_rate = 1.0 / disagg_cfg["return_period_years"]
    target_iml = interpolate_target_iml(imls, total_rates, target_rate)

    bcfg = disagg_cfg["bins"]

    slon = site_data["longitude"]
    slat = site_data["latitude"]
    vs30 = site_data["vs30"]
    kpd = config["earth_approximation"]["km_per_degree"]
    fstep = config["rupture_scaling"]["floating_step_km"]
    mref = gmm_data["reference_magnitude"]
    vref = gmm_data["reference_vs30"]
    trunc = config["truncation"]["level"]

    bins = {}

    for src in sources_data["sources"]:
        mag_rate_pairs = discretize_mfd(src["mfd"])
        for mag, rate in mag_rate_pairs:
            if src["type"] == "point":
                rjb_weights = [(
                    horizontal_distance(slon, slat,
                                        src["longitude"], src["latitude"], kpd),
                    1.0
                )]
            else:
                rjb_weights = _floating_rupture_rjb(
                    slon, slat, src["trace"], mag, kpd, fstep
                )

            for rjb, rw in rjb_weights:
                for br in gmm_data["branches"]:
                    mu, sig = evaluate_gmm(mag, rjb, vs30, br, mref, vref)
                    bw = br["weight"]

                    eps = (math.log(target_iml) - mu) / sig

                    exc = compute_exceedance(target_iml, mu, sig, trunc)
                    contribution = rate * exc * bw * rw

                    mb = _find_bin_center(mag, bcfg["mag_min"],
                                          bcfg["mag_max"], bcfg["mag_width"])
                    db = _find_bin_center(rjb, bcfg["dist_min"],
                                          bcfg["dist_max"], bcfg["dist_width"])
                    eb = _find_bin_center(eps, bcfg["eps_min"],
                                          bcfg["eps_max"], bcfg["eps_width"])

                    if mb is not None and db is not None and eb is not None:
                        key = (mb, db, eb)
                        bins[key] = bins.get(key, 0.0) + contribution

    total = sum(bins.values())
    if total > 0:
        normalized = {k: v / total for k, v in bins.items()}
    else:
        normalized = dict(bins)

    # Compute summary statistics from marginal distributions
    mag_marginal = {}
    dist_marginal = {}
    mean_eps = 0.0
    for (m, d, e), c in normalized.items():
        mag_marginal[m] = mag_marginal.get(m, 0.0) + c
        dist_marginal[d] = dist_marginal.get(d, 0.0) + c
        mean_eps += e * c

    modal_mag = max(mag_marginal, key=mag_marginal.get)
    modal_dist = max(dist_marginal, key=dist_marginal.get)

    # Write SQLite database
    os.makedirs("/app/output", exist_ok=True)
    db_path = "/app/output/disagg.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "CREATE TABLE bins ("
        "  mag_center REAL,"
        "  dist_center REAL,"
        "  eps_center REAL,"
        "  contribution REAL"
        ")"
    )
    for (m, d, e), c in normalized.items():
        cur.execute("INSERT INTO bins VALUES (?, ?, ?, ?)", (m, d, e, c))
    conn.commit()
    conn.close()

    # Write JSON summary
    summary = {
        "target_iml": target_iml,
        "modal_mag": modal_mag,
        "modal_dist": modal_dist,
        "mean_epsilon": mean_eps,
        "total_rate_at_target": total,
    }
    with open("/app/output/disagg_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    print(f"Disaggregation complete: {len(normalized)} bins, "
          f"target IML={target_iml:.6f}")
