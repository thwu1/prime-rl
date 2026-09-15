#!/usr/bin/env python3


"""
Fault-tolerant resource estimation for Shor's RSA factoring
using the Qualtran quantum computing library.

Produces /app/results.json with call graph, gate costs, algorithm qubit count,
physical cost sweep, and symbolic scaling analysis.

Key fixes applied to the original /app/estimate.py:
1. AlgorithmSummary.from_bloq() fails on RSAPhaseEstimate because
   QubitCount() cannot decompose bloqs with MeasureQFT/Free classical outputs.
   Fix: construct AlgorithmSummary manually from register analysis + gate costs.
2. Algorithm qubit count must be 3*n (2n exponent + n work register), not 2*n.
3. ts_per_rotation must be 0 for intrinsic gate counting (no rotation synthesis).
4. Remaining free symbolic parameters (p, g) must be substituted with 1.
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


def compute_gate_costs(gc_raw):
    """Extract T-gate and Toffoli/CCZ counts from a GateCounts object."""
    totals = gc_raw.total_t_and_ccz_count(ts_per_rotation=0)
    return {"n_t": int(totals['n_t']), "n_ccz": int(totals['n_ccz'])}


def compute_algo_qubits(big_n):
    """Compute algorithm qubit count from register structure.

    RSAPhaseEstimate allocates:
      - 2n qubits for the exponent register (PlusState)
      - n qubits for the work register (IntState)
    where n = ceil(log2(N)).
    """
    n = int(math.ceil(math.log2(big_n)))
    return 3 * n


def compute_physical_costs(gc_raw, algo_qubits):
    """Sweep surface code distances and compute physical costs.

    Constructs AlgorithmSummary manually (bypassing from_bloq which fails
    on RSAPhaseEstimate due to QubitCount decomposition error).
    """
    algo = AlgorithmSummary(n_algo_qubits=algo_qubits, n_logical_gates=gc_raw)
    physical_costs = {}
    min_safe_distance = None

    for d in CODE_DISTANCES:
        model = PhysicalCostModel.make_beverland_et_al(data_d=d)
        entry = {
            'phys_qubits': int(model.n_phys_qubits(algo)),
            'error': float(model.error(algo)),
            'duration_hr': float(model.duration_hr(algo)),
        }
        physical_costs[str(d)] = entry
        if min_safe_distance is None and entry['error'] < 0.01:
            min_safe_distance = d

    return physical_costs, min_safe_distance


def compute_symbolic_scaling():
    """Evaluate symbolic Toffoli count at specific bitsize values."""
    n, p, g = sympy.symbols('n p g')
    rsa_sym = RSAPhaseEstimate(n=n, mod=p, base=g)
    gc_sym = get_cost_value(rsa_sym, QECGatesCost())
    totals = gc_sym.total_t_and_ccz_count(ts_per_rotation=0)
    toffoli_expr = totals['n_ccz']

    scaling = {}
    for nv in SYMBOLIC_N_VALUES:
        val = sympy.sympify(toffoli_expr).subs(n, nv)
        for s in list(val.free_symbols):
            val = val.subs(s, 1)
        scaling[str(nv)] = int(val)
    return scaling


def main():
    print("Constructing RSAPhaseEstimate for N=221, g=9 ...")
    rsa = RSAPhaseEstimate.make_for_shor(big_n=BIG_N, g=BASE_G)

    print("Computing call graph ...")
    call_graph = compute_call_graph(rsa)

    print("Computing gate costs ...")
    gc_raw = get_cost_value(rsa, QECGatesCost())
    gate_costs = compute_gate_costs(gc_raw)

    print("Computing algorithm qubits ...")
    algo_qubits = compute_algo_qubits(BIG_N)

    print("Computing physical costs ...")
    physical_costs, min_safe_distance = compute_physical_costs(gc_raw, algo_qubits)

    print("Computing symbolic scaling ...")
    symbolic_scaling = compute_symbolic_scaling()

    results = {
        'call_graph': call_graph,
        'gate_costs': gate_costs,
        'algo_qubits': algo_qubits,
        'physical_costs': physical_costs,
        'min_safe_distance': min_safe_distance,
        'symbolic_scaling': symbolic_scaling,
    }

    with open('/app/results.json', 'w') as f:
        json.dump(results, f, indent=2)

    print("Results written to /app/results.json")
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
