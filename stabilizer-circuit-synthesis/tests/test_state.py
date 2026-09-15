
import json
import os
import re
import sys

sys.path.insert(0, "/app/tools")

from check_stabilizers import check_stabilizers
from circuit_metric import compute_metrics

VALID_CODES = {"bell", "bit_flip3", "ghz4", "five_qubit", "steane"}
INVALID_CODES = {"code_alpha", "code_beta", "code_gamma"}
ALL_CODES = VALID_CODES | INVALID_CODES


def _load_codes():
    with open("/app/codes_db.json") as f:
        return json.load(f)


def _load_results():
    with open("/app/output/results.json") as f:
        return json.load(f)


def _result_map():
    return {r["name"]: r for r in _load_results()}


def _code_map():
    return {c["name"]: c for c in _load_codes()}


# ── Structure tests ──────────────────────────────────────────────


def test_output_file_exists():
    assert os.path.isfile("/app/output/results.json"), (
        "/app/output/results.json does not exist"
    )


def test_output_is_valid_json_array():
    results = _load_results()
    assert isinstance(results, list), "results.json must contain a JSON array"


def test_all_codes_present():
    rm = _result_map()
    missing = ALL_CODES - set(rm.keys())
    assert not missing, f"Missing codes in output: {missing}"


def test_each_entry_has_required_fields():
    for r in _load_results():
        for field in ("name", "status", "diagnosis", "circuit"):
            assert field in r, f"Entry {r.get('name', '?')} missing field '{field}'"


# ── Classification tests ─────────────────────────────────────────


def test_valid_codes_classified_correctly():
    rm = _result_map()
    for name in VALID_CODES:
        assert rm[name]["status"] == "valid", (
            f"{name} should be classified as valid, got '{rm[name]['status']}'"
        )


def test_invalid_codes_classified_correctly():
    rm = _result_map()
    for name in INVALID_CODES:
        assert rm[name]["status"] == "invalid", (
            f"{name} should be classified as invalid, got '{rm[name]['status']}'"
        )


# ── Diagnosis tests ──────────────────────────────────────────────


def test_alpha_diagnosis_mentions_commutativity():
    """code_alpha has generators XZII and ZZII that anti-commute."""
    diag = _result_map()["code_alpha"]["diagnosis"].lower()
    assert len(diag) > 10, f"code_alpha diagnosis too short: {diag}"
    assert re.search(r"commut", diag), (
        f"code_alpha diagnosis should mention commutativity issue, got: {diag}"
    )


def test_beta_diagnosis_mentions_length():
    """code_beta has generator 'XZZX' (length 4) but n_qubits=5."""
    diag = _result_map()["code_beta"]["diagnosis"].lower()
    assert len(diag) > 10, f"code_beta diagnosis too short: {diag}"
    assert any(w in diag for w in ["length", "mismatch", "size", "short"]), (
        f"code_beta diagnosis should mention length/size issue, got: {diag}"
    )


def test_gamma_diagnosis_mentions_character():
    """code_gamma has generator 'ZIIIZW' containing invalid Pauli 'W'."""
    diag = _result_map()["code_gamma"]["diagnosis"].lower()
    assert len(diag) > 10, f"code_gamma diagnosis too short: {diag}"
    has_char = "character" in diag or "symbol" in diag
    has_w = bool(re.search(r"['\"]w['\"]|\bw\b", diag))
    has_pauli = "pauli" in diag
    assert has_char or has_w or has_pauli, (
        f"code_gamma diagnosis should mention invalid character/symbol, got: {diag}"
    )


# ── Circuit validity tests ───────────────────────────────────────


def test_valid_codes_have_nonempty_circuits():
    rm = _result_map()
    for name in VALID_CODES:
        circuit = rm[name].get("circuit", "")
        assert isinstance(circuit, str) and len(circuit.strip()) > 0, (
            f"{name}: valid code must have a non-empty circuit string"
        )


def test_valid_circuits_parse_as_stim():
    import stim

    rm = _result_map()
    for name in VALID_CODES:
        circuit_str = rm[name]["circuit"].replace("\\n", "\n")
        try:
            stim.Circuit(circuit_str)
        except Exception as e:
            raise AssertionError(
                f"Code {name}: circuit does not parse as valid Stim: {e}"
            )


def test_stabilizer_preservation():
    cm = _code_map()
    rm = _result_map()

    for name in VALID_CODES:
        stabs = cm[name]["stabilizers"]
        circuit_str = rm[name]["circuit"]
        verdicts = check_stabilizers(circuit_str, stabs)

        for stab, preserved in verdicts.items():
            assert preserved, (
                f"Code {name}: stabilizer {stab} is NOT a +1 eigenstate "
                f"of the circuit's output"
            )


def test_two_qubit_gate_budgets():
    cm = _code_map()
    rm = _result_map()

    for name in VALID_CODES:
        budget = cm[name]["two_qubit_gate_budget"]
        circuit_str = rm[name]["circuit"]
        metrics = compute_metrics(circuit_str)

        assert metrics.two_qubit_gates <= budget, (
            f"Code {name}: {metrics.two_qubit_gates} two-qubit gates "
            f"exceeds budget of {budget}"
        )


# ── Invalid codes should not have circuits ────────────────────────


def test_invalid_codes_have_empty_circuits():
    rm = _result_map()
    for name in INVALID_CODES:
        circuit = rm[name].get("circuit", "")
        assert circuit.strip() == "", (
            f"{name}: invalid code should have empty circuit string"
        )
