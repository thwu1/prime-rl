"""Solver for quantum Hamiltonian variance minimization.

Reads input from SQLite database and TOML config, determines optimal
measurement grouping, scale factor selection, and shot allocation,
then writes results as JSON and CSV.
"""

import csv
import json
import math
import sqlite3
import tomllib
from itertools import combinations


def load_data():
    """Load problem data from SQLite database and TOML config."""
    conn = sqlite3.connect("/app/device.db")
    c = conn.cursor()

    c.execute(
        "SELECT term_index, pauli_string, coefficient, ideal_expectation "
        "FROM hamiltonian_terms ORDER BY term_index"
    )
    terms_raw = c.fetchall()

    c.execute("SELECT qubit_index, depolarizing_rate FROM qubit_noise ORDER BY qubit_index")
    qubit_noise = {row[0]: row[1] for row in c.fetchall()}

    c.execute("SELECT factor_value FROM scale_factors ORDER BY factor_value")
    allowed_sf = [row[0] for row in c.fetchall()]

    conn.close()

    terms = []
    for idx, pauli, coeff, ideal_ev in terms_raw:
        noise_rate = sum(
            qubit_noise[q] for q, op in enumerate(pauli) if op != "I"
        )
        terms.append({
            "pauli": pauli,
            "coefficient": coeff,
            "ideal_expectation": ideal_ev,
            "noise_rate": noise_rate,
        })

    with open("/app/experiment.toml", "rb") as f:
        toml_cfg = tomllib.load(f)

    return {
        "terms": terms,
        "allowed_scale_factors": allowed_sf,
        "min_extrapolation_points": toml_cfg["extrapolation"]["min_points"],
        "max_extrapolation_points": toml_cfg["extrapolation"]["max_points"],
        "total_shot_budget": toml_cfg["measurement"]["total_shot_budget"],
    }


def pauli_commute_qubitwise(p1, p2):
    """Check if two Pauli strings commute qubitwise."""
    for a, b in zip(p1, p2):
        if a == "I" or b == "I" or a == b:
            continue
        return False
    return True


def find_min_commuting_partition(paulis):
    """Find minimum partition into qubitwise-commuting groups."""
    n = len(paulis)
    adj = [[False] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if not pauli_commute_qubitwise(paulis[i], paulis[j]):
                adj[i][j] = True
                adj[j][i] = True

    degrees = [sum(row) for row in adj]
    order = sorted(range(n), key=lambda x: -degrees[x])

    colors = [-1] * n
    for node in order:
        used = set()
        for nb in range(n):
            if adj[node][nb] and colors[nb] >= 0:
                used.add(colors[nb])
        c = 0
        while c in used:
            c += 1
        colors[node] = c

    num_colors = max(colors) + 1
    groups = [[] for _ in range(num_colors)]
    for i, c_val in enumerate(colors):
        groups[c_val].append(i)
    groups = [sorted(g) for g in groups if g]
    groups.sort(key=lambda g: g[0])
    return groups


def lagrange_coefficients_at_zero(scale_factors):
    """Compute Lagrange interpolation coefficients for extrapolation to x=0."""
    k = len(scale_factors)
    gamma = []
    for j in range(k):
        prod = 1.0
        for m in range(k):
            if m != j:
                prod *= (-scale_factors[m]) / (scale_factors[j] - scale_factors[m])
        gamma.append(prod)
    return gamma


def measurement_variance(ideal_ev, noise_rate, scale_factor):
    """Compute measurement variance for a Pauli observable at a given noise scale."""
    return 1.0 - ideal_ev ** 2 * math.exp(-2.0 * noise_rate * scale_factor)


def compute_optimal_variance_and_allocation(terms, groups, scale_factors, budget):
    """Compute minimum variance and optimal shot allocation."""
    gamma = lagrange_coefficients_at_zero(scale_factors)

    sqrt_B = []
    for group in groups:
        row = []
        for j, sf in enumerate(scale_factors):
            B_gj = 0.0
            for idx in group:
                t = terms[idx]
                sigma2 = measurement_variance(
                    t["ideal_expectation"], t["noise_rate"], sf
                )
                B_gj += t["coefficient"] ** 2 * gamma[j] ** 2 * sigma2
            row.append(math.sqrt(B_gj))
        sqrt_B.append(row)

    total_sqrt_B = sum(val for row in sqrt_B for val in row)
    opt_variance = total_sqrt_B ** 2 / budget

    allocation = []
    for g_idx in range(len(groups)):
        row = []
        for j in range(len(scale_factors)):
            n_gj = budget * sqrt_B[g_idx][j] / total_sqrt_B
            row.append(int(round(n_gj)))
        allocation.append(row)

    current_total = sum(val for row in allocation for val in row)
    diff = budget - current_total
    if diff != 0:
        max_val = -1
        max_g, max_j = 0, 0
        for g in range(len(allocation)):
            for j in range(len(allocation[g])):
                if allocation[g][j] > max_val:
                    max_val = allocation[g][j]
                    max_g, max_j = g, j
        allocation[max_g][max_j] += diff

    return opt_variance, allocation


def main():
    config = load_data()

    terms = config["terms"]
    allowed_sf = config["allowed_scale_factors"]
    min_k = config["min_extrapolation_points"]
    max_k = config["max_extrapolation_points"]
    budget = config["total_shot_budget"]

    paulis = [t["pauli"] for t in terms]
    groups = find_min_commuting_partition(paulis)

    best_variance = float("inf")
    best_sf = None
    best_allocation = None

    for k in range(min_k, max_k + 1):
        for combo in combinations(allowed_sf, k):
            sf = list(combo)
            variance, allocation = compute_optimal_variance_and_allocation(
                terms, groups, sf, budget
            )
            if variance < best_variance:
                best_variance = variance
                best_sf = sf
                best_allocation = allocation

    gamma = lagrange_coefficients_at_zero(best_sf)

    result = {
        "measurement_groups": groups,
        "selected_scale_factors": best_sf,
        "extrapolation_weights": gamma,
        "minimum_variance": best_variance,
        "shot_allocation": best_allocation,
    }

    with open("/app/result.json", "w") as f:
        json.dump(result, f, indent=2)

    with open("/app/allocation.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["group", "scale_factor", "shots"])
        for g_idx, row in enumerate(best_allocation):
            for j_idx, shots in enumerate(row):
                writer.writerow([g_idx, j_idx, shots])


if __name__ == "__main__":
    main()
