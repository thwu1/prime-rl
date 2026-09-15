#!/usr/bin/env python3
"""Tests for perturbation robustness analysis pipeline."""

import csv
import json
import math
import os
import random
import sqlite3

import pytest
from scipy.stats import kendalltau


# ── fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db_conn():
    conn = sqlite3.connect("/app/experiment.db")
    yield conn
    conn.close()


@pytest.fixture(scope="module")
def models(db_conn):
    return [r[0] for r in db_conn.execute(
        "SELECT name FROM models ORDER BY id")]


@pytest.fixture(scope="module")
def tasks(db_conn):
    return [r[0] for r in db_conn.execute(
        "SELECT name FROM tasks ORDER BY id")]


@pytest.fixture(scope="module")
def perturbations(db_conn):
    return [r[0] for r in db_conn.execute(
        "SELECT name FROM perturbations ORDER BY id")]


@pytest.fixture(scope="module")
def categories(db_conn):
    cats = {}
    for row in db_conn.execute(
            "SELECT name, category FROM perturbations "
            "WHERE category != 'baseline' ORDER BY id"):
        cats.setdefault(row[1], []).append(row[0])
    return cats


@pytest.fixture(scope="module")
def combined_components(db_conn):
    comps = {}
    for row in db_conn.execute("""
        SELECT p.name, cc.component_category
        FROM combined_components cc
        JOIN perturbations p ON cc.perturbation_id = p.id
        ORDER BY p.id
    """):
        comps.setdefault(row[0], []).append(row[1])
    return comps


@pytest.fixture(scope="module")
def sim_rollouts(db_conn, models, tasks, perturbations):
    rollouts = {}
    for model in models:
        rollouts[model] = {}
        for task in tasks:
            rollouts[model][task] = {}
            for pert in perturbations:
                outcomes = [r[0] for r in db_conn.execute("""
                    SELECT sr.success FROM sim_rollouts sr
                    JOIN models m ON sr.model_id = m.id
                    JOIN tasks t ON sr.task_id = t.id
                    JOIN perturbations p ON sr.perturbation_id = p.id
                    WHERE m.name = ? AND t.name = ? AND p.name = ?
                    ORDER BY sr.rollout_num
                """, (model, task, pert))]
                rollouts[model][task][pert] = outcomes
    return rollouts


@pytest.fixture(scope="module")
def real_data():
    data = {}
    real_tasks = set()
    real_perts = set()
    for fname in sorted(os.listdir("/app/real_validation")):
        if not fname.endswith(".csv"):
            continue
        model = fname[:-4]
        with open(os.path.join("/app/real_validation", fname)) as f:
            reader = csv.DictReader(f)
            for row in reader:
                task = row["task"]
                pert = row["perturbation"]
                success = int(row["success"])
                real_tasks.add(task)
                real_perts.add(pert)
                (data
                 .setdefault(model, {})
                 .setdefault(task, {})
                 .setdefault(pert, [])
                 .append(success))
    return sorted(real_tasks), sorted(real_perts), data


@pytest.fixture(scope="module")
def success_rates():
    with open("/app/results/success_rates.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def sensitivity():
    with open("/app/results/sensitivity_decomposition.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def correlation():
    with open("/app/results/real_sim_correlation.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def interactions():
    with open("/app/results/interactions.json") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def shapley():
    with open("/app/results/shapley_values.json") as f:
        return json.load(f)


# ── helpers ──────────────────────────────────────────────────────────────

def _wilson_ci(k, n, z=1.96):
    """Reference Wilson score CI computation."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p_hat = k / n
    denom = 1 + z ** 2 / n
    center = (p_hat + z ** 2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(
        p_hat * (1 - p_hat) / n + z ** 2 / (4 * n ** 2))
    return p_hat, max(0.0, center - margin), min(1.0, center + margin)


# ── 1. output files exist ───────────────────────────────────────────────

EXPECTED_FILES = [
    "/app/results/success_rates.json",
    "/app/results/sensitivity_decomposition.json",
    "/app/results/real_sim_correlation.json",
    "/app/results/interactions.json",
    "/app/results/shapley_values.json",
]


@pytest.mark.parametrize("fpath", EXPECTED_FILES)
def test_output_file_exists(fpath):
    assert os.path.isfile(fpath), f"Missing output file: {fpath}"


# ── 2. success rates & Wilson CIs ───────────────────────────────────────

def test_success_rates_structure(success_rates, models, perturbations):
    """All models and perturbations present with required keys."""
    for model in models:
        assert model in success_rates, f"Missing model {model}"
        for pert in perturbations:
            assert pert in success_rates[model], \
                f"Missing perturbation {pert} for {model}"
            entry = success_rates[model][pert]
            for key in ("success_rate", "ci_lower", "ci_upper",
                        "n_trials", "n_successes"):
                assert key in entry, f"Missing key {key} in {model}/{pert}"


def test_wilson_ci_correctness(success_rates, sim_rollouts,
                               models, perturbations, tasks):
    """Verify Wilson score CIs against independent computation."""
    for model in models:
        for pert in perturbations:
            outcomes = []
            for task in tasks:
                outcomes.extend(sim_rollouts[model][task][pert])
            n = len(outcomes)
            k = sum(outcomes)
            expected_rate, expected_lo, expected_hi = _wilson_ci(k, n)

            result = success_rates[model][pert]
            assert abs(result["success_rate"] - expected_rate) < 1e-3, \
                f"Rate mismatch {model}/{pert}"
            assert abs(result["ci_lower"] - expected_lo) < 1e-3, \
                f"CI lower mismatch {model}/{pert}"
            assert abs(result["ci_upper"] - expected_hi) < 1e-3, \
                f"CI upper mismatch {model}/{pert}"
            assert result["n_trials"] == n
            assert result["n_successes"] == k
            assert result["ci_lower"] <= result["success_rate"] + 1e-6
            assert result["ci_upper"] >= result["success_rate"] - 1e-6


# ── 3. sensitivity decomposition ────────────────────────────────────────

def test_sensitivity_structure(sensitivity, models, categories):
    for model in models:
        assert model in sensitivity
        for cat in categories:
            assert cat in sensitivity[model], \
                f"Missing category {cat} for {model}"
            assert "mean_degradation" in sensitivity[model][cat]
            assert "per_perturbation" in sensitivity[model][cat]


def test_sensitivity_values(sensitivity, success_rates, models, categories):
    """Verify degradation values match success_rates minus default."""
    for model in models:
        default_rate = success_rates[model]["default"]["success_rate"]
        for cat, cat_perts in categories.items():
            expected_degs = []
            for pert in cat_perts:
                expected_deg = (default_rate
                                - success_rates[model][pert]["success_rate"])
                expected_degs.append(expected_deg)
                actual_deg = sensitivity[model][cat]["per_perturbation"][pert]
                assert abs(actual_deg - expected_deg) < 1e-3, \
                    f"Degradation mismatch {model}/{cat}/{pert}"
            expected_mean = sum(expected_degs) / len(expected_degs)
            assert abs(sensitivity[model][cat]["mean_degradation"]
                       - expected_mean) < 1e-3, \
                f"Mean degradation mismatch {model}/{cat}"


# ── 4. real-to-sim correlation ──────────────────────────────────────────

def test_kendall_tau_b_value(correlation, sim_rollouts, real_data, models):
    """Verify Kendall tau-b against scipy implementation."""
    real_tasks, real_perts, real_dict = real_data

    sim_rates = []
    real_rates = []
    for model in models:
        if model not in real_dict:
            continue
        for task in real_tasks:
            for pert in real_perts:
                s = sim_rollouts[model][task][pert]
                r = real_dict[model][task][pert]
                sim_rates.append(sum(s) / len(s))
                real_rates.append(sum(r) / len(r))

    expected_tau, _ = kendalltau(sim_rates, real_rates)
    assert abs(correlation["kendall_tau_b"] - expected_tau) < 1e-3, \
        f"Kendall tau-b mismatch: {correlation['kendall_tau_b']} vs {expected_tau}"


def test_correlation_structure(correlation):
    """Verify correlation output has required keys and valid ranges."""
    assert "kendall_tau_b" in correlation
    assert "bootstrap_ci_lower" in correlation
    assert "bootstrap_ci_upper" in correlation
    assert "n_conditions" in correlation
    assert correlation["n_conditions"] == 45  # 3 models x 3 tasks x 5 perts
    assert correlation["bootstrap_ci_lower"] <= correlation["kendall_tau_b"] + 0.05
    assert correlation["bootstrap_ci_upper"] >= correlation["kendall_tau_b"] - 0.05
    assert correlation["bootstrap_ci_lower"] < correlation["bootstrap_ci_upper"]
    assert -1.0 <= correlation["kendall_tau_b"] <= 1.0


def test_bootstrap_ci(correlation, sim_rollouts, real_data, models):
    """Verify bootstrap CI uses correct seed and percentiles."""
    real_tasks, real_perts, real_dict = real_data

    sim_rates = []
    real_rates = []
    for model in models:
        if model not in real_dict:
            continue
        for task in real_tasks:
            for pert in real_perts:
                s = sim_rollouts[model][task][pert]
                r = real_dict[model][task][pert]
                sim_rates.append(sum(s) / len(s))
                real_rates.append(sum(r) / len(r))

    saved_state = random.getstate()
    random.seed(999)
    n = len(sim_rates)
    boot_taus = []
    for _ in range(1000):
        idx = [random.randint(0, n - 1) for _ in range(n)]
        bx = [sim_rates[i] for i in idx]
        by = [real_rates[i] for i in idx]
        tau, _ = kendalltau(bx, by)
        boot_taus.append(tau)
    random.setstate(saved_state)

    boot_taus.sort()
    expected_lo = boot_taus[24]
    expected_hi = boot_taus[974]

    assert abs(correlation["bootstrap_ci_lower"] - expected_lo) < 0.02, \
        f"Bootstrap CI lower: {correlation['bootstrap_ci_lower']} vs {expected_lo}"
    assert abs(correlation["bootstrap_ci_upper"] - expected_hi) < 0.02, \
        f"Bootstrap CI upper: {correlation['bootstrap_ci_upper']} vs {expected_hi}"


# ── 5. interactions ─────────────────────────────────────────────────────

def test_interactions_structure(interactions, models, combined_components):
    for model in models:
        assert model in interactions
        for comb_pert in combined_components:
            assert comb_pert in interactions[model], \
                f"Missing combined perturbation {comb_pert} for {model}"
            entry = interactions[model][comb_pert]
            for key in ("observed_degradation", "expected_additive_degradation",
                        "interaction_effect", "p_value", "significant",
                        "component_categories"):
                assert key in entry, f"Missing key {key} in {model}/{comb_pert}"


def test_interactions_deterministic_values(interactions, success_rates,
                                           models, categories,
                                           combined_components):
    """Verify deterministic interaction values (not p-values)."""
    for model in models:
        default_rate = success_rates[model]["default"]["success_rate"]
        for comb_pert, components in combined_components.items():
            entry = interactions[model][comb_pert]

            expected_obs = (default_rate
                            - success_rates[model][comb_pert]["success_rate"])
            assert abs(entry["observed_degradation"] - expected_obs) < 1e-3, \
                f"Observed degradation mismatch {model}/{comb_pert}"

            expected_add = 0.0
            for comp_cat in components:
                cat_perts = categories[comp_cat]
                cat_degs = [default_rate
                            - success_rates[model][p]["success_rate"]
                            for p in cat_perts]
                expected_add += sum(cat_degs) / len(cat_degs)
            assert abs(entry["expected_additive_degradation"]
                       - expected_add) < 1e-3, \
                f"Expected additive degradation mismatch {model}/{comb_pert}"

            expected_interaction = expected_obs - expected_add
            assert abs(entry["interaction_effect"]
                       - expected_interaction) < 1e-3, \
                f"Interaction effect mismatch {model}/{comb_pert}"

            assert 0.0 <= entry["p_value"] <= 1.0, \
                f"Invalid p-value {model}/{comb_pert}"
            assert entry["significant"] == (entry["p_value"] < 0.05)
            assert sorted(entry["component_categories"]) == sorted(components)


def test_interaction_pvalues_twosided(interactions, sim_rollouts,
                                      models, tasks, combined_components):
    """Verify permutation tests are two-sided."""
    comb_keys = list(combined_components.keys())
    for model_idx, model in enumerate(models):
        for cp_idx, comb_pert in enumerate(comb_keys):
            all_default = []
            all_combined = []
            for task in tasks:
                all_default.extend(sim_rollouts[model][task]["default"])
                all_combined.extend(sim_rollouts[model][task][comb_pert])

            n_def = len(all_default)
            observed_diff = (sum(all_default) / n_def
                             - sum(all_combined) / len(all_combined))
            pooled = all_default + all_combined

            saved_state = random.getstate()
            seed_val = model_idx * 100 + cp_idx
            random.seed(seed_val)

            count_extreme = 0
            for _ in range(1000):
                random.shuffle(pooled)
                perm_def = pooled[:n_def]
                perm_comb = pooled[n_def:]
                perm_diff = (sum(perm_def) / len(perm_def)
                             - sum(perm_comb) / len(perm_comb))
                if abs(perm_diff) >= abs(observed_diff):
                    count_extreme += 1
            random.setstate(saved_state)

            expected_pval = count_extreme / 1000
            actual_pval = interactions[model][comb_pert]["p_value"]
            assert abs(actual_pval - expected_pval) < 0.01, \
                f"P-value {model}/{comb_pert}: {actual_pval} vs {expected_pval}"


# ── 6. Shapley values ──────────────────────────────────────────────────

def test_shapley_structure(shapley, models, categories):
    for model in models:
        assert model in shapley
        assert "shapley_values" in shapley[model]
        assert "total_degradation" in shapley[model]
        assert "shapley_sum" in shapley[model]
        assert "efficiency_check" in shapley[model]
        for cat in categories:
            assert cat in shapley[model]["shapley_values"], \
                f"Missing Shapley value for {cat} in {model}"


def test_shapley_efficiency(shapley, models):
    """Shapley values must sum to total degradation (efficiency property)."""
    for model in models:
        sv = shapley[model]["shapley_values"]
        sv_sum = sum(sv.values())
        total = shapley[model]["total_degradation"]
        assert abs(sv_sum - total) < 1e-2, \
            f"Shapley efficiency violated for {model}: sum={sv_sum}, total={total}"


def test_shapley_total_degradation(shapley, success_rates, models, categories):
    """Verify total_degradation matches grand coalition (pooled) value."""
    for model in models:
        default_rate = success_rates[model]["default"]["success_rate"]
        all_degs = []
        for cat_perts in categories.values():
            for pert in cat_perts:
                all_degs.append(
                    default_rate
                    - success_rates[model][pert]["success_rate"])
        expected_total = sum(all_degs) / len(all_degs)
        assert abs(shapley[model]["total_degradation"]
                   - expected_total) < 1e-3, \
            f"Total degradation mismatch for {model}"
