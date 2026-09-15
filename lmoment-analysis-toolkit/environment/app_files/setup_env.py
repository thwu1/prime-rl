#!/usr/bin/env python3
"""
Environment setup: generates deterministic gauge data for hydrological analysis.
This script is deleted after the Docker build completes.
"""
import numpy as np
from scipy import stats
import os


STATIONS = {
    "alpine_01": {
        "scipy_c": 0.2, "loc": 100.0, "scale": 20.0,
        "n": 50, "seed": 42, "file": "gauge_alpine.csv"
    },
    "coastal_02": {
        "scipy_c": -0.15, "loc": 180.0, "scale": 30.0,
        "n": 40, "seed": 123, "file": "gauge_coastal.csv"
    },
    "plains_03": {
        "scipy_c": 0.1, "loc": 80.0, "scale": 15.0,
        "n": 60, "seed": 789, "file": "gauge_plains.csv"
    },
}


def generate_csv(sid, params):
    """Generate deterministic gauge data CSV."""
    rng = np.random.default_rng(params["seed"])
    n = params["n"]

    flows = stats.genextreme.rvs(
        c=params["scipy_c"], loc=params["loc"], scale=params["scale"],
        size=n, random_state=rng
    )
    flows = np.round(flows, 2)

    water_levels = np.round(2.5 + 0.008 * flows + rng.normal(0, 0.2, n), 4)

    quality = np.array(["GOOD"] * n)
    n_suspect = max(1, int(n * 0.15))
    suspect_idx = rng.choice(n, size=n_suspect, replace=False)
    quality[suspect_idx] = "SUSPECT"

    start_year = 2024 - n
    path = f"/app/data/{params['file']}"
    with open(path, "w") as f:
        f.write("year,month,flow_cms,water_level_m,quality\n")
        for i in range(n):
            month = int(rng.integers(3, 9))
            f.write(f"{start_year + i},{month},"
                    f"{flows[i]:.2f},{water_levels[i]:.4f},{quality[i]}\n")


os.makedirs("/app/data", exist_ok=True)
os.makedirs("/app/output", exist_ok=True)

for sid, params in STATIONS.items():
    generate_csv(sid, params)

print("Data generation complete.")
