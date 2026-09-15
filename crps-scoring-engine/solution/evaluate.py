#!/usr/bin/env python3
"""
Evaluation driver: reads forecast scenarios from /app/data/scenarios.json,
computes CRPS using scoring_rules module, writes results to /app/results.json.
"""

import json
import numpy as np
from scoring_rules import (
    crps_gev,
    crps_gpd,
    crps_gtcnormal,
    crps_normal,
    crps_mixnorm,
    crps_ensemble,
)


def main():
    with open("/app/data/scenarios.json") as f:
        scenarios = json.load(f)

    results = {}

    # GEV scenarios
    results["gev"] = []
    for s in scenarios["gev"]:
        val = crps_gev(
            s["obs"], s["shape"], s.get("location", 0.0), s.get("scale", 1.0)
        )
        results["gev"].append({"id": s["id"], "crps": float(val)})

    # GPD scenarios
    results["gpd"] = []
    for s in scenarios["gpd"]:
        val = crps_gpd(
            s["obs"],
            s["shape"],
            s.get("location", 0.0),
            s.get("scale", 1.0),
            s.get("mass", 0.0),
        )
        results["gpd"].append({"id": s["id"], "crps": float(val)})

    # gtcnormal scenarios
    results["gtcnormal"] = []
    for s in scenarios["gtcnormal"]:
        val = crps_gtcnormal(
            s["obs"],
            s["location"],
            s["scale"],
            lower=s.get("lower", float("-inf")),
            upper=s.get("upper", float("inf")),
            lmass=s.get("lmass", 0.0),
            umass=s.get("umass", 0.0),
        )
        results["gtcnormal"].append({"id": s["id"], "crps": float(val)})

    # mixnorm scenarios
    results["mixnorm"] = []
    for s in scenarios["mixnorm"]:
        val = crps_mixnorm(s["obs"], s["m"], s["s"], s.get("w"))
        results["mixnorm"].append({"id": s["id"], "crps": float(val)})

    # ensemble scenarios
    results["ensemble"] = []
    for s in scenarios["ensemble"]:
        fct = np.array(s["fct"])
        entry = {"id": s["id"]}
        for est in ["nrg", "fair", "pwm", "qd"]:
            val = crps_ensemble(s["obs"], fct, estimator=est)
            entry[f"crps_{est}"] = float(np.squeeze(val))
        results["ensemble"].append(entry)

    with open("/app/results.json", "w") as f:
        json.dump(results, f, indent=2)

    print("Evaluation complete. Results written to /app/results.json")


if __name__ == "__main__":
    main()
