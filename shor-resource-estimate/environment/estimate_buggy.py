#!/usr/bin/env python3


"""
Fault-tolerant resource estimation for Shor's RSA factoring using Qualtran.
Produces /app/results.json with call graph, gate costs, qubit counts,
physical estimates, and symbolic scaling.
"""

import json
import math
import sympy

from qualtran.bloqs.cryptography.rsa import RSAPhaseEstimate
from qualtran.resource_counting import get_cost_value, QECGatesCost
from qualtran.surface_code import AlgorithmSummary, PhysicalCostModel

BIG_N = 221       # = 13 * 17
BASE_G = 9
CODE_DISTANCES = [9, 13, 17, 21, 25, 29]
SYMBOLIC_N_VALUES = [4, 8, 16, 32]


def compute_call_graph(rsa):
    """Extract the depth-1 call graph, aggregated by class name."""
    _, sigma = rsa.call_graph(max_depth=1)
    call_graph = {}
    for bloq_inst, count in sigma.items():
        name = type(bloq_inst).__name__
        call_graph[name] = call_graph.get(name, 0) + int(count)
    return call_graph


def compute_gate_costs(rsa):
    """Compute QEC gate costs for the circuit."""
    gc = get_cost_value(rsa, QECGatesCost())
    # Standard rotation synthesis approximation for gate totals
    totals = gc.total_t_and_ccz_count(ts_per_rotation=10)
    return {"n_t": int(totals['n_t']), "n_ccz": int(totals['n_ccz'])}, gc


def compute_algo_qubits(big_n):
    """Compute algorithm qubit count from the phase estimation structure.

    The exponent register uses 2*ceil(log2(N)) qubits for the
    quantum phase estimation superposition.
    """
    n = int(math.ceil(math.log2(big_n)))
    return 2 * n


def compute_physical_costs(rsa, gc_raw, algo_qubits):
    """Compute surface-code physical costs via Beverland et al. model."""
    # Derive algorithm summary directly from the bloq for convenience
    algo = AlgorithmSummary.from_bloq(rsa)

    physical_costs = {}
    min_safe = None
    for d in CODE_DISTANCES:
        model = PhysicalCostModel.make_beverland_et_al(data_d=d)
        entry = {
            'phys_qubits': int(model.n_phys_qubits(algo)),
            'error': float(model.error(algo)),
            'duration_hr': float(model.duration_hr(algo)),
        }
        physical_costs[str(d)] = entry
        if min_safe is None and entry['error'] < 0.01:
            min_safe = d
    return physical_costs, min_safe


def compute_symbolic_scaling():
    """Evaluate symbolic Toffoli/CCZ count at specific bitsizes."""
    n, p, g = sympy.symbols('n p g')
    rsa_sym = RSAPhaseEstimate(n=n, mod=p, base=g)
    gc_sym = get_cost_value(rsa_sym, QECGatesCost())
    totals = gc_sym.total_t_and_ccz_count(ts_per_rotation=0)
    toffoli_expr = totals['n_ccz']

    scaling = {}
    for nv in SYMBOLIC_N_VALUES:
        val = sympy.sympify(toffoli_expr).subs(n, nv)
        scaling[str(nv)] = int(val)
    return scaling


def main():
    print("Constructing RSAPhaseEstimate for N=221, g=9 ...")
    rsa = RSAPhaseEstimate.make_for_shor(big_n=BIG_N, g=BASE_G)

    print("Computing call graph ...")
    call_graph = compute_call_graph(rsa)

    print("Computing gate costs ...")
    gate_costs, gc_raw = compute_gate_costs(rsa)

    print("Computing algorithm qubits ...")
    algo_qubits = compute_algo_qubits(BIG_N)

    print("Computing physical costs ...")
    physical_costs, min_safe = compute_physical_costs(rsa, gc_raw, algo_qubits)

    print("Computing symbolic scaling ...")
    symbolic_scaling = compute_symbolic_scaling()

    results = {
        'call_graph': call_graph,
        'gate_costs': gate_costs,
        'algo_qubits': algo_qubits,
        'physical_costs': physical_costs,
        'min_safe_distance': min_safe,
        'symbolic_scaling': symbolic_scaling,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)
    print("Done. Results written to /app/results.json")


if __name__ == '__main__':
    main()
