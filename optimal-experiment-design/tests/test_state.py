
import json
import numpy as np
import pytest


@pytest.fixture
def problem_data():
    V = np.load('/app/experiments.npy')
    with open('/app/config.json') as f:
        config = json.load(f)
    return V, config


@pytest.fixture
def results():
    with open('/app/results.json') as f:
        return json.load(f)


def compute_fim(weights, V):
    """Compute Fisher Information Matrix from weights and experiment vectors."""
    w = np.asarray(weights, dtype=float)
    return (V.T * w) @ V


# ---------- Test 1: Output structure ----------
def test_results_structure(results):
    for key in ['d_optimal', 'a_optimal', 'e_optimal']:
        assert key in results, f"Missing key: {key}"
        for field in ['relaxed_weights', 'relaxed_objective',
                      'integer_allocation', 'integer_objective']:
            assert field in results[key], f"Missing {key}.{field}"
    assert 'efficiency_matrix' in results, "Missing efficiency_matrix"
    assert 'robust_experiments' in results, "Missing robust_experiments"


# ---------- Test 2: Relaxed weight feasibility ----------
def test_relaxed_feasibility(problem_data, results):
    V, config = problem_data
    m = config['num_experiments']
    max_ratio = config['max_per_experiment'] / config['budget']

    for key in ['d_optimal', 'a_optimal', 'e_optimal']:
        w = np.array(results[key]['relaxed_weights'])
        assert len(w) == m, f"{key}: wrong number of weights"
        assert np.all(w >= -1e-5), f"{key}: negative weight found"
        assert abs(np.sum(w) - 1.0) < 1e-3, \
            f"{key}: weights sum to {np.sum(w)}, expected 1.0"
        assert np.all(w <= max_ratio + 1e-5), \
            f"{key}: weight exceeds cap {max_ratio}"


# ---------- Test 3: FIM positive definiteness ----------
def test_fim_positive_definite(problem_data, results):
    V, config = problem_data
    for key in ['d_optimal', 'a_optimal', 'e_optimal']:
        w = np.array(results[key]['relaxed_weights'])
        FIM = compute_fim(w, V)
        eigvals = np.linalg.eigvalsh(FIM)
        assert np.all(eigvals > 1e-8), \
            f"{key}: FIM not positive definite, min eigval={eigvals.min()}"


# ---------- Test 4: Objective consistency ----------
def test_objective_consistency(problem_data, results):
    V, config = problem_data

    for key in ['d_optimal', 'a_optimal', 'e_optimal']:
        w = np.array(results[key]['relaxed_weights'])
        FIM = compute_fim(w, V)

        if key == 'd_optimal':
            computed = np.log(np.linalg.det(FIM))
        elif key == 'a_optimal':
            computed = np.trace(np.linalg.inv(FIM))
        else:
            computed = np.min(np.linalg.eigvalsh(FIM))

        reported = results[key]['relaxed_objective']
        denom = max(abs(computed), 1e-10)
        rel_err = abs(computed - reported) / denom
        assert rel_err < 0.05, \
            f"{key}: objective mismatch computed={computed:.6f} reported={reported:.6f}"


# ---------- Test 5: D-optimal KKT (Kiefer-Wolfowitz) ----------
def test_d_optimal_kkt(problem_data, results):
    V, config = problem_data
    d = config['dimension']
    m = config['num_experiments']
    max_ratio = config['max_per_experiment'] / config['budget']

    w = np.array(results['d_optimal']['relaxed_weights'])
    FIM = compute_fim(w, V)
    FIM_inv = np.linalg.inv(FIM)

    sensitivities = np.array([V[i] @ FIM_inv @ V[i] for i in range(m)])

    # Trace identity: sum_i w_i * sens_i = d (always holds by construction)
    trace_val = np.sum(w * sensitivities)
    assert abs(trace_val - d) < 0.2, \
        f"Trace identity: {trace_val} != {d}"

    # Interior active experiments (not at bounds) should have equal sensitivity
    interior = (w > 1e-4) & (w < max_ratio - 1e-4)
    if np.sum(interior) >= 2:
        int_sens = sensitivities[interior]
        mu = np.mean(int_sens)
        assert np.all(np.abs(int_sens - mu) < 0.5), \
            f"Interior sensitivities not equal: {int_sens}"

        # Inactive experiments should have sensitivity <= mu
        inactive = w < 1e-4
        if np.sum(inactive) > 0:
            assert np.all(sensitivities[inactive] <= mu + 0.5), \
                "Inactive experiment has sensitivity above threshold"


# ---------- Test 6: A-optimal KKT ----------
def test_a_optimal_kkt(problem_data, results):
    V, config = problem_data
    m = config['num_experiments']
    max_ratio = config['max_per_experiment'] / config['budget']

    w = np.array(results['a_optimal']['relaxed_weights'])
    FIM = compute_fim(w, V)
    FIM_inv = np.linalg.inv(FIM)
    FIM_inv_sq = FIM_inv @ FIM_inv

    sensitivities = np.array([V[i] @ FIM_inv_sq @ V[i] for i in range(m)])

    interior = (w > 1e-4) & (w < max_ratio - 1e-4)
    if np.sum(interior) >= 2:
        int_sens = sensitivities[interior]
        mu = np.mean(int_sens)
        cv = np.std(int_sens) / mu if mu > 1e-12 else 0.0
        assert cv < 0.15, \
            f"A-optimal interior sensitivities not equal (CV={cv:.3f})"

        inactive = w < 1e-4
        if np.sum(inactive) > 0:
            assert np.all(sensitivities[inactive] <= mu * 1.2 + 0.1), \
                "A-optimal inactive sensitivity exceeds threshold"


# ---------- Test 7: Integer allocation feasibility ----------
def test_integer_feasibility(problem_data, results):
    V, config = problem_data
    N = config['budget']
    max_per = config['max_per_experiment']
    m = config['num_experiments']

    for key in ['d_optimal', 'a_optimal', 'e_optimal']:
        alloc = results[key]['integer_allocation']
        assert len(alloc) == m, f"{key}: wrong allocation length"
        alloc_int = [int(round(n)) for n in alloc]
        assert all(n >= 0 for n in alloc_int), f"{key}: negative allocation"
        assert all(n <= max_per for n in alloc_int), f"{key}: allocation exceeds cap"
        assert sum(alloc_int) == N, \
            f"{key}: allocations sum to {sum(alloc_int)}, expected {N}"


# ---------- Test 8: Integer objective consistency ----------
def test_integer_objective_consistency(problem_data, results):
    V, config = problem_data

    for key in ['d_optimal', 'a_optimal', 'e_optimal']:
        alloc = [int(round(n)) for n in results[key]['integer_allocation']]
        FIM = compute_fim(alloc, V)
        eigvals = np.linalg.eigvalsh(FIM)
        assert np.all(eigvals > 0), f"{key}: integer FIM not PD"

        if key == 'd_optimal':
            computed = np.log(np.linalg.det(FIM))
        elif key == 'a_optimal':
            computed = np.trace(np.linalg.inv(FIM))
        else:
            computed = np.min(eigvals)

        reported = results[key]['integer_objective']
        denom = max(abs(computed), 1e-10)
        rel_err = abs(computed - reported) / denom
        assert rel_err < 0.05, \
            f"{key}: integer obj mismatch computed={computed:.6f} reported={reported:.6f}"


# ---------- Test 9: Integer-relaxed consistency (rounding gap) ----------
def test_integer_relaxed_consistency(problem_data, results):
    V, config = problem_data
    d = config['dimension']
    N = config['budget']

    # D-optimal: int_obj ≈ d*log(N) + rel_obj
    d_rel = results['d_optimal']['relaxed_objective']
    d_int = results['d_optimal']['integer_objective']
    d_expected = d * np.log(N) + d_rel
    assert abs(d_int - d_expected) < 3.0, \
        f"D-optimal rounding gap too large: {d_int} vs expected ~{d_expected}"

    # A-optimal: int_obj ≈ rel_obj / N
    a_rel = results['a_optimal']['relaxed_objective']
    a_int = results['a_optimal']['integer_objective']
    a_expected = a_rel / N
    assert abs(a_int - a_expected) / max(abs(a_expected), 1e-10) < 0.4, \
        f"A-optimal rounding gap too large: {a_int} vs expected ~{a_expected}"

    # E-optimal: int_obj ≈ N * rel_obj
    e_rel = results['e_optimal']['relaxed_objective']
    e_int = results['e_optimal']['integer_objective']
    e_expected = N * e_rel
    assert abs(e_int - e_expected) / max(abs(e_expected), 1e-10) < 0.4, \
        f"E-optimal rounding gap too large: {e_int} vs expected ~{e_expected}"


# ---------- Test 10: Efficiency matrix ----------
def test_efficiency_matrix(problem_data, results):
    V, config = problem_data
    d = config['dimension']

    eff = results['efficiency_matrix']
    assert len(eff) == 3 and all(len(row) == 3 for row in eff), \
        "Efficiency matrix must be 3x3"

    # Diagonal should be approximately 1.0
    for i in range(3):
        assert abs(eff[i][i] - 1.0) < 0.05, \
            f"Efficiency diagonal [{i}][{i}] = {eff[i][i]}, expected 1.0"

    # All entries in [0, 1]
    for i in range(3):
        for j in range(3):
            assert -0.02 <= eff[i][j] <= 1.02, \
                f"Efficiency [{i}][{j}] = {eff[i][j]} out of range"

    # Verify values match computation from reported weights
    designs = ['d_optimal', 'a_optimal', 'e_optimal']
    fims = [compute_fim(np.array(results[k]['relaxed_weights']), V)
            for k in designs]
    log_dets = [np.log(np.linalg.det(F)) for F in fims]
    trace_invs = [np.trace(np.linalg.inv(F)) for F in fims]
    min_eigs = [np.min(np.linalg.eigvalsh(F)) for F in fims]

    for i in range(3):
        d_eff = np.exp((log_dets[i] - log_dets[0]) / d)
        assert abs(eff[i][0] - d_eff) < 0.05, \
            f"D-efficiency [{i}][0] mismatch: {eff[i][0]} vs {d_eff}"

        a_eff = trace_invs[1] / trace_invs[i]
        assert abs(eff[i][1] - a_eff) < 0.05, \
            f"A-efficiency [{i}][1] mismatch: {eff[i][1]} vs {a_eff}"

        e_eff = min_eigs[i] / min_eigs[2]
        assert abs(eff[i][2] - e_eff) < 0.05, \
            f"E-efficiency [{i}][2] mismatch: {eff[i][2]} vs {e_eff}"


# ---------- Test 11: Robust experiments ----------
def test_robust_experiments(problem_data, results):
    V, config = problem_data
    m = config['num_experiments']
    threshold = 1e-4

    supports = []
    for key in ['d_optimal', 'a_optimal', 'e_optimal']:
        w = np.array(results[key]['relaxed_weights'])
        support = set(i for i in range(m) if w[i] > threshold)
        supports.append(support)

    expected_robust = sorted(supports[0] & supports[1] & supports[2])
    reported_robust = sorted(results['robust_experiments'])

    assert reported_robust == expected_robust, \
        f"Robust experiments mismatch: expected {expected_robust}, got {reported_robust}"
