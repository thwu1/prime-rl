#!/usr/bin/env python3
"""
Quantum Constraint Satisfaction Solver using Grover's Algorithm.

Finds all binary strings of length n satisfying a set of GF(2) parity
constraints and a Hamming weight constraint via Grover's quantum search.
"""

import json
import math
from qiskit import QuantumCircuit, transpile
from qiskit_aer import AerSimulator


def build_marking_oracle(n, parity_constraints, target_weight):
    """
    Build a marking oracle for combined parity + Hamming weight constraints.

    Qubit layout (total = n + n_parity + n_counter + 1 + 1):
      [0 .. n-1]                           data qubits
      [n .. n+p-1]                          parity constraint ancillas
      [n+p .. n+p+k-1]                      binary counter for popcount
      [n+p+k]                               weight comparison ancilla
      [n+p+k+1]                             target qubit (last)

    All ancillas are returned to |0> after the oracle acts.
    """
    n_parity = len(parity_constraints)
    n_counter = math.ceil(math.log2(n + 1))

    total = n + n_parity + n_counter + 1 + 1

    data = list(range(n))
    par_anc = list(range(n, n + n_parity))
    counter = list(range(n + n_parity, n + n_parity + n_counter))
    w_anc = n + n_parity + n_counter
    target = total - 1

    # ---- Sub-circuit: parity constraint computation ----
    # For each constraint, XOR the specified variables into an ancilla.
    # After adjustment, ancilla = 1 iff constraint is satisfied.
    parity_sub = QuantumCircuit(total, name='parity')
    for i, c in enumerate(parity_constraints):
        for v in c['variables']:
            parity_sub.cx(data[v], par_anc[i])
        if c['target'] == 0:
            parity_sub.x(par_anc[i])

    # ---- Sub-circuit: popcount via controlled increment ----
    # Add each data bit to a binary counter register.
    # Controlled increment processes MSB-to-LSB to propagate carries correctly.
    popcount_sub = QuantumCircuit(total, name='popcount')
    k = len(counter)
    for d in range(n):
        for j in range(k - 1, 0, -1):
            controls = [data[d]] + counter[:j]
            popcount_sub.mcx(controls, counter[j])
        popcount_sub.cx(data[d], counter[0])

    # ---- Sub-circuit: compare counter to target weight ----
    # Flip counter bits where the target weight bit is 0 so that
    # counter == target_weight iff all counter bits are 1 after flip.
    # Then MCX into w_anc, then undo the flips.
    compare_sub = QuantumCircuit(total, name='compare')
    weight_bits = [(target_weight >> i) & 1 for i in range(n_counter)]
    for i in range(n_counter):
        if weight_bits[i] == 0:
            compare_sub.x(counter[i])
    compare_sub.mcx(counter, w_anc)
    for i in range(n_counter):
        if weight_bits[i] == 0:
            compare_sub.x(counter[i])

    # ---- Compose full oracle ----
    circ = QuantumCircuit(total)
    circ.compose(parity_sub, inplace=True)
    circ.compose(popcount_sub, inplace=True)
    circ.compose(compare_sub, inplace=True)

    # AND all constraint results into target qubit
    all_anc = par_anc + [w_anc]
    circ.mcx(all_anc, target)

    # Uncompute ancillas (reverse order)
    circ.compose(compare_sub.inverse(), inplace=True)
    circ.compose(popcount_sub.inverse(), inplace=True)
    circ.compose(parity_sub.inverse(), inplace=True)

    return circ


def build_phase_oracle(marking_oracle):
    """Convert a marking oracle to a phase oracle using phase kickback."""
    total = marking_oracle.num_qubits
    target = total - 1

    circ = QuantumCircuit(total)
    circ.x(target)
    circ.h(target)
    circ.compose(marking_oracle, inplace=True)
    circ.h(target)
    circ.x(target)
    return circ


def build_diffusion(n):
    """Grover diffusion operator on n qubits (reflection about |+>^n)."""
    circ = QuantumCircuit(n)
    circ.h(range(n))
    circ.x(range(n))
    circ.h(n - 1)
    circ.mcx(list(range(n - 1)), n - 1)
    circ.h(n - 1)
    circ.x(range(n))
    circ.h(range(n))
    return circ


def grover_search(n, marking_oracle, n_iterations, shots=8192):
    """Run Grover's search and return measurement counts."""
    total = marking_oracle.num_qubits

    phase_or = build_phase_oracle(marking_oracle)
    diff = build_diffusion(n)

    circ = QuantumCircuit(total, n)
    circ.h(range(n))

    for _ in range(n_iterations):
        circ.compose(phase_or, inplace=True)
        circ.compose(diff, range(n), inplace=True)

    circ.measure(range(n), range(n))

    simulator = AerSimulator(method='statevector')
    compiled = transpile(circ, backend=simulator)
    result = simulator.run(compiled, shots=shots).result()
    return result.get_counts()


def classical_check(bits_str, parity_constraints, target_weight):
    """Classically verify if a binary string satisfies all constraints."""
    bits = [int(c) for c in bits_str]
    for c in parity_constraints:
        parity = sum(bits[v] for v in c['variables']) % 2
        if parity != c['target']:
            return False
    return sum(bits) == target_weight


def solve(problem_path):
    """Solve the CSP and return the sorted list of solution strings."""
    with open(problem_path) as f:
        problem = json.load(f)

    n = problem['n']
    parity_constraints = problem['parity_constraints']
    target_weight = problem['target_weight']

    # Count solutions classically to determine optimal Grover iterations
    n_solutions = 0
    for x in range(2 ** n):
        bits = ''.join(str((x >> i) & 1) for i in range(n))
        if classical_check(bits, parity_constraints, target_weight):
            n_solutions += 1

    if n_solutions == 0:
        return []

    theta = math.asin(math.sqrt(n_solutions / (2 ** n)))
    n_iterations = max(1, round(math.pi / (4 * theta)))

    # Build oracle and run Grover's search
    oracle = build_marking_oracle(n, parity_constraints, target_weight)
    counts = grover_search(n, oracle, n_iterations, shots=8192)

    # Collect and verify solutions from measurement results.
    # Qiskit returns bit strings in big-endian order (rightmost char = qubit 0),
    # so reverse each string to get our convention (position i = variable x_i).
    solutions = set()
    for bitstring in counts:
        candidate = bitstring[::-1]
        if classical_check(candidate, parity_constraints, target_weight):
            solutions.add(candidate)

    return sorted(solutions)


if __name__ == '__main__':
    solutions = solve('/app/problem.json')
    with open('/app/solutions.json', 'w') as f:
        json.dump(solutions, f)
    print(f"Found {len(solutions)} solutions: {solutions}")
