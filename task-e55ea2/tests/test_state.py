
import subprocess
import pytest

EXPECTED_TAX = {
    "case_01": 4196,
    "case_02": 5136,
    "case_03": 6847,
    "case_04": 62598,
    "case_05": 0,
    "case_06": 16679,
    "case_07": 5144,
    "case_08": 5282,
    "case_09": 87321,
    "case_10": 4679,
    "case_11": 3218,
    "case_12": 3542,
}


def run_prolog_case(case_id: str) -> int:
    """Run SWI-Prolog on a case file and return the computed tax as an integer."""
    goal = (
        f"consult('/app/tax_engine'), "
        f"consult('/app/cases/{case_id}'), "
        f"(compute_tax(X) -> write(X), nl ; write('ERROR'), nl), halt"
    )
    result = subprocess.run(
        ["swipl", "-g", goal, "-t", "halt"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"SWI-Prolog exited with code {result.returncode} for {case_id}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    output = result.stdout.strip()
    assert output != "ERROR", (
        f"compute_tax/1 failed for {case_id}.\nstderr: {result.stderr}"
    )
    return int(float(output))


@pytest.mark.parametrize("case_id,expected", list(EXPECTED_TAX.items()))
def test_tax_computation(case_id: str, expected: int):
    """Verify that the Prolog tax engine produces the correct tax for each case."""
    actual = run_prolog_case(case_id)
    assert actual == expected, (
        f"Tax mismatch for {case_id}: expected {expected}, got {actual}"
    )


def test_engine_file_exists():
    """Verify that the tax engine Prolog file exists."""
    import os
    assert os.path.isfile("/app/tax_engine.pl"), (
        "/app/tax_engine.pl does not exist"
    )


def test_compute_tax_predicate_defined():
    """Verify that compute_tax/1 is a defined predicate."""
    goal = (
        "consult('/app/tax_engine'), "
        "(predicate_property(compute_tax(_), defined) -> write(ok) ; write(fail)), "
        "halt"
    )
    result = subprocess.run(
        ["swipl", "-g", goal, "-t", "halt"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.stdout.strip() == "ok", (
        "compute_tax/1 is not defined in /app/tax_engine.pl"
    )
