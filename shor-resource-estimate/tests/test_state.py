
"""
Tests for surface code deployment planning task.
Independently computes all expected values using Qualtran
and verifies the agent's /app/deployment_plan.json.
"""

import json
import math
import pytest
import numpy as np
import sympy

RESULTS_PATH = '/app/deployment_plan.json'

RSA_TARGETS = [
    {"modulus": 221, "base": 9},
    {"modulus": 1147, "base": 5},
    {"modulus": 4897, "base": 7},
]
ERROR_BUDGET = 0.01
MAX_DURATION_HR = 100.0
CODE_DISTANCES = [9, 11, 13, 15, 17, 19, 21, 23, 25, 27, 29, 31]
COST_MODELS = [
    {"name": "beverland_compact", "type": "beverland", "data_block": "compact"},
    {"name": "beverland_fast", "type": "beverland", "data_block": "fast"},
    {"name": "beverland_intermediate", "type": "beverland", "data_block": "intermediate"},
    {"name": "gidney_fowler", "type": "gidney_fowler"},
]
SCALING_BITSIZES = [4, 8, 16, 32, 64, 128]


@pytest.fixture(scope='module')
def results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


def _make_rsa_bloq(N, g):
    from qualtran.bloqs.cryptography.rsa import RSAPhaseEstimate
    return RSAPhaseEstimate.make_for_shor(big_n=N, g=g)


def _get_gate_costs(rsa_bloq):
    from qualtran.resource_counting import get_cost_value, QECGatesCost
    return get_cost_value(rsa_bloq, QECGatesCost())


def _make_algo_summary(N, gc):
    from qualtran.surface_code import AlgorithmSummary
    n = int(math.ceil(math.log2(N)))
    return AlgorithmSummary(n_algo_qubits=3 * n, n_logical_gates=gc)


def _evaluate_config(algo_summary, model_info, d):
    from qualtran.surface_code import PhysicalCostModel
    if model_info['type'] == 'beverland':
        model = PhysicalCostModel.make_beverland_et_al(
            data_d=d, data_block_name=model_info['data_block']
        )
    else:
        model = PhysicalCostModel.make_gidney_fowler(data_d=d)
    return {
        'model': model_info['name'],
        'code_distance': d,
        'phys_qubits': int(model.n_phys_qubits(algo_summary)),
        'error': float(model.error(algo_summary)),
        'duration_hr': float(model.duration_hr(algo_summary)),
    }


def _compute_all_configs(algo_summary):
    configs = []
    for d in CODE_DISTANCES:
        for m in COST_MODELS:
            configs.append(_evaluate_config(algo_summary, m, d))
    return configs


def _extract_pareto(configs):
    """Extract non-dominated points on the (phys_qubits, error) plane."""
    pareto = []
    for i, c in enumerate(configs):
        dominated = False
        for j, other in enumerate(configs):
            if i == j:
                continue
            if (other['phys_qubits'] <= c['phys_qubits'] and
                    other['error'] <= c['error'] and
                    (other['phys_qubits'] < c['phys_qubits'] or
                     other['error'] < c['error'])):
                dominated = True
                break
        if not dominated:
            pareto.append(c)
    return sorted(pareto, key=lambda x: x['phys_qubits'])


def _find_recommended(configs):
    feasible = [
        c for c in configs
        if c['error'] < ERROR_BUDGET and c['duration_hr'] < MAX_DURATION_HR
    ]
    if not feasible:
        return None
    return min(feasible, key=lambda c: c['phys_qubits'])


# ── Structure ──────────────────────────────────────────────────────────


def test_results_exist():
    """deployment_plan.json must exist and be valid JSON."""
    with open(RESULTS_PATH) as f:
        data = json.load(f)
    assert isinstance(data, dict)


def test_all_moduli_present(results):
    """All target moduli must be present as top-level keys."""
    for target in RSA_TARGETS:
        assert str(target['modulus']) in results, (
            f"Missing modulus {target['modulus']}"
        )


def test_scaling_key_present(results):
    """Top-level 'scaling' key must be present."""
    assert 'scaling' in results, "Missing 'scaling' key"


def test_per_modulus_keys(results):
    """Each modulus entry must have required sub-keys."""
    required = ['algorithm_costs', 'pareto_frontier', 'recommended_config']
    for target in RSA_TARGETS:
        entry = results[str(target['modulus'])]
        for key in required:
            assert key in entry, (
                f"N={target['modulus']}: missing key '{key}'"
            )


# ── Algorithm Costs ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "target", RSA_TARGETS,
    ids=[str(t['modulus']) for t in RSA_TARGETS]
)
def test_algorithm_costs(results, target):
    """Gate counts and qubit count must match independent computation."""
    N, g = target['modulus'], target['base']
    n = int(math.ceil(math.log2(N)))
    rsa = _make_rsa_bloq(N, g)
    gc = _get_gate_costs(rsa)
    totals = gc.total_t_and_ccz_count(ts_per_rotation=0)

    actual = results[str(N)]['algorithm_costs']
    assert int(actual['n_t']) == int(totals['n_t']), (
        f"N={N}: wrong n_t: got {actual['n_t']}, expected {int(totals['n_t'])}"
    )
    assert int(actual['n_ccz']) == int(totals['n_ccz']), (
        f"N={N}: wrong n_ccz: got {actual['n_ccz']}, expected {int(totals['n_ccz'])}"
    )
    assert int(actual['algo_qubits']) == 3 * n, (
        f"N={N}: wrong algo_qubits: got {actual['algo_qubits']}, expected {3 * n}"
    )
    assert int(actual['bitsize']) == n, (
        f"N={N}: wrong bitsize: got {actual['bitsize']}, expected {n}"
    )


# ── Pareto Frontier ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "target", RSA_TARGETS,
    ids=[str(t['modulus']) for t in RSA_TARGETS]
)
def test_pareto_frontier_correctness(results, target):
    """Pareto points must exactly match independent computation."""
    N, g = target['modulus'], target['base']
    rsa = _make_rsa_bloq(N, g)
    gc = _get_gate_costs(rsa)
    algo = _make_algo_summary(N, gc)

    all_configs = _compute_all_configs(algo)
    expected_pareto = _extract_pareto(all_configs)
    actual_pareto = results[str(N)]['pareto_frontier']

    assert len(actual_pareto) == len(expected_pareto), (
        f"N={N}: expected {len(expected_pareto)} Pareto points, "
        f"got {len(actual_pareto)}"
    )

    sort_key = lambda x: (x['phys_qubits'], x['error'], x['model'], x['code_distance'])
    actual_sorted = sorted(actual_pareto, key=sort_key)
    expected_sorted = sorted(expected_pareto, key=sort_key)

    for a, e in zip(actual_sorted, expected_sorted):
        assert a['model'] == e['model'], (
            f"N={N}: model mismatch at phys_qubits={e['phys_qubits']}: "
            f"got {a['model']}, expected {e['model']}"
        )
        assert a['code_distance'] == e['code_distance'], (
            f"N={N}: code_distance mismatch: "
            f"got {a['code_distance']}, expected {e['code_distance']}"
        )
        assert int(a['phys_qubits']) == e['phys_qubits'], (
            f"N={N}: phys_qubits mismatch: "
            f"got {a['phys_qubits']}, expected {e['phys_qubits']}"
        )
        assert float(a['error']) == pytest.approx(e['error'], rel=1e-4), (
            f"N={N}: error mismatch at d={e['code_distance']}"
        )
        assert float(a['duration_hr']) == pytest.approx(e['duration_hr'], rel=1e-4), (
            f"N={N}: duration_hr mismatch at d={e['code_distance']}"
        )


@pytest.mark.parametrize(
    "target", RSA_TARGETS,
    ids=[str(t['modulus']) for t in RSA_TARGETS]
)
def test_pareto_sorted_ascending(results, target):
    """Pareto frontier must be sorted by ascending phys_qubits."""
    pareto = results[str(target['modulus'])]['pareto_frontier']
    for i in range(len(pareto) - 1):
        assert pareto[i]['phys_qubits'] <= pareto[i + 1]['phys_qubits'], (
            f"Pareto frontier not sorted at index {i}"
        )


@pytest.mark.parametrize(
    "target", RSA_TARGETS,
    ids=[str(t['modulus']) for t in RSA_TARGETS]
)
def test_pareto_no_dominated_points(results, target):
    """No point in the frontier may be dominated by another."""
    pareto = results[str(target['modulus'])]['pareto_frontier']
    for i, a in enumerate(pareto):
        for j, b in enumerate(pareto):
            if i == j:
                continue
            assert not (
                b['phys_qubits'] <= a['phys_qubits'] and
                b['error'] <= a['error'] and
                (b['phys_qubits'] < a['phys_qubits'] or b['error'] < a['error'])
            ), (
                f"Point {i} ({a['model']} d={a['code_distance']}) "
                f"is dominated by point {j} ({b['model']} d={b['code_distance']})"
            )


# ── Recommended Config ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "target", RSA_TARGETS,
    ids=[str(t['modulus']) for t in RSA_TARGETS]
)
def test_recommended_config(results, target):
    """Recommended config must be the min-qubit feasible configuration."""
    N, g = target['modulus'], target['base']
    rsa = _make_rsa_bloq(N, g)
    gc = _get_gate_costs(rsa)
    algo = _make_algo_summary(N, gc)

    all_configs = _compute_all_configs(algo)
    expected_rec = _find_recommended(all_configs)

    actual_rec = results[str(N)]['recommended_config']

    if expected_rec is None:
        assert actual_rec is None, (
            f"N={N}: expected null recommended_config but got {actual_rec}"
        )
    else:
        assert actual_rec is not None, (
            f"N={N}: expected non-null recommended_config"
        )
        assert int(actual_rec['phys_qubits']) == expected_rec['phys_qubits'], (
            f"N={N}: wrong recommended phys_qubits: "
            f"got {actual_rec['phys_qubits']}, expected {expected_rec['phys_qubits']}"
        )
        assert actual_rec['model'] == expected_rec['model'], (
            f"N={N}: wrong recommended model"
        )
        assert actual_rec['code_distance'] == expected_rec['code_distance'], (
            f"N={N}: wrong recommended code_distance"
        )
        assert float(actual_rec['error']) < ERROR_BUDGET, (
            f"N={N}: recommended error {actual_rec['error']} >= budget {ERROR_BUDGET}"
        )
        assert float(actual_rec['duration_hr']) < MAX_DURATION_HR, (
            f"N={N}: recommended duration {actual_rec['duration_hr']} >= "
            f"max {MAX_DURATION_HR}"
        )


# ── Scaling Analysis ───────────────────────────────────────────────────


def test_scaling_toffoli_counts(results):
    """Symbolic Toffoli counts at each bitsize must match."""
    from qualtran.bloqs.cryptography.rsa import RSAPhaseEstimate
    from qualtran.resource_counting import get_cost_value, QECGatesCost

    n_sym, p_sym, g_sym = sympy.symbols('n p g')
    rsa_sym = RSAPhaseEstimate(n=n_sym, mod=p_sym, base=g_sym)
    gc_sym = get_cost_value(rsa_sym, QECGatesCost())
    totals = gc_sym.total_t_and_ccz_count(ts_per_rotation=0)
    toffoli_expr = totals['n_ccz']

    actual_scaling = results['scaling']['toffoli_counts']

    for nv in SCALING_BITSIZES:
        val = sympy.sympify(toffoli_expr).subs(n_sym, nv)
        for s in list(val.free_symbols):
            val = val.subs(s, 1)
        expected = int(val)

        assert str(nv) in actual_scaling, (
            f"Missing n={nv} in scaling.toffoli_counts"
        )
        assert int(actual_scaling[str(nv)]) == expected, (
            f"Wrong Toffoli at n={nv}: got {actual_scaling[str(nv)]}, "
            f"expected {expected}"
        )


def test_scaling_fit(results):
    """Power-law fit parameters must match log-log OLS regression."""
    scaling = results['scaling']
    toffoli_counts = scaling['toffoli_counts']

    ns = np.array(SCALING_BITSIZES, dtype=float)
    ts = np.array(
        [int(toffoli_counts[str(nv)]) for nv in SCALING_BITSIZES],
        dtype=float,
    )

    log_n = np.log(ns)
    log_t = np.log(ts)
    coeffs = np.polyfit(log_n, log_t, 1)
    expected_b = float(coeffs[0])
    expected_a = float(np.exp(coeffs[1]))
    expected_pred = int(round(expected_a * 2048 ** expected_b))

    assert float(scaling['fit_exponent']) == pytest.approx(
        expected_b, abs=0.05
    ), (
        f"fit_exponent: got {scaling['fit_exponent']}, "
        f"expected ~{expected_b:.4f}"
    )
    assert float(scaling['fit_coefficient']) == pytest.approx(
        expected_a, rel=0.15
    ), (
        f"fit_coefficient: got {scaling['fit_coefficient']}, "
        f"expected ~{expected_a:.4f}"
    )
    assert int(scaling['predicted_2048']) == pytest.approx(
        expected_pred, rel=0.15
    ), (
        f"predicted_2048: got {scaling['predicted_2048']}, "
        f"expected ~{expected_pred}"
    )


def test_scaling_monotonic(results):
    """Toffoli counts must strictly increase with bitsize."""
    toffoli_counts = results['scaling']['toffoli_counts']
    values = [int(toffoli_counts[str(nv)]) for nv in SCALING_BITSIZES]
    for i in range(len(values) - 1):
        assert values[i] < values[i + 1], (
            f"Not monotonic: n={SCALING_BITSIZES[i]}->{values[i]}, "
            f"n={SCALING_BITSIZES[i + 1]}->{values[i + 1]}"
        )


def test_scaling_prediction_positive(results):
    """Predicted Toffoli count at n=2048 must be a positive integer."""
    pred = results['scaling']['predicted_2048']
    assert int(pred) > 0, f"predicted_2048 must be positive, got {pred}"
