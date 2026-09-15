#!/usr/bin/env python3
"""
Surface code resource planner for quantum factoring.
Reads /app/targets.json, should produce /app/deployment_plan.json.

STATUS: Incomplete — crashes on AlgorithmSummary construction;
        only evaluates a single cost model and distance;
        missing Pareto analysis, recommendation, and scaling.
"""

import json
import math

from qualtran.bloqs.cryptography.rsa import RSAPhaseEstimate
from qualtran.resource_counting import get_cost_value, QECGatesCost
from qualtran.surface_code import AlgorithmSummary, PhysicalCostModel


def main():
    with open('/app/targets.json') as f:
        targets = json.load(f)

    results = {}

    for target in targets['rsa_targets']:
        N = target['modulus']
        g = target['base']
        n = int(math.ceil(math.log2(N)))

        rsa = RSAPhaseEstimate.make_for_shor(big_n=N, g=g)

        # Gate costs
        gc = get_cost_value(rsa, QECGatesCost())
        totals = gc.total_t_and_ccz_count(ts_per_rotation=0)

        # Derive algorithm summary from the bloq directly
        algo = AlgorithmSummary.from_bloq(rsa)

        # Evaluate a single configuration
        model = PhysicalCostModel.make_beverland_et_al(data_d=17)

        results[str(N)] = {
            'algorithm_costs': {
                'n_t': int(totals['n_t']),
                'n_ccz': int(totals['n_ccz']),
                'algo_qubits': int(algo.n_algo_qubits),
                'bitsize': n,
            },
            'phys_qubits': int(model.n_phys_qubits(algo)),
            'error': float(model.error(algo)),
            'duration_hr': float(model.duration_hr(algo)),
        }

    with open('/app/deployment_plan.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Done.")


if __name__ == '__main__':
    main()
