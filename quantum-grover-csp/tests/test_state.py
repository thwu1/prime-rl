
import json
import sys
import math
import pytest

sys.path.insert(0, '/app')


def load_problem():
    with open('/app/problem.json') as f:
        return json.load(f)


def classical_satisfies(x, n, parity_constraints, target_weight):
    """Check if integer x (interpreted as n-bit string) satisfies all constraints."""
    bits = [(x >> i) & 1 for i in range(n)]
    for c in parity_constraints:
        parity = sum(bits[v] for v in c['variables']) % 2
        if parity != c['target']:
            return False
    return sum(bits) == target_weight


def expected_solutions(problem):
    """Compute all solutions classically."""
    n = problem['n']
    solutions = []
    for x in range(2 ** n):
        if classical_satisfies(x, n, problem['parity_constraints'], problem['target_weight']):
            bits = [(x >> i) & 1 for i in range(n)]
            solutions.append(''.join(str(b) for b in bits))
    return sorted(solutions)


class TestMarkingOracle:
    """Verify the marking oracle on all 2^n computational basis states."""

    def test_oracle_returns_circuit(self):
        from quantum_solver import build_marking_oracle
        problem = load_problem()
        oracle = build_marking_oracle(
            problem['n'],
            problem['parity_constraints'],
            problem['target_weight']
        )
        assert oracle.num_qubits >= problem['n'] + 1, \
            "Oracle must have at least n data qubits + 1 target qubit"

    @pytest.mark.parametrize("x", range(64))
    def test_oracle_on_input(self, x):
        """For each basis state |x>, verify oracle flips target iff x satisfies constraints,
        leaves data qubits unchanged, and returns ancillas to |0>."""
        from qiskit import QuantumCircuit, transpile
        from qiskit_aer import AerSimulator

        from quantum_solver import build_marking_oracle

        problem = load_problem()
        n = problem['n']
        oracle = build_marking_oracle(
            n, problem['parity_constraints'], problem['target_weight']
        )
        total_qubits = oracle.num_qubits
        target_idx = total_qubits - 1

        expected = classical_satisfies(
            x, n, problem['parity_constraints'], problem['target_weight']
        )

        # Build verification circuit
        circ = QuantumCircuit(total_qubits)

        # Prepare input on data qubits
        for i in range(n):
            if (x >> i) & 1:
                circ.x(i)

        # Apply oracle
        circ.compose(oracle, inplace=True)

        # If oracle should have flipped target, undo that flip
        if expected:
            circ.x(target_idx)

        # Undo input preparation
        for i in range(n):
            if (x >> i) & 1:
                circ.x(i)

        # Now entire state should be |0...0>
        circ.save_statevector()
        simulator = AerSimulator(method='statevector')
        result = simulator.run(transpile(circ, backend=simulator)).result()
        sv = result.get_statevector().data

        assert abs(sv[0]) > 0.999, (
            f"Oracle incorrect for input x={x} "
            f"(bits={''.join(str((x>>i)&1) for i in range(n))}): "
            f"expected {'SAT' if expected else 'UNSAT'}, "
            f"but state is not |0...0> after undo"
        )


class TestSolutions:
    """Verify the solutions.json output file."""

    def test_solutions_file_exists(self):
        with open('/app/solutions.json') as f:
            solutions = json.load(f)
        assert isinstance(solutions, list), "solutions.json must contain a JSON array"

    def test_each_solution_satisfies_constraints(self):
        problem = load_problem()
        n = problem['n']

        with open('/app/solutions.json') as f:
            solutions = json.load(f)

        for sol in solutions:
            assert len(sol) == n, f"Solution '{sol}' has wrong length"
            bits = [int(c) for c in sol]
            for c in problem['parity_constraints']:
                parity = sum(bits[v] for v in c['variables']) % 2
                assert parity == c['target'], (
                    f"Solution {sol} fails parity constraint {c}"
                )
            assert sum(bits) == problem['target_weight'], (
                f"Solution {sol} has Hamming weight {sum(bits)}, "
                f"expected {problem['target_weight']}"
            )

    def test_solutions_complete_and_correct(self):
        problem = load_problem()
        expected = expected_solutions(problem)

        with open('/app/solutions.json') as f:
            actual = json.load(f)

        assert sorted(actual) == expected, (
            f"Solutions mismatch.\n"
            f"Expected: {expected}\n"
            f"Got:      {sorted(actual)}"
        )

    def test_solution_count(self):
        problem = load_problem()
        expected = expected_solutions(problem)

        with open('/app/solutions.json') as f:
            actual = json.load(f)

        assert len(actual) == len(expected), (
            f"Expected {len(expected)} solutions, got {len(actual)}"
        )
