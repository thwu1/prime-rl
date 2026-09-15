
import subprocess
import json
import os
import pytest


# ── Custom validator tests (existing) ──────────────────────────────────────

VALIDATOR_CASES = [
    ("case01_lia_valid", "model01_lia_valid", "VALID"),
    ("case02_lia_invalid", "model02_lia_invalid", "INVALID"),
    ("case03_nia_refine", "model03_nia_refine", "VALID"),
    ("case04_bv_overflow", "model04_bv_overflow", "VALID"),
    ("case05_bv_signed", "model05_bv_signed", "VALID"),
    ("case06_bv_extract", "model06_bv_extract", "VALID"),
    ("case07_array", "model07_array", "VALID"),
    ("case08_uflia", "model08_uflia", "INVALID"),
    ("case09_let", "model09_let", "VALID"),
    ("case10_nia_mod", "model10_nia_mod", "INVALID"),
]


@pytest.mark.parametrize(
    "bench,model,expected", VALIDATOR_CASES, ids=[c[0] for c in VALIDATOR_CASES]
)
def test_validate_model(bench, model, expected):
    """Run the custom validator on a benchmark/model pair."""
    result = subprocess.run(
        [
            "python3",
            "/app/validate_model.py",
            f"/app/benchmarks/{bench}.smt2",
            f"/app/models/{model}.smt2",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Validator exited with code {result.returncode}.\n"
        f"stderr: {result.stderr}\nstdout: {result.stdout}"
    )
    first_line = result.stdout.strip().split("\n")[0].strip()
    assert first_line == expected, (
        f"For {bench}: expected '{expected}', got '{first_line}'.\n"
        f"Full stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_validator_exists():
    """Ensure the validator script exists."""
    assert os.path.isfile("/app/validate_model.py"), (
        "/app/validate_model.py does not exist"
    )


def test_validator_usage_error():
    """Validator should exit non-zero when called with no args."""
    result = subprocess.run(
        ["python3", "/app/validate_model.py"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0, "Validator should fail when called with no arguments"


# ── Z3 solver integration tests ───────────────────────────────────────────

def test_z3_solve_exists():
    """z3_solve.py must exist."""
    assert os.path.isfile("/app/z3_solve.py"), "/app/z3_solve.py does not exist"


Z3_STATUS_CASES = [
    ("case01_lia_valid", "sat"),
    ("case04_bv_overflow", "sat"),
    ("case05_bv_signed", "sat"),
    ("case07_array", "sat"),
    ("case08_uflia", "unsat"),
    ("case09_let", "sat"),
]


@pytest.mark.parametrize(
    "bench,expected_status", Z3_STATUS_CASES, ids=[c[0] for c in Z3_STATUS_CASES]
)
def test_z3_solve_status(bench, expected_status):
    """Z3 solver should report correct sat/unsat status."""
    result = subprocess.run(
        ["python3", "/app/z3_solve.py", f"/app/benchmarks/{bench}.smt2"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"z3_solve.py failed with code {result.returncode}.\n"
        f"stderr: {result.stderr}"
    )
    status = result.stdout.strip().split("\n")[0].strip()
    assert status == expected_status, (
        f"For {bench}: expected '{expected_status}', got '{status}'"
    )


Z3_CROSSVAL_CASES = [
    "case01_lia_valid",
    "case04_bv_overflow",
    "case05_bv_signed",
    "case09_let",
]


@pytest.mark.parametrize("bench", Z3_CROSSVAL_CASES)
def test_z3_model_validates(bench):
    """Z3-generated model should validate as VALID through the custom validator."""
    model_path = f"/tmp/z3_test_{bench}.smt2"

    # Generate model with Z3
    result = subprocess.run(
        ["python3", "/app/z3_solve.py", f"/app/benchmarks/{bench}.smt2", model_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"z3_solve.py failed: {result.stderr}"
    assert result.stdout.strip().startswith("sat"), (
        f"Expected sat, got: {result.stdout.strip()}"
    )
    assert os.path.isfile(model_path), f"Z3 model file not created at {model_path}"

    # Validate the Z3 model with the custom validator
    val_result = subprocess.run(
        ["python3", "/app/validate_model.py", f"/app/benchmarks/{bench}.smt2", model_path],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert val_result.returncode == 0, (
        f"Validator failed on Z3 model: {val_result.stderr}"
    )
    verdict = val_result.stdout.strip().split("\n")[0].strip()
    assert verdict == "VALID", (
        f"Z3 model for {bench} should be VALID, got '{verdict}'.\n"
        f"Validator stderr: {val_result.stderr}"
    )


# ── Pipeline tests ─────────────────────────────────────────────────────────

def test_pipeline_exists():
    """pipeline.sh must exist and be executable."""
    assert os.path.isfile("/app/pipeline.sh"), "/app/pipeline.sh does not exist"


def test_pipeline_produces_json():
    """pipeline.sh must produce a well-formed results.json."""
    if os.path.exists("/app/results.json"):
        os.remove("/app/results.json")

    result = subprocess.run(
        ["bash", "/app/pipeline.sh"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert os.path.exists("/app/results.json"), (
        f"results.json not created.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )

    with open("/app/results.json") as f:
        data = json.load(f)

    assert len(data) == 10, f"Expected 10 entries, got {len(data)}"
    assert "case01_lia_valid" in data
    assert "case08_uflia" in data

    for key, entry in data.items():
        assert "provided_model_valid" in entry, f"{key} missing provided_model_valid"
        assert "z3_result" in entry, f"{key} missing z3_result"
        assert "z3_model_valid" in entry, f"{key} missing z3_model_valid"


def test_pipeline_results_correct():
    """Pipeline results.json must have correct validation outcomes."""
    if not os.path.exists("/app/results.json"):
        subprocess.run(
            ["bash", "/app/pipeline.sh"], capture_output=True, timeout=180
        )

    with open("/app/results.json") as f:
        data = json.load(f)

    expected_provided = {
        "case01_lia_valid": True,
        "case02_lia_invalid": False,
        "case03_nia_refine": True,
        "case04_bv_overflow": True,
        "case05_bv_signed": True,
        "case06_bv_extract": True,
        "case07_array": True,
        "case08_uflia": False,
        "case09_let": True,
        "case10_nia_mod": False,
    }
    for case, expected in expected_provided.items():
        assert data[case]["provided_model_valid"] == expected, (
            f"{case}: expected provided_model_valid={expected}, "
            f"got {data[case]['provided_model_valid']}"
        )

    # Z3 should report unsat for the unsatisfiable benchmark
    assert data["case08_uflia"]["z3_result"] == "unsat"
    assert data["case08_uflia"]["z3_model_valid"] is None

    # Z3 should report sat and produce valid models for satisfiable benchmarks
    for case in ["case01_lia_valid", "case04_bv_overflow", "case09_let"]:
        assert data[case]["z3_result"] == "sat", (
            f"{case}: expected z3_result=sat, got {data[case]['z3_result']}"
        )
        assert data[case]["z3_model_valid"] is True, (
            f"{case}: expected z3_model_valid=true, got {data[case]['z3_model_valid']}"
        )
