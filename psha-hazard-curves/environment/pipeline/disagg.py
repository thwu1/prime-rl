"""Seismic hazard disaggregation module.

Decomposes total hazard at a target return period into
magnitude-distance-epsilon contributions following the
standard PSHA disaggregation methodology.
"""

import math

from pipeline.mfd import discretize_mfd
from pipeline.distance import horizontal_distance
from pipeline.gmm import evaluate_gmm, compute_exceedance
from pipeline.hazard import _floating_rupture_rjb


def interpolate_target_iml(imls, rates, target_rate):
    """Find the IML corresponding to a target annual exceedance rate
    by interpolating the hazard curve.
    """
    for i in range(len(rates) - 1):
        if rates[i] >= target_rate >= rates[i + 1]:
            frac = (target_rate - rates[i]) / (rates[i + 1] - rates[i])
            return imls[i] + frac * (imls[i + 1] - imls[i])
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

    Decomposes the total hazard at the target return period into
    contributions binned by magnitude, distance, and epsilon.
    Results should be written to:
      /app/output/disagg.db    — SQLite with table 'bins'
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

                    eps = (mu - math.log(target_iml)) / sig

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
        for key in bins:
            bins[key] /= total

    # TODO: Write bins to SQLite database at /app/output/disagg.db
    #       Table 'bins' with columns:
    #         mag_center REAL, dist_center REAL, eps_center REAL, contribution REAL
    # TODO: Write summary to /app/output/disagg_summary.json with keys:
    #       target_iml, modal_mag, modal_dist, mean_epsilon, total_rate_at_target
    #       Modal values from marginal distributions; mean_epsilon is
    #       contribution-weighted mean; total_rate_at_target is the
    #       pre-normalization sum of all bin contributions.

    print(f"Disaggregation computed: {len(bins)} non-zero bins")
    print(f"Target IML: {target_iml:.6f}")
    print(f"Total exceedance rate: {total:.6e}")
