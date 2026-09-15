"""Tests for quantum Hamiltonian variance minimization."""

import csv
import json
import math
import os
import sqlite3
import tomllib
from itertools import combinations

import pytest


# ---------------------------------------------------------------------------
# Helper functions (independent reference implementation)
# ---------------------------------------------------------------------------

def load_config_from_sources():
    """Independently reconstruct the problem from SQLite + TOML sources."""
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
    scale_factors = [row[0] for row in c.fetchall()]

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
        "allowed_scale_factors": scale_factors,
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
    """Find minimum partition into qubitwise-commuting groups via greedy coloring."""
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


def meas_var(ideal_ev, noise_rate, sf):
    """Measurement variance at given scale factor."""
    return 1.0 - ideal_ev ** 2 * math.exp(-2.0 * noise_rate * sf)


def compute_optimal_variance(terms, groups, scale_factors, budget):
    """Compute minimum achievable variance with optimal shot allocation."""
    gamma = lagrange_coefficients_at_zero(scale_factors)
    total_sqrt_B = 0.0
    for group in groups:
        for j, sf in enumerate(scale_factors):
            B = 0.0
            for idx in group:
                t = terms[idx]
                B += t["coefficient"] ** 2 * gamma[j] ** 2 * meas_var(
                    t["ideal_expectation"], t["noise_rate"], sf
                )
            total_sqrt_B += math.sqrt(B)
    return total_sqrt_B ** 2 / budget


def find_global_optimum(config, groups):
    """Find the globally optimal scale factors and minimum variance."""
    terms = config["terms"]
    allowed = config["allowed_scale_factors"]
    min_k = config["min_extrapolation_points"]
    max_k = config["max_extrapolation_points"]
    budget = config["total_shot_budget"]

    best_var = float("inf")
    best_sf = None
    for k in range(min_k, max_k + 1):
        for combo in combinations(allowed, k):
            sf = list(combo)
            v = compute_optimal_variance(terms, groups, sf, budget)
            if v < best_var:
                best_var = v
                best_sf = sf
    return best_sf, best_var


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def config():
    return load_config_from_sources()


@pytest.fixture(scope="module")
def result():
    with open("/app/result.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def reference(config):
    terms = config["terms"]
    paulis = [t["pauli"] for t in terms]
    groups = find_min_commuting_partition(paulis)
    best_sf, best_var = find_global_optimum(config, groups)
    return {
        "groups": groups,
        "num_groups": len(groups),
        "optimal_sf": best_sf,
        "optimal_var": best_var,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestResultStructure:
    def test_result_file_valid_json(self, result):
        """result.json must be a JSON object."""
        assert isinstance(result, dict), "result.json must be a JSON object"

    def test_required_keys(self, result):
        """All required keys must be present."""
        required = [
            "measurement_groups",
            "selected_scale_factors",
            "extrapolation_weights",
            "minimum_variance",
            "shot_allocation",
        ]
        for key in required:
            assert key in result, f"Missing required key: {key}"


class TestMeasurementGroups:
    def test_all_terms_covered_once(self, config, result):
        """Every term index appears in exactly one group."""
        groups = result["measurement_groups"]
        all_idx = sorted(idx for g in groups for idx in g)
        expected = list(range(len(config["terms"])))
        assert all_idx == expected, (
            f"Term coverage mismatch: expected {expected}, got {all_idx}"
        )

    def test_within_group_commutativity(self, config, result):
        """All terms within each group must commute qubitwise."""
        terms = config["terms"]
        for g_idx, group in enumerate(result["measurement_groups"]):
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    p1 = terms[group[i]]["pauli"]
                    p2 = terms[group[j]]["pauli"]
                    assert pauli_commute_qubitwise(p1, p2), (
                        f"Group {g_idx}: terms {group[i]} ({p1}) and "
                        f"{group[j]} ({p2}) do not commute qubitwise"
                    )

    def test_num_groups_optimal(self, result, reference):
        """Number of groups must match the minimum partition size."""
        assert len(result["measurement_groups"]) == reference["num_groups"], (
            f"Expected {reference['num_groups']} groups, "
            f"got {len(result['measurement_groups'])}"
        )


class TestScaleFactorsAndWeights:
    def test_scale_factors_are_allowed(self, config, result):
        """Each chosen scale factor must be from the allowed set."""
        allowed = set(config["allowed_scale_factors"])
        for sf in result["selected_scale_factors"]:
            assert sf in allowed, f"Scale factor {sf} not in allowed set {allowed}"

    def test_scale_factors_count_in_range(self, config, result):
        """Number of scale factors must be within allowed range."""
        k = len(result["selected_scale_factors"])
        lo = config["min_extrapolation_points"]
        hi = config["max_extrapolation_points"]
        assert lo <= k <= hi, (
            f"Number of scale factors {k} outside allowed range [{lo}, {hi}]"
        )

    def test_scale_factors_match_optimal(self, result, reference):
        """Chosen scale factors must match the globally optimal selection."""
        assert sorted(result["selected_scale_factors"]) == sorted(
            reference["optimal_sf"]
        ), (
            f"Expected scale factors {reference['optimal_sf']}, "
            f"got {sorted(result['selected_scale_factors'])}"
        )

    def test_extrapolation_weights_correct(self, result):
        """Extrapolation weights must match the Lagrange formula at x=0."""
        sf = sorted(result["selected_scale_factors"])
        expected = lagrange_coefficients_at_zero(sf)
        actual = result["extrapolation_weights"]
        assert len(actual) == len(expected), (
            f"Expected {len(expected)} weights, got {len(actual)}"
        )
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert abs(a - e) < 1e-8, (
                f"Extrapolation weight {i}: expected {e:.10f}, got {a:.10f}"
            )


class TestVariance:
    def test_variance_correct_for_chosen_config(self, config, result):
        """Reported variance must be correct for the chosen groups and factors."""
        groups = result["measurement_groups"]
        sf = sorted(result["selected_scale_factors"])
        budget = config["total_shot_budget"]
        ref_var = compute_optimal_variance(config["terms"], groups, sf, budget)
        reported = result["minimum_variance"]
        rel_err = abs(reported - ref_var) / ref_var
        assert rel_err < 0.005, (
            f"Reported variance {reported:.10e} does not match expected "
            f"{ref_var:.10e} (rel error {rel_err:.4%})"
        )

    def test_variance_globally_optimal(self, result, reference):
        """Reported variance must be close to the global optimum."""
        reported = result["minimum_variance"]
        optimal = reference["optimal_var"]
        rel_err = abs(reported - optimal) / optimal
        assert rel_err < 0.005, (
            f"Reported variance {reported:.10e} is not globally optimal. "
            f"Best achievable: {optimal:.10e} (rel error {rel_err:.4%})"
        )


class TestShotAllocation:
    def test_allocation_shape(self, result):
        """Allocation dimensions must match groups and scale factors."""
        alloc = result["shot_allocation"]
        n_groups = len(result["measurement_groups"])
        n_sf = len(result["selected_scale_factors"])
        assert len(alloc) == n_groups, (
            f"Allocation has {len(alloc)} rows, expected {n_groups}"
        )
        for i, row in enumerate(alloc):
            assert len(row) == n_sf, (
                f"Allocation row {i} has {len(row)} cols, expected {n_sf}"
            )

    def test_allocation_sums_to_budget(self, config, result):
        """Total shots must equal the budget."""
        alloc = result["shot_allocation"]
        total = sum(v for row in alloc for v in row)
        budget = config["total_shot_budget"]
        assert abs(total - budget) <= 20, (
            f"Shot allocation sums to {total}, expected {budget} (tolerance 20)"
        )

    def test_allocation_nonnegative(self, result):
        """All allocation values must be non-negative."""
        for g, row in enumerate(result["shot_allocation"]):
            for j, val in enumerate(row):
                assert val >= 0, (
                    f"Negative allocation: group {g}, sf index {j} = {val}"
                )

    def test_allocation_achieves_near_optimal_variance(self, config, result):
        """Actual variance from allocation must be close to the reported minimum."""
        groups = result["measurement_groups"]
        sf = sorted(result["selected_scale_factors"])
        alloc = result["shot_allocation"]
        gamma = lagrange_coefficients_at_zero(sf)
        terms = config["terms"]

        actual_var = 0.0
        for g_idx, group in enumerate(groups):
            for j_idx, s in enumerate(sf):
                n_gj = alloc[g_idx][j_idx]
                if n_gj <= 0:
                    continue
                for idx in group:
                    t = terms[idx]
                    sigma2 = meas_var(t["ideal_expectation"], t["noise_rate"], s)
                    actual_var += (
                        t["coefficient"] ** 2 * gamma[j_idx] ** 2 * sigma2 / n_gj
                    )

        reported = result["minimum_variance"]
        rel_err = abs(actual_var - reported) / reported
        assert rel_err < 0.05, (
            f"Actual variance from allocation {actual_var:.10e} differs from "
            f"reported {reported:.10e} by {rel_err:.4%} (tolerance 5%)"
        )


class TestCSVAllocation:
    def test_csv_exists(self):
        """allocation.csv must exist."""
        assert os.path.exists("/app/allocation.csv"), (
            "/app/allocation.csv not found"
        )

    def test_csv_headers(self):
        """CSV must have the correct header columns."""
        with open("/app/allocation.csv") as f:
            reader = csv.reader(f)
            headers = next(reader)
        assert [h.strip() for h in headers] == ["group", "scale_factor", "shots"], (
            f"Expected headers ['group', 'scale_factor', 'shots'], got {headers}"
        )

    def test_csv_row_count(self, result):
        """CSV must have one row per (group, scale_factor) pair."""
        n_groups = len(result["measurement_groups"])
        n_sf = len(result["selected_scale_factors"])
        with open("/app/allocation.csv") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == n_groups * n_sf, (
            f"Expected {n_groups * n_sf} CSV rows, got {len(rows)}"
        )

    def test_csv_matches_json(self, result):
        """CSV allocation must match the JSON shot_allocation."""
        n_groups = len(result["measurement_groups"])
        n_sf = len(result["selected_scale_factors"])
        csv_alloc = [[0] * n_sf for _ in range(n_groups)]

        with open("/app/allocation.csv") as f:
            reader = csv.DictReader(f)
            for row in reader:
                g = int(row["group"].strip())
                j = int(row["scale_factor"].strip())
                csv_alloc[g][j] = int(row["shots"].strip())

        assert csv_alloc == result["shot_allocation"], (
            "CSV allocation does not match JSON shot_allocation"
        )
