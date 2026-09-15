#!/usr/bin/env python3


"""
Surface code deployment planner for quantum RSA factoring.
Reads /app/targets.json, produces /app/deployment_plan.json.

Fixes in the skeleton /app/analyze.py:
1. AlgorithmSummary.from_bloq(rsa) crashes because QubitCount cannot
   decompose RSAPhaseEstimate (MeasureQFT/Free have classical outputs).
   Solution: construct AlgorithmSummary manually with n_algo_qubits=3*n
   (2n exponent PlusState + n work IntState register).
2. Extends single-model evaluation to all 4 cost models across all code
   distances specified in targets.json.
3. Creates Pareto frontier extraction via pairwise dominance on
   (phys_qubits, error).
4. Designs constrained optimization for recommended_config (min phys_qubits
   subject to error < budget and duration < max).
5. Creates symbolic scaling analysis with power-law fitting.
"""

import json
import math
import numpy as np
import sympy

from qualtran.bloqs.cryptography.rsa import RSAPhaseEstimate
from qualtran.resource_counting import get_cost_value, QECGatesCost
from qualtran.surface_code import AlgorithmSummary, PhysicalCostModel


def compute_algo_costs(N, g):
    """Compute algorithm-level costs for a given RSA modulus and base."""
    n = int(math.ceil(math.log2(N)))
    rsa = RSAPhaseEstimate.make_for_shor(big_n=N, g=g)
    gc = get_cost_value(rsa, QECGatesCost())
    totals = gc.total_t_and_ccz_count(ts_per_rotation=0)
    return {
        'n_t': int(totals['n_t']),
        'n_ccz': int(totals['n_ccz']),
        'algo_qubits': 3 * n,
        'bitsize': n,
    }, gc


def evaluate_config(algo_summary, model_info, d):
    """Evaluate a single (cost_model, code_distance) configuration."""
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


def extract_pareto(configs):
    """Extract non-dominated points on the (phys_qubits, error) plane.

    Point A dominates B iff A.phys_qubits <= B.phys_qubits AND
    A.error <= B.error, with at least one strict inequality.
    """
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


def find_recommended(configs, error_budget, max_duration_hr):
    """Find minimum-phys_qubits config meeting error and duration budgets."""
    feasible = [
        c for c in configs
        if c['error'] < error_budget and c['duration_hr'] < max_duration_hr
    ]
    if not feasible:
        return None
    return min(feasible, key=lambda c: c['phys_qubits'])


def compute_scaling(bitsizes):
    """Compute symbolic Toffoli scaling and fit a power law."""
    n_sym, p_sym, g_sym = sympy.symbols('n p g')
    rsa_sym = RSAPhaseEstimate(n=n_sym, mod=p_sym, base=g_sym)
    gc_sym = get_cost_value(rsa_sym, QECGatesCost())
    totals = gc_sym.total_t_and_ccz_count(ts_per_rotation=0)
    toffoli_expr = totals['n_ccz']

    toffoli_counts = {}
    for nv in bitsizes:
        val = sympy.sympify(toffoli_expr).subs(n_sym, nv)
        for s in list(val.free_symbols):
            val = val.subs(s, 1)
        toffoli_counts[str(nv)] = int(val)

    ns = np.array(bitsizes, dtype=float)
    ts = np.array([toffoli_counts[str(nv)] for nv in bitsizes], dtype=float)
    log_n = np.log(ns)
    log_t = np.log(ts)
    coeffs = np.polyfit(log_n, log_t, 1)
    b = float(coeffs[0])
    a = float(np.exp(coeffs[1]))
    predicted_2048 = int(round(a * 2048 ** b))

    return {
        'toffoli_counts': toffoli_counts,
        'fit_exponent': b,
        'fit_coefficient': a,
        'predicted_2048': predicted_2048,
    }


def main():
    with open('/app/targets.json') as f:
        targets = json.load(f)

    error_budget = targets['error_budget']
    max_duration_hr = targets['max_duration_hr']
    code_distances = targets['code_distances']
    cost_models = targets['cost_models']
    scaling_bitsizes = targets['scaling_bitsizes']

    results = {}

    for target in targets['rsa_targets']:
        N = target['modulus']
        g = target['base']
        print(f"Processing N={N}, g={g} ...")

        algo_costs, gc = compute_algo_costs(N, g)

        algo_summary = AlgorithmSummary(
            n_algo_qubits=algo_costs['algo_qubits'],
            n_logical_gates=gc,
        )

        all_configs = []
        for d in code_distances:
            for m in cost_models:
                cfg = evaluate_config(algo_summary, m, d)
                all_configs.append(cfg)

        pareto = extract_pareto(all_configs)
        recommended = find_recommended(all_configs, error_budget, max_duration_hr)

        results[str(N)] = {
            'algorithm_costs': algo_costs,
            'pareto_frontier': pareto,
            'recommended_config': recommended,
        }

    print("Computing scaling analysis ...")
    results['scaling'] = compute_scaling(scaling_bitsizes)

    with open('/app/deployment_plan.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("Done. Deployment plan written to /app/deployment_plan.json")


if __name__ == '__main__':
    main()
