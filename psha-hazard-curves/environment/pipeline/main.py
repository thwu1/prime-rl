#!/usr/bin/env python3
"""PSHA hazard curve computation pipeline.

Reads a seismic source model and computes exceedance-rate hazard curves
at a single site using a weighted ground-motion-model logic tree.
"""

import json
import csv
import os
import math
import subprocess

from pipeline.mfd import discretize_mfd
from pipeline.hazard import compute_source_hazard
from pipeline.disagg import run_disaggregation


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
    trunc_level = config["truncation"]["level"]
    exposure_t = config["exposure_years"]
    kpd = config["earth_approximation"]["km_per_degree"]
    fstep = config["rupture_scaling"]["floating_step_km"]

    mref = gmm_data["reference_magnitude"]
    vref = gmm_data["reference_vs30"]
    branches = gmm_data["branches"]

    total_rates = [0.0] * len(imls)
    source_contribs = {}

    for src in sources_data["sources"]:
        src_rates = compute_source_hazard(
            src, site_lon, site_lat, vs30, imls, branches,
            mref, vref, trunc_level, kpd, fstep
        )
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
            w.writerow([f"{y:.6g}", f"{ar:.10e}", f"{pp:.10e}"])

    with open("/app/output/source_contributions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source_name", "iml", "annual_rate"])
        for name, rates in source_contribs.items():
            for i, y in enumerate(imls):
                w.writerow([name, f"{y:.6g}", f"{rates[i]:.10e}"])

    if "disaggregation" in config:
        run_disaggregation(total_rates, imls, sources_data,
                           site_data, gmm_data, config)

    # Run post-processing pipeline (generates plot, marginals, report)
    subprocess.run(["bash", "/app/pipeline/postprocess.sh"], check=True)


if __name__ == "__main__":
    main()
