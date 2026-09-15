
import json
import os
import pytest
import stim


CODES_PATH = "/app/codes.json"
RESULTS_PATH = "/app/results.json"
MAX_TOTAL_TWO_QUBIT = 45
ALLOWED_GATES = {"H", "S", "X", "Z", "CX", "CZ", "SWAP", "TICK",
                 "QUBIT_COORDS", "SHIFT_COORDS", "DETECTOR", "OBSERVABLE_INCLUDE",
                 "I"}


def load_codes():
    with open(CODES_PATH) as f:
        return json.load(f)["codes"]


def load_results():
    with open(RESULTS_PATH) as f:
        return json.load(f)


def count_two_qubit_gates(circuit_str: str) -> int:
    circ = stim.Circuit(circuit_str)
    count = 0
    for inst in circ:
        if inst.name in ("CX", "CZ", "SWAP"):
            targets = [t.value for t in inst.targets_copy() if t.is_qubit_target]
            count += len(targets) // 2
    return count


def check_stabilizers(circuit_str: str, stabilizers: list[str], n: int) -> dict[str, bool]:
    circ = stim.Circuit(circuit_str)
    sim = stim.TableauSimulator()
    sim.do(circ)
    results = {}
    for s in stabilizers:
        pauli = stim.PauliString(s + "I" * (n - len(s)))
        expectation = sim.peek_observable_expectation(pauli)
        results[s] = expectation > 0
    return results


def get_used_gates(circuit_str: str) -> set[str]:
    circ = stim.Circuit(circuit_str)
    gates = set()
    for inst in circ:
        gates.add(inst.name)
    return gates


class TestResultsExist:
    def test_results_file_exists(self):
        assert os.path.isfile(RESULTS_PATH), (
            f"{RESULTS_PATH} does not exist"
        )

    def test_results_valid_json(self):
        results = load_results()
        assert "circuits" in results, "results.json must have a 'circuits' key"

    def test_all_codes_present(self):
        codes = load_codes()
        results = load_results()
        for code in codes:
            assert code["name"] in results["circuits"], (
                f"Missing circuit for {code['name']} in results"
            )


class TestCircuitValidity:
    @pytest.fixture(params=[c["name"] for c in load_codes()])
    def code_and_circuit(self, request):
        codes = {c["name"]: c for c in load_codes()}
        results = load_results()
        name = request.param
        code = codes[name]
        circuit_str = results["circuits"][name]
        return code, circuit_str

    def test_circuit_parses(self, code_and_circuit):
        code, circuit_str = code_and_circuit
        try:
            stim.Circuit(circuit_str)
        except Exception as e:
            pytest.fail(
                f"Circuit for {code['name']} does not parse as valid Stim: {e}"
            )

    def test_correct_qubit_count(self, code_and_circuit):
        code, circuit_str = code_and_circuit
        circ = stim.Circuit(circuit_str)
        assert circ.num_qubits <= code["n"], (
            f"Circuit for {code['name']} uses {circ.num_qubits} qubits, "
            f"expected at most {code['n']}"
        )

    def test_only_clifford_gates(self, code_and_circuit):
        code, circuit_str = code_and_circuit
        gates = get_used_gates(circuit_str)
        disallowed = gates - ALLOWED_GATES
        assert not disallowed, (
            f"Circuit for {code['name']} uses disallowed gates: {disallowed}"
        )


class TestStabilizerPreservation:
    @pytest.fixture(params=[c["name"] for c in load_codes()])
    def code_and_circuit(self, request):
        codes = {c["name"]: c for c in load_codes()}
        results = load_results()
        name = request.param
        code = codes[name]
        circuit_str = results["circuits"][name]
        return code, circuit_str

    def test_all_stabilizers_preserved(self, code_and_circuit):
        code, circuit_str = code_and_circuit
        stab_results = check_stabilizers(circuit_str, code["stabilizers"], code["n"])
        failed = [s for s, ok in stab_results.items() if not ok]
        assert not failed, (
            f"Circuit for {code['name']} fails to preserve stabilizers: {failed}"
        )


class TestOptimization:
    @pytest.fixture(params=[c["name"] for c in load_codes()])
    def code_and_circuit(self, request):
        codes = {c["name"]: c for c in load_codes()}
        results = load_results()
        name = request.param
        code = codes[name]
        circuit_str = results["circuits"][name]
        return code, circuit_str

    def test_strictly_fewer_two_qubit_gates(self, code_and_circuit):
        code, circuit_str = code_and_circuit
        opt_count = count_two_qubit_gates(circuit_str)
        baseline = code["baseline_two_qubit_gates"]
        assert opt_count < baseline, (
            f"Circuit for {code['name']}: optimized has {opt_count} 2q gates, "
            f"baseline has {baseline}. Must be strictly fewer."
        )

    def test_total_two_qubit_gate_budget(self):
        codes = {c["name"]: c for c in load_codes()}
        results = load_results()
        total = 0
        for name, circuit_str in results["circuits"].items():
            total += count_two_qubit_gates(circuit_str)
        assert total <= MAX_TOTAL_TWO_QUBIT, (
            f"Total two-qubit gates = {total}, exceeds budget of {MAX_TOTAL_TWO_QUBIT}"
        )
