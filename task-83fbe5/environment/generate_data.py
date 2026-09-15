#!/usr/bin/env python3
"""Generate instance data for stochastic capacitated facility location task."""
import csv
import json
import os

DATA_DIR = "/app/data"
os.makedirs(DATA_DIR, exist_ok=True)

# --- Facilities ---
facilities = [
    {"id": 0, "fixed_cost": 100, "capacity": 35},
    {"id": 1, "fixed_cost": 120, "capacity": 40},
    {"id": 2, "fixed_cost": 130, "capacity": 45},
    {"id": 3, "fixed_cost": 110, "capacity": 30},
    {"id": 4, "fixed_cost": 105, "capacity": 35},
    {"id": 5, "fixed_cost": 115, "capacity": 40},
    {"id": 6, "fixed_cost": 125, "capacity": 45},
    {"id": 7, "fixed_cost": 95, "capacity": 30},
]
with open(os.path.join(DATA_DIR, "facilities.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["id", "fixed_cost", "capacity"])
    w.writeheader()
    w.writerows(facilities)

# --- Shipping costs (facility x customer) ---
# Facilities 0-3 serve region A (cust 0-5) cheaply; 4-7 serve region B (cust 6-11)
transport = [
    [2.1, 3.8, 1.9, 4.3, 2.7, 3.2, 25.3, 28.1, 22.6, 24.2, 27.4, 21.1],
    [3.3, 1.6, 4.2, 2.1, 3.9, 2.4, 21.2, 26.7, 25.9, 22.8, 24.1, 28.3],
    [2.7, 4.1, 2.2, 3.6, 1.7, 3.1, 27.8, 22.3, 25.4, 28.2, 22.6, 24.3],
    [4.1, 2.4, 3.3, 1.8, 4.2, 2.3, 24.1, 28.3, 21.2, 25.6, 27.1, 22.4],
    [25.6, 27.9, 22.7, 24.1, 28.3, 21.4, 2.3, 3.6, 1.9, 4.1, 2.8, 3.1],
    [21.3, 25.4, 28.2, 22.6, 24.1, 27.4, 3.1, 1.7, 4.3, 2.2, 3.4, 2.6],
    [27.9, 21.1, 25.6, 28.4, 22.8, 24.2, 2.6, 4.2, 2.1, 3.8, 1.6, 3.3],
    [24.2, 28.6, 21.1, 25.7, 26.8, 22.6, 4.3, 2.4, 3.2, 1.7, 3.9, 2.3],
]
cust_ids = [f"cust_{j}" for j in range(12)]
with open(os.path.join(DATA_DIR, "shipping_costs.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["facility_id"] + cust_ids)
    for i, row in enumerate(transport):
        w.writerow([i] + row)

# --- Demand scenarios ---
demands = [
    [22, 20, 24, 18, 26, 21, 5, 7, 4, 6, 5, 8],
    [20, 24, 18, 22, 20, 23, 7, 5, 6, 4, 7, 6],
    [24, 18, 26, 20, 22, 19, 4, 8, 3, 7, 4, 7],
    [18, 25, 20, 24, 28, 22, 6, 4, 7, 5, 8, 3],
    [21, 22, 22, 19, 24, 20, 5, 6, 5, 6, 5, 7],
    [23, 19, 25, 21, 21, 24, 4, 7, 4, 7, 3, 8],
    [25, 21, 23, 17, 27, 18, 7, 5, 6, 5, 6, 6],
    [19, 23, 19, 23, 19, 25, 6, 6, 5, 4, 7, 5],
    [22, 20, 24, 18, 26, 21, 5, 7, 4, 6, 5, 8],
    [26, 22, 28, 16, 30, 17, 3, 5, 3, 5, 4, 5],
    [17, 19, 16, 20, 18, 22, 8, 8, 7, 8, 6, 9],
    [24, 20, 22, 21, 25, 20, 5, 6, 5, 5, 6, 6],
    [20, 21, 21, 20, 22, 21, 6, 6, 5, 6, 5, 7],
    [5, 7, 4, 6, 5, 8, 22, 20, 24, 18, 26, 21],
    [7, 5, 6, 4, 7, 6, 20, 24, 18, 22, 20, 23],
    [4, 8, 3, 7, 4, 7, 24, 18, 26, 20, 22, 19],
    [6, 4, 7, 5, 8, 3, 18, 25, 20, 24, 28, 22],
    [5, 6, 5, 6, 5, 7, 21, 22, 22, 19, 24, 20],
    [4, 7, 4, 7, 3, 8, 23, 19, 25, 21, 21, 24],
    [7, 5, 6, 5, 6, 6, 25, 21, 23, 17, 27, 18],
    [6, 6, 5, 4, 7, 5, 19, 23, 19, 23, 19, 25],
    [5, 7, 4, 6, 5, 8, 22, 20, 24, 18, 26, 21],
    [3, 5, 3, 5, 4, 5, 26, 22, 28, 16, 30, 17],
    [8, 8, 7, 8, 6, 9, 17, 19, 16, 20, 18, 22],
    [5, 6, 5, 5, 6, 6, 24, 20, 22, 21, 25, 20],
]
with open(os.path.join(DATA_DIR, "demand_scenarios.csv"), "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["scenario_id"] + cust_ids)
    for s, row in enumerate(demands):
        w.writerow([s] + row)

# --- Parameters ---
params = {
    "shortage_penalty_per_unit": 50,
    "tail_quantile": 0.95,
    "risk_weight": 0.3,
    "scenario_weighting": "equiprobable",
}
with open(os.path.join(DATA_DIR, "parameters.json"), "w") as f:
    json.dump(params, f, indent=2)

print("Instance data written to", DATA_DIR)
