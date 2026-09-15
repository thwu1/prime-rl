#!/usr/bin/env python3
"""Generate deterministic problem data for two-stage stochastic MILP with CVaR."""
import json
import random
import os

random.seed(42)

n_suppliers = 3
n_warehouses = 6
n_customers = 10
n_scenarios = 100

supplier_capacities = [500, 400, 600]
warehouse_capacities = [300, 250, 350, 200, 280, 320]
warehouse_fixed_costs = [100, 150, 120, 180, 90, 160]
base_demands = [50, 40, 60, 35, 45, 55, 30, 65, 42, 48]

# Transport costs supplier->warehouse
cost_sw = [
    [round(random.uniform(5, 25), 1) for _ in range(n_warehouses)]
    for _ in range(n_suppliers)
]
# Transport costs warehouse->customer
cost_wc = [
    [round(random.uniform(3, 20), 1) for _ in range(n_customers)]
    for _ in range(n_warehouses)
]

# Scenarios: demand realizations with moderate variability
random.seed(123)
scenarios = []
for _ in range(n_scenarios):
    multipliers = [round(random.uniform(0.7, 1.3), 4) for _ in range(n_customers)]
    demands = [round(base_demands[k] * multipliers[k], 2) for k in range(n_customers)]
    scenarios.append(demands)

probabilities = [1.0 / n_scenarios] * n_scenarios

data = {
    "n_suppliers": n_suppliers,
    "n_warehouses": n_warehouses,
    "n_customers": n_customers,
    "n_scenarios": n_scenarios,
    "supplier_capacities": supplier_capacities,
    "warehouse_capacities": warehouse_capacities,
    "warehouse_fixed_costs": warehouse_fixed_costs,
    "base_demands": base_demands,
    "cost_supplier_warehouse": cost_sw,
    "cost_warehouse_customer": cost_wc,
    "scenario_demands": scenarios,
    "probabilities": probabilities,
    "budget": 500,
    "alpha": 0.95,
    "lambda_cvar": 0.5,
}

os.makedirs("/app/data", exist_ok=True)
with open("/app/data/problem_data.json", "w") as f:
    json.dump(data, f, indent=2)

print("Generated /app/data/problem_data.json")
