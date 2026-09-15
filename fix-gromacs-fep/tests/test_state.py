"""
Verification tests for GROMACS solvation free energy task.

"""

import os
import re
import pytest


# ---------------------------------------------------------------------------
# 1. Result file exists and contains a valid free energy value
# ---------------------------------------------------------------------------

def test_result_file_exists():
    """result.txt must exist at /app/result.txt."""
    assert os.path.isfile("/app/result.txt"), "/app/result.txt not found"


def test_result_is_valid_float():
    """result.txt must contain a single parseable floating-point number."""
    with open("/app/result.txt") as fh:
        content = fh.read().strip()
    try:
        value = float(content)
    except ValueError:
        pytest.fail(f"result.txt content is not a valid float: '{content}'")
    assert isinstance(value, float)


def test_result_in_physical_range():
    """Solvation free energy of methanol should be in [-50, -2] kJ/mol.

    The experimental value is approximately -21.3 kJ/mol.  Short simulations
    may produce noisy estimates, so we accept a wide window.
    """
    with open("/app/result.txt") as fh:
        value = float(fh.read().strip())
    assert -50.0 < value < -2.0, (
        f"Computed solvation free energy {value:.2f} kJ/mol is outside the "
        f"physically reasonable range (-50, -2) for methanol"
    )


# ---------------------------------------------------------------------------
# 2. Lambda directories and dhdl.xvg files exist with real data
# ---------------------------------------------------------------------------

def test_lambda_directories_exist():
    """At least 9 of lambda_0 .. lambda_10 directories must exist."""
    count = sum(
        1 for i in range(11) if os.path.isdir(f"/app/lambda_{i}")
    )
    assert count >= 9, (
        f"Expected >= 9 lambda directories, found {count}"
    )


def test_dhdl_files_exist_with_data():
    """dhdl.xvg files must exist in >= 9 lambda directories and each must
    contain at least 30 data lines (excluding comments/headers)."""
    found = 0
    for i in range(11):
        path = f"/app/lambda_{i}/dhdl.xvg"
        if os.path.isfile(path):
            with open(path) as fh:
                data_lines = [
                    line for line in fh
                    if not line.startswith(("#", "@", ";"))
                    and line.strip()
                ]
            assert len(data_lines) >= 30, (
                f"lambda_{i}/dhdl.xvg has only {len(data_lines)} data lines"
            )
            found += 1
    assert found >= 9, f"Expected >= 9 dhdl.xvg files, found {found}"


def test_dhdl_files_are_distinct():
    """dH/dl files from different lambda windows must contain different data,
    confirming that distinct lambda states were actually simulated."""
    signatures = []
    for i in range(11):
        path = f"/app/lambda_{i}/dhdl.xvg"
        if os.path.isfile(path):
            with open(path) as fh:
                data_lines = [
                    line.strip() for line in fh
                    if not line.startswith(("#", "@", ";"))
                    and line.strip()
                ]
            # Use the 5th data line as a fingerprint (avoids header jitter)
            if len(data_lines) >= 5:
                signatures.append(data_lines[4])
    unique = set(signatures)
    assert len(unique) >= min(5, len(signatures)), (
        f"Only {len(unique)} unique signatures out of {len(signatures)} — "
        f"lambda windows may not have used different init-lambda-state values"
    )


# ---------------------------------------------------------------------------
# 3. Key MDP bug fixes are confirmed in the resolved parameter files
# ---------------------------------------------------------------------------

def _find_mdp_content():
    """Return content of the first mdout.mdp or grompp.mdp found in any
    lambda directory.  mdout.mdp (written by grompp) is authoritative."""
    for i in range(11):
        for name in ("mdout.mdp", "grompp.mdp", "fep.mdp"):
            path = f"/app/lambda_{i}/{name}"
            if os.path.isfile(path):
                with open(path) as fh:
                    return fh.read()
    return None


def test_couple_moltype_is_mol():
    """couple-moltype must reference 'MOL' (methanol), not 'SOL' (water).
    GROMACS mdout.mdp may use hyphens or underscores in parameter names."""
    content = _find_mdp_content()
    assert content is not None, "No MDP file found in lambda directories"
    m = re.search(r"couple[-_]moltype\s*=\s*(\S+)", content)
    assert m is not None, "couple-moltype not found in MDP"
    assert m.group(1) == "MOL", (
        f"couple-moltype = {m.group(1)}, expected MOL"
    )


def test_sc_alpha_is_positive():
    """sc-alpha must be > 0 (soft-core enabled) for vdW decoupling."""
    content = _find_mdp_content()
    assert content is not None, "No MDP file found in lambda directories"
    m = re.search(r"sc[-_]alpha\s*=\s*([\d.eE+-]+)", content)
    assert m is not None, "sc-alpha not found in MDP"
    assert float(m.group(1)) > 0.0, (
        f"sc-alpha = {m.group(1)}, must be > 0 for soft-core vdW decoupling"
    )


def test_nstdhdl_is_positive():
    """nstdhdl must be > 0 so dH/dl values are written for BAR analysis."""
    content = _find_mdp_content()
    assert content is not None, "No MDP file found in lambda directories"
    m = re.search(r"nstdhdl\s*=\s*(\d+)", content)
    assert m is not None, "nstdhdl not found in MDP"
    assert int(m.group(1)) > 0, (
        f"nstdhdl = {m.group(1)}, must be > 0 to produce dH/dl output"
    )


def test_init_lambda_state_varies():
    """Different lambda directories must have used different init-lambda-state
    values, confirming the sed substitution in the run script works."""
    states = set()
    for i in range(11):
        for name in ("mdout.mdp", "grompp.mdp"):
            path = f"/app/lambda_{i}/{name}"
            if os.path.isfile(path):
                with open(path) as fh:
                    content = fh.read()
                m = re.search(r"init[-_]lambda[-_]state\s*=\s*(\d+)", content)
                if m:
                    states.add(int(m.group(1)))
                break
    assert len(states) >= 9, (
        f"Expected >= 9 distinct init-lambda-state values, found {len(states)}: {sorted(states)}"
    )
