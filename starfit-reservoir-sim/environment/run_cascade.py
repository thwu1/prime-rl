#!/usr/bin/env python3
"""Run the cascade simulation pipeline."""
import csv
import json
import os

from reservoir.io_utils import load_cascade_data
from reservoir.cascade import run_cascade
from reservoir.metrics import compute_metrics


def write_cascade_csv(results, filepath):
    """Write cascade results for all reservoirs to CSV."""
    fieldnames = [
        "date", "reservoir_id", "storage_MCM", "release_cms",
        "spill_cms", "outflow_cms", "availability_status", "total_inflow_cms",
    ]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for res_id, res_results in enumerate(results):
            for row in res_results:
                out = {"reservoir_id": res_id}
                for k, v in row.items():
                    out[k] = f"{v:.12f}" if isinstance(v, float) else v
                writer.writerow(out)


def write_routed_csv(routed, filepath):
    """Write routed flows to CSV."""
    fieldnames = ["date", "reach_id", "inflow_cms", "outflow_cms"]
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for reach_id, reach_results in enumerate(routed):
            for row in reach_results:
                out = {"reach_id": reach_id}
                for k, v in row.items():
                    out[k] = f"{v:.12f}" if isinstance(v, float) else v
                writer.writerow(out)


def main():
    res_params, reach_params, dates, lat_inflows, meta = load_cascade_data()
    demand = meta["demand_target_cms"]

    os.makedirs("/app/output", exist_ok=True)

    # Independent policy
    results_ind, routed_ind, balance_ind = run_cascade(
        res_params, reach_params, dates, lat_inflows, mode="independent"
    )
    write_cascade_csv(results_ind, "/app/output/cascade_independent.csv")
    write_routed_csv(routed_ind, "/app/output/routed_flows_independent.csv")
    print(f"Independent policy mass balance error: "
          f"{balance_ind['system_mass_balance_relative_error']:.2e}")

    # Coordinated policy
    results_coord, routed_coord, balance_coord = run_cascade(
        res_params, reach_params, dates, lat_inflows,
        mode="coordinated", demand_target=demand,
    )
    write_cascade_csv(results_coord, "/app/output/cascade_coordinated.csv")
    write_routed_csv(routed_coord, "/app/output/routed_flows_coordinated.csv")
    print(f"Coordinated policy mass balance error: "
          f"{balance_coord['system_mass_balance_relative_error']:.2e}")

    # Performance metrics
    downstream_ind = [r["outflow_cms"] for r in results_ind[2]]
    downstream_coord = [r["outflow_cms"] for r in results_coord[2]]

    metrics_ind = compute_metrics(downstream_ind, demand)
    metrics_coord = compute_metrics(downstream_coord, demand)

    performance = {
        "independent": {
            **metrics_ind,
            "system_mass_balance_relative_error":
                balance_ind["system_mass_balance_relative_error"],
        },
        "coordinated": {
            **metrics_coord,
            "system_mass_balance_relative_error":
                balance_coord["system_mass_balance_relative_error"],
        },
    }

    with open("/app/output/performance.json", "w") as f:
        json.dump(performance, f, indent=2)

    print(f"\nIndependent: {metrics_ind}")
    print(f"Coordinated: {metrics_coord}")
    print("Pipeline complete.")


if __name__ == "__main__":
    main()
